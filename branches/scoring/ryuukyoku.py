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

def _iter_structures(tiles):
    """枚举手牌拆解结构(去重): 面子(碰/吃) + 对子 + 余牌。

    yield (melds, pair):
      melds: [[t,t,t], ...] 手牌面子(碰/吃)
      pair:  [t,t,...] 对子牌(平铺, 允许多个对子), 无对子时 []
    余牌不进入结构(不参与番种判定); 副露不在此拆解(固定)。
    只枚举有效拆解, 相同结构只产生一次。
    """
    from collections import Counter
    cnt = Counter(tiles)
    seen = set()

    def dfs(rem, melds, pair):
        # 取最小的剩余牌, 保证确定性
        key = None
        for t in sorted(rem, key=lambda x: x.to_shorthand()):
            if rem[t] > 0:
                key = t
                break
        if key is None:
            sig = (
                tuple(sorted(
                    (tuple(sorted(m, key=lambda x: x.to_shorthand())) for m in melds),
                    key=lambda mm: tuple(t.to_shorthand() for t in mm),
                )),
                tuple(sorted(pair, key=lambda x: x.to_shorthand())),
            )
            if sig not in seen:
                seen.add(sig)
                yield (list(melds), list(pair))
            return
        c = rem[key]
        # 1) 对子 (允许多个)
        if c >= 2:
            rem[key] -= 2
            if rem[key] == 0:
                del rem[key]
            yield from dfs(rem, melds, pair + [key, key])
            rem[key] = c
        # 2) 刻子
        if c >= 3:
            rem[key] -= 3
            if rem[key] == 0:
                del rem[key]
            yield from dfs(rem, melds + [[key, key, key]], pair)
            rem[key] = c
        # 3) 顺子 (数牌 rank<=7)
        if key.tile_type != TileType.HONOUR and key.rank <= 7:
            k2 = Tile(key.tile_type, key.rank + 1)
            k3 = Tile(key.tile_type, key.rank + 2)
            if rem.get(k2, 0) > 0 and rem.get(k3, 0) > 0:
                rem[key] -= 1
                if rem[key] == 0:
                    del rem[key]
                for kk in (k2, k3):
                    rem[kk] -= 1
                    if rem[kk] == 0:
                        del rem[kk]
                yield from dfs(rem, melds + [[key, k2, k3]], pair)
                for kk in (k2, k3):
                    rem[kk] = rem.get(kk, 0) + 1
                rem[key] = c
        # 4) 留作余牌 (不参与番种判定)
        del rem[key]
        yield from dfs(rem, melds, pair)
        rem[key] = c

    yield from dfs(cnt, [], [])

def calculate_ryuukyoku(hand, melds_outside=None, locked_yaku=None, fan_map=None):
    """对 13+杠张手牌计算流局得分(组合番)

    拆解模型: 手牌拆为 面子(碰/吃) + 对子 + 余牌; 每种拆解独立计分取最大值;
    余牌不参与番种判定; 副露固定(不参与拆解, 作为固定单位参与判定)。
    大三元与十二归等"跨拆法叠加"由该模型天然消除。
    locked_yaku: 未解锁(锁定)番种集合(冒险模式番种锁/章节计分策略), 锁定的不参与流局组合番
    fan_map:     番值覆盖 {番种名: 番值}
    """
    if melds_outside is None:
        melds_outside = []
    if locked_yaku is None:
        locked_yaku = set()
    if fan_map is None:
        fan_map = {}

    kong_tiles = []
    for m in melds_outside:
        ts = m.tiles if hasattr(m, 'tiles') else (m if isinstance(m, list) else [])
        if hasattr(m, 'meld_type') and m.meld_type in ('KONG', 'DARK_KONG'):
            kong_tiles.append(ts[0])

    best_total = 0
    best_details = []

    class FakeDecomp:
        def __init__(self, melds, pair):
            self.melds = [list(m) for m in melds]
            self.pair = list(pair)
            self.is_menzen = (len(melds_outside) == 0)

    for melds, pair in _iter_structures(hand):
        decomp = FakeDecomp(melds, pair)
        # 已使用手牌 = 面子牌 + 对子牌 (余牌不参与)
        used = []
        for m in melds:
            used.extend(m)
        used.extend(pair)

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
                    hand_all=used,
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
