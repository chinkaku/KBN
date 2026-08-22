# -*- coding: utf-8 -*-
"""组合麻将 主计分器"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from typing import List, Tuple, Dict
from collections import Counter
from game_engine import Tile, TileType, PlayerRole
from .hand_decomp import enum_standard_decompositions, MeldsAndPair, YakuGroup
from .yaku import ALL_YAKU, YAKU_BY_GROUP

# 直属番种(九莲宝灯/十三幺)不计的番种组: 全体番 + 组合番
JHIHO_EXCLUDED = {
    YakuGroup.COLOR, YakuGroup.FREE, YakuGroup.CLUSTER, YakuGroup.NUMFORM,
    YakuGroup.TERMINAL, YakuGroup.PAIR,
    YakuGroup.TRIPLET, YakuGroup.CONCEALED, YakuGroup.MIXED_TRIP, YakuGroup.SEQ_TRIP,
    YakuGroup.MIXED_SEQ, YakuGroup.SEQ_SEQ, YakuGroup.DRAGON, YakuGroup.SAME_SEQ,
    YakuGroup.RETURN, YakuGroup.KONG, YakuGroup.ALL_HONOR, YakuGroup.HONOR_TRIP,
    YakuGroup.HONOR_PAIR, YakuGroup.SAME_PAIR,
}

def calculate_fan(
    hand: List[Tile],
    melds_outside: List = None,
    win_type: str = "标准和",
    is_self_draw: bool = False,
    is_dealer: bool = False,
    extra: dict = None,
    return_details: bool = False,
    fan_map: dict = None,
    locked_yaku: set = None,
    exclude_groups: set = None,
):
    """
    核心函数：计算和牌番数。

    流程：
    1. 标准化 win_type（"标准"/"标准和"→"标准和", "七对子"→"七对"）
    2. 对标准和牌型，枚举手牌的全部合法拆解（enum_standard_decompositions）
    3. 对每种拆解，遍历 ALL_YAKU 中所有番种，调用其 check() 方法
    4. 按 YakuGroup 分组，每组只取番数最大的番种
    5. 各组番数相加 = 总番数
    6. 不同拆解可能得到不同总番数，取最大值
    7. 总番数=0 表示不满足任何番种（无番和已取消，不得和牌）

    Args:
        hand: 手牌列表
        melds_outside: 副露（碰/吃/杠/暗杠）
        win_type: 和牌类型
        return_details: 是否返回番种详情列表

    Returns:
        如果 return_details=False: int — 番数
        如果 return_details=True:  (番数, [{group, name, fan}, ...])
    """
    if melds_outside is None:
        melds_outside = []
    if extra is None:
        extra = {}
    if fan_map is None:
        fan_map = {}
    if locked_yaku is None:
        locked_yaku = set()
    if exclude_groups is None:
        exclude_groups = set()

    # ---- 构建总牌列表 ----
    all_tiles = list(hand)
    for m in melds_outside:
        all_tiles.extend(list(m.tiles) if hasattr(m, 'tiles') else m)

    # ---- 手牌拆解 ----
    # 标准化 win_type
    wt = win_type
    if wt in ("标准", "标准和"):
        wt = "标准和"
    elif wt == "七对子":
        wt = "七对"

    decomps = []
    if wt == "标准和":
        decomps = enum_standard_decompositions(hand, melds_outside)
        if not decomps:
            return (0, []) if return_details else 0
    elif wt == "七对":
        # 验证牌型确实是七对子: 14张, 7个对子, 无副露
        if melds_outside:
            return (0, []) if return_details else 0
        if len(hand) != 14:
            return (0, []) if return_details else 0
        cnt = Counter([t.to_shorthand() for t in hand])
        pairs = sum(c // 2 for c in cnt.values())  # 4张同牌=两个对子(龙对)
        if pairs != 7:
            return (0, []) if return_details else 0
        decomps = [None]
    elif wt == "十三幺":
        # 验证牌型确实是十三幺: 14张, 13种幺九牌各1 + 1种2张
        if melds_outside:
            return (0, []) if return_details else 0
        if len(hand) != 14:
            return (0, []) if return_details else 0
        orphans = [
            Tile(TileType.MAN,1),Tile(TileType.MAN,9),
            Tile(TileType.PIN,1),Tile(TileType.PIN,9),
            Tile(TileType.SOU,1),Tile(TileType.SOU,9),
        ] + [Tile(TileType.HONOUR,i) for i in range(7)]
        cnt2 = Counter(hand)
        for ot in orphans:
            if cnt2[ot] == 0:
                return (0, []) if return_details else 0
        pair_count = sum(1 for c in cnt2.values() if c == 2)
        if pair_count != 1 or len(cnt2) != 13:
            return (0, []) if return_details else 0
        decomps = [None]

    # ---- 对每种拆解计算番数,取最大 ----
    best_total = 0
    best_details = []
    for decomp in decomps:
        group_best = {}  # group -> max_fan
        group_name = {}  # group -> best yaku name

        # 收集杠子牌(用于归类排除)
        kong_tiles = []
        for m in melds_outside:
            if hasattr(m, 'meld_type') and m.meld_type in ('KONG', 'DARK_KONG'):
                kong_tiles.extend(m.tiles[:1])  # 只需要一张代表

        kwargs = {
            'hand_all': all_tiles,
            'hand': hand,  # 手牌(不含副露), 供暗刻家族按和牌张判定
            'decomp': decomp,
            'melds_outside': melds_outside,
            'win_type': wt,
            'is_self_draw': is_self_draw,
            'is_dealer': is_dealer,
            'extra': extra,
            'kong_tiles': kong_tiles,
        }

        has_jhiho = False
        jhiho_fan = 0
        jhiho_name = ""
        for yaku_class in ALL_YAKU:
            # 番种锁: 未解锁的番种不计分
            if yaku_class.name in locked_yaku:
                continue
            # 排除指定分组(听算时排除门前清/偶然番)
            if yaku_class.group in exclude_groups:
                continue
            # win_type filter - use normalized `wt`
            if wt == "标准和":
                if not yaku_class.applies_to_standard: continue
            elif wt == "七对":
                if not yaku_class.applies_to_seven_pairs: continue
            elif wt == "十三幺":
                if not yaku_class.applies_to_thirteen_orphans: continue

            # 直属番种(九莲宝灯/十三幺)不计全体番和组合番, 但保留状态类/偶然类
            if has_jhiho and yaku_class.group in JHIHO_EXCLUDED:
                continue

            fan = yaku_class.check(**kwargs)
            if fan > 0:
                # 可调番值(冒险模式)
                fan = fan_map.get(yaku_class.name, fan)
                g = yaku_class.group
                if g == YakuGroup.JHIHO:
                    has_jhiho = True
                    jhiho_fan = fan
                    jhiho_name = yaku_class.name
                    continue
                gv = g.value if hasattr(g, 'value') else str(g)
                # 同组取最高番; 番相同时优先"更具体"的番种(prefer_on_tie, 如番牌刻之于字刻)
                if gv not in group_best or fan > group_best[gv] or (
                        fan == group_best[gv] and getattr(yaku_class, 'prefer_on_tie', False)):
                    group_best[gv] = fan
                    group_name[gv] = yaku_class.name

        # 直属番种单独加入
        if has_jhiho:
            group_best["直属"] = jhiho_fan
            group_name["直属"] = jhiho_name

        total = sum(group_best.values())

        if total > best_total:
            best_total = total
            best_details = [
                {'group': g, 'name': group_name.get(g, ''), 'fan': v}
                for g, v in group_best.items() if v > 0
            ]

    if return_details:
        return best_total, best_details
    return best_total


def calculate_score_with_details(
    hand: List[Tile],
    melds_outside: List = None,
    win_type: str = "标准和",
    winner_role=None,
    dealer_role=None,
    is_self_draw: bool = False,
    extra: dict = None,
    fan_map: dict = None,
    locked_yaku: set = None,
):
    """
    返回 (番数, 详情列表)
    详情列表: [{'group': '色形类', 'name': '清一色', 'fan': 12}, ...]
    fan_map: 番值覆盖 {番种名: 番值}; locked_yaku: 未解锁番种名集合
    """
    fan, details = calculate_fan(hand, melds_outside, win_type, is_self_draw,
                                 is_dealer=(winner_role == PlayerRole.EAST if winner_role else False),
                                 extra=extra,
                                 return_details=True,
                                 fan_map=fan_map,
                                 locked_yaku=locked_yaku)
    if fan < 0:
        fan = 0
        details = []
    return fan, details


def calculate_score(
    hand: List[Tile],
    melds_outside: List = None,
    win_type: str = "标准和",
    winner_role=None,
    dealer_role=None,
    is_self_draw: bool = False,
    extra: dict = None,
    fan_map: dict = None,
    locked_yaku: set = None,
) -> int:
    fan, _ = calculate_score_with_details(hand, melds_outside, win_type,
                                          winner_role, dealer_role,
                                          is_self_draw, extra,
                                          fan_map=fan_map,
                                          locked_yaku=locked_yaku)
    return fan
