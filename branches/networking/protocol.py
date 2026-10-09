# -*- coding: utf-8 -*-
"""组合麻将 — 联机协议层 (照搬 mmcr14.online 的信封/应答设计)

协议要点(移植自 mmcr):
- 信封统一为 {"version": 1, "type": <str>, "payload": {...}, "requestId": <str|null>}
- 客户端每个请求可带 requestId; 服务端处理成功后回 ack(requestId), 失败回 error(code, message)
- 服务端主动推送: lobby.list.snapshot / session.snapshot / game.event / game.pass.ack /
  game.abandon.notify / pong
- 输入幂等: 每条 game.input 带 stage_counter; 与当前阶段不符(小于当前)则丢弃并回 error("stale_input")
- 路由校验: 只允许在对应 socket 上发送的消息类型(否则 error("wrong_socket"))
"""

PROTOCOL_VERSION = 1

# ---- WebSocket 路径 ----
WS_LOBBY = "/ws/lobby"      # 大厅: 会话列表订阅 / 创建 / 加入 / 准备
WS_GAME = "/ws/game"        # 对局: 输入 / 快照 / 事件
WS_SPECTATE = "/ws/spectate"  # 观战: 只读视图

# ---- 客户端 -> 服务端 消息类型 ----
C2S = {
    "ping",                     # 心跳 (回 pong)
    "lobby.list",               # 请求大厅列表
    "lobby.create",             # 创建会话 {config?}
    "lobby.join",               # 加入会话 {session_id}
    "lobby.leave",              # 离开会话
    "queue.ready",              # 准备/取消准备 {ready}
    "queue.start",              # 房主开局 (4人齐且全准备)
    "queue.kick",               # 房主踢人 {player_id}
    "game.input",               # 对局输入 {kind, stage_counter, ...}
    "game.abandon",             # 投降/取消投降 {abandon}
    "game.snapshot",            # 主动请求全量快照(重连后)
    "resume.ack",               # 重连确认
    "spectate.subscribe",       # 观战订阅 {session_id}
    "spectate.unsubscribe",     # 取消观战
    "spectator.perspective",    # 切换观战视角 {seat_index}
    "replay.list",              # 回放列表
    "replay.load",              # 加载回放 {session_identifier}
}

# ---- 服务端 -> 客户端 消息类型 ----
S2C = {
    "pong",
    "ack",
    "error",
    "lobby.list.snapshot",      # {sessions: [...], active_sessions: [...]}
    "session.snapshot",         # {session: {phase: 'pending'|'active', ...}}
    "game.event",               # {category, event, state, viewer, seat_status}
    "game.pass.ack",            # {stage_counter}
    "game.abandon.notify",      # {player_id, abandon}
    "replay.list.snapshot",     # {replays: [...]}
    "replay.snapshot",          # {replay: {...}}
}

# ---- 每条消息允许出现在哪个 socket (None = 任意) ----
ROUTE_MAP = {
    "ping": None,
    "lobby.list": WS_LOBBY,
    "lobby.create": WS_LOBBY,
    "lobby.join": WS_LOBBY,
    "lobby.leave": WS_LOBBY,
    "queue.ready": WS_LOBBY,
    "queue.start": WS_LOBBY,
    "queue.kick": WS_LOBBY,
    "game.input": WS_GAME,
    "game.abandon": WS_GAME,
    "game.snapshot": WS_GAME,
    "resume.ack": WS_GAME,
    "spectate.subscribe": WS_SPECTATE,
    "spectate.unsubscribe": WS_SPECTATE,
    "spectator.perspective": WS_SPECTATE,
    "replay.list": None,
    "replay.load": None,
}

# ---- 错误码 (移植 mmcr 的 code 语义) ----
ERR_UNAUTHORIZED = "unauthorized"
ERR_INVALID_REQUEST = "invalid_request"
ERR_WRONG_SOCKET = "wrong_socket"
ERR_STALE_INPUT = "stale_input"
ERR_NOT_FOUND = "not_found"
ERR_SESSION_FULL = "session_full"
ERR_SESSION_STARTED = "session_started"
ERR_NOT_IN_SESSION = "not_in_session"
ERR_NOT_OWNER = "not_owner"
ERR_NOT_READY = "not_ready"
ERR_ILLEGAL_ACTION = "illegal_action"
ERR_SPECTATOR_READ_ONLY = "spectator_read_only"


def envelope(msg_type, payload=None, request_id=None):
    """构造服务端 -> 客户端信封"""
    return {
        "version": PROTOCOL_VERSION,
        "type": msg_type,
        "payload": payload if payload is not None else {},
        "requestId": request_id,
    }


def ack(request_id, payload=None):
    """成功应答"""
    return envelope("ack", payload or {}, request_id)


def error(code, message, request_id=None, extra=None):
    """失败应答: {code, message} (+ 附加字段)"""
    payload = {"code": code, "message": message}
    if extra:
        payload.update(extra)
    return envelope("error", payload, request_id)


def parse_message(root):
    """解析客户端消息 -> (type, payload, requestId) 或抛 ValueError"""
    if not isinstance(root, dict):
        raise ValueError("消息必须是 JSON 对象")
    msg_type = root.get("type")
    if not isinstance(msg_type, str) or not msg_type:
        raise ValueError("缺少 type 字段")
    payload = root.get("payload")
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError("payload 必须是对象")
    request_id = root.get("requestId") or root.get("request_id")
    if request_id is not None and not isinstance(request_id, str):
        request_id = str(request_id)
    return msg_type, payload, request_id


def route_ok(msg_type, route):
    """该消息类型是否允许在当前 socket 路由上发送"""
    expect = ROUTE_MAP.get(msg_type)
    if expect is None:
        return True
    return expect == route
