#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""组合麻将 · 联机 WebSocket 端到端冒烟测试（真实 TCP/WS 连接，只读不改服务端）

参考 mmcr14.online 的 backend/tests/integration/ws_smoke.py 的写法与覆盖面，
针对本仓库 branches/networking 的新联机架构（protocol.py / hub.py / session.py / server.py）。

覆盖项：
  1) 注册 + 登录 4 名随机用户（另加 1 名观战用户）拿到 token
  2) 4 个客户端连 /ws/lobby，收到 lobby.list.snapshot（附 ping→pong、wrong_socket 路由校验）
  3) HTTP 建桌 → 3 人加入 → 4 人准备 → 房主开局，各自收到含 started 的 session.snapshot
  4) 4 人连 /ws/game 并请求全量快照，校验 viewer.hand（13 张；庄家已自动摸牌时 14 张）
  5) 用收到的快照驱动真人 game.input，直到一局结束或超时；校验 ack 与非空 game.event
  6) 输入幂等：过期 stage_counter → error(stale_input)
  7) 断线重连：重新收到 session.snapshot 且手牌还在
  8) 观战：/ws/spectate 订阅该局，收到快照且 spectator 为真
  9) 大厅列表能看到该对局（active_sessions 非空）

执行顺序（不是 1→9，为了让"重连/观战"在牌局仍在进行时完成）：
  1 → 2 → 3 → 4 → 7 → 9 → 5（含 6、8）

前置：服务器已在 127.0.0.1:8766 运行（python run_server_8766.py）
运行：$env:PYTHONIOENCODING='utf-8'; python -u test_ws_smoke.py
退出码：全部通过 0 / 有失败 1 / 缺少 WebSocket 客户端库时跳过 0 / 服务器不可达 2
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid

try:  # Windows 控制台编码
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ---------------------------------------------------------------- 配置
HOST = os.environ.get("CMJ_TEST_HOST", "127.0.0.1")
PORT = int(os.environ.get("CMJ_TEST_PORT", "8766"))
BASE_HTTP = f"http://{HOST}:{PORT}"
BASE_WS = f"ws://{HOST}:{PORT}"
PASSWORD = "smoke-pass-1234"
ROUND_COUNT = 4           # PendingSession 只接受 4/8/16
TOTAL_BUDGET_S = 115.0    # 整体上限（要求 120s 内跑完）
DRIVER_BUDGET_S = 30.0    # 真人驱动最长时长

created_usernames = []    # 本次运行创建的测试账号(结束时清理)


# ---------------------------------------------------------------- 结果记录
ITEM_TITLES = {
    1: "注册/登录 5 个随机用户（4 选手 + 1 观战），拿到 token",
    2: "4 个客户端连 /ws/lobby，收到 lobby.list.snapshot",
    3: "HTTP 建桌 → 加入 → 准备 → 房主开局，各自收到 started 快照",
    4: "4 人连 /ws/game，收到 session.snapshot 且 viewer.hand 13 张",
    5: "真实驱动 4 名真人 game.input，直到一局结束或超时（ack + game.event）",
    6: "输入幂等：过期 stage_counter → error(stale_input)",
    7: "断线重连：重新收到 session.snapshot 且手牌还在",
    8: "观战：/ws/spectate 订阅该局，收到快照且 spectator 为真",
    9: "大厅列表能看到该对局（active_sessions 非空）",
}


class Item:
    def __init__(self, idx, title):
        self.idx = idx
        self.title = title
        self.subs = []
        self.started = False

    def begin(self):
        if not self.started:
            self.started = True
            print(f"\n[{self.idx}] {self.title}", flush=True)
        return self

    def check(self, name, cond, detail=""):
        ok = bool(cond)
        self.subs.append((ok, name, detail))
        line = f"    {'✓' if ok else '✗'} {name}"
        if detail:
            line += f"  — {detail}"
        print(line, flush=True)
        return ok

    @property
    def ok(self):
        return bool(self.subs) and all(s[0] for s in self.subs)

    def counts(self):
        p = sum(1 for s in self.subs if s[0])
        return p, len(self.subs) - p


ITEMS = {i: Item(i, t) for i, t in ITEM_TITLES.items()}
OBSERVATIONS = []


def item(idx):
    return ITEMS[idx].begin()


def info(text):
    print(f"    ℹ {text}", flush=True)


def observe(title, detail):
    OBSERVATIONS.append((title, detail))
    print(f"    ⚠ 观察: {title} — {detail}", flush=True)


def finalize_items():
    for i in sorted(ITEMS):
        if not ITEMS[i].subs:
            ITEMS[i].begin().check("该测试项未执行到（前序步骤失败或整体超时）", False)


# ---------------------------------------------------------------- HTTP（标准库）
def _http_sync(method, path, token=None, body=None, timeout=10.0):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(BASE_HTTP + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            status = resp.status
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        status = exc.code
    try:
        parsed = json.loads(raw) if raw.strip() else None
    except Exception:
        parsed = {"_raw": raw}
    return status, parsed


async def http(method, path, token=None, body=None, timeout=10.0):
    return await asyncio.to_thread(_http_sync, method, path, token, body, timeout)


# ---------------------------------------------------------------- WebSocket 客户端
_WEBSOCKETS = None
_WS_CLIENT = None
BACKEND = None


def detect_backend():
    """优先 websockets(asyncio)，退回 websocket-client(同步)，都没有则跳过"""
    global _WEBSOCKETS, _WS_CLIENT, BACKEND
    want = (os.environ.get("CMJ_WS_BACKEND") or "").strip().lower()
    if want in ("", "websockets", "ws", "async"):
        try:
            import websockets  # type: ignore
            _WEBSOCKETS = websockets
            BACKEND = "websockets"
            return
        except Exception as exc:
            print(f"  · 未安装 websockets（{exc.__class__.__name__}），改用 websocket-client …")
    if want in ("", "client", "websocket-client"):
        try:
            import websocket  # type: ignore  # websocket-client
            _WS_CLIENT = websocket
            BACKEND = "client"
            return
        except Exception as exc:
            print(f"  · 未安装 websocket-client（{exc.__class__.__name__}）")
    BACKEND = None


class AsyncWsConn:
    """websockets（asyncio）后端"""

    def __init__(self, raw):
        self.raw = raw

    async def recv(self, timeout=None):
        if timeout is None:
            return await self.raw.recv()
        return await asyncio.wait_for(self.raw.recv(), timeout)

    async def send(self, text):
        await self.raw.send(text)

    async def close(self):
        try:
            await self.raw.close()
        except Exception:
            pass


class ThreadWsConn:
    """websocket-client（同步）→ asyncio 适配：后台线程读入队列"""

    def __init__(self, url, timeout=10.0):
        self._ws = _WS_CLIENT.create_connection(url, timeout=timeout)
        self._queue = asyncio.Queue()
        self._loop = asyncio.get_running_loop()
        self._lock = threading.Lock()
        self._closed = False
        self._thread = threading.Thread(target=self._reader, name="ws-reader", daemon=True)
        self._thread.start()

    def _reader(self):
        try:
            while not self._closed:
                msg = self._ws.recv()
                if not msg:
                    break
                self._loop.call_soon_threadsafe(self._queue.put_nowait, msg)
        except Exception:
            pass
        finally:
            try:
                self._loop.call_soon_threadsafe(self._queue.put_nowait, None)
            except Exception:
                pass

    async def recv(self, timeout=None):
        if timeout is None:
            got = await self._queue.get()
        else:
            got = await asyncio.wait_for(self._queue.get(), timeout)
        if got is None:
            raise ConnectionError("websocket 已关闭")
        return got

    async def send(self, text):
        with self._lock:
            self._ws.send(text)

    async def close(self):
        self._closed = True
        try:
            self._ws.close()
        except Exception:
            pass


async def open_conn(url):
    if BACKEND == "websockets":
        kwargs = dict(open_timeout=10, close_timeout=2, max_size=None, ping_interval=20)
        try:
            raw = await _WEBSOCKETS.connect(url, proxy=None, **kwargs)
        except TypeError:            # 老版本 websockets 无 proxy 参数
            raw = await _WEBSOCKETS.connect(url, **kwargs)
        return AsyncWsConn(raw)
    return ThreadWsConn(url)


class Client:
    """一个真实 WS 连接：后台读消息、可等待指定条件、可随时重连"""

    def __init__(self, label, token, path):
        self.label = label
        self.token = token
        self.path = path
        self.conn = None
        self.reader = None
        self.messages = []
        self.queue = asyncio.Queue()
        self.closed = False
        self.reader_error = None
        self.latest_viewer = None
        self.latest_state = None
        self.latest_stage = 0
        self._send_lock = asyncio.Lock()
        self._seq = 0

    async def connect(self):
        url = f"{BASE_WS}{self.path}?access_token={urllib.parse.quote(self.token)}"
        self.conn = await open_conn(url)
        self.closed = False
        self.reader = asyncio.create_task(self._read_loop(), name=f"reader-{self.label}")
        return self

    async def _read_loop(self):
        try:
            while True:
                raw = await self.conn.recv()
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                if not isinstance(msg, dict):
                    continue
                self.messages.append(msg)
                self._track(msg)
                self.queue.put_nowait(msg)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.reader_error = exc
        finally:
            self.queue.put_nowait(None)

    def _track(self, msg):
        payload = msg.get("payload")
        if not isinstance(payload, dict):
            return
        session = payload.get("session")
        viewer = payload.get("viewer")
        if viewer is None and isinstance(session, dict):
            viewer = session.get("viewer")
        if isinstance(viewer, dict):
            self.latest_viewer = viewer
            try:
                stage = int(viewer.get("stage_counter") or 0)
            except Exception:
                stage = 0
            if stage > self.latest_stage:
                self.latest_stage = stage
        state = payload.get("state")
        if state is None and isinstance(session, dict):
            state = session.get("state")
        if isinstance(state, dict):
            self.latest_state = state

    async def send(self, message):
        async with self._send_lock:
            await self.conn.send(json.dumps(message, ensure_ascii=False))

    async def request(self, msg_type, payload=None, request_id=None):
        self._seq += 1
        rid = request_id or f"{self.label}-{msg_type}-{self._seq}"
        await self.send({"version": 1, "type": msg_type, "payload": payload or {}, "requestId": rid})
        return rid

    async def expect(self, predicate, timeout, desc):
        for msg in self.messages:          # 先扫历史（快照可能在等待前就到了）
            if predicate(msg):
                return msg
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                recent = [m.get("type") for m in self.messages[-8:]]
                raise AssertionError(f"{self.label}: 等待「{desc}」超时（{timeout}s，最近消息 {recent}）")
            try:
                msg = await asyncio.wait_for(self.queue.get(), remaining)
            except asyncio.TimeoutError:
                continue
            if msg is None:
                raise AssertionError(f"{self.label}: 连接已关闭，等待「{desc}」失败")
            if predicate(msg):
                return msg

    async def close(self):
        self.closed = True
        if self.reader is not None:
            self.reader.cancel()
            try:
                await self.reader
            except (asyncio.CancelledError, Exception):
                pass
            self.reader = None
        if self.conn is not None:
            await self.conn.close()
            self.conn = None


def envelope_type(msg):
    return msg.get("type")


def payload_of(msg):
    p = msg.get("payload")
    return p if isinstance(p, dict) else {}


def session_of(msg):
    s = payload_of(msg).get("session")
    return s if isinstance(s, dict) else {}


def snapshot_predicate(session_id=None, request_id=None):
    def _pred(msg):
        if envelope_type(msg) != "session.snapshot":
            return False
        if request_id is not None and msg.get("requestId") != request_id:
            return False
        sess = session_of(msg)
        if session_id is not None and sess.get("session_id") != session_id:
            return False
        return True

    return _pred


# ---------------------------------------------------------------- 真人驱动
PASS_TYPES = ("pass", "skip")


def pick_action(actions):
    for a in actions:                      # 优先和牌
        if a.get("type") in ("tsumo", "ron"):
            return a
    for a in actions:
        if a.get("type") not in PASS_TYPES:
            return a
    return actions[0] if actions else None


def build_input(pick, stage):
    kind = pick.get("type")
    payload = {"kind": kind, "stage_counter": stage}
    if kind == "discard":
        tiles = pick.get("tiles") or []
        if not tiles:
            return None
        payload["tile"] = tiles[-1]
    elif kind in ("dark_kong", "add_kong"):
        payload["tile"] = pick.get("tile")
        if pick.get("meld_idx") is not None:
            payload["meld_idx"] = pick["meld_idx"]
    elif kind == "chow":
        payload["choice"] = 0
    return payload


class Driver:
    """用服务端快照驱动 4 名真人：轮到自己就发 game.input

    注意：viewer.available_actions 是"当前决策者"的选项（所有视角共用，见报告中的信息泄露观察），
    因此必须先确定"决策座位"再决定由哪个客户端发送。
      · DISCARD / SELF_MELD → viewer.current_player_idx
      · CLAIM_CHOW         → 下家 (current_player_idx + 1) % 4
      · CLAIM_PK           → 三档计时器的 timer.checker（推送事件里恒为 null，需 game.snapshot 探一次）
    """

    def __init__(self, clients_by_seat):
        self.clients = clients_by_seat
        self.acted_stage = {}
        self.sent = 0
        self.acks = 0
        self.ack_by_seat = {}
        self.events = 0
        self.empty_events = 0
        self.round_ends = 0
        self.session_ends = 0
        self.err_codes = {}
        self.kinds = {}
        self.probes = 0
        self.probe_failures = 0
        self.error = None
        self.stop = False
        self._seq = 0
        self._cursor = {}
        self._claim_seat = {}

    # ---- 统计 ----
    def _scan(self):
        for seat, cli in list(self.clients.items()):
            msgs = cli.messages
            start = self._cursor.get(cli, 0)
            for msg in msgs[start:]:
                self._on_message(seat, msg)
            self._cursor[cli] = len(msgs)

    def _on_message(self, seat, msg):
        mtype = envelope_type(msg)
        rid = str(msg.get("requestId") or "")
        if mtype == "ack":
            if rid.startswith("input-s"):
                self.acks += 1
                try:
                    who = int(rid.split("-")[1][1:])
                except Exception:
                    who = seat
                self.ack_by_seat[who] = self.ack_by_seat.get(who, 0) + 1
        elif mtype == "error":
            if rid.startswith("input-s"):
                code = payload_of(msg).get("code")
                self.err_codes[code] = self.err_codes.get(code, 0) + 1
        elif mtype == "game.event":
            p = payload_of(msg)
            if p.get("event"):
                self.events += 1
            else:
                self.empty_events += 1
            cat = p.get("category")
            if cat == "round_end":
                self.round_ends += 1
            elif cat == "session_end":
                self.session_ends += 1

    # ---- 决策座位判定 ----
    def _live_client(self):
        for seat in sorted(self.clients):
            cli = self.clients[seat]
            if cli is not None and cli.conn is not None and not cli.closed:
                return cli
        return None

    async def _probe_claim_seat(self, stage):
        """CLAIM_PK 阶段：推送事件里 viewer.timer 恒为 null（见报告中的计时器观察），
        只能靠 game.snapshot 拿到 timer.checker；且该快照必须在"决策计时器已挂上"之后取，
        否则 timer 仍是 null —— 所以这里带重试。"""
        probe = self._live_client()
        if probe is None:
            return None
        self.probes += 1
        deadline = time.monotonic() + 1.2
        attempt = 0
        while time.monotonic() < deadline:
            attempt += 1
            rid = f"probe-s{stage}-{attempt}"
            mark = len(probe.messages)
            try:
                await probe.send({"version": 1, "type": "game.snapshot", "payload": {},
                                  "requestId": rid})
            except Exception:
                return None
            answer = None
            wait_until = time.monotonic() + 0.15
            while time.monotonic() < wait_until and answer is None:
                for msg in probe.messages[mark:]:
                    if msg.get("requestId") == rid:
                        answer = msg
                        break
                if answer is None:
                    await asyncio.sleep(0.005)
            if answer is None:
                continue
            viewer = session_of(answer).get("viewer") or {}
            timer = viewer.get("timer")
            if isinstance(timer, dict) and isinstance(timer.get("checker"), int) \
                    and timer["checker"] >= 0 and int(viewer.get("stage_counter") or 0) == stage:
                return timer["checker"]
        self.probe_failures += 1
        return None

    async def _decision_seat(self, viewer, stage, phase):
        if phase in ("DISCARD", "SELF_MELD"):
            cur = viewer.get("current_player_idx")
            return cur if isinstance(cur, int) else None
        if phase == "CLAIM_CHOW":
            cur = viewer.get("current_player_idx")
            return (int(cur) + 1) % 4 if isinstance(cur, int) else None
        key = (stage, phase)
        if key in self._claim_seat:
            return self._claim_seat[key]
        timer = viewer.get("timer")
        checker = None
        if isinstance(timer, dict) and isinstance(timer.get("checker"), int) and timer["checker"] >= 0:
            checker = timer["checker"]
        if checker is None:
            checker = await self._probe_claim_seat(stage)
        self._claim_seat[key] = checker
        return checker

    # ---- 主循环 ----
    async def run(self, deadline):
        try:
            while not self.stop and time.monotonic() < deadline:
                self._scan()
                progressed = False
                for seat in sorted(self.clients):
                    cli = self.clients.get(seat)
                    if cli is None or cli.conn is None or cli.closed:
                        continue
                    viewer = cli.latest_viewer
                    if not isinstance(viewer, dict) or viewer.get("game_over"):
                        continue
                    if viewer.get("seat_index") != seat:      # 保险：只用本人视角
                        continue
                    phase = viewer.get("phase")
                    stage = int(viewer.get("stage_counter") or 0)
                    actions = viewer.get("available_actions") or []
                    if not actions:                      # 没有可执行动作 → 不需要判定决策座位
                        continue
                    if self.acted_stage.get(seat) == stage:
                        continue
                    if await self._decision_seat(viewer, stage, phase) != seat:
                        continue
                    pick = pick_action(actions)
                    payload = build_input(pick, stage) if pick else None
                    if not payload:
                        continue
                    self.acted_stage[seat] = stage
                    self._seq += 1
                    rid = f"input-s{seat}-{self._seq}"
                    self.kinds[pick["type"]] = self.kinds.get(pick["type"], 0) + 1
                    try:
                        await cli.send({"version": 1, "type": "game.input",
                                        "payload": payload, "requestId": rid})
                        self.sent += 1
                        progressed = True
                    except Exception:
                        self.acted_stage.pop(seat, None)
                if not progressed:
                    await asyncio.sleep(0.005)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.error = f"{exc.__class__.__name__}: {exc}"
        finally:
            try:
                self._scan()
            except Exception:
                pass


# ---------------------------------------------------------------- 附加探针
def probe_available_actions_leak(clients):
    """非当前行动者是否收到「当前决策者的 available_actions」（discard.tiles 实为其手牌）"""
    hits = []
    for cli in clients:
        for msg in cli.messages:
            if envelope_type(msg) != "game.event":
                continue
            viewer = payload_of(msg).get("viewer") or {}
            if viewer.get("spectator") or viewer.get("seat_index") is None:
                continue
            if viewer.get("seat_index") == viewer.get("current_player_idx"):
                continue
            for act in (viewer.get("available_actions") or []):
                if act.get("type") == "discard" and act.get("tiles"):
                    if list(act["tiles"]) != list(viewer.get("hand") or []):
                        hits.append((cli.label, viewer.get("seat_index"), viewer.get("current_player_idx"),
                                     list(act["tiles"])[:4], list(viewer.get("hand") or [])[:4]))
                        break
    return hits


def probe_spectator_drawn_tile(clients):
    """观战/他人视角里是否出现了别的座位的 drawn_tile"""
    hits = []
    for cli in clients:
        for msg in cli.messages:
            p = payload_of(msg)
            viewer = p.get("viewer") or {}
            if not viewer.get("spectator"):
                continue
            for idx, ps in enumerate((p.get("state") or {}).get("players") or []):
                if isinstance(ps, dict) and ps.get("drawn_tile"):
                    hits.append((cli.label, idx, ps.get("drawn_tile")))
    return hits


# ---------------------------------------------------------------- 主流程
async def run_all():
    uniq = uuid.uuid4().hex[:6]
    player_names = [f"w{uniq}{i}" for i in range(4)]
    observer_name = f"w{uniq}ob"
    # 记录本次创建的账号, 供 main() 结束时清理(避免污染 users.json)
    created_usernames.clear()
    created_usernames.extend(player_names + [observer_name])
    player_tokens = []
    observer_token = None
    session_id = None
    lobby_clients = []
    observer_lobby = None
    observer_spectate = None
    game_clients = []
    clients_by_seat = {}
    initial_hands = {}
    driver = None
    driver_task = None

    try:
        # ============ 1) 注册 / 登录 ============
        it = item(1)
        ok_reg = True
        ok_login = True
        details = []
        for name in player_names:
            status, body = await http("POST", "/api/auth/register", body={"user": name, "pass": PASSWORD})
            tok = (body or {}).get("token") if isinstance(body, dict) else None
            if status != 200 or not tok:
                ok_reg = False
                details.append(f"register({name}) status={status} body={str(body)[:100]}")
                continue
            status2, body2 = await http("POST", "/api/auth/login", body={"user": name, "pass": PASSWORD})
            tok2 = (body2 or {}).get("token") if isinstance(body2, dict) else None
            if status2 != 200 or not tok2:
                ok_login = False
                details.append(f"login({name}) status={status2} body={str(body2)[:100]}")
            player_tokens.append(tok2 or tok)
        it.check("POST /api/auth/register 注册 4 名随机用户并返回 token", ok_reg and len(player_tokens) == 4,
                 "; ".join(details))
        it.check("POST /api/auth/login 登录同一批用户并返回 token", ok_login and len(player_tokens) == 4,
                 "; ".join(details))
        bad_status, bad_body = await http("POST", "/api/auth/login", body={"user": player_names[0], "pass": "wrong-pass"})
        it.check("错误密码登录被拒（不返回 token）",
                 isinstance(bad_body, dict) and not bad_body.get("token"),
                 f"status={bad_status} body={str(bad_body)[:100]}")

        obs_body = None
        status, obs_body = await http("POST", "/api/auth/register", body={"user": observer_name, "pass": PASSWORD})
        observer_token = (obs_body or {}).get("token") if isinstance(obs_body, dict) else None
        if not observer_token:
            status, obs_body = await http("POST", "/api/auth/login", body={"user": observer_name, "pass": PASSWORD})
            observer_token = (obs_body or {}).get("token") if isinstance(obs_body, dict) else None
        it.check("观战用户注册/登录成功", bool(observer_token), f"status={status} body={str(obs_body)[:100]}")

        # ============ 2) 大厅 WS ============
        it = item(2)
        snap_ok = True
        snap_detail = []
        stage_counts = []
        for i, tok in enumerate(player_tokens):
            cli = Client(f"P{i}/lobby", tok, "/ws/lobby")
            await cli.connect()
            lobby_clients.append(cli)
            try:
                snap = await cli.expect(lambda m: envelope_type(m) == "lobby.list.snapshot", 6.0,
                                        "初始 lobby.list.snapshot")
            except AssertionError as exc:
                snap_ok = False
                snap_detail.append(str(exc))
                continue
            p = payload_of(snap)
            if not isinstance(p.get("sessions"), list) or not isinstance(p.get("active_sessions"), list):
                snap_ok = False
                snap_detail.append(f"P{i} payload 缺少 sessions/active_sessions: {str(p)[:120]}")
            else:
                stage_counts.append((len(p["sessions"]), len(p["active_sessions"])))
        it.check("4 个 /ws/lobby 连接各收到 lobby.list.snapshot（含 sessions/active_sessions）",
                 snap_ok, "; ".join(snap_detail) or f"初始 (sessions, active_sessions)={stage_counts}")

        rid = await lobby_clients[0].request("ping", {"identifier": "smoke"})
        try:
            pong = await lobby_clients[0].expect(
                lambda m: envelope_type(m) == "pong" and m.get("requestId") == rid, 5.0, "pong")
            it.check("大厅连接 ping → pong（回同一 requestId）", payload_of(pong).get("identifier") == "smoke")
        except AssertionError as exc:
            it.check("大厅连接 ping → pong（回同一 requestId）", False, str(exc))

        rid = await lobby_clients[0].request("game.input", {"kind": "discard"})
        try:
            err = await lobby_clients[0].expect(
                lambda m: m.get("requestId") == rid and envelope_type(m) in ("ack", "error"), 5.0, "wrong_socket 错误")
            code = payload_of(err).get("code")
            it.check("在 /ws/lobby 上发 game.input → error(wrong_socket)",
                     envelope_type(err) == "error" and code == "wrong_socket",
                     f"type={envelope_type(err)} code={code}")
        except AssertionError as exc:
            it.check("在 /ws/lobby 上发 game.input → error(wrong_socket)", False, str(exc))

        observer_lobby = Client("OBS/lobby", observer_token, "/ws/lobby")
        await observer_lobby.connect()
        await observer_lobby.expect(lambda m: envelope_type(m) == "lobby.list.snapshot", 6.0, "观战者大厅快照")

        # ============ 3) 建桌 / 加入 / 准备 / 开局 ============
        it = item(3)
        status, body = await http("POST", "/api/v1/lobby/sessions", token=player_tokens[0],
                                  body={"config": {"round_count": ROUND_COUNT,
                                                   "bot_delay_ms": 1, "round_pause_ms": 1}})
        sess = (body or {}).get("session") if isinstance(body, dict) else None
        sess = sess if isinstance(sess, dict) else {}
        session_id = sess.get("session_id")
        it.check("房主 POST /api/v1/lobby/sessions 建桌成功（phase=pending）",
                 status == 200 and isinstance(session_id, int) and sess.get("phase") == "pending",
                 f"status={status} body={str(body)[:160]}")
        if not isinstance(session_id, int):
            raise AssertionError(f"未能拿到 session_id: {str(body)[:200]}")

        for i, tok in enumerate(player_tokens):
            cli = Client(f"P{i}/game", tok, "/ws/game")
            await cli.connect()
            game_clients.append(cli)

        join_ok = True
        join_detail = []
        for i in (1, 2, 3):
            status, body = await http("POST", f"/api/v1/lobby/sessions/{session_id}/join", token=player_tokens[i])
            s = (body or {}).get("session") if isinstance(body, dict) else None
            s = s if isinstance(s, dict) else {}
            occupied = sum(1 for x in (s.get("seats") or []) if x.get("player_id"))
            if status != 200 or occupied != i + 1:
                join_ok = False
                join_detail.append(f"P{i}: status={status} 入座={occupied} body={str(body)[:110]}")
        it.check("其余 3 人经 HTTP join 成功（座位数 1→4）", join_ok, "; ".join(join_detail))

        ready_ok = True
        last_ready = {}
        for i, tok in enumerate(player_tokens):
            status, body = await http("POST", f"/api/v1/lobby/sessions/{session_id}/ready",
                                      token=tok, body={"ready": True})
            s = (body or {}).get("session") if isinstance(body, dict) else None
            s = s if isinstance(s, dict) else {}
            if status != 200 or not s:
                ready_ok = False
            last_ready = s
        summary = last_ready.get("summary") or {}
        it.check("4 人经 HTTP ready 成功（ready_seat_count=4, can_start=true）",
                 ready_ok and summary.get("ready_seat_count") == 4 and summary.get("can_start") is True,
                 f"ready_seat_count={summary.get('ready_seat_count')} can_start={summary.get('can_start')}")

        status, body = await http("POST", f"/api/v1/lobby/sessions/{session_id}/start", token=player_tokens[0])
        it.check("房主 POST …/start 开局成功", status == 200 and isinstance(body, dict) and body.get("ok") is True,
                 f"status={status} body={str(body)[:120]}")

        started_ok = True
        started_detail = []
        for i, cli in enumerate(game_clients):
            try:
                snap = await cli.expect(
                    lambda m: envelope_type(m) == "session.snapshot" and
                    (payload_of(m).get("started") is True or session_of(m).get("phase") == "active"), 6.0,
                    "started 快照")
                if session_of(snap).get("session_id") != session_id:
                    started_ok = False
                    started_detail.append(f"P{i}: session_id={session_of(snap).get('session_id')}")
            except AssertionError as exc:
                started_ok = False
                started_detail.append(str(exc))
        it.check("start 后 4 名玩家各收到 started=true / phase=active 的 session.snapshot",
                 started_ok, "; ".join(started_detail))

        # ============ 4) 4 人连 /ws/game + 全量快照 + 手牌 ============
        it = item(4)
        views = {}
        snap_ok = True
        snap_detail = []
        for i, cli in enumerate(game_clients):
            rid = await cli.request("game.snapshot")
            try:
                snap = await cli.expect(snapshot_predicate(session_id, rid), 6.0, "game.snapshot 全量快照")
            except AssertionError as exc:
                snap_ok = False
                snap_detail.append(str(exc))
                continue
            sess = session_of(snap)
            viewer = sess.get("viewer") or {}
            views[i] = (cli, sess, viewer)
            if viewer.get("seat_index") is None or not isinstance(viewer.get("hand"), list):
                snap_ok = False
                snap_detail.append(f"P{i}: viewer={str(viewer)[:120]}")
        it.check("4 人各收到含 viewer 的 session.snapshot（seat_index 覆盖 0~3）",
                 snap_ok and sorted(v.get("seat_index") for _, _, v in views.values()) == [0, 1, 2, 3],
                 "; ".join(snap_detail) or f"座位={[v.get('seat_index') for _, _, v in views.values()]}")

        for i, cli, viewer in [(i, c, v) for i, (c, _, v) in sorted(views.items())]:
            seat = viewer.get("seat_index")
            clients_by_seat[seat] = cli
            initial_hands[seat] = list(viewer.get("hand") or [])

        lens = {v.get("seat_index"): len(v.get("hand") or []) for _, _, v in views.values()}
        thirteen = [s for s, n in lens.items() if n == 13]
        fourteen = [s for s, n in lens.items() if n == 14]
        it.check("每名玩家的 viewer.hand 为 13 张（庄家自动摸牌后为 14 张）",
                 len(lens) == 4 and all(n in (13, 14) for n in lens.values()),
                 f"各座位手牌数={lens}")
        it.check("3 名非行动玩家手牌恰为 13 张", len(thirteen) >= 3, f"13 张的座位={thirteen} 14 张的座位={fourteen}")
        if fourteen:
            cur = (views[0][2].get("current_player_idx"))
            it.check("14 张的那个座位正是当前行动者（引擎开局已替庄家摸牌）", fourteen == [cur],
                     f"14 张={fourteen} current_player_idx={cur} phase={views[0][2].get('phase')}")
        it.check("玩家视角 spectator=False 且 stage_counter 为整数（可作幂等输入）",
                 all(v.get("spectator") is False and isinstance(v.get("stage_counter"), int)
                     for _, _, v in views.values()),
                 f"stages={[v.get('stage_counter') for _, _, v in views.values()]}")
        del i, cli, viewer

        # ============ 7) 断线重连（趁牌局刚开始，保证 session 仍 active）============
        it = item(7)
        victim_idx = 3
        victim = game_clients[victim_idx]
        vseat = None
        for seat, cli in clients_by_seat.items():
            if cli is victim:
                vseat = seat
        before_hand = list(initial_hands.get(vseat) or [])
        others = [c for s, c in clients_by_seat.items() if c is not victim]
        await victim.close()

        disc = None
        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline and disc is None:
            for cli in others:
                for msg in cli.messages:
                    if envelope_type(msg) == "game.event" and payload_of(msg).get("category") == "disconnect":
                        disc = msg
                        break
                if disc:
                    break
            await asyncio.sleep(0.02)
        it.check("服务端广播了 disconnect 事件（断线被识别）", disc is not None,
                 "已收到" if disc else "6s 内未收到 disconnect 事件")

        reconnected = Client(f"P{victim_idx}/game", player_tokens[victim_idx], "/ws/game")
        await reconnected.connect()
        try:
            snap = await reconnected.expect(snapshot_predicate(session_id), 6.0, "重连后的全量快照")
            sess = session_of(snap)
            viewer = sess.get("viewer") or {}
            hand = list(viewer.get("hand") or [])
            overlap = len(set(hand) & set(before_hand))
            it.check("重连后立即收到 session.snapshot（含 viewer）", viewer.get("seat_index") == vseat,
                     f"seat_index={viewer.get('seat_index')} stage={viewer.get('stage_counter')}")
            it.check("重连后手牌还在（viewer.hand >= 13 张）", len(hand) >= 13, f"len={len(hand)}")
            it.check("手牌与断线前高度重合（>= 10 张相同）", overlap >= 10,
                     f"重合 {overlap} 张 / 断线前 {len(before_hand)} 张")
            seat_status = {x.get("seat_index"): x for x in (sess.get("seat_status") or [])}
            flag = (seat_status.get(vseat) or {}).get("disconnected")
            if flag:
                observe("重连后 seat_status.disconnected 未清除",
                        f"座位 {vseat} 重连后 seat_status.disconnected 仍为 True —— hub.disconnect 只写入、"
                        f"hub.connect 从不清除（hub.py:116 / hub.py:89），超过 DISCONNECT_GRACE_MS=60s 后"
                        f"_is_auto() 会把这个已重连的座位当成掉线代打")
        except AssertionError as exc:
            it.check("重连后立即收到 session.snapshot（含 viewer）", False, str(exc))
        game_clients[victim_idx] = reconnected
        clients_by_seat[vseat] = reconnected

        # ============ 9) 大厅列表（观战者的大厅 WS 仍在，稍后会切到 spectate）============
        it = item(9)
        status, body = await http("GET", "/api/v1/lobby/sessions", token=observer_token)
        body = body if isinstance(body, dict) else {}
        active_ids = [s.get("session_id") for s in (body.get("active_sessions") or [])]
        pending_ids = [s.get("session_id") for s in (body.get("sessions") or [])]
        it.check("GET /api/v1/lobby/sessions 的 active_sessions 含本局",
                 status == 200 and session_id in active_ids, f"active_sessions={active_ids}")
        it.check("已开局的会话不再出现在等待房 sessions 列表", session_id not in pending_ids,
                 f"sessions={pending_ids}")
        try:
            await observer_lobby.expect(
                lambda m: envelope_type(m) == "lobby.list.snapshot" and
                any(s.get("session_id") == session_id
                    for s in (payload_of(m).get("active_sessions") or [])), 6.0, "含本局的大厅推送")
            it.check("大厅订阅者收到含该对局的 lobby.list.snapshot 推送", True)
        except AssertionError as exc:
            it.check("大厅订阅者收到含该对局的 lobby.list.snapshot 推送", False, str(exc))

        # ============ 5) 真人驱动 + 6) 幂等 + 8) 观战 ============
        info("开始用快照驱动 4 名真人出牌 …")
        driver = Driver(clients_by_seat)
        driver_deadline = time.monotonic() + DRIVER_BUDGET_S
        driver_task = asyncio.create_task(driver.run(driver_deadline))

        # ---- 等 stage_counter >= 2（说明已经有真人动作被处理）----
        stage_now = 0
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            stage_now = max([c.latest_stage for c in game_clients if c.conn] or [0])
            if stage_now >= 2:
                break
            await asyncio.sleep(0.02)

        # ============ 6) 输入幂等 ============
        it = item(6)
        it.check("观察到 stage_counter >= 2（可用于构造过期输入）", stage_now >= 2, f"stage_counter={stage_now}")
        if stage_now >= 2:
            target = None
            for seat in sorted(clients_by_seat):
                cli = clients_by_seat[seat]
                v = cli.latest_viewer or {}
                if v.get("seat_index") != v.get("current_player_idx"):
                    target = cli
                    break
            if target is None:
                target = clients_by_seat[sorted(clients_by_seat)[0]]
            stale_stage = stage_now - 1
            tile = (target.latest_viewer or {}).get("hand") or ["1m"]
            rid = f"stale-check-{uuid.uuid4().hex[:6]}"
            await target.send({"version": 1, "type": "game.input",
                               "payload": {"kind": "discard", "stage_counter": stale_stage,
                                           "tile": tile[-1]},
                               "requestId": rid})
            try:
                err = await target.expect(
                    lambda m: m.get("requestId") == rid and envelope_type(m) in ("ack", "error"), 6.0,
                    "stale_input 错误")
                code = payload_of(err).get("code")
                it.check(f"过期输入（stage_counter={stale_stage} < 当前 {stage_now}）被拒为 stale_input",
                         envelope_type(err) == "error" and code == "stale_input",
                         f"type={envelope_type(err)} code={code} message={payload_of(err).get('message')}")
            except AssertionError as exc:
                it.check("过期输入被拒为 stale_input", False, str(exc))

        # ============ 8) 观战（牌局仍在进行中）============
        it = item(8)
        observer_spectate = Client("OBS/spectate", observer_token, "/ws/spectate")
        await observer_spectate.connect()
        rid = await observer_spectate.request("spectate.subscribe", {"session_id": session_id})
        try:
            snap = await observer_spectate.expect(snapshot_predicate(session_id), 6.0, "观战 session.snapshot")
            sess = session_of(snap)
            viewer = sess.get("viewer") or {}
            it.check("spectate.subscribe 后收到该局的 session.snapshot", True,
                     f"session_id={sess.get('session_id')} phase={sess.get('phase')}")
            it.check("session.spectator 与 viewer.spectator 均为真",
                     sess.get("spectator") is True and viewer.get("spectator") is True,
                     f"session.spectator={sess.get('spectator')} viewer.spectator={viewer.get('spectator')}")
            it.check("观战视角不泄露手牌（viewer 无 hand 字段）", "hand" not in viewer,
                     f"viewer keys={sorted(viewer.keys())}")
            it.check("观战视角 available_actions 为空", (viewer.get("available_actions") or []) == [],
                     f"available_actions={viewer.get('available_actions')}")
            it.check("观战视角 seat_index=-1（不在座）", viewer.get("seat_index") == -1,
                     f"seat_index={viewer.get('seat_index')}")
        except AssertionError as exc:
            it.check("spectate.subscribe 后收到该局的 session.snapshot", False, str(exc))
        try:
            await observer_spectate.expect(
                lambda m: envelope_type(m) == "game.event" and payload_of(m).get("spectator") is True, 5.0,
                "观战 game.event")
            it.check("收到 spectator=true 的 game.event（观战实时推送）", True)
        except AssertionError:
            info("5s 内未收到观战 game.event（对局可能已结束）")

        # ============ 5) 等一局结束并核对驱动统计 ============
        it = item(5)
        elapsed0 = time.monotonic()
        while time.monotonic() < driver_deadline and not driver_task.done():
            if driver.round_ends or driver.session_ends:
                break
            await asyncio.sleep(0.02)
        round_elapsed = time.monotonic() - elapsed0

        driver.stop = True
        try:
            await asyncio.wait_for(driver_task, 5.0)
        except Exception:
            driver_task.cancel()
        it.check("驱动期间收到 game.input 的成功 ack", driver.acks >= 5,
                 f"acks={driver.acks} sent={driver.sent} 分座位={driver.ack_by_seat}")
        it.check("收到非空 game.event（category + event 均存在）", driver.events >= 5,
                 f"events={driver.events} 空事件={driver.empty_events}")
        it.check("至少 3 名玩家实际出牌成功（由本人视角驱动）",
                 len([k for k, n in driver.ack_by_seat.items() if n > 0]) >= 3, f"{driver.ack_by_seat}")
        it.check("驱动期间没有出现驱动异常", driver.error is None, str(driver.error))
        it.check("在一局结束前保持驱动有效（round_end 或 session_end）",
                 bool(driver.round_ends or driver.session_ends),
                 f"round_end={driver.round_ends} session_end={driver.session_ends}")
        info(f"动作分布={driver.kinds} 输入被拒={driver.err_codes} "
             f"计时器探测={driver.probes}(失败 {driver.probe_failures}) 等待一局结束={round_elapsed:.1f}s")

        # ============ 附加探针（不影响结论，仅报告）============
        import json as _json
        _phases = {}
        _hit = None
        _disc_other = 0
        for _c in game_clients:
            for _m in _c.messages:
                if envelope_type(_m) != "game.event":
                    continue
                _v = payload_of(_m).get("viewer") or {}
                if _v.get("spectator") or _v.get("seat_index") is None:
                    continue
                _acts = _v.get("available_actions") or []
                _key = (_v.get("phase"), _v.get("seat_index") == _v.get("current_player_idx"), bool(_acts))
                _phases[_key] = _phases.get(_key, 0) + 1
                if _acts and _v.get("seat_index") != _v.get("current_player_idx") and _hit is None:
                    _hit = (_c.label, _v)
                for _a in _acts:
                    if _a.get("type") == "discard" and _v.get("seat_index") != _v.get("current_player_idx"):
                        _disc_other += 1
                        break
        print("  [DEBUG 探针] (phase, 是否当前行动者, 是否有动作) 计数 = " + _json.dumps(
            {str(k): v for k, v in sorted(_phases.items(), key=lambda x: str(x[0]))}, ensure_ascii=False), flush=True)
        print(f"  [DEBUG 探针] 非当前行动者却收到 discard 动作的事件数 = {_disc_other}", flush=True)
        print("  [DEBUG 探针] 非当前行动者视角样本 = " +
              (_json.dumps(_hit[1], ensure_ascii=False)[:400] if _hit else "无"), flush=True)
        leaks = probe_available_actions_leak(game_clients)
        if leaks:
            label, seat, cur, tiles, hand = leaks[0]
            observe("viewer.available_actions 未按视角过滤（泄露当前行动者手牌）",
                    f"共 {len(leaks)} 条事件命中；例：{label} seat={seat} 非当前行动者"
                    f"(current_player_idx={cur}) 却收到 discard.tiles={tiles} …，其本人手牌={hand} …。"
                    f"session.py _viewer_for 直接调用 engine.get_available_actions()（基于 current_player_idx），"
                    f"而 DISCARD 阶段该项即当前行动者的整手牌 → 客户端可据此看穿对手手牌")
        drawn = probe_spectator_drawn_tile(game_clients)
        if drawn:
            observe("state.players[*].drawn_tile 对所有视角暴露",
                    f"共 {len(drawn)} 处（例：{drawn[0]}）。engine.get_state() 的 _player_state 对每个座位都带 "
                    f"drawn_tile，game.event/game.snapshot 原样下发 → 别的玩家/观战者能看见当前摸到的牌")

        # ============ 清理：让服务器把剩余对局代打完，避免真人长期挂起 ============
        try:
            for seat in sorted(clients_by_seat):
                cli = clients_by_seat[seat]
                if cli.conn is not None and not cli.closed:
                    await cli.send({"version": 1, "type": "game.abandon",
                                    "payload": {"abandon": True},
                                    "requestId": f"cleanup-s{seat}"})
            await asyncio.sleep(0.3)
        except Exception:
            pass
        info("清理：已发送 game.abandon 让服务器代打收尾（best-effort）")

    finally:
        for cli in [c for c in game_clients] + [observer_spectate, observer_lobby] + lobby_clients:
            if cli is None:
                continue
            try:
                await cli.close()
            except Exception:
                pass


# ---------------------------------------------------------------- 汇总 / 入口
def print_summary(elapsed):
    print("\n" + "═" * 66)
    print("  汇总")
    print("═" * 66)
    total = passed = failed_items = 0
    for i in sorted(ITEMS):
        it = ITEMS[i]
        p, f = it.counts()
        total += p + f
        passed += p
        if not it.ok:
            failed_items += 1
        print(f"  {'✓' if it.ok else '✗'} [{i}] {it.title}  ({p}/{p + f} 子项)")
    print("─" * 66)
    print(f"  测试项: {len(ITEMS)}   通过: {len(ITEMS) - failed_items}   失败: {failed_items}")
    print(f"  子断言: {total}   通过: {passed}   失败: {total - passed}")
    print(f"  用时: {elapsed:.1f}s")
    if OBSERVATIONS:
        print("─" * 66)
        print(f"  发现 {len(OBSERVATIONS)} 处服务端缺陷/协议不一致（不影响本测试结论，供排查）:")
        for n, (title, detail) in enumerate(OBSERVATIONS, 1):
            print(f"   {n}) {title}")
            print(f"      {detail}")
    print("═" * 66)
    return failed_items == 0


def cleanup_test_accounts(names):
    """清理本次注册的测试账号, 避免反复运行污染 users.json(只删本脚本创建的那几个)"""
    import json as _json
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "branches", "networking", "users.json")
    if not os.path.exists(path):
        return 0
    try:
        with open(path, encoding="utf-8") as f:
            users = _json.load(f)
    except Exception:
        return 0
    removed = 0
    for n in names:
        if n and n in users:
            users.pop(n, None)
            removed += 1
    if removed:
        try:
            with open(path, "w", encoding="utf-8") as f:
                _json.dump(users, f, ensure_ascii=False, indent=2)
        except Exception:
            return 0
    return removed


def main():
    print("组合麻将 · 联机 WebSocket 端到端冒烟测试")
    print(f"  HTTP: {BASE_HTTP}    WS: {BASE_WS}")
    detect_backend()
    if BACKEND is None:
        print("\n✗ 未找到可用的 WebSocket 客户端库：websockets 与 websocket-client 都不可用。")
        print("  安装其一后重试：pip install websockets   或   pip install websocket-client")
        print("→ 跳过 WS 冒烟测试（退出码 0）")
        return 0
    print(f"  WebSocket 客户端后端: {BACKEND}")

    try:
        status, body = _http_sync("GET", "/api/v1/lobby/sessions", timeout=5.0)
        print(f"  服务器健康检查: HTTP {status} {str(body)[:100]}")
    except Exception as exc:
        print(f"\n✗ 无法连接服务器 {BASE_HTTP}: {exc.__class__.__name__}: {exc}")
        print("  请先启动：python run_server_8766.py（不要由本脚本启动服务端）")
        return 2

    started = time.monotonic()
    try:
        asyncio.run(asyncio.wait_for(run_all(), TOTAL_BUDGET_S))
    except asyncio.TimeoutError:
        print(f"\n✗ 整体超时（>{TOTAL_BUDGET_S}s）")
    except Exception:
        print("\n✗ 执行中抛出异常：")
        traceback.print_exc()
    elapsed = time.monotonic() - started
    # 清理本次注册的测试账号(users.json 里的 w<uniq>0..3 / w<uniq>ob)
    removed = cleanup_test_accounts(created_usernames)
    if removed:
        print(f"  已清理 {removed} 个测试账号（users.json）")
    finalize_items()
    ok = print_summary(elapsed)
    print("  结果: 全部通过 ✓" if ok else "  结果: 存在失败 ✗（退出码 1）")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
