# -*- coding: utf-8 -*-
"""组合麻将 — 联机会话 (移植 mmcr14.online 的 PendingSession / ActiveSession)

设计要点(照搬 mmcr):
- PendingSession: 等待房——4 个座位 + ready 标记 + 空房超时; 支持加入/离开/准备/房主开局
- ActiveSession: 进行中对局——包住 game_engine, 维护 stage_counter(输入幂等)、
  三档计时器(primary 7s 本人回合 / secondary 4s 鸣牌决策 / auxiliary 12s 兜底),
  全量快照(session.snapshot)与逐阶段事件(game.event), 观战视图, 回放记录
- 计时器按 stage 失效: 到期回调先校验 stage_counter, 不匹配则 no-op
  (mmcr ActiveSession::set_timer 的做法, 天然避免"旧计时器打断新阶段")
"""
import asyncio
import os
import sys
import time

_BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

from game_engine import GameEngine  # noqa: E402

from . import protocol as P  # noqa: E402

# ---- 三档计时器 (照搬 mmcr: primary/secondary/auxiliary) ----
DEFAULT_TIMERS = {"primary_ms": 7000, "secondary_ms": 4000, "auxiliary_ms": 12000}
ROUND_PAUSE_MS = 6000        # 一局结束后停留多久进下一局
DISCONNECT_GRACE_MS = 60000  # 断线宽限(超时后自动代打)
BOT_DELAY_MS = 900           # 机器人逐帧延迟
MAX_ROUNDS_CHOICES = (4, 8, 16)


def _now_ms():
    return int(time.time() * 1000)


class PendingSession:
    """等待房: 座位 + 准备状态 + 空房超时(移植 mmcr PendingSession)"""

    def __init__(self, hub, session_id, owner_id, config=None):
        self.hub = hub
        self.session_id = session_id
        self.owner_id = owner_id
        self.seats = [None, None, None, None]   # 每座 player_id 或 None
        self.ready = {}                          # player_id -> bool
        self.created_at = _now_ms()
        self.last_activity = _now_ms()
        self.config = dict(DEFAULT_TIMERS)
        self.config["round_count"] = 8
        self.config["public"] = True
        if config:
            self.config.update({k: v for k, v in config.items() if k in
                                ("round_count", "public", "primary_ms", "secondary_ms", "auxiliary_ms",
                                 "bot_delay_ms", "round_pause_ms")})
        if self.config.get("round_count") not in MAX_ROUNDS_CHOICES:
            self.config["round_count"] = 8

    # ---- 状态查询 ----
    def seat_of(self, player_id):
        for i, pid in enumerate(self.seats):
            if pid == player_id:
                return i
        return -1

    def is_member(self, player_id):
        return self.seat_of(player_id) >= 0

    def is_empty(self):
        return all(p is None for p in self.seats)

    def is_full(self):
        return all(p is not None for p in self.seats)

    def all_ready(self):
        if not self.is_full():
            return False
        return all(self.ready.get(pid, False) for pid in self.seats)

    def occupied(self):
        return sum(1 for p in self.seats if p is not None)

    def empty_timeout_elapsed(self, timeout_ms=15000):
        return self.is_empty() and (_now_ms() - self.last_activity > timeout_ms)

    # ---- 快照 ----
    def summary(self):
        return {
            "session_id": self.session_id,
            "owner_id": self.owner_id,
            "occupied_seat_count": self.occupied(),
            "ready_seat_count": sum(1 for pid in self.seats if pid and self.ready.get(pid)),
            "seat_count": 4,
            "can_join": not self.is_full(),
            "can_start": self.all_ready() and self.is_full(),
            "created_at_ms": self.created_at,
            "round_count": self.config.get("round_count", 8),
            "primary_timer_ms": self.config.get("primary_ms"),
            "secondary_timer_ms": self.config.get("secondary_ms"),
            "auxiliary_timer_ms": self.config.get("auxiliary_ms"),
            "names": self.names(),
        }

    def names(self):
        return [self.hub.name_of(pid) if pid else "" for pid in self.seats]

    def snapshot(self):
        return {
            "phase": "pending",
            "session_id": self.session_id,
            "owner_id": self.owner_id,
            "summary": self.summary(),
            "seats": [{"seat_index": i, "player_id": pid,
                       "username": self.hub.name_of(pid) if pid else None,
                       "ready": bool(self.ready.get(pid, False)) if pid else False}
                      for i, pid in enumerate(self.seats)],
        }

    # ---- 成员操作 ----
    def join(self, player_id):
        """加入(有座则直接返回该座)"""
        seat = self.seat_of(player_id)
        if seat >= 0:
            return seat
        for i, pid in enumerate(self.seats):
            if pid is None:
                self.seats[i] = player_id
                self.ready[player_id] = False
                self.last_activity = _now_ms()
                return i
        return -1

    def leave(self, player_id):
        seat = self.seat_of(player_id)
        if seat < 0:
            return False
        self.seats[seat] = None
        self.ready.pop(player_id, None)
        self.last_activity = _now_ms()
        if player_id == self.owner_id:
            # 房主转移给下一个在座玩家
            for pid in self.seats:
                if pid:
                    self.owner_id = pid
                    break
        return True

    def set_ready(self, player_id, ready):
        if not self.is_member(player_id):
            return False
        self.ready[player_id] = bool(ready)
        self.last_activity = _now_ms()
        return True


class ActiveSession:
    """进行中对局: 包住 game_engine + stage_counter + 三档计时 + 快照 + 观战 + 回放"""

    def __init__(self, hub, session_id, seats, config=None, names=None):
        self.hub = hub
        self.session_id = session_id
        self.seats = list(seats)             # [player_id|None] * 4
        self.created_at = _now_ms()
        self.config = dict(DEFAULT_TIMERS)
        self.config["round_count"] = 8
        if config:
            self.config.update(config)
        self.round_count = int(self.config.get("round_count", 8))
        self.stage_counter = 0
        self.spectators = set()              # {player_id}
        self.spectator_seat = {}             # 观战者视角 {player_id: seat_index|-1}
        self.disconnected = {}               # player_id -> since_ms
        self.abandoned = set()               # 投降/放弃的 player_id
        self.ended = False
        self.final_scores = None
        self.last_progress_ms = _now_ms()   # 安全网: 长时间无进展的会话会被强制收尾
        self._timer_task = None
        self._timer_stage = -1
        self._timer_deadline_ms = None
        self._timer_owner = -1
        self._pause_task = None
        self._replay = {"session_identifier": f"s{self.session_id}-{self.created_at}",
                        "created_at_ms": self.created_at, "rounds": [],
                        "player_ids": list(self.seats), "names": list(names or ["", "", "", ""])}
        # 引擎
        self.engine = GameEngine(num_humans=4)
        for i, pid in enumerate(self.seats):
            self.engine.players[i].is_human = pid is not None
        self.engine.min_fan = 4   # 联机为正规规则(起和4番), 与单机一致

    # ---- 基础查询 ----
    def seat_of(self, player_id):
        for i, pid in enumerate(self.seats):
            if pid == player_id:
                return i
        return -1

    def is_member(self, player_id):
        return self.seat_of(player_id) >= 0

    def human_seats(self):
        return [i for i, pid in enumerate(self.seats) if pid is not None]

    def summary(self):
        return {
            "session_id": self.session_id,
            "phase": "active",
            "ended": self.ended,
            "round_count": self.round_count,
            "round_counter": self.engine.round_num,
            "created_at_ms": self.created_at,
            "primary_timer_ms": self.config.get("primary_ms"),
            "secondary_timer_ms": self.config.get("secondary_ms"),
            "auxiliary_timer_ms": self.config.get("auxiliary_ms"),
            "spectator_count": len(self.spectators),
            "names": self.names(),
            "scores": self._scores_by_seat(),
        }

    def names(self):
        out = []
        for i, pid in enumerate(self.seats):
            out.append(self.hub.name_of(pid) if pid else f"机器人{i+1}")
        return out

    def _scores_by_seat(self):
        sc = self.engine.accumulated_scores
        return [sc.get(self.engine.players[i].role, 0) for i in range(4)]

    # ---- 开局 ----
    async def start(self):
        self.engine.start_round()
        self.engine._auto_advance()
        await self._publish("round_start")
        await self._pump()

    # ---- 计时器 (照搬 mmcr set_timer: 到期校验 stage) ----
    def set_timer(self, delay_ms, stage_counter, callback):
        if self._timer_task and not self._timer_task.done():
            self._timer_task.cancel()
        self._timer_stage = stage_counter
        self._timer_deadline_ms = _now_ms() + max(0, int(delay_ms))
        self._timer_owner = self._decision_seat()

        async def runner():
            try:
                await asyncio.sleep(max(0, delay_ms) / 1000.0)
            except asyncio.CancelledError:
                return
            if self.ended:
                return
            if stage_counter != self.stage_counter:
                return  # 阶段已推进 → 旧计时器作废(no-op)
            await callback()

        self._timer_task = asyncio.create_task(runner())

    def _decision_seat(self):
        """当前需要决策的座位(无则 -1)"""
        ph = self.engine.phase
        if ph in ("DISCARD", "SELF_MELD"):
            return self.engine.current_player_idx
        if ph in ("CLAIM_PK", "CLAIM_CHOW"):
            return self._checker_idx()
        return -1

    def cancel_timer(self):
        if self._timer_task and not self._timer_task.done():
            self._timer_task.cancel()
        self._timer_task = None
        self._timer_deadline_ms = None
        self._timer_owner = -1

    # ---- 人类决策判定 ----
    def _checker_idx(self):
        chk = self.engine._claim_check_player()
        if chk is None:
            return -1
        return self.engine.players.index(chk)

    def _needs_human_input(self):
        ph = self.engine.phase
        if ph == "DISCARD":
            idx = self.engine.current_player_idx
            return self.engine.players[idx].is_human and not self._is_auto(idx)
        if ph == "SELF_MELD":
            idx = self.engine.current_player_idx
            if not self.engine.players[idx].is_human or self._is_auto(idx):
                return False
            # 无自摸/暗杠/加杠选项时自动跳过(同单机 _auto_advance 行为)
            return self.engine._has_self_meld_options(self.engine.players[idx])
        if ph == "CLAIM_PK":
            idx = self._checker_idx()
            return idx >= 0 and self.engine.players[idx].is_human and not self._is_auto(idx) \
                and self.engine._has_any_claim(self.engine.players[idx])
        if ph == "CLAIM_CHOW":
            idx = self._checker_idx()
            return idx >= 0 and self.engine.players[idx].is_human and not self._is_auto(idx)
        return False

    def _is_auto(self, idx):
        """该座位是否由服务器代打(断线超时/已投降)"""
        pid = self.seats[idx] if idx < len(self.seats) else None
        if pid is None:
            return False
        if pid in self.abandoned:
            return True
        since = self.disconnected.get(pid)
        return since is not None and (_now_ms() - since) > DISCONNECT_GRACE_MS

    def _auto_act(self, idx):
        """服务器代打: 该座位自动出牌/过牌 (AFK 处理)"""
        ph = self.engine.phase
        cp = self.engine.players[idx]
        if ph == "DISCARD" and cp.hand:
            disc = self.engine._choose_bot_discard(cp.hand, len(cp.discards))
            self.engine._do_discard(disc.to_shorthand())
        elif ph == "SELF_MELD":
            self.engine._do_skip_self_meld()
        elif ph in ("CLAIM_PK", "CLAIM_CHOW"):
            self.engine._do_pass_claim()

    # ---- 主推进循环: 机器人逐帧推进, 直到需要人类决策 ----
    async def _pump(self):
        guard = 0
        while not self.engine.game_over and guard < 800:
            guard += 1
            if getattr(self.engine, "_skip_rest", False):
                self.engine._auto_advance(stepwise=True)
                self.stage_counter += 1
                continue
            if self.engine.phase == "DRAW" and self.engine.players[self.engine.current_player_idx].is_human:
                self.engine._auto_advance(stepwise=True)
                self.stage_counter += 1
                continue
            if self._needs_human_input():
                break
            idx = self.engine.current_player_idx
            if self._is_auto(idx) and self.engine.phase in ("DISCARD", "SELF_MELD"):
                self._auto_act(idx)
                self.stage_counter += 1
                await self._publish("action")
                continue
            # 鸣牌阶段轮到"已放弃/断线超时"的玩家: 必须替他过牌,
            # 否则引擎会一直等这个人类输入 → 既无计时器也无代打 → 对局永久卡死
            if self.engine.phase in ("CLAIM_PK", "CLAIM_CHOW"):
                chk_idx = self._checker_idx()
                if chk_idx >= 0 and self._is_auto(chk_idx):
                    self.engine._do_pass_claim()
                    self.stage_counter += 1
                    await self._publish("action")
                    continue
            # 推进: 机器人动作 / 人类无鸣牌自动过 / 摸牌
            self.cancel_timer()
            acted = self.engine._auto_advance(stepwise=True)
            self.stage_counter += 1
            if acted:
                # 只有"机器人真的打了一张牌"才延时, 让前端看得清节奏;
                # 自动过牌/摸牌这类内部推进不延时, 否则一局会被拖到几分钟
                await self._publish("action")
                await asyncio.sleep(self.config.get("bot_delay_ms", BOT_DELAY_MS) / 1000.0)
            else:
                await self._publish("action")
        if self.engine.game_over:
            await self._on_round_end()
            return
        # 先装好三档计时器再广播, 这样推送事件里就带着 viewer.timer
        # (否则客户端只能靠主动快照才能拿到倒计时)
        await self._start_decision_timer()
        await self._publish("state")

    async def _start_decision_timer(self):
        """为当前需要决策的人类玩家设置三档计时"""
        ph = self.engine.phase
        idx = self.engine.current_player_idx if ph in ("DISCARD", "SELF_MELD") else self._checker_idx()
        if idx < 0:
            return
        pid = self.seats[idx] if idx < len(self.seats) else None
        if pid is None or self._is_auto(idx):
            return
        if ph in ("DISCARD", "SELF_MELD"):
            delay = int(self.config.get("primary_ms", 7000))
        elif ph in ("CLAIM_PK", "CLAIM_CHOW"):
            delay = int(self.config.get("secondary_ms", 4000))
        else:
            delay = int(self.config.get("auxiliary_ms", 12000))
        stage = self.stage_counter

        async def on_timeout():
            if self.engine.game_over:
                return
            if ph in ("DISCARD", "SELF_MELD") and self.engine.current_player_idx == idx:
                self._auto_act(idx)
            elif ph in ("CLAIM_PK", "CLAIM_CHOW") and self._checker_idx() == idx:
                self._auto_act(idx)
            else:
                return
            self.stage_counter += 1
            await self._publish("timeout")
            await self._pump()

        self.set_timer(delay, stage, on_timeout)

    # ---- 人类输入 ----
    async def handle_input(self, player_id, payload):
        """处理 game.input; 返回 (ok, err_code, err_msg)"""
        idx = self.seat_of(player_id)
        if idx < 0:
            return False, P.ERR_NOT_IN_SESSION, "你不在本局中"
        if self.ended:
            return False, P.ERR_SESSION_STARTED, "本局已结束"
        if not self.engine or self.engine.game_over:
            return False, P.ERR_STALE_INPUT, "本局已结束"
        kind = payload.get("kind")
        if not isinstance(kind, str) or not kind:
            return False, P.ERR_INVALID_REQUEST, "缺少 kind"
        stage = payload.get("stage_counter", 0)
        try:
            stage = int(stage)
        except Exception:
            stage = 0
        if stage and stage < self.stage_counter:
            return False, P.ERR_STALE_INPUT, f"输入已过期(阶段 {stage} < {self.stage_counter})"
        # 轮次校验: 必须轮到自己
        ph = self.engine.phase
        if ph in ("DISCARD", "SELF_MELD") and self.engine.current_player_idx != idx:
            return False, P.ERR_ILLEGAL_ACTION, "现在不是你的回合"
        if ph in ("CLAIM_PK", "CLAIM_CHOW") and self._checker_idx() != idx:
            return False, P.ERR_ILLEGAL_ACTION, "现在不是你的鸣牌时机"
        params = {}
        for k in ("tile", "choice", "meld_idx"):
            if k in payload:
                params[k] = payload[k]
        try:
            self.engine.do_action(kind, stepwise=True, auto_advance=False, **params)
        except Exception as e:
            return False, P.ERR_ILLEGAL_ACTION, f"动作失败: {e}"
        self.cancel_timer()
        self.stage_counter += 1
        self._record_event(kind, idx, params)
        await self._publish("action")
        if self.engine.game_over:
            await self._on_round_end()
        else:
            await self._pump()
        return True, None, None

    # ---- 快照 / 事件 ----
    def _sanitize_state(self, viewer_idx):
        """按视角裁剪状态: 只保留公开信息。

        - 别人"刚摸的牌"不泄露(真麻将看不到别人摸到什么), 只保留"是否已摸牌"的计数信息
        - 自己的摸牌保留(前端要显示手牌空档)
        """
        st = self.engine.get_state()
        for i, p in enumerate(st.get("players", [])):
            has_drawn = bool(p.get("drawn_tile"))
            p["has_drawn_tile"] = has_drawn
            if i != viewer_idx:
                p["drawn_tile"] = None
        return st

    def _seat_status(self):
        st = self.engine.get_state()
        out = []
        for i in range(4):
            p = st["players"][i]
            out.append({
                "seat_index": i,
                "player_id": self.seats[i],
                "username": self.hub.name_of(self.seats[i]) if self.seats[i] else f"机器人{i+1}",
                "score": self._scores_by_seat()[i],
                "hand_tile_count": p.get("hand_count", 0),
                "has_drawn_tile": bool(p.get("drawn_tile")),
                "discards": p.get("discards", []),
                "melds": p.get("melds", []),
                "disconnected": bool(self.seats[i] and self.seats[i] in self.disconnected),
                "abandoned": bool(self.seats[i] and self.seats[i] in self.abandoned),
            })
        return out

    def _viewer_for(self, player_id):
        idx = self.seat_of(player_id)
        spectator = idx < 0
        st = self.engine.get_state()
        # 观战者可切换视角(只影响画面朝向, 手牌永远不给)
        view_seat = idx
        if spectator:
            view_seat = self.spectator_seat.get(player_id, -1)
        viewer = {
            "seat_index": view_seat,
            "spectator": spectator,
            "phase": self.engine.phase,
            "current_player_idx": self.engine.current_player_idx,
            "round_num": self.engine.round_num,
            "round_count": self.round_count,
            "remaining_tiles": st.get("remaining_tiles"),
            "stage_counter": self.stage_counter,
            # 当前"该谁决策"(客户端用它做轮次提示; -1 = 无人需决策)
            "decision_seat": self._decision_seat(),
            # 只有"当前该决策的人"才看得到可用操作(避免把别人的操作泄露给旁观者/其他玩家)
            "available_actions": (self.engine.get_available_actions()
                                  if (idx >= 0 and idx == self._decision_seat()) else []),
            "game_over": self.engine.game_over,
            "winner_idx": st.get("winner_idx"),
            "win_type": st.get("win_type"),
            "win_kind": st.get("win_kind"),
            "fan_details": st.get("fan_details"),
            "total_fan": st.get("total_fan"),
        }
        if idx >= 0:
            viewer["hand"] = self.engine.players[idx].sorted_hand_shorthands()
            viewer["drawn_tile"] = (self.engine.players[idx].drawn_tile.to_shorthand()
                                    if self.engine.players[idx].drawn_tile else None)
        # 三档计时器: 只对当前决策者显示剩余时间
        if self._timer_deadline_ms and self._timer_task and not self._timer_task.done():
            viewer["timer"] = {
                "phase": self.engine.phase,
                "checker": self._timer_owner,
                "remaining": max(0.0, (self._timer_deadline_ms - _now_ms()) / 1000.0),
                "visible": (idx >= 0 and idx == self._timer_owner),
            }
        else:
            viewer["timer"] = None
        return viewer

    def _revealed_hands(self):
        return {i: self.engine.players[i].sorted_hand_shorthands() for i in range(4)}

    def snapshot_for(self, player_id):
        """全量快照(重连直接给这个, 不依赖补发中间消息)"""
        return {
            "phase": "active",
            "session_id": self.session_id,
            "summary": self.summary(),
            "state": self._sanitize_state(self.seat_of(player_id)),
            "seat_status": self._seat_status(),
            "viewer": self._viewer_for(player_id),
            "spectator": self.seat_of(player_id) < 0,
            "ended": self.ended,
            "final_scores": self.final_scores,
            "round_count": self.round_count,
        }

    async def _publish(self, category, event=None):
        """向所有成员与观战者推送一条 game.event"""
        self.last_progress_ms = _now_ms()
        ev = event or {"kind": category, "actor_seat": self.engine.current_player_idx,
                       "stage_counter": self.stage_counter,
                       "timestamp_ms": _now_ms()}
        for idx, pid in enumerate(self.seats):
            if pid is None:
                continue
            await self.hub.send_event(pid, {
                "category": category,
                "event": ev,
                "state": self._sanitize_state(idx),
                "viewer": self._viewer_for(pid),
                "seat_status": self._seat_status(),
                "session_id": self.session_id,
            })
        for sid in list(self.spectators):
            await self.hub.send_event(sid, {
                "category": category,
                "event": ev,
                "state": self._sanitize_state(-1),
                "viewer": self._viewer_for(sid),
                "seat_status": self._seat_status(),
                "session_id": self.session_id,
                "spectator": True,
                "reveal_all_hands": self.engine.game_over,
            })

    # ---- 局末 ----
    async def _on_round_end(self):
        self.cancel_timer()
        st = self.engine.get_state()
        result = {
            "round_num": self.engine.round_num,
            "winner_idx": st.get("winner_idx"),
            "win_type": st.get("win_type"),
            "win_kind": st.get("win_kind"),
            "fan_details": st.get("fan_details"),
            "total_fan": st.get("total_fan"),
            "scores": self._scores_by_seat(),
            "revealed_hands": self._revealed_hands(),
        }
        self._record_round(result)
        hook = getattr(self.hub, "record_stats_hook", None)
        if hook:
            try:
                hook(self, result)
            except Exception as e:
                print(f"[Session] stats hook failed: {e}")
        await self._publish("round_end", {"kind": "round_end", "stage_counter": self.stage_counter,
                                          "timestamp_ms": _now_ms(), "result": result})
        if self.engine.round_num >= self.round_count:
            await self._finish()
            return
        # 停留片刻后自动进入下一局
        stage = self.stage_counter

        async def next_round():
            if self.ended or not self.engine.game_over:
                return
            if self.engine.round_num >= self.round_count:
                await self._finish()
                return
            self.engine.settle_round()
            self.engine.start_round()
            self.engine._auto_advance()
            self.stage_counter += 1
            await self._publish("round_start")
            await self._pump()

        self.set_timer(int(self.config.get("round_pause_ms", ROUND_PAUSE_MS)), stage, next_round)

    async def _finish(self):
        self.ended = True
        self.cancel_timer()
        self.final_scores = self._scores_by_seat()
        self._replay["final_scores"] = self.final_scores
        self._replay["ended_at_ms"] = _now_ms()
        try:
            from . import replay as replay_mod
            replay_mod.save_replay(self._replay)
        except Exception:
            pass
        for idx, pid in enumerate(self.seats):
            if pid is None:
                continue
            await self.hub.send(pid, P.envelope("game.event", {
                "category": "session_end",
                "event": {"kind": "session_end", "stage_counter": self.stage_counter,
                          "timestamp_ms": _now_ms()},
                "state": self._sanitize_state(idx),
                "viewer": self._viewer_for(pid),
                "seat_status": self._seat_status(),
                "session_id": self.session_id,
                "ended": True,
                "final_scores": self.final_scores,
            }))
        for sid in list(self.spectators):
            await self.hub.send(sid, P.envelope("game.event", {
                "category": "session_end",
                "event": {"kind": "session_end", "timestamp_ms": _now_ms()},
                "session_id": self.session_id, "ended": True,
                "final_scores": self.final_scores, "spectator": True,
            }))
        self.hub.on_session_ended(self)

    # ---- 回放记录 ----
    def _record_event(self, kind, seat_idx, params):
        rnd = self._current_record()
        rnd["events"].append({
            "kind": kind, "actor_seat": seat_idx, "params": params,
            "stage_counter": self.stage_counter, "timestamp_ms": _now_ms(),
            "seat_status": self._seat_status(),
        })

    def _current_record(self):
        num = self.engine.round_num
        rounds = self._replay["rounds"]
        while len(rounds) < num:
            rounds.append({"round_number": len(rounds) + 1, "events": []})
        return rounds[num - 1]

    def _record_round(self, result):
        rnd = self._current_record()
        rnd["result"] = result
        rnd["dealer_idx"] = self.engine.dealer_idx
        rnd["names"] = self.names()
        rnd["player_ids"] = list(self.seats)
