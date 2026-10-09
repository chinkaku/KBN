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

    print("=" * 52)
    if FAIL:
        print(f"失败 {len(FAIL)} 项: {FAIL}")
        return 1
    print(f"全部通过 ({PASS} 项)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
