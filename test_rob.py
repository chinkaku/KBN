# -*- coding: utf-8 -*-
"""组合麻将 — 抢杠(加杠被抢) & 头跳 回归测试

规则(站主确认):
- 加入抢杠: 加杠的牌可被其他家荣和; 暗杠不可抢
- 不能多家和: 多家可和时按座次(下家→对家→上家)先到先得 = 头跳
- 不包牌、不连庄(由引擎其他部分保证, 这里验证抢杠路径不破坏)
运行: python test_rob.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from game_engine import GameEngine, MeldSet, is_winning_hand
from branches.scoring.tester import parse_remaining_tiles

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


def P(s):
    return parse_remaining_tiles(s)


def mk():
    e = GameEngine(num_humans=4)
    e.min_fan = 1
    e.locked_yaku = set()
    e.round_num = 1
    for p in e.players:
        p.is_human = True
    return e


def setup_addkong(e, kong_seat=0):
    """座0 有 5s 的碰 + 手里还剩一张 5s(共11张: 10张+刚摸的牌), 准备加杠"""
    e.current_player_idx = kong_seat
    e.players[kong_seat].melds = [MeldSet([t for t in P("5s5s5s")], 'PUNG')]
    # 有1个副露(3张)时, 摸牌后手牌=11张(含要加杠的那张 5s)
    e.players[kong_seat].hand = (P("5s") + P("111m222m333m789s9m9p"))[:11]
    e.players[kong_seat].status_flag = 'DRAW'
    e.phase = 'SELF_MELD'


def test_rob_basic():
    print("[1] 加杠被抢杠")
    e = mk()
    setup_addkong(e)
    # 座1(下家) 听 5s: 111m222m333m789s5s 等 5s 成对
    e.players[1].hand = P("111m222m333m789s5s")[:13]
    is_win, _ = is_winning_hand(e.players[1].hand + P("5s"), e.players[1].melds)
    check("座1 确实在等 5s(抢杠前可和)", is_win)
    e._do_add_kong("5s", 0)
    check("加杠后进入抢杠询问(ROB_KONG)", e.phase == 'ROB_KONG', f"phase={e.phase}")
    check("可抢杠者=座1(下家)", e._rob_order == [1], f"{e._rob_order}")
    # 座1 抢杠和
    e._do_ron()
    check("抢杠者(座1)和牌", e.winner is e.players[1] and e.game_over, f"winner={e.winner and e.players.index(e.winner)}")
    check("杠家碰子还原为3张(PUNG)", e.players[0].melds[0].meld_type == 'PUNG' and len(e.players[0].melds[0].tiles) == 3,
          f"{e.players[0].melds[0].meld_type}/{len(e.players[0].melds[0].tiles)}")
    check("牌河清空(抢杠牌归和牌者)", e.discard_pool == [])
    win_sh = sorted(t.to_shorthand() for t in e.players[1].hand)
    check("和牌者手牌含 5s 共14张", len(win_sh) == 14 and "5s" in win_sh, f"{len(win_sh)}")


def test_no_rob():
    print("[2] 无人可抢杠 → 正常补岭上牌")
    e = mk()
    setup_addkong(e)
    # 三家都听不到 5s
    e.players[1].hand = P("111m222m333m789p11p")[:13]
    e.players[2].hand = P("111p222p333p789m11s")[:13]
    e.players[3].hand = P("111s222s333s789p11m")[:13]
    e._do_add_kong("5s", 0)
    check("无人可抢 → 不进 ROB_KONG", e.phase != 'ROB_KONG', f"phase={e.phase}")
    check("无人可抢 → 进入补牌流程(_skip_rest)", e._skip_rest is True)
    check("加杠后手牌 10 张(11-1, 杠子4张)", len(e.players[0].hand) == 10, f"{len(e.players[0].hand)}")


def test_head_jump():
    print("[3] 头跳: 多家可和按座次先到先得")
    e = mk()
    setup_addkong(e)
    # 座1(下家) 与 座2(对家) 都能抢 5s
    e.players[1].hand = P("111m222m333m789s5s")[:13]
    e.players[2].hand = P("111p222p333p789p5p1s1s2s")[:13]
    # 座2 听 5p? 让座2 也听 5s 更直观: 用 5s 单吊
    e.players[2].hand = P("111p222p333p789s5s")[:13]
    e._do_add_kong("5s", 0)
    check("座1、座2 都在可抢名单", set(e._rob_order) == {1, 2}, f"{e._rob_order}")
    check("座1(下家)排在座2(对家)前 = 头跳", e._rob_order[0] == 1, f"{e._rob_order}")
    # 座1 先和 → 座2 没有机会(不能多家和)
    e._do_ron()
    check("只有一家和(座1)", e.winner is e.players[1])
    check("座2 未和", e.winner is not e.players[2])


def test_dark_kong_not_rob():
    print("[4] 暗杠不可抢")
    e = mk()
    setup_addkong(e)
    e.players[0].hand = P("5s5s5s5s111m222m333m789s9m9p")[:13]
    e._do_dark_kong("5s")
    check("暗杠后不进入抢杠询问", e.phase != 'ROB_KONG', f"phase={e.phase}")
    check("暗杠后进入补牌流程(_skip_rest)", e._skip_rest is True)


def test_pass_then_skip():
    print("[5] 抢杠者选择过 → 杠家正常补牌")
    e = mk()
    setup_addkong(e)
    e.players[1].hand = P("111m222m333m789s5s")[:13]
    e._do_add_kong("5s", 0)
    e._do_pass_claim()          # 座1 过
    check("唯一抢杠者过后退出 ROB_KONG", e.phase != 'ROB_KONG', f"phase={e.phase}")
    check("杠家恢复补岭上(_skip_rest)", e._skip_rest is True)
    check("牌河清空", e.discard_pool == [])


if __name__ == "__main__":
    print("=" * 46)
    print("抢杠 & 头跳 回归测试")
    print("=" * 46)
    test_rob_basic()
    test_no_rob()
    test_head_jump()
    test_dark_kong_not_rob()
    test_pass_then_skip()
    print("=" * 46)
    if FAIL:
        print(f"失败 {len(FAIL)} 项: {FAIL}")
        sys.exit(1)
    print(f"全部通过 ({PASS} 项)")
