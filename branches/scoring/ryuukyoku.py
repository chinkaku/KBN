# -*- coding: utf-8 -*-
"""组合麻将 — 流局计分(组合类番种)"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from collections import Counter
from game_engine import Tile, TileType
from .yaku import (
    YakuGroup, ALL_YAKU,
    _get_sequences, _count_pungs_by_rank,
    meld_is_pung, meld_is_sequence,
    _count_honor_pungs, _count_by_full_tile, _has_n_gui,
)
from .hand_decomp import YakuGroup as YG

# 组合类番种的 group 列表
COMBO_GROUPS = {
    YG.TRIPLET, YG.CONCEALED, YG.MIXED_TRIP, YG.SEQ_TRIP,
    YG.MIXED_SEQ, YG.SEQ_SEQ, YG.DRAGON, YG.SAME_SEQ,
    YG.RETURN, YG.KONG, YG.ALL_HONOR, YG.HONOR_TRIP,
    YG.HONOR_PAIR, YG.SAME_PAIR,
}

def find_all_meld_sets(tiles):
    """枚举所有合法的不重叠面子子集 (支持重复面子, 如两般高需两个相同顺子)"""
    cnt = Counter(tiles)
    candidates = []
    # 刻子: 每种牌最多组成 cnt//3 个刻子
    for t, c in cnt.items():
        for _ in range(c // 3):
            candidates.append(('pung', [t, t, t]))
    # 顺子: 每种顺子最多组成 min(cnt[t1],cnt[t2],cnt[t3]) 个
    for ttype in [TileType.MAN, TileType.PIN, TileType.SOU]:
        for r in range(1, 8):
            t1 = Tile(ttype, r); t2 = Tile(ttype, r+1); t3 = Tile(ttype, r+2)
            max_count = min(cnt[t1], cnt[t2], cnt[t3])
            for _ in range(max_count):
                candidates.append(('chow', [t1, t2, t3]))
    if not candidates:
        return [[]]

    all_sets = []
    n = len(candidates)
    for mask in range(1 << n):
        used = Counter()
        ok = True
        for i in range(n):
            if mask & (1 << i):
                _, meld = candidates[i]
                for t in meld:
                    used[t] += 1
        for t, c in used.items():
            if c > cnt[t]:
                ok = False
                break
        if not ok:
            continue
        melds = [candidates[i] for i in range(n) if mask & (1 << i)]
        all_sets.append(melds)

    return all_sets if all_sets else [[]]

def calculate_ryuukyoku(hand, melds_outside=None):
    """对 13+杠张手牌计算流局得分(组合番)

    枚举手牌所有可能的合法面子子集,对每种组合计算番数,取最大值。
    """
    if melds_outside is None:
        melds_outside = []

    all_tiles = list(hand)
    kong_tiles = []
    outside_melds = []
    for m in melds_outside:
        all_tiles.extend(m.tiles)
        if hasattr(m, 'meld_type') and m.meld_type in ('KONG', 'DARK_KONG'):
            kong_tiles.append(m.tiles[0])
        # 副露面子的标准化形式
        ts = m.tiles
        if len(ts) >= 3 and all(ts[0] == t for t in ts):
            num = 3 if len(ts) == 4 else len(ts)
            outside_melds.append(('pung', [ts[0]] * num if num == 3 else list(ts)[:3]))
        elif len(ts) == 3:
            outside_melds.append(('chow', list(ts)))

    # 枚举所有手牌面子组合，对每种计算番数
    all_hand_sets = find_all_meld_sets(hand)
    best_total = 0
    best_details = []

    class FakeDecomp:
        def __init__(self, melds):
            self.melds = [list(m[1]) for m in melds]
            self.pair = []
            self.is_menzen = (len(melds_outside) == 0)

    for hand_melds in all_hand_sets:
        full_melds = hand_melds + outside_melds
        decomp = FakeDecomp(full_melds)

        group_best = {}
        group_name = {}
        for yaku_class in ALL_YAKU:
            g = yaku_class.group
            if g not in COMBO_GROUPS:
                continue
            try:
                fan = yaku_class.check(
                    hand_all=all_tiles,
                    decomp=decomp,
                    melds_outside=melds_outside,
                    win_type="标准和",
                    extra={},
                    kong_tiles=kong_tiles,
                )
            except Exception:
                fan = 0
            if fan > 0:
                gv = g.value if hasattr(g, 'value') else str(g)
                if gv not in group_best or fan > group_best[gv]:
                    group_best[gv] = fan
                    group_name[gv] = yaku_class.name

        total = sum(group_best.values())
        if total > best_total:
            best_total = total
            best_details = [
                {'group': g, 'name': group_name[g], 'fan': v}
                for g, v in group_best.items() if v > 0
            ]

    return best_total, best_details
