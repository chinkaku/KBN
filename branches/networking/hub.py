# -*- coding: utf-8 -*-
"""组合麻将 — 联机中心 GameHub (移植 mmcr14.online 的 GameHub/GameTransport)

核心设计(照搬 mmcr, 用来根治旧 rooms.py 的 socket↔槽位竞态):
- **按玩家身份路由**: 传输层是 {player_id: 连接}, 发消息只认身份不认 socket;
  socket 只是"当前通道", 新连接覆盖旧连接, 断线只是清空通道
- 显式生命周期: connect_player / disconnect_player; 槽位属于身份, 不属于连接
- 两张会话表: pending_sessions(等待房) / active_sessions(进行中对局)
- 反查映射: player_pending / player_active (一个人同时只能在一个会话里)
- 大厅订阅者集合 browsing, 会话表变化时推送 lobby.list.snapshot
- GC: 空房超时清理 + 已结束对局清理
"""
import asyncio
import json
import os
import sys
import time

_BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

from . import protocol as P          # noqa: E402
from .session import PendingSession, ActiveSession  # noqa: E402

PENDING_EMPTY_TIMEOUT_MS = 15000     # 空房超时(无人则回收)
ACTIVE_ENDED_TTL_MS = 120000         # 已结束对局保留时长(便于看结算/回放)
STALLED_SESSION_MS = 90000           # 对局无进展超时(安全网: 强制收尾, 防止永久卡在会话表)
GC_INTERVAL_MS = 3000


def now_ms():
    return int(time.time() * 1000)


class GameHub:
    def __init__(self):
        self.connections = {}       # player_id -> ws
        self.pending_sessions = {}  # session_id -> PendingSession
        self.active_sessions = {}   # session_id -> ActiveSession
        self.player_pending = {}    # player_id -> session_id
        self.player_active = {}     # player_id -> session_id
        self.browsing = set()       # player_id (大厅订阅者)
        self.watching = {}          # player_id -> session_id (观战者)
        self._names = {}            # player_id -> username
        self._sid = 0
        self._gc_task = None
        self.record_stats_hook = None   # 由 server 注入: fn(session, round_result) 记录战绩
        self.record_replay_hook = None  # 由 server 注入: fn(replay) 落库

    # ---- 身份/名字 ----
    def name_of(self, player_id):
        if player_id is None:
            return ""
        return self._names.get(player_id, f"玩家{player_id}")

    def register_name(self, player_id, username):
        if player_id is not None and username:
            self._names[player_id] = username

    # ---- 传输层: 按身份发送 ----
    async def send(self, player_id, message):
        ws = self.connections.get(player_id)
        if ws is None:
            return False
        try:
            await ws.send_text(json.dumps(message, ensure_ascii=False))
            return True
        except Exception:
            return False

    async def send_event(self, player_id, payload):
        return await self.send(player_id, P.envelope("game.event", payload))

    async def broadcast(self, player_ids, message):
        for pid in player_ids:
            if pid is not None:
                await self.send(pid, message)

    async def notify_lobby(self):
        """会话表变化 → 推送大厅快照(移植 mmcr notify_session_lists_changed)"""
        if not self.browsing:
            return
        msg = P.envelope("lobby.list.snapshot", {
            "sessions": self.list_joinable(),
            "active_sessions": self.list_active(),
        })
        for pid in list(self.browsing):
            await self.send(pid, msg)

    # ---- 连接生命周期 ----
    async def connect(self, player_id, username, ws, browsing=True):
        """玩家连接: 覆盖旧连接(旧 socket 自动作废), 并回发当前会话快照"""
        self.register_name(player_id, username)
        self.connections[player_id] = ws
        if browsing:
            self.browsing.add(player_id)
        # 重连即清掉断线标记(否则超过宽限期会被服务器代打)
        asid = self.player_active.get(player_id)
        if asid is not None:
            sess = self.active_sessions.get(asid)
            if sess is not None:
                was_off = sess.disconnected.pop(player_id, None) is not None
                if was_off:
                    await sess._publish("reconnect", {
                        "kind": "reconnect", "seat_index": sess.seat_of(player_id),
                        "timestamp_ms": now_ms(), "stage_counter": sess.stage_counter})
        snap = self.session_snapshot_of(player_id)
        if snap:
            await self.send(player_id, P.envelope("session.snapshot", {"session": snap}))
        await self.notify_lobby()
        return snap

    async def disconnect(self, player_id, ws=None):
        """玩家断线: 只清通道(槽位/身份保留), 对局中标记断线"""
        if ws is not None and self.connections.get(player_id) is not ws:
            return  # 已被新连接覆盖, 不动
        self.connections.pop(player_id, None)
        self.browsing.discard(player_id)
        self.watching.pop(player_id, None)
        # 等待房里的人断线 → 直接离开(还没开局)
        psid = self.player_pending.get(player_id)
        if psid is not None:
            await self.leave_session(player_id)
        asid = self.player_active.get(player_id)
        if asid is not None:
            sess = self.active_sessions.get(asid)
            if sess is not None and not sess.ended:
                sess.disconnected[player_id] = now_ms()
                await sess._publish("disconnect", {"kind": "disconnect", "seat_index": sess.seat_of(player_id),
                                                   "timestamp_ms": now_ms(),
                                                   "stage_counter": sess.stage_counter})
        await self.notify_lobby()

    # ---- 会话列表 ----
    def list_joinable(self):
        return [s.summary() for s in self.pending_sessions.values()]

    def list_active(self):
        return [s.summary() for s in self.active_sessions.values()]

    def session_snapshot_of(self, player_id):
        sid = self.player_pending.get(player_id)
        if sid is not None and sid in self.pending_sessions:
            return self.pending_sessions[sid].snapshot()
        sid = self.player_active.get(player_id)
        if sid is not None and sid in self.active_sessions:
            return self.active_sessions[sid].snapshot_for(player_id)
        return None

    # ---- 创建/加入/离开/准备 ----
    async def create_session(self, player_id, username, config=None):
        self.register_name(player_id, username)
        await self.leave_session(player_id)   # 一人同时只在一个会话
        self._sid += 1
        sid = self._sid
        ps = PendingSession(self, sid, player_id, config)
        ps.join(player_id)
        self.pending_sessions[sid] = ps
        self.player_pending[player_id] = sid
        await self.send(player_id, P.envelope("session.snapshot", {"session": ps.snapshot()}))
        await self.notify_lobby()
        return sid

    async def join_session(self, player_id, username, sid):
        self.register_name(player_id, username)
        ps = self.pending_sessions.get(sid)
        if ps is None:
            return False, P.ERR_NOT_FOUND, "房间不存在或已开始"
        if ps.is_full() and not ps.is_member(player_id):
            return False, P.ERR_SESSION_FULL, "房间已满"
        await self.leave_session(player_id)
        seat = ps.join(player_id)
        if seat < 0:
            return False, P.ERR_SESSION_FULL, "房间已满"
        self.player_pending[player_id] = sid
        # 广播新状态给房内所有人
        for pid in ps.seats:
            if pid:
                await self.send(pid, P.envelope("session.snapshot", {"session": ps.snapshot()}))
        await self.notify_lobby()
        return True, None, None

    async def leave_session(self, player_id):
        sid = self.player_pending.get(player_id)
        if sid is not None:
            ps = self.pending_sessions.get(sid)
            self.player_pending.pop(player_id, None)
            if ps is not None:
                ps.leave(player_id)
                if ps.is_empty():
                    ps.last_activity = now_ms()
                else:
                    for pid in ps.seats:
                        if pid:
                            await self.send(pid, P.envelope("session.snapshot", {"session": ps.snapshot()}))
        # 观战退订
        self.watching.pop(player_id, None)
        await self.notify_lobby()
        return True

    async def kick_player(self, owner_id, target_id):
        """房主踢人(等待房阶段)"""
        sid = self.player_pending.get(owner_id)
        if sid is None:
            return False, P.ERR_NOT_IN_SESSION, "你不在任何房间中"
        ps = self.pending_sessions.get(sid)
        if ps is None:
            return False, P.ERR_NOT_FOUND, "房间不存在"
        if ps.owner_id != owner_id:
            return False, P.ERR_NOT_OWNER, "只有房主可以踢人"
        if not ps.is_member(target_id):
            return False, P.ERR_NOT_FOUND, "该玩家不在房间里"
        self.player_pending.pop(target_id, None)
        ps.leave(target_id)
        await self.send(target_id, P.envelope("session.snapshot", {"session": None, "kicked": True}))
        for pid in ps.seats:
            if pid:
                await self.send(pid, P.envelope("session.snapshot", {"session": ps.snapshot()}))
        await self.notify_lobby()
        return True, None, None

    async def set_spectator_perspective(self, player_id, seat_index):
        """观战者切换视角(只影响画面朝向, 永远看不到手牌)"""
        sid = self.watching.get(player_id)
        if sid is None:
            return False, P.ERR_NOT_FOUND, "你不在观战中"
        act = self.active_sessions.get(sid)
        if act is None:
            return False, P.ERR_NOT_FOUND, "对局不存在"
        try:
            seat_index = int(seat_index)
        except Exception:
            seat_index = -1
        if seat_index < 0 or seat_index > 3:
            seat_index = -1
        act.spectator_seat[player_id] = seat_index
        await self.send(player_id, P.envelope("session.snapshot",
                                             {"session": act.snapshot_for(player_id)}))
        return True, None, None

    async def set_ready(self, player_id, ready):
        sid = self.player_pending.get(player_id)
        if sid is None:
            return False, P.ERR_NOT_IN_SESSION, "你不在任何房间中"
        ps = self.pending_sessions.get(sid)
        if ps is None:
            return False, P.ERR_NOT_FOUND, "房间不存在"
        if not ps.set_ready(player_id, ready):
            return False, P.ERR_NOT_IN_SESSION, "你不在该房间"
        for pid in ps.seats:
            if pid:
                await self.send(pid, P.envelope("session.snapshot", {"session": ps.snapshot()}))
        await self.notify_lobby()
        return True, None, None

    async def start_session(self, player_id):
        sid = self.player_pending.get(player_id)
        if sid is None:
            return False, P.ERR_NOT_IN_SESSION, "你不在任何房间中"
        ps = self.pending_sessions.get(sid)
        if ps is None:
            return False, P.ERR_NOT_FOUND, "房间不存在"
        if ps.owner_id != player_id:
            return False, P.ERR_NOT_OWNER, "只有房主可以开始游戏"
        if not ps.is_full():
            return False, P.ERR_NOT_READY, "需要 4 名玩家"
        if not ps.all_ready():
            return False, P.ERR_NOT_READY, "还有玩家未准备"
        # 从等待房升级为进行中对局
        seats = list(ps.seats)
        names = [self.name_of(pid) if pid else "" for pid in seats]
        self.pending_sessions.pop(sid, None)
        act = ActiveSession(self, sid, seats, ps.config, names)
        self.active_sessions[sid] = act
        for pid in seats:
            self.player_pending.pop(pid, None)
            self.player_active[pid] = sid
        await self.notify_lobby()
        # 先开局(发牌)再下发 started 快照, 否则客户端拿到的是空手牌/第0局
        await act.start()
        for pid in seats:
            await self.send(pid, P.envelope("session.snapshot",
                                            {"session": act.snapshot_for(pid), "started": True}))
        return True, None, None

    # ---- 对局输入 ----
    async def handle_game_input(self, player_id, payload):
        sid = self.player_active.get(player_id)
        if sid is None:
            # 可能在等待房(未开局): 允许 queue.* 之外的消息报错
            return False, P.ERR_NOT_IN_SESSION, "你不在对局中"
        act = self.active_sessions.get(sid)
        if act is None:
            return False, P.ERR_NOT_FOUND, "对局不存在"
        return await act.handle_input(player_id, payload)

    async def abandon(self, player_id, abandon=True):
        sid = self.player_active.get(player_id)
        if sid is None:
            return False, P.ERR_NOT_IN_SESSION, "你不在对局中"
        act = self.active_sessions.get(sid)
        if act is None:
            return False, P.ERR_NOT_FOUND, "对局不存在"
        if abandon:
            act.abandoned.add(player_id)
        else:
            act.abandoned.discard(player_id)
        for pid in act.seats:
            if pid:
                await self.send(pid, P.envelope("game.abandon.notify", {
                    "player_id": player_id, "seat_index": act.seat_of(player_id),
                    "abandon": bool(abandon)}))
        # 代打推进
        await act._pump()
        return True, None, None

    # ---- 观战 ----
    async def subscribe_spectate(self, player_id, sid):
        act = self.active_sessions.get(sid)
        if act is None:
            return False, P.ERR_NOT_FOUND, "对局不存在"
        await self.leave_session(player_id)
        act.spectators.add(player_id)
        self.watching[player_id] = sid
        await self.send(player_id, P.envelope("session.snapshot",
                                             {"session": act.snapshot_for(player_id)}))
        await self.notify_lobby()
        return True, None, None

    async def unsubscribe_spectate(self, player_id):
        sid = self.watching.pop(player_id, None)
        if sid is not None:
            act = self.active_sessions.get(sid)
            if act is not None:
                act.spectators.discard(player_id)
        return True

    # ---- 结束/GC ----
    def on_session_ended(self, act):
        for pid in list(self.player_active.keys()):
            if self.player_active.get(pid) == act.session_id:
                self.player_active.pop(pid, None)
        act._ended_at = now_ms()

    async def gc_loop(self):
        while True:
            try:
                await asyncio.sleep(GC_INTERVAL_MS / 1000.0)
                await self.gc_once()
            except asyncio.CancelledError:
                return
            except Exception:
                continue

    async def gc_once(self):
        changed = False
        # 空等待房回收
        for sid, ps in list(self.pending_sessions.items()):
            if ps.empty_timeout_elapsed(PENDING_EMPTY_TIMEOUT_MS):
                self.pending_sessions.pop(sid, None)
                for pid in list(self.player_pending.keys()):
                    if self.player_pending.get(pid) == sid:
                        self.player_pending.pop(pid, None)
                changed = True
        # 长时间无进展的对局强制收尾(安全网: 避免任何异常路径把会话永久留在表里)
        for sid, act in list(self.active_sessions.items()):
            if act.ended:
                continue
            if (now_ms() - getattr(act, "last_progress_ms", now_ms())) > STALLED_SESSION_MS:
                print(f"[Hub] 会话 {sid} 超过 {STALLED_SESSION_MS/1000:.0f}s 无进展, 强制收尾")
                try:
                    await act._finish()
                except Exception as e:
                    print(f"[Hub] 强制收尾失败 {sid}: {e}")
                    act.ended = True
                    act._ended_at = now_ms()
                changed = True
        # 已结束对局保留一段时间后回收
        for sid, act in list(self.active_sessions.items()):
            ended_at = getattr(act, "_ended_at", None)
            if act.ended and ended_at and (now_ms() - ended_at) > ACTIVE_ENDED_TTL_MS:
                self.active_sessions.pop(sid, None)
                changed = True
        if changed:
            await self.notify_lobby()
        return changed


# 全局单例
hub = GameHub()
