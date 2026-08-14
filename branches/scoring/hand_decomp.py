# -*- coding: utf-8 -*-
"""组合麻将 算番引擎 — 手牌拆解 + 番种判定"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from collections import Counter, defaultdict
from itertools import combinations
from enum import Enum
from typing import List, Tuple, Dict, Set, Optional
from game_engine import Tile, TileType

# ============================================================
# 拆解结构
# ============================================================
# 一副标准和牌型（14张）可以拆成 4个面子 + 1个雀头。
# 面子可以是 刻子(pung) 或 顺子(chow)，各3张。
# 副露(melds_outside)是已经摊开的吃碰杠，不计入拆解，
# 直接作为已知的固定面子抵扣（需要的手牌面子数 = 4 - len(melds_outside)）。
# ============================================================

class MeldsAndPair:
    """一副手牌的完整拆解：4面子+1雀头

    Attributes:
        melds: List[List[Tile]]  每个面子是3张牌的list
        pair:  List[Tile]        雀头的2张牌
        is_menzen: bool          门前清（无副露时True）
    """
    def __init__(self):
        self.melds = []
        self.pair = []
        self.is_menzen = True

def enum_standard_decompositions(tiles: List[Tile], melds_outside: List = None) -> List[MeldsAndPair]:
    """枚举手牌在给定副露下的所有合法面子和雀头拆解。

    算法思路：
    1. 确定还需要几个手牌面子：needed_melds = 4 - len(melds_outside)
    2. 遍历所有可能的雀头（手中出现>=2次的牌）
    3. 对于每种雀头，递归找出所有能把剩余手牌拆成 needed_melds 个面子的方案
    4. 返回所有合法拆解

    Args:
        tiles: 手牌（不含副露的牌）
        melds_outside: 副露面子列表（碰/吃/杠），不计入手牌拆解
    Returns:
        所有合法拆解的列表，无合法拆解时返回空列表
    """
    if melds_outside is None:
        melds_outside = []
    outside_count = sum(len(m) if isinstance(m, list) else len(m.tiles) for m in melds_outside)
    hand_tiles = list(tiles)
    needed_melds = 4 - len(melds_outside)

    results = []
    tile_count = Counter(hand_tiles)
    candidates = [t for t, c in tile_count.items() if c >= 2]
    seen_pairs = set()

    for pair_tile in candidates:
        pid = pair_tile.to_shorthand()
        if pid in seen_pairs:
            continue
        seen_pairs.add(pid)

        remaining = list(hand_tiles)
        for _ in range(2):
            remaining.remove(pair_tile)

        meld_results = []
        find_melds(remaining, needed_melds, [], meld_results)

        for melds in meld_results:
            r = MeldsAndPair()
            r.pair = [pair_tile, pair_tile]
            r.melds = melds
            r.is_menzen = (len(melds_outside) == 0)
            results.append(r)

    # 如果没有合法拆解，返回空
    return results

def find_melds(remaining: List[Tile], count: int, current: List, results: List):
    """递归回溯：从 remaining 中找出 count 个面子的所有组合。

    算法：
    1. 如果 count==0 且 remaining 为空：找到一个完整拆解，加入 results
    2. 取 remaining 中按 (花色,序数) 排序最小的牌作为 first
    3. 尝试用 first 做刻子（需要3张相同）
    4. 尝试用 first 做顺子（需要同花色 first+1, first+2 各至少1张）
    5. 两种分支各递归一次

    这样可以保证每个面子组合只被枚举一次，不会重复。
    注意：这里的顺子判定永远按 first 作为最小张构造，
    避免了 (2,3,4) 和 (3,4,5) 重叠双计的问题。

    Args:
        remaining: 剩余未分配的牌
        count: 还需要几个面子
        current: 当前已构造的面子列表（递归栈）
        results: 输出结果列表
    """
    if count == 0:
        if len(remaining) == 0:
            results.append([list(m) for m in current])
        return
    if len(remaining) < 3:
        return

    cnt = Counter(remaining)
    first = min(cnt.keys(), key=lambda t: (t.tile_type.value, t.rank))

    # 刻子
    if cnt[first] >= 3:
        nc = cnt.copy()
        nc[first] -= 3
        rem = tiles_from_counter(nc)
        find_melds(rem, count - 1, current + [[first, first, first]], results)

    # 顺子
    if first.tile_type != TileType.HONOUR and first.rank <= 7:
        t2 = Tile(first.tile_type, first.rank + 1)
        t3 = Tile(first.tile_type, first.rank + 2)
        if cnt[t2] > 0 and cnt[t3] > 0:
            nc = cnt.copy()
            nc[first] -= 1
            nc[t2] -= 1
            nc[t3] -= 1
            rem = tiles_from_counter(nc)
            find_melds(rem, count - 1, current + [[first, t2, t3]], results)

def tiles_from_counter(cnt: Counter) -> List[Tile]:
    result = []
    for t, c in cnt.items():
        result.extend([t] * c)
    return result

# ========== 番种判定 基类 ==========

# ============================================================
# 番种类别（22行，每行内只取最大番种，行间累加）
# ============================================================
# 计分规则：同一行内的多个番种只取番数最大的那个，
# 不同行之间的番数累加。比如同时满足"清一色12番"和"混一色6番"
# （都在色形类），只取清一色12番。
# 但如果还满足"一气贯通6番"（龙顺类），则再加6番。
# ============================================================

class YakuGroup(Enum):
    JHIHO = "直属"           # 九莲宝灯 十三幺 — 不计全体番和组合番
    COLOR = "色形类"          # 字一色 清一色 混一色 缺一门
    FREE = "自由类"           # 连数 五门齐
    CLUSTER = "数聚类"         # 三聚 四聚
    NUMFORM = "数形类"         # 二数 三数 间数
    TERMINAL = "幺九类"        # 清幺九 混幺九 清全带幺 混全带幺
    PAIR = "对子类"           # 七对子
    TRIPLET = "刻子类"         # 四刻
    CONCEALED = "暗刻类"       # 四暗刻 三暗刻 双暗刻
    MIXED_TRIP = "杂刻类"      # 三色同刻 三色连刻 两双同刻 双同刻
    SEQ_TRIP = "连刻类"        # 四连刻 三连刻 双连刻
    MIXED_SEQ = "杂顺类"       # 三色贯通 三色同顺 镜同 双相逢 喜相逢
    SEQ_SEQ = "连顺类"         # 四步高 四连环 三步高 三连环
    DRAGON = "龙顺类"          # 一气贯通 双龙会 连六
    SAME_SEQ = "同顺类"        # 四同顺 三同顺 两般高 一般高
    RETURN = "归子类"          # 三龙对 十二归 双龙对 八归 龙对 四归
    KONG = "杠子类"            # 四杠 三杠 双杠 暗杠 一杠
    ALL_HONOR = "全字类"       # 大四喜 小四喜 大三元 小三元
    HONOR_TRIP = "字刻类"      # 四字刻 三字刻 双字刻 字刻
    HONOR_PAIR = "字对类"       # 字七对～字对
    SAME_PAIR = "同对类"       # 三双同对～三同对（仅七对子）
    STATE = "状态类"           # 门前清 无番和
    CHANCE = "偶然类"           # 天地和 岭上开花 枯木逢春 金鸡夺食

class Yaku:
    """番种基类 — 每个具体番种继承此类并覆写 check()。

    Attributes:
        group: YakuGroup — 所属类别（同一类别只取最大番数）
        name: str — 番种中文名
        fan: int — 番数
        applies_to_standard: bool — 是否适用于标准和牌
        applies_to_seven_pairs: bool — 是否适用于七对子
        applies_to_thirteen_orphans: bool — 是否适用于十三幺

    check() 方法:
        接收 **kwargs:
            hand_all: 全部14张牌（手牌+副露）
            decomp: MeldsAndPair — 拆解结果（七对/十三幺时为None）
            melds_outside: 副露列表
            win_type: "标准和" / "七对" / "十三幺"
            is_self_draw: 是否自摸
            is_dealer: 是否庄家
            extra: dict — 偶然类触发条件
        返回 int — 番数，不满足返回 0
    """
    group: YakuGroup = None
    name: str = ""
    fan: int = 0
    applies_to_standard: bool = True
    applies_to_seven_pairs: bool = False
    applies_to_thirteen_orphans: bool = False

    @classmethod
    def check(cls, hand_all: List[Tile], decomp: MeldsAndPair = None,
             melds_outside: List = None, win_type: str = "标准和",
             is_self_draw: bool = False, is_dealer: bool = False,
             extra: dict = None) -> int:
        """返回番数，不满足返回0"""
        return 0

# ========== 开始写具体番种 ==========

