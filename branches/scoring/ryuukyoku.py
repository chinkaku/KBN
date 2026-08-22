# -*- coding: utf-8 -*-
"""组合麻将 — 流局计分(组合类番种)"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from collections import Counter
from game_engine import Tile, TileType, is_winning_hand
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

def calculate_ryuukyoku(hand, melds_outside=None, locked_yaku=None, fan_map=None):
    """对 13+杠张手牌计算流局得分(组合番)

    枚举手牌所有可能的合法面子子集,对每种组合计算番数,取最大值。
    locked_yaku: 未解锁(锁定)番种集合(冒险模式番种锁/章节计分策略), 锁定的不参与流局组合番
    fan_map:     番值覆盖 {番种名: 番值}
    """
    if melds_outside is None:
        melds_outside = []
    if locked_yaku is None:
        locked_yaku = set()
    if fan_map is None:
        fan_map = {}

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
        full_melds = hand_melds  # 只含手牌面子, 副露单独通过 melds_outside 传入, 避免重复计数
        decomp = FakeDecomp(full_melds)

        group_best = {}
        group_name = {}
        for yaku_class in ALL_YAKU:
            g = yaku_class.group
            if g not in COMBO_GROUPS:
                continue
            if yaku_class.name in locked_yaku:
                continue  # 未解锁(锁定)的番种不参与流局组合番
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
                fan = fan_map.get(yaku_class.name, fan)  # 番值覆盖(冒险模式)
                gv = g.value if hasattr(g, 'value') else str(g)
                if gv not in group_best or fan > group_best[gv]:
                    group_best[gv] = fan
                    group_name[gv] = yaku_class.name

        # 大三元不能复合十二归: 中发白四张不能既当三元刻子又当"四张不成杠"
        if "大三元" in group_name.values() and "十二归" in group_name.values():
            for _g in list(group_name):
                if group_name[_g] == "十二归":
                    del group_best[_g]
                    del group_name[_g]

        total = sum(group_best.values())
        if total > best_total:
            best_total = total
            best_details = [
                {'group': g, 'name': group_name[g], 'fan': v}
                for g, v in group_best.items() if v > 0
            ]

    return best_total, best_details


# ---- 听算 (流局听牌得分) ----

_ALL_TILE_TYPES = None

def _all_tile_types():
    """34种可能的牌张(用于枚举听牌和牌可能)"""
    global _ALL_TILE_TYPES
    if _ALL_TILE_TYPES is None:
        _ALL_TILE_TYPES = []
        for tt in (TileType.MAN, TileType.PIN, TileType.SOU):
            for r in range(1, 10):
                _ALL_TILE_TYPES.append(Tile(tt, r))
        for r in range(7):
            _ALL_TILE_TYPES.append(Tile(TileType.HONOUR, r))
    return _ALL_TILE_TYPES

def calculate_tenpai_score(hand, melds_outside=None, locked_yaku=None, fan_map=None):
    """听算: 枚举当前手牌所有和牌可能, 计算(全体番+组合番, 不含门前清/偶然番)最高番数

    返回 (fan, details, waiting_count)
      fan:          最高番数 (听算得分 = fan × 1)
      details:      该和牌型的番种详情
      waiting_count: 听牌张数 (>0 表示听牌; 未听牌返回 0)
    locked_yaku: 未解锁(锁定)番种集合, 锁定的不参与听算
    fan_map:     番值覆盖 {番种名: 番值}
    """
    if melds_outside is None:
        melds_outside = []
    if locked_yaku is None:
        locked_yaku = set()
    if fan_map is None:
        fan_map = {}
    from .scorer import calculate_fan

    # 已用牌张计数(手牌+副露): 某张已用满4张则不能再听它(不存在第5张)
    used = Counter(hand)
    for m in melds_outside:
        used.update(m.tiles if hasattr(m, 'tiles') else m)

    best_fan = 0
    best_details = []
    waiting = 0
    for tile in _all_tile_types():
        if used[tile] >= 4:
            continue  # 手牌+副露已用尽4张, 无法听
        test_hand = hand + [tile]
        ok, wt = is_winning_hand(test_hand, melds_outside)
        if not ok:
            continue
        waiting += 1
        fan, details = calculate_fan(
            test_hand, melds_outside, win_type=wt, return_details=True,
            exclude_groups={YG.STATE, YG.CHANCE},
            locked_yaku=locked_yaku, fan_map=fan_map,
        )
        if fan > best_fan:
            best_fan = fan
            best_details = details

    return best_fan, best_details, waiting


def calculate_ryuukyoku_full(hand, melds_outside=None, locked_yaku=None, fan_map=None):
    """流局总分: 取 [组合番×2] 与 [听算×1] 更高者 (听算默认开启)

    返回 dict:
      fan:        采用的番数(展示用)
      score:      实际得分
      details:    采用的番种详情
      method:     '听算' 或 '组合番'
      waiting:    听牌张数
      combo_fan:  组合番番数
      tenpai_fan: 听算番数(未听牌为0)
    locked_yaku: 未解锁(锁定)番种集合(冒险模式番种锁/章节计分策略)
    fan_map:     番值覆盖 {番种名: 番值}
    """
    if melds_outside is None:
        melds_outside = []

    combo_fan, combo_details = calculate_ryuukyoku(hand, melds_outside, locked_yaku=locked_yaku, fan_map=fan_map)
    tenpai_fan, tenpai_details, waiting = calculate_tenpai_score(hand, melds_outside, locked_yaku=locked_yaku, fan_map=fan_map)

    combo_score = combo_fan * 2
    tenpai_score = tenpai_fan * 1  # 听算按番数×1计分

    if tenpai_score > combo_score:
        return {
            'fan': tenpai_fan, 'score': tenpai_score, 'details': tenpai_details,
            'method': '听算', 'waiting': waiting,
            'combo_fan': combo_fan, 'tenpai_fan': tenpai_fan,
        }
    return {
        'fan': combo_fan, 'score': combo_score, 'details': combo_details,
        'method': '组合番', 'waiting': waiting,
        'combo_fan': combo_fan, 'tenpai_fan': tenpai_fan,
    }
