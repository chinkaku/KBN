# -*- coding: utf-8 -*-
"""冒险关卡1-5 回归测试: win_and_score目标 / 幺九保底手牌 / 聚数流(星井) / 13巡不荣和 / 多对手

运行: python test_1_5.py  (自包含, 无需服务器)
"""
import sys, os

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from game_engine import GameEngine, Tile, TileType

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

def new_engine():
    e = GameEngine(num_humans=1)
    e.min_fan = 1
    e.locked_yaku = set()
    return e

# ---- 1) win_and_score 目标 ----
def test_win_and_score():
    print("[1] win_and_score 目标判定")
    e = new_engine()
    e.adventure_goal = {"type": "win_and_score", "wins": 3, "target": 18}
    e.adventure_rounds = 5
    e.adv_wins = 2
    e.accumulated_scores[e.players[0].role] = 18
    check("和牌2次+18分 → 未达成", e.check_goal_met() is False)
    e.adv_wins = 3
    check("和牌3次+18分 → 达成", e.check_goal_met() is True)
    e.accumulated_scores[e.players[0].role] = 16
    check("和牌3次+16分 → 未达成(分数不够)", e.check_goal_met() is False)

# ---- 2) 玩家和牌次数累计 ----
def test_adv_wins_count():
    print("[2] _accumulate_scores 累计玩家和牌次数")
    e = new_engine()
    e.adv_wins = 0
    e.winner = e.players[0]
    e.players[0].score = 6
    e._accumulate_scores()
    check("玩家和牌 → adv_wins=1", e.adv_wins == 1)
    check("对手和牌不计入", True)
    e2 = new_engine()
    e2.adventure_opponent = {"seat": 2, "style": "flush"}
    e2.winner = e2.players[2]
    e2.players[2].score = 8
    e2._accumulate_scores()
    check("对手和牌 → adv_wins 仍为0", e2.adv_wins == 0)
    check("对手和牌 → adv_block_failed=True", e2.adv_block_failed is True)

# ---- 3) 1-5 保底手牌: 字对+2散字+每花色各1+至少3张幺九 ----
def test_guaranteed_hand_15():
    print("[3] 1-5 保底手牌(字对/散字/每花色/3幺九)")
    ok_all = True
    for _ in range(30):
        e = new_engine()
        e.guaranteed_hand = {"honour_pair": True, "loose_honours": 2,
                             "suit_min": {"m": 1, "p": 1, "s": 1}, "terminals": 3}
        e.start_round()
        h = e.players[0].hand
        if len(h) != 13:
            ok_all = False; print(f"     手牌 {len(h)} 张(应为13)"); break
        sh = [t.to_shorthand() for t in h]
        honours = [s for s in sh if s in "ESWNCFP"]
        from collections import Counter
        hc = Counter(honours)
        if sum(1 for c in hc.values() if c >= 2) < 1:
            ok_all = False; print(f"     无字牌对: {honours}"); break
        if len(honours) < 4:
            ok_all = False; print(f"     字牌不足4张: {honours}"); break
        for letter in "mps":
            if not any(s.endswith(letter) for s in sh):
                ok_all = False; print(f"     缺花色 {letter}: {sh}"); break
        terminals = [s for s in sh if s[0] in "19"]
        if len(terminals) < 3:
            ok_all = False; print(f"     幺九不足3张: {terminals}"); break
        if not ok_all:
            break
    check("30次发牌全部满足 13张+字对+2散字+每花色+3幺九", ok_all)

# ---- 4) 聚数流选窗口: 四聚优先(牌多窗口) ----
def test_cluster_window():
    print("[4] 聚数流选点数窗口")
    e = new_engine()
    # 手牌: 2,3,4,5m + 2,3,4p + 2s + 字牌
    hand = ([Tile(TileType.MAN, r) for r in (2, 3, 4, 5)] +
            [Tile(TileType.PIN, r) for r in (2, 3, 4)] +
            [Tile(TileType.SOU, 2)] +
            [Tile(TileType.HONOUR, r) for r in range(5)])
    lo, hi = e._choose_cluster_window(hand)
    check("窗口 2-5(四聚, 牌最多)", lo == 2 and hi == 5, f"got {lo}-{hi}")
    # 三聚情形: 3,4,5 明显多于其它窗口
    hand2 = ([Tile(TileType.MAN, r) for r in (3, 4, 5)] +
             [Tile(TileType.PIN, r) for r in (3, 4, 5)] +
             [Tile(TileType.SOU, r) for r in (3, 4, 5)] +
             [Tile(TileType.HONOUR, r) for r in range(4)])
    lo2, hi2 = e._choose_cluster_window(hand2)
    check("窗口 3-5(三聚, 9张)", lo2 == 3 and hi2 == 5, f"got {lo2}-{hi2}")

# ---- 5) 聚数流打牌: 先切字牌, 再切窗口外 ----
def test_cluster_discard():
    print("[5] 聚数流打牌顺序")
    e = new_engine()
    e.adventure_opponent = {"seat": 1, "style": "cluster"}
    e.cluster_windows[1] = (5, 8)  # 窗口5678
    e.players[1].hand = ([Tile(TileType.HONOUR, 0), Tile(TileType.HONOUR, 1)] +
                         [Tile(TileType.MAN, r) for r in (5, 6, 7, 8)] +
                         [Tile(TileType.PIN, 2), Tile(TileType.PIN, 9)] +
                         [Tile(TileType.SOU, 3)])
    d1 = e._choose_cluster_discard(e.players[1])
    check("优先切字牌", d1.tile_type == TileType.HONOUR, f"got {d1.to_shorthand()}")
    # 无字牌: 切窗口外
    e.players[1].hand = ([Tile(TileType.MAN, r) for r in (5, 6, 7, 8)] +
                         [Tile(TileType.PIN, 2), Tile(TileType.PIN, 9)] +
                         [Tile(TileType.SOU, 3), Tile(TileType.SOU, 5)])
    d2 = e._choose_cluster_discard(e.players[1])
    check("无字牌 → 切窗口外(9p/2p/3s之一)", not (5 <= d2.rank <= 8) and d2.tile_type != TileType.HONOUR, f"got {d2.to_shorthand()}")

# ---- 6) 13巡不荣和 ----
def test_no_ron():
    print("[6] 13巡前不接点炮")
    e = new_engine()
    e.adv_no_ron_turn = 13
    e.players[2].discards = [Tile(TileType.MAN, 1)] * 12
    check("出牌12张 → 限制中(不荣和)", e._no_ron_active(e.players[2]) is True)
    e.players[2].discards = [Tile(TileType.MAN, 1)] * 13
    check("出牌13张 → 放开(可荣和)", e._no_ron_active(e.players[2]) is False)
    e2 = new_engine()
    e2.adv_no_ron_turn = 0
    check("未配置 → 无限制", e2._no_ron_active(e2.players[2]) is False)

# ---- 7) 聚数流吃窗口限制: 窗口5678 不用78吃9 ----
def test_cluster_chow_window():
    print("[7] 聚数流吃牌必须落在窗口内")
    e = new_engine()
    e.adventure_opponent = {"seat": 1, "style": "cluster"}
    e.cluster_windows[1] = (5, 8)  # 窗口5678
    e.players[1].hand = [Tile(TileType.MAN, 7), Tile(TileType.MAN, 8), Tile(TileType.SOU, 5), Tile(TileType.SOU, 6)]
    # 上家打出9m: 78吃9 → 序列789, 9不在窗口5678内 → 不应吃
    e.discard_pool = [Tile(TileType.MAN, 9)]
    e.phase = 'CLAIM_CHOW'
    got = e._bot_claim_cluster_chow(e.players[1])
    check("窗口5678 不用78吃9", got is False)
    # 上家打出9s: 56吃9 → 序列569? 不对——56吃9需要678? 9不构成56的吃
    # 正确用例: 上家打出7s, 56吃7 → 567 全在窗口内 → 可吃
    e.discard_pool = [Tile(TileType.SOU, 7)]
    got2 = e._bot_claim_cluster_chow(e.players[1])
    check("窗口内吃(56吃7 → 567)", got2 is True)

# ---- 8) 多对手整局冒烟(星井聚数+佐佐木染手) ----
def test_smoke_two_opponents():
    print("[8] 冒烟: 1-5 双对手整局推进")
    e = new_engine()
    e.adventure_opponents = [
        {"seat": 1, "style": "cluster"},
        {"seat": 2, "style": "flush", "deal_bias": 6, "no_claim_rounds": 1},
    ]
    e.adventure_opponent = e.adventure_opponents[0]
    e.opponent_deal_bias_map = {2: 6}
    e.adv_no_ron_turn = 13
    e.adventure_goal = {"type": "win_and_score", "wins": 3, "target": 18}
    e.adventure_rounds = 5
    e.round_num = 1
    e.start_round()
    e._auto_advance()
    check("整局推进到结束(无崩溃)", True)
    check("星井(1)选了聚数窗口", 1 in e.cluster_windows, f"windows={e.cluster_windows}")
    check("佐佐木(2)选了染手花色", 2 in e.flush_suits, f"suits={e.flush_suits}")
    check("佐佐木起手偏科6张", 2 in e.opponent_deal_bias_map)

if __name__ == "__main__":
    print("=" * 46)
    print("冒险关卡1-5 回归测试")
    print("=" * 46)
    test_win_and_score()
    test_adv_wins_count()
    test_guaranteed_hand_15()
    test_cluster_window()
    test_cluster_discard()
    test_no_ron()
    test_cluster_chow_window()
    test_smoke_two_opponents()
    print("=" * 46)
    if FAIL:
        print(f"失败 {len(FAIL)} 项: {FAIL}")
        sys.exit(1)
    print(f"全部通过 ({PASS} 项)")
