# -*- coding: utf-8 -*-
from enum import Enum
from collections import Counter, defaultdict
from itertools import combinations, product
from typing import List, Tuple, Dict, Set, Optional
from .hand_decomp import (
    Yaku, YakuGroup, MeldsAndPair, enum_standard_decompositions,
    tiles_from_counter
)
from game_engine import Tile, TileType

# ============================================================
# 辅助函数
# ============================================================
# 这些工具函数供番种 check() 方法调用，用来判断牌型特征。
# ============================================================

def flatten_melds(decomp: MeldsAndPair) -> List[Tile]:
    """把所有面子和雀头展平为一维牌列表"""
    return decomp.pair + sum([list(m) for m in decomp.melds], [])

def all_tiles_equal(tiles, prop):
    """判断 tiles 中每张牌是否都满足 prop(t)==True"""
    return all(prop(t) for t in tiles)

def ranks_from_melds(decomp: MeldsAndPair) -> Set[int]:
    """从拆解的面子和雀头中提取所有非字牌的序数集合"""
    r = set()
    for m in decomp.melds:
        for t in m:
            if t.tile_type != TileType.HONOUR:
                r.add(t.rank)
    for t in decomp.pair:
        if t.tile_type != TileType.HONOUR:
            r.add(t.rank)
    return r

def has_honours(tiles):
    """牌列表中是否包含字牌"""
    return any(t.tile_type == TileType.HONOUR for t in tiles)

def is_terminal_or_honour(t):
    """幺九牌判定: 字牌 或 序数为1/9的数牌"""
    return t.tile_type == TileType.HONOUR or t.rank in (1, 9)

def is_terminal(t):
    """纯幺牌判定: 序数为1/9的数牌(不含字牌)"""
    return t.tile_type != TileType.HONOUR and t.rank in (1, 9)

def is_middle(t):
    """中张牌判定: 序数2~8的数牌"""
    return t.tile_type != TileType.HONOUR and 2 <= t.rank <= 8

def meld_contains_tiles(meld, rank, ttype=None):
    """面子中是否包含指定序数(和可选花色)的牌"""
    return any(t.rank == rank and (ttype is None or t.tile_type == ttype) for t in meld)

def meld_is_pung(meld):
    """判断一个面子是否为刻子(三张完全相同)"""
    return len(meld) == 3 and all(meld[0] == t for t in meld)

def meld_is_sequence(meld):
    """判断一个面子是否为顺子(同花色,序数连续,如2-3-4)

    注意: 字牌不能组成顺子，调用前需确保 meld 中的牌已经被排序或
    通过 ranks[2]-ranks[0]==2 判断 range 为 2。
    当前实现要求 meld 中 3 张牌的序数排好后首尾差=2，且花色全同。
    """
    if len(meld) != 3: return False
    if any(t.tile_type == TileType.HONOUR for t in meld): return False
    ranks = sorted(t.rank for t in meld)
    return ranks[2] - ranks[0] == 2 and len(set(t.tile_type for t in meld)) == 1

def meld_is_kong(meld_outside):
    """判断一个副露面子是否为杠子(4张)"""
    return isinstance(meld_outside, list) and len(meld_outside) == 4

# ========== 直属 ==========

class 九莲宝灯(Yaku):
    group = YakuGroup.JHIHO; name = "九莲宝灯"; fan = 48
    @classmethod
    def check(cls, hand_all, decomp=None, melds_outside=None, win_type="标准和", **kw):
        if win_type != "标准和": return 0
        if melds_outside: return 0  # 必须门前清
        if decomp is None or not decomp.is_menzen: return 0
        cnt = Counter(hand_all)
        ttype = None
        for t in hand_all:
            if t.tile_type != TileType.HONOUR:
                if ttype is None: ttype = t.tile_type
                elif t.tile_type != ttype: return 0
        if ttype is None: return 0
        for rank in range(1, 10):
            required = 3 if rank in (1, 9) else 1
            if cnt[Tile(ttype, rank)] < required: return 0
        return cls.fan

class 十三幺(Yaku):
    group = YakuGroup.JHIHO; name = "十三幺"; fan = 24
    applies_to_thirteen_orphans = True
    applies_to_standard = False  # 仅十三幺牌型
    @classmethod
    def check(cls, hand_all, win_type="", melds_outside=None, **kw):
        if melds_outside: return 0  # 十三幺不能有副露
        if len(hand_all) != 14: return 0  # 必须是14张
        # 验证手牌确实是十三幺型: 13种幺九牌各1张 + 其中1种2张
        orphans = [
            Tile(TileType.MAN,1),Tile(TileType.MAN,9),
            Tile(TileType.PIN,1),Tile(TileType.PIN,9),
            Tile(TileType.SOU,1),Tile(TileType.SOU,9),
        ] + [Tile(TileType.HONOUR,i) for i in range(7)]
        cnt = Counter(hand_all)
        for ot in orphans:
            if cnt[ot] == 0:
                return 0
        pair_count = sum(1 for c in cnt.values() if c == 2)
        if pair_count == 1 and len(cnt) == 13:
            return cls.fan
        return 0

# ========== 色形类 ==========

class 字一色(Yaku):
    applies_to_seven_pairs = True
    group = YakuGroup.COLOR; name = "字一色"; fan = 16
    @classmethod
    def check(cls, hand_all, melds_outside=None, **kw):
        all_tiles = list(hand_all)
        if melds_outside:
            all_tiles += sum([list(m.tiles) for m in melds_outside], [])
        if all_tiles_equal(all_tiles, lambda t: t.tile_type == TileType.HONOUR): return cls.fan
        return 0

class 清一色(Yaku):
    applies_to_seven_pairs = True
    group = YakuGroup.COLOR; name = "清一色"; fan = 12
    @classmethod
    def check(cls, hand_all, melds_outside=None, **kw):
        all_tiles = list(hand_all)
        if melds_outside: all_tiles += sum([list(m.tiles) for m in melds_outside], [])
        suits = set(t.tile_type for t in all_tiles if t.tile_type != TileType.HONOUR)
        if len(suits) == 1 and not has_honours(all_tiles): return cls.fan
        return 0

class 混一色(Yaku):
    applies_to_seven_pairs = True
    group = YakuGroup.COLOR; name = "混一色"; fan = 6
    @classmethod
    def check(cls, hand_all, melds_outside=None, **kw):
        all_tiles = list(hand_all)
        if melds_outside: all_tiles += sum([list(m.tiles) for m in melds_outside], [])
        suits = set(t.tile_type for t in all_tiles if t.tile_type != TileType.HONOUR)
        if len(suits) == 1 and has_honours(all_tiles): return cls.fan
        return 0

class 缺一门(Yaku):
    applies_to_seven_pairs = True
    group = YakuGroup.COLOR; name = "缺一门"; fan = 2
    @classmethod
    def check(cls, hand_all, melds_outside=None, **kw):
        all_tiles = list(hand_all)
        if melds_outside: all_tiles += sum([list(m.tiles) for m in melds_outside], [])
        suits = set(t.tile_type for t in all_tiles if t.tile_type != TileType.HONOUR)
        if len(suits) == 2: return cls.fan
        return 0

# ========== 自由类 ==========

class 连数(Yaku):
    """仅由序数牌组成,含且仅含连续的某几种序数,任意两组牌之间无重复序数"""
    group = YakuGroup.FREE; name = "连数"; fan = 8
    @classmethod
    def check(cls, hand_all, decomp=None, melds_outside=None, **kw):
        if decomp is None: return 0
        if has_honours(hand_all): return 0
        # 每个面子(含副露)和雀头的序数区间不交叉
        parts = []
        for m in decomp.melds:
            ranks = sorted([t.rank for t in m])
            parts.append((ranks[0], ranks[-1]))
        for mo in (melds_outside or []):
            ts = mo.tiles if hasattr(mo, 'tiles') else mo
            ranks = sorted([t.rank for t in ts if t.tile_type != TileType.HONOUR])
            if ranks:
                parts.append((ranks[0], ranks[-1]))
        rpair = [t.rank for t in decomp.pair]
        parts.append((rpair[0], rpair[0]))
        parts.sort()
        for i in range(len(parts) - 1):
            if parts[i][1] >= parts[i+1][0]:
                return 0
        # 占满连续序数: 从 min_rank 到 max_rank 每个rank都有牌
        ranks_used = set(t.rank for t in hand_all if t.tile_type != TileType.HONOUR)
        if not ranks_used: return 0
        min_r, max_r = min(ranks_used), max(ranks_used)
        for r in range(min_r, max_r + 1):
            if r not in ranks_used:
                return 0
        return cls.fan

class 五门齐(Yaku):
    """包含万/筒/索/风/箭五类牌"""
    group = YakuGroup.FREE; name = "五门齐"; fan = 3
    @classmethod
    def check(cls, hand_all, melds_outside=None, **kw):
        all_tiles = list(hand_all)
        if melds_outside: all_tiles += sum([list(m.tiles) for m in melds_outside], [])
        types = set()
        has_wind = False; has_dragon = False
        for t in all_tiles:
            if t.tile_type == TileType.HONOUR:
                if t.rank <= 3: has_wind = True
                else: has_dragon = True
            else:
                types.add(t.tile_type)
        if len(types) == 3 and has_wind and has_dragon: return cls.fan
        return 0

# ========== 数聚类 ==========

class 三聚(Yaku):
    applies_to_seven_pairs = True
    """所有牌序数在{x,x+1,x+2}中,允许缺项"""
    group = YakuGroup.CLUSTER; name = "三聚"; fan = 12
    @classmethod
    def check(cls, hand_all, decomp=None, melds_outside=None, **kw):
        all_tiles = list(hand_all)
        if melds_outside: all_tiles += sum([list(m.tiles) for m in melds_outside], [])
        if has_honours(all_tiles): return 0
        ranks = set(t.rank for t in all_tiles)
        if len(ranks) <= 3 and max(ranks) - min(ranks) <= 2: return cls.fan
        return 0

class 四聚(Yaku):
    applies_to_seven_pairs = True
    group = YakuGroup.CLUSTER; name = "四聚"; fan = 4
    @classmethod
    def check(cls, hand_all, melds_outside=None, **kw):
        all_tiles = list(hand_all)
        if melds_outside: all_tiles += sum([list(m.tiles) for m in melds_outside], [])
        if has_honours(all_tiles): return 0
        ranks = set(t.rank for t in all_tiles)
        if len(ranks) <= 4 and max(ranks) - min(ranks) <= 3: return cls.fan
        return 0

# ========== 数形类 ==========

class 二数(Yaku):
    applies_to_seven_pairs = True
    """含且仅含两个数字,无字牌"""
    group = YakuGroup.NUMFORM; name = "二数"; fan = 16
    @classmethod
    def check(cls, hand_all, melds_outside=None, **kw):
        all_tiles = list(hand_all)
        if melds_outside: all_tiles += sum([list(m.tiles) for m in melds_outside], [])
        if has_honours(all_tiles): return 0
        ranks = set(t.rank for t in all_tiles)
        if len(ranks) == 2: return cls.fan
        return 0

class 间数(Yaku):
    applies_to_seven_pairs = True
    """所有序数在公差不为1的等差数列中,无字牌"""
    group = YakuGroup.NUMFORM; name = "间数"; fan = 6
    @classmethod
    def check(cls, hand_all, melds_outside=None, **kw):
        all_tiles = list(hand_all)
        if melds_outside: all_tiles += sum([list(m.tiles) for m in melds_outside], [])
        if has_honours(all_tiles): return 0
        ranks = sorted(set(t.rank for t in all_tiles))
        if len(ranks) < 3: return 0
        diffs = set(ranks[i+1] - ranks[i] for i in range(len(ranks)-1))
        if len(diffs) == 1 and next(iter(diffs)) != 1: return cls.fan
        return 0

# ========== 幺九类 ==========

class 清幺九(Yaku):
    applies_to_seven_pairs = True
    """仅由一、九序数牌组成(无字牌无中张)"""
    group = YakuGroup.TERMINAL; name = "清幺九"; fan = 24
    @classmethod
    def check(cls, hand_all, melds_outside=None, **kw):
        all_tiles = list(hand_all)
        if melds_outside: all_tiles += sum([list(m.tiles) for m in melds_outside], [])
        if has_honours(all_tiles): return 0
        if all(t.rank in (1, 9) for t in all_tiles if t.tile_type != TileType.HONOUR): return cls.fan
        return 0

class 混幺九(Yaku):
    applies_to_seven_pairs = True
    """仅由一、九序数牌和/或字牌组成(无中张)"""
    group = YakuGroup.TERMINAL; name = "混幺九"; fan = 12
    @classmethod
    def check(cls, hand_all, melds_outside=None, **kw):
        all_tiles = list(hand_all)
        if melds_outside: all_tiles += sum([list(m.tiles) for m in melds_outside], [])
        if all(is_terminal_or_honour(t) for t in all_tiles): return cls.fan
        return 0

class 清全带幺(Yaku):
    applies_to_seven_pairs = True
    """诸面子和雀头都含1或9且不含字牌"""
    group = YakuGroup.TERMINAL; name = "清全带幺"; fan = 8
    @classmethod
    def check(cls, hand_all, decomp=None, melds_outside=None, **kw):
        if has_honours(hand_all): return 0
        if decomp is None or not decomp.melds: return 0
        for m in decomp.melds:
            if not any(is_terminal(t) for t in m): return 0
        if not any(is_terminal(t) for t in decomp.pair): return 0
        return cls.fan

class 混全带幺(Yaku):
    applies_to_seven_pairs = True
    """诸面子和雀头都含幺九"""
    group = YakuGroup.TERMINAL; name = "混全带幺"; fan = 4
    @classmethod
    def check(cls, hand_all, decomp=None, melds_outside=None, **kw):
        if decomp is None or not decomp.melds: return 0
        for m in decomp.melds:
            if not any(is_terminal_or_honour(t) for t in m): return 0
        if not any(is_terminal_or_honour(t) for t in decomp.pair): return 0
        return cls.fan

# ========== 对子类 ==========

class 七对子(Yaku):
    """七对子 — 由七个对子组成的特殊和牌(仅适用于七对和牌型)"""
    group = YakuGroup.PAIR; name = "七对子"; fan = 8
    applies_to_seven_pairs = True
    applies_to_standard = False  # 标准和牌型不适用七对子
    @classmethod
    def check(cls, hand_all=None, win_type="", **kw):
        if win_type != "七对": return 0
        if hand_all is None: return 0
        if len(hand_all) != 14: return 0
        cnt = Counter(hand_all)
        pairs = sum(1 for c in cnt.values() if c == 2)
        if pairs == 7 and len(cnt) == 7: return cls.fan
        return 0

# ========== 刻子类 ==========

class 四刻(Yaku):
    """和牌中有四个刻子(含杠子)"""
    group = YakuGroup.TRIPLET; name = "四刻"; fan = 4
    @classmethod
    def check(cls, decomp=None, melds_outside=None, **kw):
        if decomp is None: return 0
        pung_count = sum(1 for m in decomp.melds if meld_is_pung(m))
        # 副露中的碰和杠都算
        outside_count = 0
        for m in (melds_outside or []):
            ts = m.tiles if hasattr(m, 'tiles') else (m if isinstance(m, list) else [])
            if len(ts) >= 3 and all(ts[0] == t for t in ts):
                outside_count += 1
        if pung_count + outside_count >= 4: return cls.fan
        return 0

# ========== 暗刻类 ==========

def _is_concealed_pung(meld, extra):
    """判断一个刻子是否为暗刻(不包含荣和牌或副露牌)"""
    ron_tile = (extra or {}).get('ron_tile')
    if ron_tile and any(t == ron_tile for t in meld):
        return False
    return True

class 四暗刻(Yaku):
    group = YakuGroup.CONCEALED; name = "四暗刻"; fan = 24
    @classmethod
    def check(cls, decomp=None, melds_outside=None, extra=None, **kw):
        if melds_outside: return 0
        if decomp is None or not decomp.is_menzen: return 0
        # 荣和时,含荣和牌的刻子不算暗刻
        concealed = sum(1 for m in decomp.melds if meld_is_pung(m) and _is_concealed_pung(m, extra))
        if concealed == 4: return cls.fan
        return 0

class 三暗刻(Yaku):
    group = YakuGroup.CONCEALED; name = "三暗刻"; fan = 12
    @classmethod
    def check(cls, decomp=None, melds_outside=None, extra=None, **kw):
        if decomp is None: return 0
        concealed = sum(1 for m in decomp.melds if meld_is_pung(m) and _is_concealed_pung(m, extra))
        dark_kong = sum(1 for m in (melds_outside or []) if hasattr(m,'meld_type') and m.meld_type == 'DARK_KONG')
        if concealed + dark_kong >= 3: return cls.fan
        return 0

class 双暗刻(Yaku):
    group = YakuGroup.CONCEALED; name = "双暗刻"; fan = 3
    @classmethod
    def check(cls, decomp=None, melds_outside=None, extra=None, **kw):
        if decomp is None: return 0
        concealed = sum(1 for m in decomp.melds if meld_is_pung(m) and _is_concealed_pung(m, extra))
        dark_kong = sum(1 for m in (melds_outside or []) if hasattr(m,'meld_type') and m.meld_type == 'DARK_KONG')
        if concealed + dark_kong >= 2: return cls.fan
        return 0

# ============================================================
# 杂刻类
# ============================================================
# 统计不同 rank 上各有多少个花色的刻子。
# 例如 rank=2 上有 MAN 和 PIN 的刻子 -> rank_pungs[2] = {MAN, PIN}
# 可用于判断"三色同刻"(一个rank三个花色各有一刻)、
# "双同刻"(一个rank两个花色各有一刻)等。
# ============================================================

def _count_pungs_by_rank(decomp, melds_outside):
    rank_pungs = defaultdict(set)
    if decomp is None: return rank_pungs
    for m in decomp.melds:
        if meld_is_pung(m) and m[0].tile_type != TileType.HONOUR:
            rank_pungs[m[0].rank].add(m[0].tile_type)
    for mo in (melds_outside or []):
        ts = mo.tiles if hasattr(mo,'tiles') else (mo if isinstance(mo,list) else [])
        if len(ts) >= 3 and all(ts[0] == t for t in ts) and ts[0].tile_type != TileType.HONOUR:
            rank_pungs[ts[0].rank].add(ts[0].tile_type)
    return rank_pungs

class 三色同刻(Yaku):
    group = YakuGroup.MIXED_TRIP; name = "三色同刻"; fan = 12
    @classmethod
    def check(cls, decomp=None, melds_outside=None, **kw):
        if decomp is None: return 0
        rp = _count_pungs_by_rank(decomp, melds_outside)
        if any(len(suits) == 3 for suits in rp.values()): return cls.fan
        return 0

class 三色连刻(Yaku):
    group = YakuGroup.MIXED_TRIP; name = "三色连刻"; fan = 6
    @classmethod
    def check(cls, decomp=None, melds_outside=None, **kw):
        if decomp is None: return 0
        rp = _count_pungs_by_rank(decomp, melds_outside)
        suits_per_rank = {r: s for r, s in rp.items() if s}
        if len(suits_per_rank) < 3: return 0
        # 需要三个连续rank各有至少一个花色刻子
        ranks = sorted(suits_per_rank.keys())
        for i in range(len(ranks) - 2):
            r1, r2, r3 = ranks[i], ranks[i+1], ranks[i+2]
            if r2 - r1 == 1 and r3 - r2 == 1:
                # 三个rank不能是同一个花色的
                all_suits = set()
                for r in [r1, r2, r3]:
                    all_suits |= suits_per_rank[r]
                if len(all_suits) >= 3:  # 至少三个花色
                    return cls.fan
        return 0

class 两双同刻(Yaku):
    group = YakuGroup.MIXED_TRIP; name = "两双同刻"; fan = 6
    @classmethod
    def check(cls, decomp=None, melds_outside=None, **kw):
        if decomp is None: return 0
        rp = _count_pungs_by_rank(decomp, melds_outside)
        count = sum(1 for s in rp.values() if len(s) >= 2)
        if count >= 2: return cls.fan
        return 0

class 双同刻(Yaku):
    group = YakuGroup.MIXED_TRIP; name = "双同刻"; fan = 2
    @classmethod
    def check(cls, decomp=None, melds_outside=None, **kw):
        if decomp is None: return 0
        rp = _count_pungs_by_rank(decomp, melds_outside)
        if any(len(s) >= 2 for s in rp.values()): return cls.fan
        return 0

# ========== 连刻类 ==========

# BUG: 第 421 行 'return rank_pungs' 中 rank_pungs 未定义，
# 这行永远不会执行（因为前一行已经 if decomp is None: return r），
# 实际不会触发运行时错误，但应删除此行。
def _get_pung_ranks(decomp, melds_outside):
    """收集所有序数刻子按花色分组的 rank, 已排序。
    供四连刻/三连刻/双连刻/四刻等 yaku 复用。
    返回 {TileType: [ranks]} — 同名 yaku 的要求是同色, 须按花色分别检查。
    例: 手牌 111m 222m + 副露 333m(碰) → {MAN: [1,2,3]}
    """
    from collections import defaultdict
    r = defaultdict(list)
    if decomp is None: return r
    for m in decomp.melds:
        if meld_is_pung(m) and m[0].tile_type != TileType.HONOUR:
            r[m[0].tile_type].append(m[0].rank)
    for mo in (melds_outside or []):
        ts = mo.tiles if hasattr(mo,'tiles') else (mo if isinstance(mo,list) else [])
        if len(ts) >= 3 and all(ts[0] == t for t in ts) and ts[0].tile_type != TileType.HONOUR:
            r[ts[0].tile_type].append(ts[0].rank)
    # 每组花色内排序
    for t in r: r[t] = sorted(r[t])
    return r

class 四连刻(Yaku):
    """同色四副序数连续的刻子, 如 111m 222m 333m 444m"""
    group = YakuGroup.SEQ_TRIP; name = "四连刻"; fan = 24
    @classmethod
    def check(cls, decomp=None, melds_outside=None, **kw):
        ranks_by_suit = _get_pung_ranks(decomp, melds_outside)
        # 每个花色的rank分别检查连续四连
        for ranks in ranks_by_suit.values():
            if len(ranks) >= 4:
                for i in range(len(ranks)-3):
                    if ranks[i+1]-ranks[i]==1 and ranks[i+2]-ranks[i+1]==1 and ranks[i+3]-ranks[i+2]==1:
                        return cls.fan
        return 0

class 三连刻(Yaku):
    """三连刻: 同色至少三副序数连续的刻子(或杠), 如 111m 222m 333m"""
    group = YakuGroup.SEQ_TRIP; name = "三连刻"; fan = 12
    @classmethod
    def check(cls, decomp=None, melds_outside=None, **kw):
        ranks_by_suit = _get_pung_ranks(decomp, melds_outside)
        # 每个花色分别检查: 是否有三个连续的 rank
        # 例: {MAN: [1,2,3,4]} → 找到 [1,2,3] 连续 → 12番
        # 反例: {MAN: [1], PIN: [2], SOU: [3]} → 不同花色不算
        for ranks in ranks_by_suit.values():
            for i in range(len(ranks)-2):
                if ranks[i+1]-ranks[i]==1 and ranks[i+2]-ranks[i+1]==1:
                    return cls.fan
        return 0

class 两双连刻(Yaku):
    """和牌中有独立的两组各两副同色序数递增1的刻子。"""
    group = YakuGroup.SEQ_TRIP; name = "两双连刻"; fan = 12
    @classmethod
    def check(cls, decomp=None, melds_outside=None, **kw):
        pungs = defaultdict(list)  # suit -> [ranks]
        if decomp:
            for m in decomp.melds:
                if meld_is_pung(m) and m[0].tile_type != TileType.HONOUR:
                    pungs[m[0].tile_type].append(m[0].rank)
        for mo in (melds_outside or []):
            ts = mo.tiles if hasattr(mo,'tiles') else (mo if isinstance(mo,list) else [])
            if len(ts) >= 3 and all(ts[0] == t2 for t2 in ts) and ts[0].tile_type != TileType.HONOUR:
                pungs[ts[0].tile_type].append(ts[0].rank)
        pair_count = 0
        for ranks in pungs.values():
            s = sorted(set(ranks))
            i = 0
            while i < len(s) - 1:
                if s[i+1] - s[i] == 1:
                    pair_count += 1
                    i += 2
                else:
                    i += 1
        if pair_count >= 2: return cls.fan
        return 0

class 双连刻(Yaku):
    """同色至少两副序数连续的刻子, 如 111m 222m"""
    group = YakuGroup.SEQ_TRIP; name = "双连刻"; fan = 2
    @classmethod
    def check(cls, decomp=None, melds_outside=None, **kw):
        ranks_by_suit = _get_pung_ranks(decomp, melds_outside)
        for ranks in ranks_by_suit.values():
            for i in range(len(ranks)-1):
                if ranks[i+1]-ranks[i]==1: return cls.fan
        return 0

# ========== 杂顺类 ==========

def _get_sequences(decomp, melds_outside):
    """返回所有顺子: [(花色, 起始rank), ...]"""
    seqs = []
    if decomp is None: return seqs
    for m in decomp.melds:
        if meld_is_sequence(m):
            seqs.append((m[0].tile_type, m[0].rank))
    for mo in (melds_outside or []):
        ts = mo.tiles if hasattr(mo,'tiles') else (mo if isinstance(mo,list) else [])
        if len(ts) == 3 and all(t.tile_type != TileType.HONOUR for t in ts):
            ranks = sorted(t.rank for t in ts)
            if ranks[2]-ranks[0]==2 and len(set(t.tile_type for t in ts))==1:
                seqs.append((ts[0].tile_type, min(t.rank for t in ts)))
    return seqs

class 三色贯通(Yaku):
    """三色三副序数依次递增3的顺子, 如 123m 456p 789s (1,4,7跨三色)"""
    group = YakuGroup.MIXED_SEQ; name = "三色贯通"; fan = 4
    @classmethod
    def check(cls, decomp=None, melds_outside=None, **kw):
        seqs = _get_sequences(decomp, melds_outside)
        # 收集每个 rank 有哪些花色有顺子
        suit_at_rank = {}
        for ttype, rank in seqs:
            if rank not in suit_at_rank: suit_at_rank[rank] = set()
            suit_at_rank[rank].add(ttype)
        # 检查 1-4-7, 2-5-8, 3-6-9 三组
        for r in range(1, 4):
            s1 = suit_at_rank.get(r, set())
            s2 = suit_at_rank.get(r+3, set())
            s3 = suit_at_rank.get(r+6, set())
            # 三个rank都有顺子, 且花色并集 = 三种花色
            if s1 and s2 and s3 and len(s1|s2|s3) >= 3:
                return cls.fan
        return 0

class 三色同顺(Yaku):
    """三色三副序数相同的顺子, 如 123m 123p 123s"""
    group = YakuGroup.MIXED_SEQ; name = "三色同顺"; fan = 4
    @classmethod
    def check(cls, decomp=None, melds_outside=None, **kw):
        seqs = _get_sequences(decomp, melds_outside)
        by_rank = defaultdict(set)
        for ttype, rank in seqs: by_rank[rank].add(ttype)
        if any(len(s) >= 3 for s in by_rank.values()): return cls.fan
        return 0

class 镜同(Yaku):
    """两色各两副面子互相序数匹配(刻子/杠子等效)"""
    group = YakuGroup.MIXED_SEQ; name = "镜同"; fan = 4
    @classmethod
    def check(cls, decomp=None, melds_outside=None, **kw):
        if decomp is None: return 0
        suit_melds = defaultdict(set)  # suit -> {frozenset of ranks}
        for m in decomp.melds:
            ranks = frozenset(t.rank for t in m)
            suit_melds[m[0].tile_type].add(ranks)
        for mo in (melds_outside or []):
            ts = mo.tiles if hasattr(mo,'tiles') else (mo if isinstance(mo,list) else [])
            if ts:
                ranks = frozenset(t.rank for t in ts)
                suit_melds[ts[0].tile_type].add(ranks)
        suits = [s for s in [TileType.MAN,TileType.PIN,TileType.SOU] if len(suit_melds[s]) >= 2]
        for i in range(len(suits)):
            for j in range(i+1, len(suits)):
                if suit_melds[suits[i]] == suit_melds[suits[j]]:
                    return cls.fan
        return 0

class 双相逢(Yaku):
    """独立的两组各两副序数相同且花色不同的顺子"""
    group = YakuGroup.MIXED_SEQ; name = "双相逢"; fan = 3
    @classmethod
    def check(cls, decomp=None, melds_outside=None, **kw):
        seqs = _get_sequences(decomp, melds_outside)
        by_rank = defaultdict(set)
        for ttype, rank in seqs: by_rank[rank].add(ttype)
        count = sum(1 for s in by_rank.values() if len(s) >= 2)
        if count >= 2: return cls.fan
        return 0

class 喜相逢(Yaku):
    """两副序数相同且花色不同的顺子"""
    group = YakuGroup.MIXED_SEQ; name = "喜相逢"; fan = 1
    @classmethod
    def check(cls, decomp=None, melds_outside=None, **kw):
        seqs = _get_sequences(decomp, melds_outside)
        by_rank = defaultdict(set)
        for ttype, rank in seqs: by_rank[rank].add(ttype)
        if any(len(s) >= 2 for s in by_rank.values()): return cls.fan
        return 0

# ========== 连顺类 ==========

def _get_seq_ranks(decomp, melds_outside):
    """返回所有顺子的起始rank list"""
    seqs = _get_sequences(decomp, melds_outside)
    return sorted(r for _, r in seqs)

class 四步高(Yaku):
    """四个顺子在同花色,起始rank递增"""
    group = YakuGroup.SEQ_SEQ; name = "四步高"; fan = 24
    @classmethod
    def check(cls, decomp=None, melds_outside=None, **kw):
        seqs = _get_sequences(decomp, melds_outside)
        by_type = defaultdict(list)
        for ttype, rank in seqs: by_type[ttype].append(rank)
        for ranks in by_type.values():
            if len(ranks) >= 4:
                s = sorted(ranks)
                for i in range(len(s)-3):
                    if s[i+1]-s[i]==1 and s[i+2]-s[i+1]==1 and s[i+3]-s[i+2]==1:
                        return cls.fan
        return 0

class 四连环(Yaku):
    """同色四副序数依次递增2的顺子(123,345,567,789)"""
    group = YakuGroup.SEQ_SEQ; name = "四连环"; fan = 16
    @classmethod
    def check(cls, decomp=None, melds_outside=None, **kw):
        seqs = _get_sequences(decomp, melds_outside)
        by_type = defaultdict(list)
        for ttype, rank in seqs: by_type[ttype].append(rank)
        for ranks in by_type.values():
            if len(ranks) >= 4:
                s = sorted(ranks)
                for i in range(len(s)-3):
                    if s[i+1]-s[i]==2 and s[i+2]-s[i+1]==2 and s[i+3]-s[i+2]==2:
                        return cls.fan
        return 0

class 三步高(Yaku):
    group = YakuGroup.SEQ_SEQ; name = "三步高"; fan = 8
    @classmethod
    def check(cls, decomp=None, melds_outside=None, **kw):
        seqs = _get_sequences(decomp, melds_outside)
        by_type = defaultdict(list)
        for ttype, rank in seqs: by_type[ttype].append(rank)
        for ranks in by_type.values():
            if len(ranks) >= 3:
                s = sorted(ranks)
                for i in range(len(s)-2):
                    if s[i+1]-s[i]==1 and s[i+2]-s[i+1]==1: return cls.fan
        return 0

class 三连环(Yaku):
    """同色至少三副序数依次递增2的顺子"""
    group = YakuGroup.SEQ_SEQ; name = "三连环"; fan = 6
    @classmethod
    def check(cls, decomp=None, melds_outside=None, **kw):
        seqs = _get_sequences(decomp, melds_outside)
        by_type = defaultdict(list)
        for ttype, rank in seqs: by_type[ttype].append(rank)
        for ranks in by_type.values():
            if len(ranks) >= 3:
                s = sorted(ranks)
                for i in range(len(s)-2):
                    if s[i+1]-s[i]==2 and s[i+2]-s[i+1]==2: return cls.fan
        return 0

# ========== 龙顺类 ==========

class 一气贯通(Yaku):
    """同花色123+456+789"""
    group = YakuGroup.DRAGON; name = "一气贯通"; fan = 6
    @classmethod
    def check(cls, decomp=None, melds_outside=None, **kw):
        seqs = _get_sequences(decomp, melds_outside)
        by_type = defaultdict(set)
        for ttype, rank in seqs: by_type[ttype].add(rank)
        for ttype, sranks in by_type.items():
            if 1 in sranks and 4 in sranks and 7 in sranks: return cls.fan
        return 0

class 双龙会(Yaku):
    """独立的两组各两副同色且序数相差3的顺子(如123+456为一组)"""
    group = YakuGroup.DRAGON; name = "双龙会"; fan = 3
    @classmethod
    def check(cls, decomp=None, melds_outside=None, **kw):
        seqs = _get_sequences(decomp, melds_outside)
        by_type = defaultdict(list)
        for ttype, rank in seqs: by_type[ttype].append(rank)
        pair_count = 0
        for ranks in by_type.values():
            s = sorted(set(ranks))
            used = set()
            for r in s:
                if r in used: continue
                if r + 3 in s:
                    used.add(r); used.add(r + 3)
                    pair_count += 1
        if pair_count >= 2: return cls.fan
        return 0

class 连六(Yaku):
    """同花色顺子连六个数字"""
    group = YakuGroup.DRAGON; name = "连六"; fan = 1
    @classmethod
    def check(cls, decomp=None, melds_outside=None, **kw):
        seqs = _get_sequences(decomp, melds_outside)
        by_type = defaultdict(set)
        for ttype, rank in seqs: by_type[ttype].add(rank)
        for ranks in by_type.values():
            s = sorted(ranks)
            for i in range(len(s)-1):
                if s[i+1]-s[i]==3: return cls.fan  # 差3=中间缺一个,两顺连六
        return 0

# ========== 同顺类 ==========

class 四同顺(Yaku):
    group = YakuGroup.SAME_SEQ; name = "四同顺"; fan = 40
    @classmethod
    def check(cls, decomp=None, melds_outside=None, **kw):
        seqs = _get_sequences(decomp, melds_outside)
        by_rank_type = defaultdict(int)
        for ttype, rank in seqs:
            by_rank_type[(ttype, rank)] += 1
        if any(c >= 4 for c in by_rank_type.values()): return cls.fan
        return 0

class 三同顺(Yaku):
    group = YakuGroup.SAME_SEQ; name = "三同顺"; fan = 16
    @classmethod
    def check(cls, decomp=None, melds_outside=None, **kw):
        seqs = _get_sequences(decomp, melds_outside)
        by_rank_type = defaultdict(int)
        for ttype, rank in seqs:
            by_rank_type[(ttype, rank)] += 1
        if any(c >= 3 for c in by_rank_type.values()): return cls.fan
        return 0

class 两般高(Yaku):
    group = YakuGroup.SAME_SEQ; name = "两般高"; fan = 12
    @classmethod
    def check(cls, decomp=None, melds_outside=None, **kw):
        seqs = _get_sequences(decomp, melds_outside)
        by_rank_type = defaultdict(int)
        for ttype, rank in seqs:
            by_rank_type[(ttype, rank)] += 1
        pairs = sum(1 for c in by_rank_type.values() if c >= 2)
        if pairs >= 2: return cls.fan
        return 0

class 一般高(Yaku):
    group = YakuGroup.SAME_SEQ; name = "一般高"; fan = 2
    @classmethod
    def check(cls, decomp=None, melds_outside=None, **kw):
        seqs = _get_sequences(decomp, melds_outside)
        by_rank_type = defaultdict(int)
        for ttype, rank in seqs:
            by_rank_type[(ttype, rank)] += 1
        if any(c >= 2 for c in by_rank_type.values()): return cls.fan
        return 0

# ============================================================
# 归子类
# ============================================================
# "归"指同一个序数的牌出现4张但不成杠。在不同和牌型中有不同形式:
#   标准和牌: 四归=同一花色同一序数的牌出现4张且不成杠
#            如手中4张1s分在顺子和刻子里: 123s + 111s 等
#            八归=2组四归, 十二归=3组四归
#   七对子:   龙对=同一花色同一序数的牌出现4张作为两个对子
#            (如1s1s+1s1s,不是1m1m+1s1s)
#            双龙对=2组龙对=3组龙对
#
# _count_same_ranks: 跨花色统计(用于标准和牌的归子)
# _count_by_full_tile: 按完整牌身统计(用于七对子的龙对)
# _count_dragon_pairs: 统计七对子中同色同序4张的对子数
# ============================================================

def _count_same_ranks(tiles):
    """统计每个rank出现的次数(跨花色,用于标准和牌归子)"""
    cnt = defaultdict(int)
    for t in tiles:
        if t.tile_type != TileType.HONOUR:
            cnt[t.rank] += 1
    return cnt

def _count_by_full_tile(tiles):
    """统计每张完整牌出现的次数(同花色同序数)"""
    return Counter(t.to_shorthand() for t in tiles)

def _count_dragon_pairs(hand_all):
    """统计七对子中的龙对数量。"""
    cnt = _count_by_full_tile(hand_all)
    dragons = 0
    for c in cnt.values():
        if c == 4:
            dragons += 1
    return dragons

def _has_n_gui(hand_tiles, n, kong_tiles=None):
    """检查是否是n归(不计杠子牌)"""
    rc = _count_by_full_tile(hand_tiles)
    # 扣除杠子牌
    if kong_tiles:
        for t in kong_tiles:
            sh = t.to_shorthand()
            if sh in rc:
                rc[sh] = max(0, rc[sh] - 4)
    gui_count = sum(c // 4 for c in rc.values())
    return gui_count >= n // 4

class 十二归(Yaku):
    group = YakuGroup.RETURN; name = "十二归"; fan = 24
    @classmethod
    def check(cls, hand_all, win_type="", kong_tiles=None, **kw):
        if win_type != "标准和": return 0
        if _has_n_gui(hand_all, 12, kong_tiles): return cls.fan
        return 0

class 八归(Yaku):
    group = YakuGroup.RETURN; name = "八归"; fan = 12
    @classmethod
    def check(cls, hand_all, win_type="", kong_tiles=None, **kw):
        if win_type != "标准和": return 0
        if _has_n_gui(hand_all, 8, kong_tiles): return cls.fan
        return 0

class 四归(Yaku):
    group = YakuGroup.RETURN; name = "四归"; fan = 2
    @classmethod
    def check(cls, hand_all, win_type="", kong_tiles=None, **kw):
        if win_type not in ("标准和", ""): return 0
        if _has_n_gui(hand_all, 4, kong_tiles): return cls.fan
        return 0

# ========== 杠子类 ==========

def _count_kongs(melds_outside):
    if not melds_outside: return 0
    return sum(1 for m in melds_outside if hasattr(m,'meld_type') and m.meld_type in ('KONG','DARK_KONG'))

def _count_dark_kongs(melds_outside):
    if not melds_outside: return 0
    return sum(1 for m in melds_outside if hasattr(m,'meld_type') and m.meld_type == 'DARK_KONG')

class 四杠(Yaku):
    group = YakuGroup.KONG; name = "四杠"; fan = 40
    @classmethod
    def check(cls, melds_outside=None, **kw):
        if _count_kongs(melds_outside) >= 4: return cls.fan
        return 0

class 三杠(Yaku):
    group = YakuGroup.KONG; name = "三杠"; fan = 16
    @classmethod
    def check(cls, melds_outside=None, **kw):
        if _count_kongs(melds_outside) >= 3: return cls.fan
        return 0

class 双杠(Yaku):
    group = YakuGroup.KONG; name = "双杠"; fan = 4
    @classmethod
    def check(cls, melds_outside=None, **kw):
        if _count_kongs(melds_outside) >= 2: return cls.fan
        return 0

class 暗杠番(Yaku):
    group = YakuGroup.KONG; name = "暗杠"; fan = 2
    @classmethod
    def check(cls, melds_outside=None, **kw):
        if _count_dark_kongs(melds_outside) >= 1: return cls.fan
        return 0

class 一杠(Yaku):
    group = YakuGroup.KONG; name = "一杠"; fan = 1
    @classmethod
    def check(cls, melds_outside=None, **kw):
        if _count_kongs(melds_outside) >= 1: return cls.fan
        return 0

# ========== 全字类 ==========

def _honor_counts(hand_all, melds_outside):
    all_tiles = list(hand_all)
    if melds_outside: all_tiles += sum([list(m.tiles) for m in melds_outside], [])
    # 只计数字牌
    cnt = Counter(t for t in all_tiles if t.tile_type == TileType.HONOUR)
    return cnt

class 大四喜(Yaku):
    applies_to_seven_pairs = True
    group = YakuGroup.ALL_HONOR; name = "大四喜"; fan = 40
    @classmethod
    def check(cls, hand_all, melds_outside=None, **kw):
        cnt = _honor_counts(hand_all, melds_outside)
        # 东南西北各至少3张
        if all(cnt[Tile(TileType.HONOUR, i)] >= 3 for i in range(4)): return cls.fan
        return 0

class 小四喜(Yaku):
    applies_to_seven_pairs = True
    group = YakuGroup.ALL_HONOR; name = "小四喜"; fan = 24
    @classmethod
    def check(cls, hand_all, melds_outside=None, **kw):
        cnt = _honor_counts(hand_all, melds_outside)
        wind_counts = [cnt[Tile(TileType.HONOUR, i)] for i in range(4)]
        # 三个各>=3, 一个>=2
        big = sum(1 for c in wind_counts if c >= 3)
        pair = sum(1 for c in wind_counts if c >= 2)
        if big >= 3 and pair == 4: return cls.fan
        return 0

class 大三元(Yaku):
    applies_to_seven_pairs = True
    group = YakuGroup.ALL_HONOR; name = "大三元"; fan = 24
    @classmethod
    def check(cls, hand_all, melds_outside=None, **kw):
        cnt = _honor_counts(hand_all, melds_outside)
        if all(cnt[Tile(TileType.HONOUR, i)] >= 3 for i in [4, 5, 6]): return cls.fan
        return 0

class 小三元(Yaku):
    applies_to_seven_pairs = True
    group = YakuGroup.ALL_HONOR; name = "小三元"; fan = 12
    @classmethod
    def check(cls, hand_all, melds_outside=None, **kw):
        cnt = _honor_counts(hand_all, melds_outside)
        drg = [cnt[Tile(TileType.HONOUR, i)] for i in [4, 5, 6]]
        big = sum(1 for c in drg if c >= 3)
        pair = sum(1 for c in drg if c >= 2)
        if big >= 2 and pair == 3: return cls.fan
        return 0

# ========== 字刻类 ==========

def _count_honor_pungs(decomp, melds_outside):
    count = 0
    if decomp is None: return count
    for m in decomp.melds:
        if meld_is_pung(m) and m[0].tile_type == TileType.HONOUR:
            count += 1
    for mo in (melds_outside or []):
        ts = mo.tiles if hasattr(mo,'tiles') else (mo if isinstance(mo,list) else [])
        if len(ts) >= 3 and all(ts[0] == t for t in ts) and ts[0].tile_type == TileType.HONOUR:
            count += 1
    return count

class 四字刻(Yaku):
    group = YakuGroup.HONOR_TRIP; name = "四字刻"; fan = 12
    @classmethod
    def check(cls, decomp=None, melds_outside=None, **kw):
        if _count_honor_pungs(decomp, melds_outside) >= 4: return cls.fan
        return 0

class 三字刻(Yaku):
    group = YakuGroup.HONOR_TRIP; name = "三字刻"; fan = 6
    @classmethod
    def check(cls, decomp=None, melds_outside=None, **kw):
        if _count_honor_pungs(decomp, melds_outside) >= 3: return cls.fan
        return 0

class 双字刻(Yaku):
    group = YakuGroup.HONOR_TRIP; name = "双字刻"; fan = 2
    @classmethod
    def check(cls, decomp=None, melds_outside=None, **kw):
        if _count_honor_pungs(decomp, melds_outside) >= 2: return cls.fan
        return 0

class 字刻(Yaku):
    group = YakuGroup.HONOR_TRIP; name = "字刻"; fan = 1
    @classmethod
    def check(cls, decomp=None, melds_outside=None, **kw):
        if _count_honor_pungs(decomp, melds_outside) >= 1: return cls.fan
        return 0

# ========== 字对类 ==========

def _count_honor_pairs(hand_all):
    """统计七对子中的字牌对子数量。
    例如 hand_all = [E,E,S,S,C,C] → 返回 3 (三个字牌对)。
    注意：这里用 to_shorthand() 做 key，避免 Tile 对象 equals 的问题。
    """
    cnt_short = Counter(t.to_shorthand() for t in hand_all if t.tile_type == TileType.HONOUR)
    return sum(1 for c in cnt_short.values() if c >= 2)

class 字对(Yaku):
    """雀头或未成面的余牌中有一对字牌(标准和牌=雀头;流局=余牌对)"""
    group = YakuGroup.HONOR_PAIR; name = "字对"; fan = 1
    applies_to_standard = True
    @classmethod
    def check(cls, hand_all=None, decomp=None, win_type="", **kw):
        # 标准和牌: 检查雀头是否为字牌
        if decomp is not None and decomp.pair and decomp.pair[0].tile_type == TileType.HONOUR:
            return cls.fan
        # 流局: 统计全部字牌张数, 若有未被刻子完全消耗的字牌2张以上,即算字对
        if hand_all is not None:
            honor_total = Counter(t for t in hand_all if t.tile_type == TileType.HONOUR)
            used_in_pungs = Counter()
            if decomp is not None:
                for m in decomp.melds:
                    if meld_is_pung(m) and m[0].tile_type == TileType.HONOUR:
                        used_in_pungs[m[0]] += 3
            for t, total in honor_total.items():
                used = used_in_pungs.get(t, 0)
                remaining = total - used
                if remaining >= 2:
                    return cls.fan
        return 0
# ============================================================
# 同对类 (仅适用于七对子和牌型)
# ============================================================
# 双同对: 同一序数在两个花色各有一对 (如1m1m+1p1p)
# 三同对: 同一序数在三个花色各有一对 (如1m1m+1p1p+1s1s)
# _analyze_seven_pairs: 返回 { double_pairs: n, triple_pairs: m }
# ============================================================

def _analyze_seven_pairs(hand_all):
    """返回(数字同对计数, 三色同三对计数)"""
    cnt = Counter(t.to_shorthand() for t in hand_all)
    # 只分析数牌
    rank_suit = defaultdict(set)  # rank -> {suit}
    pairs = {}  # shorthand -> count
    for sh, c in cnt.items():
        if c >= 2:
            pairs[sh] = c // 2
            if sh[-1] in 'mps':
                rank_suit[int(sh[0])].add(sh[-1])

    # 双同对: 同一rank在两个花色各有一对
    double_pairs = 0
    for rank, suits in rank_suit.items():
        suit_list = list(suits)
        for s1, s2 in combinations(suit_list, 2):
            sh1 = f"{rank}{s1}"; sh2 = f"{rank}{s2}"
            # 检查两个花色是否都满足>=2
            if cnt.get(sh1, 0) >= 2 and cnt.get(sh2, 0) >= 2:
                double_pairs += 1

    # 三同对: 同一rank在三个花色各有一对
    triple_pairs = 0
    for rank, suits in rank_suit.items():
        if len(suits) >= 3:
            if all(cnt.get(f"{rank}{s}", 0) >= 2 for s in ['m', 'p', 's']):
                triple_pairs += 1

    return {
        'double_pairs': double_pairs,
        'triple_pairs': triple_pairs,
    }

class 三双同对(Yaku):
    group = YakuGroup.SAME_PAIR; name = "三双同对"; fan = 8
    applies_to_seven_pairs = True; applies_to_standard = False
    @classmethod
    def check(cls, hand_all, win_type="", **kw):
        if win_type != "七对": return 0
        d = _analyze_seven_pairs(hand_all)
        if d['double_pairs'] >= 3: return cls.fan
        return 0

class 两双同对(Yaku):
    group = YakuGroup.SAME_PAIR; name = "两双同对"; fan = 3
    applies_to_seven_pairs = True; applies_to_standard = False
    @classmethod
    def check(cls, hand_all, win_type="", **kw):
        if win_type != "七对": return 0
        d = _analyze_seven_pairs(hand_all)
        if d['double_pairs'] >= 2: return cls.fan
        return 0

class 双同对(Yaku):
    group = YakuGroup.SAME_PAIR; name = "双同对"; fan = 1
    applies_to_seven_pairs = True; applies_to_standard = False
    @classmethod
    def check(cls, hand_all, win_type="", **kw):
        if win_type != "七对": return 0
        d = _analyze_seven_pairs(hand_all)
        if d['double_pairs'] >= 1: return cls.fan
        return 0

class 两三同对(Yaku):
    group = YakuGroup.SAME_PAIR; name = "两三同对"; fan = 12
    applies_to_seven_pairs = True; applies_to_standard = False
    @classmethod
    def check(cls, hand_all, win_type="", **kw):
        if win_type != "七对": return 0
        d = _analyze_seven_pairs(hand_all)
        if d['triple_pairs'] >= 2: return cls.fan
        return 0

class 三同对(Yaku):
    group = YakuGroup.SAME_PAIR; name = "三同对"; fan = 3
    applies_to_seven_pairs = True; applies_to_standard = False
    @classmethod
    def check(cls, hand_all, win_type="", **kw):
        if win_type != "七对": return 0
        d = _analyze_seven_pairs(hand_all)
        if d['triple_pairs'] >= 1: return cls.fan
        return 0

# ========== 状态类 ==========

class 门前清(Yaku):
    applies_to_seven_pairs = True
    group = YakuGroup.STATE; name = "门前清"; fan = 2
    @classmethod
    def check(cls, melds_outside=None, **kw):
        if not melds_outside: return cls.fan
        return 0

class 无番和(Yaku):
    group = YakuGroup.STATE; name = "无番和"; fan = 6
    @classmethod
    def check(cls, **kw):
        return 0  # 在计算总番数后判断

# ========== 偶然类 ==========

class 天地和(Yaku):
    group = YakuGroup.CHANCE; name = "天地和"; fan = 12
    @classmethod
    def check(cls, extra=None, **kw):
        if extra and extra.get('tenhou_chiho'): return cls.fan
        return 0

class 岭上开花(Yaku):
    group = YakuGroup.CHANCE; name = "岭上开花"; fan = 3
    @classmethod
    def check(cls, extra=None, **kw):
        if extra and extra.get('rinshan'): return cls.fan
        return 0

class 枯木逢春(Yaku):
    group = YakuGroup.CHANCE; name = "枯木逢春"; fan = 3
    @classmethod
    def check(cls, extra=None, **kw):
        if extra and extra.get('haitei'): return cls.fan
        return 0

class 金鸡夺食(Yaku):
    group = YakuGroup.CHANCE; name = "金鸡夺食"; fan = 3
    @classmethod
    def check(cls, extra=None, **kw):
        if extra and extra.get('chankan'): return cls.fan
        return 0

# ========== 注册所有番种 ==========

ALL_YAKU = [
    九莲宝灯, 十三幺,
    字一色, 清一色, 混一色, 缺一门,
    连数, 五门齐,
    三聚, 四聚,
    二数, 间数,
    清幺九, 混幺九, 清全带幺, 混全带幺,
    七对子,
    四刻,
    四暗刻, 三暗刻, 双暗刻,
    三色同刻, 三色连刻, 两双同刻, 双同刻,
    四连刻, 三连刻, 两双连刻, 双连刻,
    三色贯通, 三色同顺, 镜同, 双相逢, 喜相逢,
    四步高, 四连环, 三步高, 三连环,
    一气贯通, 双龙会, 连六,
    四同顺, 三同顺, 两般高, 一般高, 十二归, 八归, 四归,
    四杠, 三杠, 双杠, 暗杠番, 一杠,
    大四喜, 小四喜, 大三元, 小三元,
    四字刻, 三字刻, 双字刻, 字刻, 字对,
    三双同对, 两双同对, 双同对, 两三同对, 三同对,
    门前清, 无番和,
    天地和, 岭上开花, 枯木逢春, 金鸡夺食,
]

YAKU_BY_GROUP = defaultdict(list)
for y in ALL_YAKU:
    YAKU_BY_GROUP[y.group].append(y)
