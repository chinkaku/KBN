# -*- coding: utf-8 -*-
import sys, os, json, asyncio, time, secrets, logging
from typing import Dict, Optional, List
from dataclasses import dataclass, field

log = logging.getLogger("rooms")
log.setLevel(logging.DEBUG)
if not log.handlers:
    h = logging.StreamHandler(sys.stderr); h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    log.addHandler(h)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from game_engine import GameEngine, Tile, PlayerRole

TIMING = {'round': 8, 'spare': 20, 'claim_upper': 10, 'claim_other': 5, 'chow_pung_window': 3, 'bot_delay': 1.0}
DISCONNECT_GRACE = 30

@dataclass
class ClientSlot:
    idx: int
    name: str = ""
    connected: bool = False
    spare_sec: float = 0.0
    disconnect_at: float = 0.0
    ws: object = None  # 不参与 __init__, 手动赋值

class Room:
    def __init__(self, room_id: str, host_name: str = ""):
        self.room_id = room_id; self.host_name = host_name
        self.host_idx: int = 0             # 房主所在槽位
        self.engine = GameEngine(num_humans=4)
        self.slots: Dict[int, ClientSlot] = {}
        self.started = False
        self.timer_task = None; self.timer_deadline = 0
        self.timer_phase = ""; self.timer_checker = -1
        self.last_activity = time.time()
        self.chow_pending = False          # 吃牌已被喊出，正在3秒碰牌窗口
        self.chow_pung_window = {}         # {idx: ws} 抢占碰的玩家队列
        self.solo_mode = False             # 单机模式: 不限鸣牌时间
        self.debug_mode = False            # 调试模式: 不计入数据, 可指定手牌

    def _is_bot_name(self, name: str) -> bool:
        return name.startswith("伯特") or name.startswith("bot:") or name in ("摸打机器人", "对手")

    def _find_next_human(self) -> int:
        """找到下一个可接任房主的真人槽位, 没有返回 -1"""
        for i in range(4):
            if i == self.host_idx: continue
            s = self.slots.get(i)
            if s and s.connected and s.ws and not self._is_bot_name(s.name):
                return i
        return -1

    def _transfer_host(self, leaving_idx: int):
        """如果离开的是房主, 转移房主给下一个真人"""
        if leaving_idx != self.host_idx: return
        nxt = self._find_next_human()
        if nxt >= 0:
            self.host_idx = nxt
            self.host_name = self.slots[nxt].name
        # 没有真人可接任 -> 房间将在 cleanup_loop 中自动销毁

    def is_host(self, ws_or_name) -> bool:
        """检查 ws 或用户名是否属于房主"""
        if isinstance(ws_or_name, str):
            s = self.slots.get(self.host_idx)
            return s is not None and s.name == ws_or_name
        # WebSocket object
        s = self.slots.get(self.host_idx)
        return s is not None and s.ws is ws_or_name

    def join(self, ws, name: str) -> int:
        # 优先匹配已有槽位(无WS的预留槽或断线槽) —— 但跳过机器人槽
        log.debug("JOIN name=%s slots=%s", name, {i:(s.name,s.connected,s.ws is not None) for i,s in self.slots.items()})
        for i in range(4):
            if i in self.slots:
                s = self.slots[i]
                if self._is_bot_name(s.name):
                    continue
                if not s.ws or not s.connected:
                    log.debug("JOIN matched slot %d", i)
                    self.slots[i].ws = ws
                    self.slots[i].connected = True
                    self.slots[i].name = name
                    self.slots[i].disconnect_at = 0
                    self.last_activity = time.time()
                    if self.started and i < len(self.engine.players):
                        self.engine.players[i].is_human = True
                    return i
        for i in range(4):
            if i not in self.slots:
                log.debug("JOIN new slot %d", i)
                slot = ClientSlot(idx=i, name=name, connected=True)
                slot.ws = ws
                self.slots[i] = slot
                self.last_activity = time.time()
                if self.started and i < len(self.engine.players):
                    self.engine.players[i].is_human = not self._is_bot_name(name)
                return i
        # 兜底: 按名字匹配, 强制回收旧WS占着的槽位(解决等待页→游戏页的WS竞态)
        for i in range(4):
            if i in self.slots:
                s = self.slots[i]
                if self._is_bot_name(s.name):
                    continue
                if s.name == name:
                    log.debug("JOIN reclaiming slot %d by name", i)
                    self.slots[i].ws = ws
                    self.slots[i].connected = True
                    self.slots[i].disconnect_at = 0
                    self.last_activity = time.time()
                    if self.started and i < len(self.engine.players):
                        self.engine.players[i].is_human = True
                    return i
        log.debug("JOIN FAILED")
        return -1

    def add_bot(self, slot: int) -> bool:
        """房主在空槽位添加机器人(伯特)"""
        if slot < 0 or slot > 3: return False
        if slot in self.slots: return False
        bot_names = ["伯特1", "伯特2", "伯特3", "伯特4"]
        name = bot_names[slot] if slot < len(bot_names) else f"伯特{slot+1}"
        slot_obj = ClientSlot(idx=slot, name=name, connected=True)
        self.slots[slot] = slot_obj
        # 机器人: is_human=False (在 start_game 时统一设置)
        self.last_activity = time.time()
        return True

    def slot_status(self) -> dict:
        """返回4个槽位的状态 + 房主信息"""
        status = {}
        for i in range(4):
            if i in self.slots:
                s = self.slots[i]
                if self._is_bot_name(s.name):
                    status[i] = f"bot:{s.name}"
                else:
                    status[i] = s.name
            else:
                status[i] = ""
        result = {"slots": status, "host_idx": self.host_idx, "started": self.started}
        return result

    def _broadcast_log(self, msg: str):
        self.engine.add_log(msg)

    def leave(self, idx: int):
        if idx in self.slots:
            del self.slots[idx]
            self._transfer_host(idx)

    def disconnect(self, ws):
        for idx, slot in self.slots.items():
            if slot.ws == ws:
                log.debug("DISCONNECT slot %d (%s)", idx, slot.name)
                slot.connected = False; slot.disconnect_at = time.time(); slot.ws = None
                self._transfer_host(idx)

    def reconnect(self, ws, idx: int):
        if idx in self.slots: self.slots[idx].ws = ws; self.slots[idx].connected = True; self.slots[idx].disconnect_at = 0

    @property
    def player_count(self): return len(self.slots)
    @property
    def human_count(self): return sum(1 for s in self.slots.values() if s.connected and s.ws)

    def _player_state_for(self, viewer_idx: int):
        s = self.engine.get_state()
        s["human_hand"] = self.engine.players[viewer_idx].sorted_hand_shorthands()
        s["drawn_tile"] = self.engine.players[viewer_idx].drawn_tile.to_shorthand() if self.engine.players[viewer_idx].drawn_tile else None
        s["my_idx"] = viewer_idx
        s["room"] = {"id": self.room_id, "host_idx": self.host_idx, "players": {i: {"name": sl.name, "online": sl.connected} for i, sl in self.slots.items()}}
        if self.timer_deadline:
            remaining = max(0, self.timer_deadline - time.time())
            is_checker = (viewer_idx == self.timer_checker)
            s["timer"] = {
                "phase": self.timer_phase,
                "remaining": remaining,
                "checker": self.timer_checker,
                "visible": is_checker,  # 只有当事人看到具体数字
                "chow_window": self.chow_pending,  # 碰牌窗口标记
            }
        else:
            s["timer"] = None
        return s

    async def broadcast(self):
        for idx, slot in list(self.slots.items()):
            if slot.connected and slot.ws:
                try:
                    st = self._player_state_for(idx)
                    hh = st.get("human_hand", [])
                    log.debug("BROADCAST slot %d phase=%s hand=%dtiles", idx, self.engine.phase, len(hh))
                    await slot.ws.send_text(json.dumps({"type": "state", "data": st}, ensure_ascii=False))
                except Exception as e:
                    log.debug("BROADCAST FAIL slot %d: %s", idx, e)

    async def start_game(self):
        for idx in range(4):
            s = self.slots.get(idx)
            self.engine.players[idx].is_human = (s is not None and not self._is_bot_name(s.name))
        self.engine.start_round(); self.engine._auto_advance()
        await self.broadcast()
        if not self.engine.game_over: await self._start_timer()

    async def handle_action(self, ws, action_type: str, params: dict):
        player_idx = -1
        for idx, slot in self.slots.items():
            if slot.ws == ws: player_idx = idx; break
        if player_idx < 0: return

        # ---- 碰覆盖吃: 吃已被喊出但碰牌窗口未关 ----
        if action_type == 'pung' and self.chow_pending:
            # 撤销 pending chow, 立即执行 pung
            self._cancel_timer()
            self.chow_pending = False
            self.chow_pung_window = {}
            # 还原引擎到 CLAIM_PK 状态 (chow 还未真正执行)
            if self.engine.phase == 'CLAIM_CHOW':
                self.engine.phase = 'CLAIM_PK'
                self.engine._claim_idx = 0
            # 执行 pung
            self.engine.current_player_idx = self.engine._last_discarder
            self.engine.do_action('pung')
            await self.broadcast()
            if not self.engine.game_over: await self._start_timer()
            return

        # ---- 吃被喊出, 启动3秒碰牌窗口 ----
        if action_type == 'chow' and self.engine.phase == 'CLAIM_CHOW':
            self.chow_pending = True
            self.chow_pung_window[player_idx] = time.time()
            # 暂时不执行吃, 先广播碰牌窗口给所有人
            await self.broadcast()
            # 启动3秒碰牌窗口
            self.timer_deadline = time.time() + TIMING['chow_pung_window']
            self.timer_phase = 'CHOW_PUNG_WINDOW'
            self.timer_checker = -1  # 没有特定等待者
            self.timer_task = asyncio.create_task(self._chow_pung_window_tick())
            return

        # ---- 正常操作 ----
        try: self.engine.do_action(action_type, stepwise=True, auto_advance=False, **params)
        except Exception as e: print(f"[Room] Action error: {e}"); return
        self._cancel_timer()
        self.chow_pending = False
        self.chow_pung_window = {}
        await self._bot_advance_loop()

    def _needs_human_input(self) -> bool:
        """判断引擎当前是否需要人类决策"""
        ph = self.engine.phase
        if ph in ('DISCARD', 'SELF_MELD'):
            return self.engine.players[self.engine.current_player_idx].is_human
        if ph == 'CLAIM_PK':
            chk = self.engine._claim_check_player()
            return chk is not None and chk.is_human and self.engine._has_any_claim(chk)
        if ph == 'CLAIM_CHOW':
            chk = self.engine._claim_check_player()
            return chk is not None and chk.is_human
        if ph == 'DRAW':
            # DRAW 阶段人类自动摸牌, 但 bot 需要推进
            return False
        return False

    async def _bot_advance_loop(self):
        """逐一推进bot回合, 每步广播+延时, 直到人类需要决策"""
        bd = TIMING['bot_delay']
        while not self.engine.game_over:
            # 杠牌后补牌: 处理 _skip_rest
            if getattr(self.engine, '_skip_rest', False):
                self.engine._auto_advance(stepwise=True)
                continue
            # 人类在DRAW阶段不用等, 直接自动摸牌
            if self.engine.phase == 'DRAW' and self.engine.players[self.engine.current_player_idx].is_human:
                self.engine._auto_advance(stepwise=True)
                continue
            if self._needs_human_input():
                break
            await self.broadcast()
            await asyncio.sleep(bd)
            self._cancel_timer()
            self.engine._auto_advance(stepwise=True)
        await self.broadcast()
        if not self.engine.game_over:
            await self._start_timer()

    def _cancel_timer(self):
        if self.timer_task and not self.timer_task.done(): self.timer_task.cancel()
        self.timer_task = None; self.timer_deadline = 0; self.timer_checker = -1

    async def _start_timer(self):
        self._cancel_timer()
        if self.solo_mode: return  # 单机模式不限时
        sec = 0; checker = -1; cp = self.engine.players[self.engine.current_player_idx]; ph = self.engine.phase
        if ph in ("DRAW", "SELF_MELD", "DISCARD") and cp.is_human:
            sec = TIMING["round"]; checker = self.engine.current_player_idx
        elif ph == "CLAIM_PK":
            chk = self.engine._claim_check_player()
            if chk is not None and chk.is_human:
                co = getattr(self.engine, "_claim_order", []); ci = getattr(self.engine, "_claim_idx", 0)
                if ci < len(co): checker = co[ci]
                rel = (checker - self.engine.current_player_idx) % 4
                sec = TIMING["claim_upper"] if rel == 1 else TIMING["claim_other"]
        elif not self.solo_mode and ph == "CLAIM_CHOW":
            chk = self.engine._claim_check_player()
            if chk is not None and chk.is_human:
                checker = self.engine._next_idx(self.engine.current_player_idx); sec = TIMING["claim_upper"]
        if sec > 0 and checker >= 0:
            self.timer_deadline = time.time() + sec; self.timer_phase = ph; self.timer_checker = checker
            self.timer_task = asyncio.create_task(self._timer_tick(sec, checker))

    async def _chow_pung_window_tick(self):
        """吃牌后的3秒碰牌窗口: 超时后完成吃牌"""
        await asyncio.sleep(TIMING['chow_pung_window'])
        if self.chow_pending and self.engine.phase == 'CLAIM_CHOW':
            # 无人碰, 完成吃牌
            self.engine.do_action('chow', choice=0)  # 默认第一组吃法
            self.engine._auto_advance()
            self._cancel_timer()
            self.chow_pending = False
            self.chow_pung_window = {}
            await self.broadcast()
            if not self.engine.game_over: await self._start_timer()

    async def _timer_tick(self, total_sec: int, checker: int):
        await asyncio.sleep(total_sec)
        if self.solo_mode: return  # 单机模式永不自动操作(兜底)
        if self.engine.phase in ("CLAIM_PK", "CLAIM_CHOW"):
            self.engine._do_pass_claim(); self.engine._auto_advance(stepwise=True)
        else:
            cp = self.engine.players[self.engine.current_player_idx]
            if cp.hand and self.engine.phase == "DISCARD": self.engine._do_discard(cp.hand[-1].to_shorthand())
            elif cp.hand and self.engine.phase == "SELF_MELD": self.engine._do_skip_self_meld()
            self.engine._auto_advance(stepwise=True)
        self._cancel_timer()
        await self._bot_advance_loop()

    async def check_disconnects(self):
        for idx, slot in list(self.slots.items()):
            if not slot.connected and slot.disconnect_at > 0 and time.time() - slot.disconnect_at > DISCONNECT_GRACE:
                self.engine.players[idx].is_human = False; slot.disconnect_at = -1
                if self.engine.current_player_idx == idx:
                    self.engine._auto_advance(); await self.broadcast()
                    if not self.engine.game_over: await self._start_timer()

rooms: Dict[str, Room] = {}
def create_room(host: str = ""): rid = secrets.token_hex(3).upper()[:6]; rooms[rid] = Room(rid, host); return rid
def get_room(rid: str): return rooms.get(rid)
