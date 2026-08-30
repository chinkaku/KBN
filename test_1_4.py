# -*- coding: utf-8 -*-
"""冒险关卡1-4 回归测试: 染手流bot / block_win目标 / 第二段保底手牌 / 多fight剧情解析

运行: python test_1_4.py  (自包含, 无需服务器)
"""
import sys, os, random

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
    return e

def shorthands(hand):
    return sorted(t.to_shorthand() for t in hand)

# ---- 1) 染手流选花色: 张数优先 ----
def test_suit_count_priority():
    print("[1] 染手流选花色: 张数优先")
    e = new_engine()
    hand = [Tile(TileType.MAN, r) for r in (2, 3, 4, 5, 6)] + \
           [Tile(TileType.PIN, r) for r in (1, 2, 9)] + \
           [Tile(TileType.SOU, 5), Tile(TileType.SOU, 8)] + \
           [Tile(TileType.HONOUR, 0), Tile(TileType.HONOUR, 4)]
    suit = e._choose_flush_suit(hand)
    check("5万 > 3筒 > 2条 → 选万", suit == TileType.MAN, f"got {suit}")

# ---- 2) 染手流选花色: 平手比质量(中张) ----
def test_suit_quality_priority():
    print("[2] 染手流选花色: 平手比中张数")
    e = new_engine()
    hand = [Tile(TileType.MAN, r) for r in (1, 2, 3, 4)] + \
           [Tile(TileType.PIN, r) for r in (1, 9, 9, 9)] + \
           [Tile(TileType.SOU, 5), Tile(TileType.SOU, 8)] + \
           [Tile(TileType.HONOUR, 0), Tile(TileType.HONOUR, 4), Tile(TileType.HONOUR, 6)]
    suit = e._choose_flush_suit(hand)
    check("4万(3中张) > 4筒(1中张) → 选万", suit == TileType.MAN, f"got {suit}")

# ---- 3) 染手流打牌: 非目标花色优先弃 ----
def test_flush_discard_off_suit():
    print("[3] 染手流打牌: 弃非目标花色数牌")
    e = new_engine()
    e.adventure_opponent = {"seat": 2, "style": "flush", "no_claim_rounds": 0}
    e.flush_suits[2] = TileType.MAN
    e.players[2].hand = [Tile(TileType.MAN, r) for r in (2, 3, 4, 5)] + \
                        [Tile(TileType.PIN, r) for r in (1, 2, 9)] + \
                        [Tile(TileType.SOU, 5), Tile(TileType.SOU, 8)] + \
                        [Tile(TileType.HONOUR, 0), Tile(TileType.HONOUR, 4), Tile(TileType.HONOUR, 6), Tile(TileType.HONOUR, 1)]
    disc = e._choose_flush_discard(e.players[2])
    check("打出的不是万字(非目标花色)", disc.tile_type != TileType.MAN, f"got {disc.to_shorthand()}")
    check("打出的不是字牌(混一色保留字牌)", disc.tile_type != TileType.HONOUR, f"got {disc.to_shorthand()}")

# ---- 4) 染手流打牌: 目标花色内弃最孤的牌 ----
def test_flush_discard_isolated():
    print("[4] 染手流打牌: 目标花色内弃孤张")
    e = new_engine()
    e.adventure_opponent = {"seat": 2, "style": "flush", "no_claim_rounds": 0}
    e.flush_suits[2] = TileType.MAN
    e.players[2].hand = [Tile(TileType.MAN, 2), Tile(TileType.MAN, 3), Tile(TileType.MAN, 4), Tile(TileType.MAN, 9)] + \
                        [Tile(TileType.HONOUR, r) for r in range(4)]
    disc = e._choose_flush_discard(e.players[2])
    check("孤张9万应被弃", disc == Tile(TileType.MAN, 9), f"got {disc.to_shorthand()}")

# ---- 5) block_win 目标判定 ----
def test_block_win_goal():
    print("[5] block_win 目标判定")
    e = new_engine()
    e.adventure_goal = {"type": "block_win", "target": 5, "opponent_seat": 2}
    e.adventure_rounds = 5
    e.adv_block_failed = False
    e.round_num = 5
    check("5局对手未和牌 → 达成", e.check_goal_met() is True)
    e.adv_block_failed = True
    check("对手和过牌 → 失败", e.check_goal_met() is False)
    e.round_num = 4
    e.adv_block_failed = False
    check("未打满5局 → 不结算", e.check_goal_met() is False)

# ---- 6) 对手和牌记录 adv_block_failed ----
def test_block_failed_flag():
    print("[6] _accumulate_scores 记录对手和牌")
    e = new_engine()
    e.adventure_opponent = {"seat": 2, "style": "flush", "no_claim_rounds": 0}
    e.winner = e.players[2]
    e.players[2].score = 8
    e._accumulate_scores()
    check("对家(座2)和牌 → adv_block_failed=True", e.adv_block_failed is True)
    check("累计分累加到对家", e.accumulated_scores[e.players[2].role] == 8)

# ---- 7) 第二段保底手牌: 字对+2散字+每花色一副12/56/89 ----
def test_guaranteed_hand_partials():
    print("[7] 第二段保底手牌 partials")
    ok_all = True
    for trial in range(30):
        e = new_engine()
        e.guaranteed_hand = {"honour_pair": True, "loose_honours": 2, "partials": {"m": 1, "p": 1, "s": 1}}
        e.start_round()
        h = e.players[0].hand
        if len(h) != 13:
            ok_all = False
            print(f"     手牌 {len(h)} 张(应为13)")
            break
        sh = shorthands(h)
        # 字牌: 至少一对 + 2散张 (字牌简写为单个字母 E/S/W/N/C/F/P)
        honours = [s for s in sh if s in "ESWNCFP"]
        from collections import Counter
        hc = Counter(honours)
        if sum(1 for c in hc.values() if c >= 2) < 1:
            ok_all = False; print(f"     无字牌对: {honours}"); break
        if len(honours) < 4:
            ok_all = False; print(f"     字牌不足4张: {honours}"); break
        # 每花色含一副 12/56/89
        for letter in "mps":
            tiles = sorted(int(s[0]) for s in sh if s.endswith(letter))
            has_partial = any(all(r in tiles for r in pr) for pr in ((1,2),(5,6),(8,9)))
            if not has_partial:
                ok_all = False; print(f"     {letter} 无12/56/89: {tiles}"); break
        if not ok_all:
            break
    check("30次发牌全部满足 13张+字对+2散字+每花色12/56/89", ok_all)

# ---- 8) 多fight剧情解析 ----
def test_story_multi_fight():
    print("[8] 多fight剧情解析")
    from branches.networking.story import parse_story
    path = os.path.join(BASE, "story", "1-4.txt")
    s = parse_story(path)
    check("before 14句(第一段战前)", len(s["before"]) == 14, f"got {len(s['before'])}")
    check("中间段 1 段", len(s["segments"]) == 1, f"got {len(s['segments'])}")
    check("中间段 18句(失败+都茂教学)", len(s["segments"][0]) == 18, f"got {len(s['segments'][0])}")
    check("after 2句(胜利结算)", len(s["after"]) == 2, f"got {len(s['after'])}")
    # 单fight兼容
    path3 = os.path.join(BASE, "story", "1-3.txt")
    s3 = parse_story(path3)
    check("单fight: segments为空", len(s3["segments"]) == 0)
    check("单fight: before/after 存在", len(s3["before"]) > 0 and len(s3["after"]) > 0)

# ---- 9) 整局冒烟: 染手流对手正常推进不崩溃 ----
def test_smoke_full_round():
    print("[9] 冒烟: 染手流对手整局推进")
    e = new_engine()
    e.adventure_opponent = {"seat": 2, "style": "flush", "no_claim_rounds": 0}
    e.adv_fight = 0
    e.adventure_goal = {"type": "block_win", "target": 5, "opponent_seat": 2}
    e.adventure_rounds = 5
    e.locked_yaku = set()
    e.start_round()
    e._auto_advance()
    check("整局推进到结束(无崩溃)", e.game_over is True or e.phase in ("DISCARD", "SELF_MELD", "CLAIM_PK", "CLAIM_CHOW") or e._needs_human_input() is not None, f"phase={e.phase} game_over={e.game_over}")
    # 染手流对手: 若推进过打牌, flush_suits 应有目标花色
    check("染手流目标花色已选定", 2 in e.flush_suits, f"flush_suits={e.flush_suits}")

# ---- 10) 放水局: 前N局不鸣牌, 第N+1局恢复 ----
def test_fangshui():
    print("[10] 放水局判定")
    e = new_engine()
    e.adventure_opponent = {"seat": 2, "style": "flush", "no_claim_rounds": 3}
    e.round_num = 1
    check("第1局放水", e._bot_fangshui(e.players[2]) is True)
    e.round_num = 3
    check("第3局放水", e._bot_fangshui(e.players[2]) is True)
    e.round_num = 4
    check("第4局恢复", e._bot_fangshui(e.players[2]) is False)

if __name__ == "__main__":
    print("=" * 46)
    print("冒险关卡1-4 回归测试")
    print("=" * 46)
    test_suit_count_priority()
    test_suit_quality_priority()
    test_flush_discard_off_suit()
    test_flush_discard_isolated()
    test_block_win_goal()
    test_block_failed_flag()
    test_guaranteed_hand_partials()
    test_story_multi_fight()
    test_smoke_full_round()
    test_fangshui()
    print("=" * 46)
    if FAIL:
        print(f"失败 {len(FAIL)} 项: {FAIL}")
        sys.exit(1)
    print(f"全部通过 ({PASS} 项)")
