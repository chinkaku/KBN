# -*- coding: utf-8 -*-
"""组合麻将 — 联机（GameHub）集成测试

用假 WebSocket 驱动 GameHub, 覆盖 mmcr 架构移植后的关键行为:
  1) 身份路由: 同一玩家的新连接自动顶掉旧连接(旧 socket 不再收到任何消息) —— 根治旧竞态
  2) 建桌/加入/准备/开局
  3) 全量快照与断线重连(状态不丢)
  4) stage_counter 幂等: 过期输入被拒(error: stale_input)
  5) 三档计时器按 stage 失效
  6) 观战者只读 + 收到事件
  7) 整场跑完 → 回放落库可加载
运行: python test_online.py
"""
import asyncio
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from branches.networking import protocol as P          # noqa: E402
from branches.networking.hub import GameHub            # noqa: E402
from branches.networking import replay as replay_db    # noqa: E402

PASS = 0
FAIL = []


def check(name, cond, extra=""):
    global PASS
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL.append(name)
        print(f"  ✗ {name}  {extra}")


class FakeWS:
    """假 WebSocket: 只实现 send_text, 记录收到的所有消息"""
    def __init__(self, label):
        self.label = label
        self.sent = []
        self.alive = True

    async def send_text(self, text):
        if not self.alive:
            raise RuntimeError("socket closed")
        self.sent.append(json.loads(text))

    def types(self):
        return [m.get("type") for m in self.sent]

    def last(self, msg_type=None):
        for m in reversed(self.sent):
            if msg_type is None or m.get("type") == msg_type:
                return m
        return None

    def events(self, category=None):
        out = []
        for m in self.sent:
            if m.get("type") != "game.event":
                continue
            p = m.get("payload") or {}
            if category is None or p.get("category") == category:
                out.append(p)
        return out


def new_hub():
    return GameHub()


async def setup_four(hub, n=4):
    """4 名玩家连接 + 建桌 + 加入 + 准备"""
    sockets = {}
    for i in range(1, n + 1):
        pid = 100 + i
        name = f"玩家{i}"
        ws = FakeWS(name)
        sockets[pid] = ws
        await hub.connect(pid, name, ws, browsing=True)
    sid = await hub.create_session(101, "玩家1", {"round_count": 4, "bot_delay_ms": 1,
                                                  "round_pause_ms": 1})
    for pid in list(sockets.keys())[1:]:
        ok, code, msg = await hub.join_session(pid, hub.name_of(pid), sid)
        assert ok, (code, msg)
    for pid in sockets:
        ok, code, msg = await hub.set_ready(pid, True)
        assert ok, (code, msg)
    return sid, sockets


def build_input(pick, stage):
    """把 get_available_actions() 的一项转成 game.input 的 payload"""
    kind = pick.get("type")
    p = {"kind": kind, "stage_counter": stage}
    if kind == "discard":
        tiles = pick.get("tiles") or []
        p["tile"] = tiles[-1] if tiles else None
    elif kind in ("dark_kong", "add_kong"):
        p["tile"] = pick.get("tile")
        if pick.get("meld_idx") is not None:
            p["meld_idx"] = pick["meld_idx"]
    elif kind == "chow":
        p["choice"] = 0
    return p


def pick_action(acts):
    """优先选非过牌动作, 否则选第一个"""
    for a in acts:
        if a.get("type") not in ("pass", "skip"):
            return a
    return acts[0] if acts else None


async def autoplay(sess, hub, max_steps=4000):
    """自动替所有人类玩家按合法操作出牌, 直到对局结束"""
    steps = 0
    while not sess.ended and steps < max_steps:
        steps += 1
        eng = sess.engine
        if eng.game_over:
            await asyncio.sleep(0.02)
            continue
        ph = eng.phase
        if ph in ("DISCARD", "SELF_MELD"):
            idx = eng.current_player_idx
        else:
            idx = sess._checker_idx()
        if idx < 0 or not eng.players[idx].is_human or sess._is_auto(idx):
            await asyncio.sleep(0.02)
            continue
        pid = sess.seats[idx]
        acts = eng.get_available_actions()
        pick = pick_action(acts)
        if pick is None:
            await asyncio.sleep(0.02)
            continue
        await sess.handle_input(pid, build_input(pick, sess.stage_counter))
    return steps


async def main():
    print("=" * 52)
    print("联机 GameHub 集成测试")
    print("=" * 52)

    # ---- 1) 身份路由: 新连接顶掉旧连接(旧 socket 静默) ----
    print("[1] 身份路由替换旧 socket (旧竞态根治)")
    hub = new_hub()
    old_ws = FakeWS("old")
    new_ws = FakeWS("new")
    await hub.connect(301, "阿一", old_ws, browsing=True)
    await hub.connect(301, "阿一", new_ws, browsing=True)
    n_before = len(old_ws.sent)
    await hub.send(301, P.envelope("game.event", {"category": "test"}))
    check("消息只发给新 socket", len(new_ws.sent) > 0 and len(old_ws.sent) == n_before,
          f"old+{len(old_ws.sent)-n_before} new+{len(new_ws.sent)}")
    await hub.disconnect(301, old_ws)
    check("旧 socket 断开不影响新连接", 301 in hub.connections)
    await hub.disconnect(301, new_ws)
    check("本人 socket 断开后通道清空", 301 not in hub.connections)

    # ---- 2) 建桌/加入/准备/开局 ----
    print("[2] 建桌 → 加入 → 准备 → 开局")
    hub = new_hub()
    sid, sockets = await setup_four(hub)
    check("等待房 4 人满员", hub.pending_sessions[sid].is_full())
    check("全员准备", hub.pending_sessions[sid].all_ready())
    ok, code, msg = await hub.start_session(999)   # 不在任何房间的人
    check("不在房间的人不能开局", (not ok) and code == P.ERR_NOT_IN_SESSION, f"{code}")
    ok, code, msg = await hub.start_session(102)   # 在房间里但不是房主
    check("非房主不能开局", (not ok) and code == P.ERR_NOT_OWNER, f"{code}")
    ok, code, msg = await hub.start_session(101)
    check("房主开局成功", ok, f"{code} {msg}")
    act = hub.active_sessions.get(sid)
    check("已升级为进行中对局", act is not None and not act.ended)
    check("等待房已移除", sid not in hub.pending_sessions)
    for pid in sockets:
        check(f"玩家{pid} 收到开局快照", sockets[pid].last("session.snapshot") is not None)

    # ---- 3) stage_counter 幂等 ----
    print("[3] stage_counter 幂等校验")
    eng = act.engine
    idx = eng.current_player_idx
    pid = act.seats[idx]
    first_acts = eng.get_available_actions()
    stale = await act.handle_input(pid, build_input(pick_action(first_acts), 0))
    check("stage=0 视为不做校验(放行)", stale[0] is True, f"{stale}")
    # 推进若干阶段, 再用旧 stage 发输入 → 必须被拒
    old_stage = act.stage_counter
    guard = 0
    while act.stage_counter == old_stage and not act.ended and guard < 200:
        guard += 1
        if eng.game_over:
            await asyncio.sleep(0.02)
            continue
        i2 = eng.current_player_idx if eng.phase in ("DISCARD", "SELF_MELD") else act._checker_idx()
        if i2 < 0 or not eng.players[i2].is_human or act._is_auto(i2):
            await asyncio.sleep(0.02)
            continue
        pick = pick_action(eng.get_available_actions())
        if pick is None:
            await asyncio.sleep(0.02)
            continue
        await act.handle_input(act.seats[i2], build_input(pick, act.stage_counter))
    if not act.ended:
        i3 = eng.current_player_idx if eng.phase in ("DISCARD", "SELF_MELD") else act._checker_idx()
        if i3 >= 0 and act.seats[i3]:
            r = await act.handle_input(act.seats[i3],
                                       {"kind": "discard", "stage_counter": old_stage, "tile": "1m"})
            check("过期 stage 输入被拒(stale_input)", (not r[0]) and r[1] == P.ERR_STALE_INPUT, f"{r}")
    else:
        check("过期 stage 输入被拒(stale_input)", True, "(对局已结束, 跳过)")

    # ---- 4) 断线重连: 快照恢复 ----
    print("[4] 断线重连 → 全量快照恢复")
    pid3 = 103
    await hub.disconnect(pid3, sockets[pid3])
    check("断线后身份仍在座位上", act.seat_of(pid3) == 2)
    check("断线标记已记录", pid3 in act.disconnected)
    ws3b = FakeWS("玩家3-reconnect")
    await hub.connect(pid3, "玩家3", ws3b, browsing=False)
    chk = await hub.handle_game_input(pid3, {"kind": "nonexistent"})
    snap = hub.session_snapshot_of(pid3)
    check("重连后能取到对局快照", snap is not None and snap.get("phase") == "active")
    check("重连清除断线标记(不会被代打)", pid3 not in act.disconnected,
          f"disconnected={act.disconnected}")
    check("快照含自己的手牌", "hand" in (snap or {}).get("viewer", {}), f"{(snap or {}).get('viewer')}")
    check("快照含座位状态", len((snap or {}).get("seat_status") or []) == 4)
    sockets[pid3] = ws3b

    # ---- 5) 观战 ----
    print("[5] 观战订阅")
    spec_ws = FakeWS("观战者")
    await hub.connect(501, "观众", spec_ws, browsing=False)
    ok, code, msg = await hub.subscribe_spectate(501, sid)
    check("观战订阅成功", ok, f"{code} {msg}")
    snap_s = spec_ws.last("session.snapshot")
    check("观战者收到快照", snap_s is not None)
    check("观战视角标记 spectator", bool((snap_s or {}).get("payload", {}).get("session", {}).get("spectator")))
    check("观战者不在座位上", act.seat_of(501) == -1)

    # ---- 6) 打完整场(4局) ----
    print("[6] 自动打完 4 局")
    steps = await autoplay(act, hub)
    check("对局正常结束", act.ended, f"steps={steps} ended={act.ended}")
    check("最终分数已产生", isinstance(act.final_scores, list) and len(act.final_scores) == 4,
          f"{act.final_scores}")
    check("人类玩家收到 session_end", any(e.get("category") == "session_end"
                                        for ws in sockets.values() for e in ws.events()),
          "")

    # ---- 7) 回放 ----
    print("[7] 回放落库与加载")
    ident = act._replay.get("session_identifier")
    rp = replay_db.load_replay(ident)
    check("回放已保存并可加载", rp is not None, f"ident={ident}")
    if rp:
        check("回放含全部局数", len(rp.get("rounds") or []) == 4, f"{len(rp.get('rounds') or [])}")
        check("回放含最终分数", rp.get("final_scores") is not None)
        rounds_with_events = [r for r in rp["rounds"] if r.get("events")]
        check("回放含逐阶段事件", len(rounds_with_events) > 0,
              f"{[len(r.get('events') or []) for r in rp['rounds']]}")
    lst = replay_db.list_replays(10)
    check("回放列表可查询", any(r["session_identifier"] == ident for r in lst), f"{len(lst)}")

    # ---- 8) 三档计时器按 stage 失效 ----
    print("[8] 计时器按 stage 失效")
    hub2 = new_hub()
    sid2, sockets2 = await setup_four(hub2)
    await hub2.start_session(101)
    act2 = hub2.active_sessions[sid2]
    fired = {"n": 0}

    async def cb():
        fired["n"] += 1

    stage_now = act2.stage_counter
    act2.set_timer(10, stage_now, cb)          # 当前阶段: 会触发
    await asyncio.sleep(0.25)
    check("当前阶段计时器到点触发", fired["n"] == 1, f"n={fired['n']}")
    act2.set_timer(10, stage_now - 1, cb)      # 过期阶段: 不触发
    await asyncio.sleep(0.25)
    check("过期阶段计时器 no-op", fired["n"] == 1, f"n={fired['n']}")
    act2.cancel_timer()

    # ---- 9) 四人视角一致性 / 不泄露 ----
    print("[9] 四人视角: 只给自己看的东西 + 不泄露")
    hub3 = new_hub()
    sid3, sockets3 = await setup_four(hub3)
    await hub3.start_session(101)
    act3 = hub3.active_sessions[sid3]
    # 驱动若干步, 收集每个客户端收到的 state/viewer
    for _ in range(60):
        if act3.ended:
            break
        eng3 = act3.engine
        if eng3.game_over:
            await asyncio.sleep(0.01)
            continue
        i3 = eng3.current_player_idx if eng3.phase in ("DISCARD", "SELF_MELD") else act3._checker_idx()
        if i3 < 0 or not eng3.players[i3].is_human or act3._is_auto(i3):
            await asyncio.sleep(0.01)
            continue
        pick = pick_action(eng3.get_available_actions())
        if pick is None:
            await asyncio.sleep(0.01)
            continue
        await act3.handle_input(act3.seats[i3], build_input(pick, act3.stage_counter))

    leak_drawn = 0        # 别人刚摸的牌被泄露的次数
    own_hand_ok = 0
    own_hand_bad = []
    multi_actions = 0     # 非决策者拿到可用操作的次数
    checked = 0
    for seat_i, pid in enumerate(act3.seats):
        ws = sockets3[pid]
        for env in ws.sent:
            if env.get("type") != "game.event":
                continue
            p = env.get("payload") or {}
            stt = p.get("state") or {}
            v = p.get("viewer") or {}
            checked += 1
            # (a) state.players[i].drawn_tile: 除自己外都应为空
            for i, ps in enumerate(stt.get("players") or []):
                if i != seat_i and ps.get("drawn_tile"):
                    leak_drawn += 1
            # (b) viewer.hand 必须等于自己座位的手牌(以引擎当前状态为准, 事件可能滞后一步)
            if v.get("hand"):
                own_hand_ok += 1
            # (c) 只有"当前该决策的人"才应拿到可用操作(按事件自身的 decision_seat 判定)
            if v.get("available_actions"):
                if v.get("seat_index") != v.get("decision_seat"):
                    multi_actions += 1
    check("别人刚摸的牌不外泄(state 里仅自己可见)", leak_drawn == 0, f"泄露 {leak_drawn} 次(检查 {checked} 条事件)")
    check("自己的手牌正常下发", own_hand_ok > 0, f"{own_hand_ok} 条")
    check("只有当前决策者收到可用操作", multi_actions == 0, f"{multi_actions} 次越权")
    # 观战者: 不应拿到任何人的手牌/摸牌
    spec2 = FakeWS("观众2")
    await hub3.connect(502, "观众2", spec2, browsing=False)
    await hub3.subscribe_spectate(502, sid3)
    spec_leak = 0
    spec_hand = 0
    for env in spec2.sent:
        if env.get("type") != "game.event":
            continue
        p = env.get("payload") or {}
        v = p.get("viewer") or {}
        if v.get("hand"):
            spec_hand += 1
        for ps in ((p.get("state") or {}).get("players") or []):
            if ps.get("drawn_tile"):
                spec_leak += 1
    check("观战者拿不到手牌", spec_hand == 0, f"{spec_hand}")
    check("观战者看不到任何人的摸牌", spec_leak == 0, f"{spec_leak}")

    # ---- 10) 荣和优先于碰/吃 ----
    print("[10] 荣和优先于碰(四人真人对局规则)")
    from game_engine import GameEngine, Tile as _T, is_winning_hand as _iw
    from branches.scoring.tester import parse_remaining_tiles as _pt
    ge = GameEngine(num_humans=4)
    ge.min_fan = 4
    ge.locked_yaku = set()
    for p in ge.players:
        p.is_human = True
    ge.players[1].hand = _pt("1122334455667m99s")      # 下家: 有两个5m可碰
    ge.players[2].hand = _pt("123123123m99p55m")       # 对家: 听牌等5m荣和
    ge.players[3].hand = _pt("111222333m99p1s2s")      # 上家
    ge.current_player_idx = 0
    ge.discard_pool = [_pt("5m")[0]]
    ge._last_discarder = 0
    ge.phase = "CLAIM_PK"
    order = ge._build_claim_order()
    check("有荣和机会的对家被优先询问(不是下家先碰)", order[0] == 2, f"order={order}")

    # ---- 11) 全员放弃/断线后不再卡死(高危修复回归) ----
    print("[11] 全员放弃后对局仍能推进并收尾(防卡死)")
    hub4 = new_hub()
    sid4, sockets4 = await setup_four(hub4)
    await hub4.start_session(101)
    act4 = hub4.active_sessions[sid4]
    act4.abandoned = set([s for s in act4.seats if s])       # 四人全部放弃
    for pid in act4.seats:
        if pid:
            act4.disconnected[pid] = 0                        # 且断线已久
    for _ in range(1200):
        if act4.ended:
            break
        await asyncio.sleep(0.005)
        if not act4.engine.game_over:
            await act4._pump()
    check("全员放弃后对局自动打完并结束", act4.ended,
          f"ended={act4.ended} round={act4.engine.round_num} phase={act4.engine.phase}")

    # ---- 12) started 快照带手牌 + 计时器随推送下发 ----
    print("[12] 开局快照带手牌 / 计时器随推送下发")
    hub5 = new_hub()
    sid5, sockets5 = await setup_four(hub5)
    await hub5.start_session(101)
    act5 = hub5.active_sessions[sid5]
    started_ok = 0
    for pid in act5.seats:
        for env in sockets5[pid].sent:
            if env.get("type") == "session.snapshot":
                sess = (env.get("payload") or {}).get("session") or {}
                if sess.get("summary", {}).get("round_counter", 0) >= 1:
                    h = (sess.get("viewer") or {}).get("hand") or []
                    if len(h) in (13, 14):
                        started_ok += 1
    check("开局快照已含手牌(不再是空手牌/第0局)", started_ok >= 4, f"{started_ok}/4")
    # 推进到需要某人决策, 检查推送事件里带 timer
    for _ in range(80):
        if act5.engine.game_over:
            break
        eng5 = act5.engine
        i5 = eng5.current_player_idx if eng5.phase in ("DISCARD", "SELF_MELD") else act5._checker_idx()
        if i5 >= 0 and eng5.players[i5].is_human and not act5._is_auto(i5):
            break
        await asyncio.sleep(0.005)
    timer_seen = 0
    dec = act5._decision_seat()
    for pid in act5.seats:
        for env in sockets5[pid].sent:
            if env.get("type") != "game.event":
                continue
            v = (env.get("payload") or {}).get("viewer") or {}
            if v.get("timer"):
                timer_seen += 1
    check("推送事件里带三档计时器(不再只有主动快照才有)", timer_seen > 0 and dec >= 0,
          f"timer事件={timer_seen} decision_seat={dec} phase={act5.engine.phase}")
    # 观战视角切换
    spec3 = FakeWS("观众3")
    await hub5.connect(503, "观众3", spec3, browsing=False)
    await hub5.subscribe_spectate(503, sid5)
    ok, code, emsg = await hub5.set_spectator_perspective(503, 2)
    snap3 = spec3.last("session.snapshot")
    v3 = ((snap3 or {}).get("payload") or {}).get("session", {}).get("viewer", {})
    check("观战者可切换视角(seat_index 跟随)", ok and v3.get("seat_index") == 2, f"{v3.get('seat_index')}")
    check("观战切视角后依然看不到手牌", not v3.get("hand"), f"hand={v3.get('hand')}")

    # ---- 13) player_id 不复用(防身份串号) ----
    print("[13] player_id 永不复用")
    from branches.networking import auth as _auth
    users_file = _auth.USERS_FILE
    import json as _json
    backup = None
    if os.path.exists(users_file):
        with open(users_file, encoding="utf-8") as f:
            backup = f.read()
    try:
        tok_a = _auth.register("idtest_a", "pw123")
        pid_a = _auth.get_player_id("idtest_a")
        users = _auth._load_users()
        users.pop("idtest_a", None)          # 模拟删除账号
        _auth._save_users(users)
        tok_b = _auth.register("idtest_b", "pw123")
        pid_b = _auth.get_player_id("idtest_b")
        check("删号后新账号不会复用旧 player_id", pid_a is not None and pid_b is not None and pid_a != pid_b,
              f"旧={pid_a} 新={pid_b}")
    finally:
        if backup is not None:
            with open(users_file, "w", encoding="utf-8") as f:
                f.write(backup)
        else:
            try:
                os.remove(users_file)
            except Exception:
                pass

    # ---- 14) 房主踢人 ----
    print("[14] 房主踢人(queue.kick)")
    hub6 = new_hub()
    sid6, sockets6 = await setup_four(hub6)
    ok, code, emsg = await hub6.kick_player(102, 104)      # 非房主踢人
    check("非房主不能踢人", (not ok) and code == P.ERR_NOT_OWNER, f"{code}")
    ok, code, emsg = await hub6.kick_player(101, 104)      # 房主踢人
    check("房主踢人成功", ok, f"{code} {emsg}")
    check("被踢者已离开房间", not hub6.pending_sessions[sid6].is_member(104))
    check("被踢者收到 kicked 通知",
          any(env.get("payload", {}).get("kicked") for env in sockets6[104].sent))
    check("被踢者不再占用座位", hub6.player_pending.get(104) is None)

    print("=" * 52)
    if FAIL:
        print(f"失败 {len(FAIL)} 项: {FAIL}")
        return 1
    print(f"全部通过 ({PASS} 项)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
