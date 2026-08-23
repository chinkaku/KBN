# -*- coding: utf-8 -*-
"""麻将游戏引擎 - 纯逻辑层，无 I/O"""
from enum import Enum
from typing import List, Optional, Tuple, Dict, Any
from dataclasses import dataclass
from collections import Counter
import random
import os, sys
# 算番模块延迟加载(避免循环引用)

class TileType(Enum):
    MAN = 'm'
    PIN = 'p'
    SOU = 's'
    HONOUR = 'z'

HONOUR_NAMES = ['E','S','W','N','C','F','P']
HONOUR_DISPLAY = ['东','南','西','北','中','发','白']
TYPE_DISPLAY = {'m':'万','p':'筒','s':'条'}

@dataclass(frozen=True)
class Tile:
    tile_type: TileType
    rank: int
    def to_shorthand(self):
        if self.tile_type == TileType.HONOUR:
            return HONOUR_NAMES[self.rank]
        return f'{self.rank}{self.tile_type.value}'
    @staticmethod
    def from_shorthand(s):
        s = s.strip().upper()
        if s in HONOUR_NAMES:
            return Tile(TileType.HONOUR, HONOUR_NAMES.index(s))
        rank = int(s[0])
        return Tile(TileType(s[1].lower()), rank)
    def is_terminal_or_honour(self):
        if self.tile_type == TileType.HONOUR:
            return True
        return self.rank in (1, 9)
    def display_name(self):
        if self.tile_type == TileType.HONOUR:
            return HONOUR_DISPLAY[self.rank]
        return f'{self.rank}{TYPE_DISPLAY[self.tile_type.value]}'

class PlayerRole(Enum):
    EAST = '东'
    SOUTH = '南'
    WEST = '西'
    NORTH = '北'

@dataclass
class MeldSet:
    tiles: list
    meld_type: str
    hidden_count: int = 0
    claimed_from: int = 0   # 鸣牌来源方向: 1=上家 2=对家 3=下家 0=无
    claimed_tile: object = None  # 被鸣走的那张牌(横置)
    added_tile: object = None    # 加杠新增的那张牌(横置,叠在原横置牌上)

class TileWall:
    def __init__(self):
        self.tiles = []
        self.head_idx = 0
        self.tail_idx = -1
    def initialize(self):
        self.tiles = []
        for tt in (TileType.MAN, TileType.PIN, TileType.SOU):
            for rank in range(1, 10):
                for _ in range(4):
                    self.tiles.append(Tile(tt, rank))
        for rank in range(7):
            for _ in range(4):
                self.tiles.append(Tile(TileType.HONOUR, rank))
        random.shuffle(self.tiles)
        self.head_idx = 0
        self.tail_idx = len(self.tiles) - 1
    def draw_from_head(self):
        if self.head_idx <= self.tail_idx:
            t = self.tiles[self.head_idx]
            self.head_idx += 1
            return t
        return None
    def draw_from_tail(self):
        if self.head_idx <= self.tail_idx:
            t = self.tiles[self.tail_idx]
            self.tail_idx -= 1
            return t
        return None
    def remaining_count(self):
        return max(0, self.tail_idx - self.head_idx + 1)
    def is_empty(self):
        return self.head_idx > self.tail_idx


class Player:
    def __init__(self, role, is_human=False):
        self.role = role
        self.is_human = is_human
        self.hand = []
        self.melds = []
        self.status_flag = None
        self.discards = []
        self.score = 0
        self.drawn_tile = None  # 本回合刚摸的牌
    def add_tile(self, tile):
        self.hand.append(tile)
    def remove_tile(self, tile):
        for i, t in enumerate(self.hand):
            if t == tile:
                self.hand.pop(i)
                return True
        return False
    def discard_tile(self, tile):
        if self.remove_tile(tile):
            self.discards.append(tile)
            return True
        return False
    def add_meld(self, meld):
        self.melds.append(meld)
    def sorted_hand_shorthands(self):
        s = sorted(self.hand, key=lambda t: (t.tile_type.value, t.rank))
        return [t.to_shorthand() for t in s]

# ==================== 和牌判定 ====================

def check_standard_win(hand, melds):
    total = hand + sum([m.tiles for m in melds], [])
    kong_count = sum(1 for m in melds if len(m.tiles) == 4)
    if len(total) != 14 + kong_count:
        return False
    meld_count = len(melds)
    needed = 4 - meld_count
    if len(hand) != 3 * needed + 2:
        return False
    cnt = Counter(hand)
    for pair_tile in list(cnt):
        if cnt[pair_tile] >= 2:
            remaining = list(hand)
            remaining.remove(pair_tile)
            remaining.remove(pair_tile)
            if can_form_melds(remaining, needed):
                return True
    return False

def check_seven_pairs(hand, melds):
    if melds:
        return False
    if len(hand) != 14:
        return False
    cnt = Counter(hand)
    return sum(1 for c in cnt.values() if c == 2) == 7 and len(cnt) == 7

def check_thirteen_orphans(tiles, melds):
    if melds:
        return False
    if len(tiles) != 14:
        return False
    orphans = [
        Tile(TileType.MAN,1),Tile(TileType.MAN,9),
        Tile(TileType.PIN,1),Tile(TileType.PIN,9),
        Tile(TileType.SOU,1),Tile(TileType.SOU,9),
    ] + [Tile(TileType.HONOUR,i) for i in range(7)]
    cnt = Counter(tiles)
    for ot in orphans:
        if cnt[ot] == 0:
            return False
    pair_count = sum(1 for c in cnt.values() if c == 2)
    return pair_count == 1 and len(cnt) == 13

def can_form_melds(tiles, meld_count):
    if meld_count == 0:
        return len(tiles) == 0
    if len(tiles) < 3:
        return False
    cnt = Counter(tiles)
    first = min(cnt.keys(), key=lambda t: (t.tile_type.value, t.rank))
    if cnt[first] >= 3:
        nc = cnt.copy()
        nc[first] -= 3
        rem = []
        for t, c in nc.items():
            rem.extend([t] * c)
        if can_form_melds(rem, meld_count - 1):
            return True
    if first.tile_type != TileType.HONOUR and first.rank <= 7:
        t2 = Tile(first.tile_type, first.rank + 1)
        t3 = Tile(first.tile_type, first.rank + 2)
        if cnt[t2] > 0 and cnt[t3] > 0:
            nc = cnt.copy()
            nc[first] -= 1
            nc[t2] -= 1
            nc[t3] -= 1
            rem = []
            for t, c in nc.items():
                rem.extend([t] * c)
            if can_form_melds(rem, meld_count - 1):
                return True
    return False

def is_winning_hand(hand, melds):
    total = hand + sum([m.tiles for m in melds], [])
    kong_count = sum(1 for m in melds if len(m.tiles) == 4)
    if len(total) != 14 + kong_count:
        return False, ''
    if check_thirteen_orphans(total, melds):
        return True, '十三幺'
    if check_seven_pairs(hand, melds):
        return True, '七对'
    if check_standard_win(hand, melds):
        return True, '标准和'
    return False, ''

def get_chow_options(hand, claimed_tile):
    if claimed_tile.tile_type == TileType.HONOUR:
        return []
    cnt = Counter(hand)
    options = []
    tt = claimed_tile.tile_type
    r = claimed_tile.rank
    if r >= 3:
        t1, t2 = Tile(tt, r-2), Tile(tt, r-1)
        if cnt[t1] > 0 and cnt[t2] > 0:
            options.append((t1, t2))
    if 1 < r < 9:
        t1, t2 = Tile(tt, r-1), Tile(tt, r+1)
        if cnt[t1] > 0 and cnt[t2] > 0:
            options.append((t1, t2))
    if r <= 7:
        t1, t2 = Tile(tt, r+1), Tile(tt, r+2)
        if cnt[t1] > 0 and cnt[t2] > 0:
            options.append((t1, t2))
    return options


# ==================== 游戏引擎 ====================

class GameEngine:
    """麻将游戏引擎 - 事件驱动、无 I/O"""
    def __init__(self, num_humans=1):
        roles = [PlayerRole.EAST, PlayerRole.SOUTH, PlayerRole.WEST, PlayerRole.NORTH]
        self.players = [Player(roles[i], is_human=(i < num_humans)) for i in range(4)]
        self.tile_wall = TileWall()
        self.dealer_idx = 0
        self.debug_hand = None  # 调试模式指定手牌(牌面简写列表)
        self.fan_map = {}       # 番值覆盖 {番种名: 番值} (冒险模式动态调整)
        self.locked_yaku = set() # 未解锁番种名集合 (冒险模式番种锁)
        self.min_fan = 4        # 起和番数 (冒险模式为1)
        self.round_num = 0
        self.discard_pool = []
        self.game_over = False
        self.winner = None
        self.win_type = ''
        self.logs = []
        self.phase = 'IDLE'
        self.current_player_idx = 0
        self._skip_rest = False
        self._last_discarder = -1
        self._claim_order = []
        self._claim_idx = 0
        self.accumulated_scores = {r: 0 for r in roles}
        self.fan_details = []
        self.total_fan = 0
        self._ron_tile = None   # 荣和的牌(和牌张, 供单吊字等听牌类番种使用)
        # ---- 冒险关卡配置 (由服务器按关卡注入) ----
        self.guaranteed_pair = None  # 'honour'=开局保证玩家(0)有一对字牌, 其余随机
        self.guaranteed_hand = None  # {'honour_pair':True,'loose_honours':2,'suit_min':{'m':2,...}}=按配置保底(点数随机)
        self.no_ryuukyoku_score = False  # True=流局不算分(关闭听算/组合算分, 关卡可配 ryuukyoku_scoring:false)
        self.adventure_goal = None   # {'type':'win_yaku','yaku':'五门齐'} / {'type':'score','target':16}
        self.adventure_rounds = None # 关卡总局数
        self.adventure_boss = None   # {'seat':2,'win_between':[14,20],'max_score':12}: 对家Boss窗口内和牌
        self.boss_win_turn = None    # 本局Boss和牌的巡数(开局随机取 win_between 内)

    # ---- 公开 API ----

    def check_goal_met(self):
        """冒险关卡目标是否达成。
        win_yaku: 玩家(0) 和出指定番种(必须实际和牌, 听牌/流局不算)
        score: 玩家(0) 本关卡累计得分达到目标(跨局累计, 流局得分也计入)
        score_lead: 玩家累计分领先指定对手(座次)达到目标分差
        """
        g = getattr(self, 'adventure_goal', None)
        if not g:
            return False
        if g.get('type') == 'win_yaku':
            if self.winner is self.players[0] and self.win_type:
                for d in self.fan_details:
                    if d.get('name') == g.get('yaku'):
                        return True
        elif g.get('type') == 'score':
            target = g.get('target', 0)
            return self.accumulated_scores[self.players[0].role] >= target
        elif g.get('type') == 'score_lead':
            opp = self.players[g.get('opponent_seat', 2)]
            diff = self.accumulated_scores[self.players[0].role] - self.accumulated_scores[opp.role]
            return diff >= g.get('target', 5)
        return False

    def start_round(self):
        self.round_num += 1
        self.game_over = False
        self.winner = None
        self.win_type = ''
        self.logs = []
        self.discard_pool = []
        self._skip_rest = False
        self._last_discarder = -1
        self._ron_tile = None
        for p in self.players:
            p.hand.clear()
            p.melds.clear()
            p.status_flag = None
            p.discards.clear()
            p.score = 0
            p.drawn_tile = None
        self.tile_wall.initialize()
        self._deal_tiles()
        self.current_player_idx = self.dealer_idx
        self.phase = 'DRAW'
        self.boss_win_turn = None  # 每局重新抽取Boss和牌巡数

    def get_state(self):
        state = {
            'phase': self.phase,
            'current_player_idx': self.current_player_idx,
            'players': [self._player_state(i) for i in range(4)],
            'last_discard': self.discard_pool[-1].to_shorthand() if self.discard_pool else None,
            'last_discard_by': self._last_discarder if self.discard_pool else None,
            'remaining_tiles': self.tile_wall.remaining_count(),
            'round_num': self.round_num,
            'dealer_idx': self.dealer_idx,
            'game_over': self.game_over,
            'winner_idx': self.players.index(self.winner) if self.winner else None,
            'win_type': self.win_type,
            'logs': self.logs[-20:],
            'scores': {r.value: s for r, s in self.accumulated_scores.items()},
            'actions': self.get_available_actions(),
            'fan_details': self.fan_details,
            'total_fan': self.total_fan,
            'adv_goal_met': self.check_goal_met(),
            'adv_rounds': self.adventure_rounds,
            'ryuukyoku_scores': getattr(self, 'ryuukyoku_scores', None),
            'ryuukyoku_details': getattr(self, 'ryuukyoku_details', None),
            'revealed_hands': None,
        }
        # 终局亮牌: 四家手牌全部揭晓(结果表用)
        if self.game_over:
            state['revealed_hands'] = {i: self.players[i].sorted_hand_shorthands() for i in range(4)}
        return state

    def get_available_actions(self):
        if self.game_over:
            return []
        cp = self.players[self.current_player_idx]
        if self.phase == 'DRAW':
            # 自动摸牌，不再需要用户操作
            return []
        if self.phase == 'SELF_MELD':
            if not cp.is_human:
                return []
            actions = []
            is_win, wt = is_winning_hand(cp.hand, cp.melds)
            if is_win and self._check_win_fan(cp.hand, cp.melds, wt, is_self_draw=True,
                                              extra={'win_tile': cp.drawn_tile}) >= self.min_fan:
                actions.append({'type': 'tsumo', 'win_type': wt})
            cnt = Counter(cp.hand)
            for tile, count in cnt.items():
                if count == 4:
                    actions.append({'type': 'dark_kong', 'tile': tile.to_shorthand()})
            for mi, meld in enumerate(cp.melds):
                if meld.meld_type == 'PUNG':
                    for tile in cp.hand:
                        if tile in meld.tiles:
                            actions.append({'type': 'add_kong', 'tile': tile.to_shorthand(), 'meld_idx': mi})
                            break
            actions.append({'type': 'skip'})
            return actions
        if self.phase == 'DISCARD':
            if not cp.is_human:
                return []
            return [{'type': 'discard', 'tiles': cp.sorted_hand_shorthands()}]
        if self.phase == 'CLAIM_PK':
            checker = self._claim_check_player()
            if checker is None or not checker.is_human:
                return []
            actions = []
            tile = self.discard_pool[-1]
            cnt = Counter(checker.hand)
            if cnt[tile] >= 2:
                actions.append({'type': 'pung'})
            if cnt[tile] >= 3:
                actions.append({'type': 'kong'})
            test_hand = checker.hand + [tile]
            is_win, wt = is_winning_hand(test_hand, checker.melds)
            if is_win and self._check_win_fan(test_hand, checker.melds, wt, is_self_draw=False,
                                              extra={'win_tile': tile}) >= self.min_fan:
                actions.append({'type': 'ron', 'win_type': wt})
            if actions:
                actions.append({'type': 'pass'})
            return actions
        if self.phase == 'CLAIM_CHOW':
            checker = self._claim_check_player()
            if checker is None or not checker.is_human:
                return []
            tile = self.discard_pool[-1]
            opts = get_chow_options(checker.hand, tile)
            if not opts:
                return []
            chow_display = []
            for t1, t2 in opts:
                seq = sorted([t1, t2, tile], key=lambda t: t.rank)
                chow_display.append([t.to_shorthand() for t in seq])
            return [{'type': 'chow', 'options': chow_display}, {'type': 'pass'}]
        return []

    def do_action(self, action_type, stepwise=False, auto_advance=True, **params):
        self.add_log(f'[操作] {action_type}')
        if action_type == 'draw':
            self._do_draw()
        elif action_type == 'tsumo':
            self._do_tsumo()
        elif action_type == 'dark_kong':
            self._do_dark_kong(params.get('tile', ''))
        elif action_type == 'add_kong':
            self._do_add_kong(params.get('tile', ''), params.get('meld_idx', 0))
        elif action_type == 'skip':
            self._do_skip_self_meld()
        elif action_type == 'discard':
            self._do_discard(params.get('tile', ''))
        elif action_type == 'pung':
            self._do_pung()
        elif action_type == 'kong':
            self._do_kong()
        elif action_type == 'ron':
            self._do_ron()
        elif action_type == 'chow':
            self._do_chow(params.get('choice', 0))
        elif action_type == 'pass':
            self._do_pass_claim()
        if auto_advance:
            self._auto_advance(stepwise=stepwise)
        return self.get_state()


    # ---- 内部：发牌 ----

    def _deal_tiles(self):
        if getattr(self, 'debug_hand', None):
            self._deal_debug_hand()
        else:
            self._deal_normal()
        self.add_log('发牌完成, 每家13张')

    def _deal_normal(self):
        """常规发牌; guaranteed_pair=='honour' 或 guaranteed_hand 时, 先给玩家(0)抽保底牌, 其余随机"""
        p0 = self.players[0]
        skip0 = 0
        if getattr(self, 'guaranteed_pair', None) == 'honour':
            from collections import Counter
            cnt = Counter(self.tile_wall.tiles)
            cand = [t for t, c in cnt.items() if t.tile_type == TileType.HONOUR and c >= 2]
            if cand:
                target = random.choice(cand)
                got = 0
                for i in range(len(self.tile_wall.tiles) - 1, -1, -1):
                    if got >= 2:
                        break
                    if self.tile_wall.tiles[i] == target:
                        self.tile_wall.tiles.pop(i)
                        p0.add_tile(target)
                        got += 1
                # pop 后同步牌墙指针, 避免牌墙将尽时越界
                self.tile_wall.tail_idx = len(self.tile_wall.tiles) - 1
                skip0 = got
                self.add_log(f'保证手牌: 玩家东持有 {target.to_shorthand()}×{got}')
        if getattr(self, 'guaranteed_hand', None):
            skip0 += self._deal_guaranteed_hand(p0)
        for _ in range(3):
            for i in range(4):
                p = self.players[(self.dealer_idx + i) % 4]
                for _ in range(4):
                    if p is p0 and skip0 > 0:
                        skip0 -= 1
                        continue
                    t = self.tile_wall.draw_from_head()
                    if t:
                        p.add_tile(t)
        for i in range(4):
            p = self.players[(self.dealer_idx + i) % 4]
            if p is p0 and skip0 > 0:
                skip0 -= 1
                continue
            t = self.tile_wall.draw_from_head()
            if t:
                p.add_tile(t)

    def _deal_guaranteed_hand(self, p0):
        """按 guaranteed_hand 配置给玩家(0)保底手牌 (从牌墙抽取, 返回抽走张数)。

        配置形如: {'honour_pair': True, 'loose_honours': 2, 'suit_min': {'m':2,'p':2,'s':2}}
          - honour_pair: 一对字牌 (同张×2)
          - loose_honours: 额外散张字牌数
          - suit_min: 每种花色至少 n 张
        保底牌的**点数全部随机** (只保证花色/字牌种类, 不固定点数, 避免刻意感)。
        保底张数不足13时, 其余随机发。
        """
        gh = self.guaranteed_hand
        if not gh:
            return 0
        from collections import Counter
        wall = self.tile_wall.tiles
        got = 0

        def take_idxs(idxs):
            """按索引倒序弹出(先弹后面的, 保证前面索引不失效), 发给玩家0"""
            nonlocal got
            for i in sorted(idxs, reverse=True):
                p0.add_tile(wall.pop(i))
                got += 1

        # 1) 一对字牌 (点数随机)
        if gh.get('honour_pair'):
            cnt = Counter(wall)
            cand = [t for t, c in cnt.items() if t.tile_type == TileType.HONOUR and c >= 2]
            if cand:
                target = random.choice(cand)
                idxs = []
                for i in range(len(wall) - 1, -1, -1):
                    if len(idxs) >= 2:
                        break
                    if wall[i] == target:
                        idxs.append(i)
                take_idxs(idxs)
        # 2) 散张字牌 (点数随机)
        n_loose = int(gh.get('loose_honours') or 0)
        if n_loose > 0:
            loose = [i for i, t in enumerate(wall) if t.tile_type == TileType.HONOUR]
            random.shuffle(loose)
            take_idxs(loose[:n_loose])
        # 3) 各花色保底 (点数随机, 不固定)
        suit_map = {'m': TileType.MAN, 'p': TileType.PIN, 's': TileType.SOU}
        for letter, n in (gh.get('suit_min') or {}).items():
            ttype = suit_map.get(letter)
            if ttype is None or n <= 0:
                continue
            idxs = [i for i, t in enumerate(wall) if t.tile_type == ttype]
            random.shuffle(idxs)
            take_idxs(idxs[:n])
        if got:
            self.tile_wall.tail_idx = len(wall) - 1
            self.add_log(f'保证手牌: 玩家东获得 {got} 张关卡保底牌')
        return got

    def _deal_debug_hand(self):
        """调试模式: 先给玩家(0号)发指定手牌, 剩余牌重洗后发其余3家"""
        p0 = self.players[0]
        for sh in self.debug_hand:
            tile = Tile.from_shorthand(sh)
            for i, t in enumerate(self.tile_wall.tiles):
                if t == tile:
                    self.tile_wall.tiles.pop(i)
                    p0.add_tile(tile)
                    break
        # 重洗剩余牌墙
        random.shuffle(self.tile_wall.tiles)
        self.tile_wall.head_idx = 0
        self.tile_wall.tail_idx = len(self.tile_wall.tiles) - 1
        # 给其余3家各发13张
        others = [(self.dealer_idx + i) % 4 for i in range(4) if (self.dealer_idx + i) % 4 != 0]
        for _ in range(13):
            for idx in others:
                t = self.tile_wall.draw_from_head()
                if t:
                    self.players[idx].add_tile(t)

    # ---- 内部：操作实现 ----

    def _do_draw(self):
        cp = self.players[self.current_player_idx]
        tile = None
        if cp.status_flag == 'KONG':
            tile = self.tile_wall.draw_from_tail()
        else:
            tile = self.tile_wall.draw_from_head()
        if tile is None:
            self.add_log('牌山为空！流局')
            self.game_over = True
            self.phase = 'GAME_OVER'
            self._calc_ryuukyoku_scores()
            return
        cp.add_tile(tile)
        cp.status_flag = None
        # 清除所有玩家的 drawn_tile (旧回合结束)
        for p in self.players: p.drawn_tile = None
        cp.drawn_tile = tile  # 当前玩家刚摸的牌
        self.add_log(f'{cp.role.value} 摸牌')
        self.phase = 'SELF_MELD'

    def _do_tsumo(self):
        cp = self.players[self.current_player_idx]
        is_win, wt = is_winning_hand(cp.hand, cp.melds)
        if is_win:
            self.add_log(f'{cp.role.value} 自摸！{wt}')
            self.winner = cp
            self.win_type = wt
            cp.score = self._calc_score(cp, wt, True)
            self.game_over = True
            self.phase = 'GAME_OVER'
            self._accumulate_scores()

    def _do_dark_kong(self, tile_shorthand):
        cp = self.players[self.current_player_idx]
        tile = Tile.from_shorthand(tile_shorthand)
        for _ in range(4):
            cp.remove_tile(tile)
        cp.add_meld(MeldSet([tile]*4, 'DARK_KONG', hidden_count=2))
        cp.status_flag = 'KONG'
        cp.drawn_tile = None  # 暗杠后本回合摸牌标记失效
        self.add_log(f'{cp.role.value} 暗杠 {tile.to_shorthand()}')
        self._skip_rest = True

    def _do_add_kong(self, tile_shorthand, meld_idx):
        cp = self.players[self.current_player_idx]
        tile = Tile.from_shorthand(tile_shorthand)
        cp.remove_tile(tile)
        meld = cp.melds[meld_idx]
        meld.tiles.append(tile)
        meld.meld_type = 'KONG'
        meld.added_tile = tile  # 加杠新增的横置牌,叠在原横置牌上
        cp.status_flag = 'KONG'
        cp.drawn_tile = None  # 加杠后本回合摸牌标记失效
        self.add_log(f'{cp.role.value} 加杠 {tile.to_shorthand()}')
        self._robbing_kong_tile = tile  # 记录加杠牌，用于抢杠检查
        self._skip_rest = True

    def _do_skip_self_meld(self):
        self.phase = 'DISCARD'

    def _do_discard(self, tile_shorthand):
        cp = self.players[self.current_player_idx]
        tile = Tile.from_shorthand(tile_shorthand)
        if cp.discard_tile(tile):
            self.discard_pool = [tile]
            self._last_discarder = self.current_player_idx
            cp.drawn_tile = None  # 出牌后本回合摸牌标记失效(摸切后不会再被前端重加)
            self.add_log(f'{cp.role.value} 打出 {tile.to_shorthand()}')
            self.phase = 'CLAIM_PK'
            self._claim_order = self._build_claim_order()
            self._claim_idx = 0

    def _claim_direction(self, checker):
        """返回鸣牌来源方向: 1=上家 2=对家 3=下家"""
        d = getattr(self, '_last_discarder', -1)
        if d < 0: return 0
        c = self.players.index(checker)
        return (c - d) % 4  # 1=上家 2=对家 3=下家

    def _do_pung(self):
        checker = self._claim_check_player()
        if checker is None:
            return
        tile = self.discard_pool[-1]
        ok1 = checker.remove_tile(tile)
        ok2 = checker.remove_tile(tile)
        if not ok1 or not ok2:
            self.add_log(f'错误: {checker.role.value} 碰 {tile.to_shorthand()} 时手牌不足')
            return
        self.discard_pool.pop()
        self._remove_from_discarder(tile)
        checker.add_meld(MeldSet([tile]*3, 'PUNG', claimed_from=self._claim_direction(checker), claimed_tile=tile))
        self.add_log(f'{checker.role.value} 碰 {tile.to_shorthand()}')
        self.current_player_idx = self.players.index(checker)
        self.phase = 'DISCARD'

    def _do_kong(self):
        checker = self._claim_check_player()
        if checker is None:
            return
        tile = self.discard_pool[-1]
        removed = 0
        for _ in range(3):
            if checker.remove_tile(tile):
                removed += 1
        if removed < 3:
            self.add_log(f'错误: {checker.role.value} 杠 {tile.to_shorthand()} 时手牌不足')
            return
        self.discard_pool.pop()
        self._remove_from_discarder(tile)
        checker.add_meld(MeldSet([tile]*4, 'KONG', claimed_from=self._claim_direction(checker), claimed_tile=tile))
        checker.status_flag = 'KONG'
        self.add_log(f'{checker.role.value} 杠 {tile.to_shorthand()}')
        self.current_player_idx = self.players.index(checker)
        self.phase = 'DRAW'

    def _do_ron(self):
        checker = self._claim_check_player()
        tile = self.discard_pool[-1]
        self._ron_tile = tile  # 记录荣和的牌(从外部获取,不算暗刻)
        checker.add_tile(tile)
        self.discard_pool.pop()
        _, wt = is_winning_hand(checker.hand, checker.melds)
        self.add_log(f'{checker.role.value} 荣和！{tile.to_shorthand()} ({wt})')
        self.winner = checker
        self.win_type = wt
        checker.score = self._calc_score(checker, wt, False)
        self.game_over = True
        self.phase = 'GAME_OVER'
        self._accumulate_scores()

    def _do_chow(self, choice):
        checker = self._claim_check_player()
        tile = self.discard_pool[-1]
        opts = get_chow_options(checker.hand, tile)
        if 0 <= choice < len(opts):
            t1, t2 = opts[choice]
            ok1 = checker.remove_tile(t1)
            ok2 = checker.remove_tile(t2)
            if not ok1 or not ok2:
                self.add_log(f'错误: 吃牌时手牌不足')
                return
            self.discard_pool.pop()
            self._remove_from_discarder(tile)
            seq = sorted([t1, t2, tile], key=lambda t: t.rank)
            checker.add_meld(MeldSet(seq, 'CHOW', claimed_from=self._claim_direction(checker), claimed_tile=tile))
            self.add_log(f'{checker.role.value} 吃 {tile.to_shorthand()}')
            self.current_player_idx = self.players.index(checker)
            self.phase = 'DISCARD'


    def _remove_from_discarder(self, tile):
        """被鸣走的牌要从出牌人的牌河中移除"""
        d_idx = getattr(self, '_last_discarder', -1)
        if d_idx >= 0:
            d_p = self.players[d_idx]
            # 从尾部找最后一张相同的牌（最近出的那张）
            for i in range(len(d_p.discards) - 1, -1, -1):
                if d_p.discards[i] == tile:
                    d_p.discards.pop(i)
                    break

    def _do_pass_claim(self):
        if self.phase == 'CLAIM_PK':
            self._claim_idx += 1
            if self._claim_idx >= len(self._claim_order):
                self._start_chow_phase()
        elif self.phase == 'CLAIM_CHOW':
            self._next_player_turn()

    # ---- 内部：流程控制 ----

    def _auto_advance(self, stepwise=False):
        for _ in range(500):
            if self.game_over:
                return
            if self._skip_rest:
                self._skip_rest = False
                # 杠牌者应立刻补摸岭上牌(不跳家): current_player_idx 仍是杠牌者,
                # 置回 DRAW 后下一轮即摸牌(status_flag=='KONG' → 从牌尾摸岭上)。
                # 旧实现 advance 3 会延迟补牌, 延迟期间若再鸣牌会覆盖 status,
                # 导致多次杠的岭上补牌丢失, 手牌被耗尽。
                self.phase = 'DRAW'
                cp = self.players[self.current_player_idx]
                if cp.is_human:
                    return
                continue
            cp = self.players[self.current_player_idx]
            if self.phase == 'DRAW':
                # 冒险Boss: 打完第N张后再摸牌时, 按概率用生成的门清牌直接和牌
                if not cp.is_human and self._boss_try_win(cp):
                    return
                if cp.is_human:
                    # ---- 人类自动摸牌 ----
                    self._do_draw()
                    if self.game_over:
                        return
                    # 继续到 SELF_MELD，如果需要决策就停下
                else:
                    self._do_draw()
                    if self.game_over:
                        return
            if self.phase == 'SELF_MELD':
                if cp.is_human:
                    # 有自摸/暗杠/加杠才停下来；否则自动跳过
                    if self._has_self_meld_options(cp):
                        return
                    self._do_skip_self_meld()
                else:
                    self._do_skip_self_meld()
            if self.phase == 'DISCARD':
                if cp.is_human:
                    return  # 需要玩家选牌
                if cp.hand:
                    disc = self._choose_bot_discard(cp.hand)
                    self._do_discard(disc.to_shorthand())
                    if stepwise:
                        return True  # 逐一推进: 处理完一个bot后返回, 让调用方延时再继续
                else:
                    self.game_over = True
                    return
            if self.phase in ('CLAIM_PK', 'CLAIM_CHOW'):
                checker = self._claim_check_player()
                if checker is None:
                    if self.phase == 'CLAIM_PK':
                        self._start_chow_phase()
                    else:
                        self._next_player_turn()
                    continue
                if checker.is_human:
                    # ---- 人类：无可鸣牌则自动过 ----
                    if self._has_any_claim(checker):
                        return  # 有鸣牌选项，等玩家决定
                    self._do_pass_claim()
                    continue
                self._do_pass_claim()
                continue
        self.add_log('警告: _auto_advance 达最大迭代')

    def _build_claim_order(self):
        return [(self.current_player_idx + i) % 4 for i in range(1, 4)]

    def _claim_check_player(self):
        if self.phase == 'CLAIM_PK':
            if self._claim_idx < len(self._claim_order):
                return self.players[self._claim_order[self._claim_idx]]
            return None
        if self.phase == 'CLAIM_CHOW':
            return self.players[self._next_idx(self.current_player_idx)]
        return None

    def _has_self_meld_options(self, player):
        """检查玩家在鸣牌阶段是否有自摸/暗杠/加杠选项（不含跳过）"""
        is_win, _ = is_winning_hand(player.hand, player.melds)
        if is_win:
            return True
        cnt = Counter(player.hand)
        if any(c == 4 for c in cnt.values()):
            return True
        for meld in player.melds:
            if meld.meld_type == 'PUNG':
                for tile in player.hand:
                    if tile in meld.tiles:
                        return True
        return False

    def _has_any_claim(self, player):
        """检查玩家在当前待鸣阶段是否有实质的鸣牌操作"""
        tile = self.discard_pool[-1]
        cnt = Counter(player.hand)
        if self.phase == 'CLAIM_PK':
            if cnt[tile] >= 2:
                return True   # 可碰
            if cnt[tile] >= 3:
                return True   # 可杠
            test_hand = player.hand + [tile]
            is_win, wt = is_winning_hand(test_hand, player.melds)
            if is_win and self._check_win_fan(test_hand, player.melds, wt, is_self_draw=False,
                                              extra={'win_tile': tile}) >= self.min_fan:
                return True   # 可荣(且达到起和线)
            return False
        if self.phase == 'CLAIM_CHOW':
            opts = get_chow_options(player.hand, tile)
            return len(opts) > 0  # 可吃
        return False

    def _start_chow_phase(self):
        next_p = self.players[self._next_idx(self.current_player_idx)]
        tile = self.discard_pool[-1] if self.discard_pool else None
        if tile:
            opts = get_chow_options(next_p.hand, tile)
            if opts:
                self.phase = 'CLAIM_CHOW'
                return
        self._next_player_turn()

    def _next_player_turn(self):
        self.current_player_idx = self._next_idx(self.current_player_idx)
        self.phase = 'DRAW'

    def _next_idx(self, idx):
        return (idx + 1) % 4

    # ========== 抢杠 ==========

    def _do_robbing_kong(self, robber_idx):
        """抢杠: robber 抢加杠者的杠牌荣和"""
        tile = self.discard_pool[-1]
        kong_player = self.players[self.current_player_idx]
        robber = self.players[robber_idx]

        # 破杠: 牌回到加杠者手牌中
        for m in kong_player.melds:
            if m.meld_type == 'KONG' and tile in m.tiles:
                # 还原为碰
                if len(m.tiles) >= 4:
                    m.tiles.pop()
                m.meld_type = 'PUNG'
                kong_player.add_tile(tile)
                break

        robber.add_tile(tile)
        self.discard_pool.pop()
        _, wt = is_winning_hand(robber.hand, robber.melds)
        self.add_log(f'{robber.role.value} 抢杠和！{tile.to_shorthand()} ({wt})')
        self.winner = robber
        self.win_type = wt
        robber.score = self._calc_score(robber, wt, False)
        self.game_over = True
        self.phase = 'GAME_OVER'
        self._accumulate_scores()

    def _player_state(self, idx):
        p = self.players[idx]
        return {
            'idx': idx,
            'role': p.role.value,
            'type': 'human' if p.is_human else 'ai',
            'hand_count': len(p.hand),
            'melds': [{
                'type': m.meld_type,
                'tiles': [t.to_shorthand() for t in m.tiles],
                'hidden': m.hidden_count,
                'claimed_from': m.claimed_from,
                'claimed_tile': m.claimed_tile.to_shorthand() if m.claimed_tile else None,
                'added_tile': m.added_tile.to_shorthand() if m.added_tile else None,
            } for m in p.melds],
            'discards': [t.to_shorthand() for t in p.discards],
            'score': p.score,
            'drawn_tile': p.drawn_tile.to_shorthand() if p.drawn_tile else None,
        }

    def get_human_hand(self, human_idx=0):
        return self.players[human_idx].sorted_hand_shorthands()

    MIN_FAN = 4  # 起和番数

    def _check_win_fan(self, hand, melds, win_type, is_self_draw=False, extra=None):
        """快速算番, 用于判断是否达到起和线"""
        try:
            engine_dir = os.path.dirname(os.path.abspath(__file__))
            if engine_dir not in sys.path:
                sys.path.insert(0, engine_dir)
            from branches.scoring.scorer import calculate_score_with_details as _scorer_fn
            cp = self.players[self.current_player_idx]
            fan, _ = _scorer_fn(
                hand, list(melds), win_type,
                winner_role=cp.role,
                dealer_role=self.players[self.dealer_idx].role,
                is_self_draw=is_self_draw,
                extra=extra,
                fan_map=self.fan_map,
                locked_yaku=self.locked_yaku,
            )
            return fan
        except:
            return 999  # 无法算番时放行

    def _calc_score(self, player, win_type, is_self_draw):
        # 延迟加载算番模块
        try:
            engine_dir = os.path.dirname(os.path.abspath(__file__))
            if engine_dir not in sys.path:
                sys.path.insert(0, engine_dir)
            from branches.scoring.scorer import calculate_score_with_details as _scorer_fn
            # 和牌张: 自摸=刚摸的牌, 荣和=被荣的牌 (供 单吊字 等听牌类番种使用)
            win_tile = player.drawn_tile if is_self_draw else getattr(self, '_ron_tile', None)
            fan, details = _scorer_fn(
                player.hand,
                list(player.melds),
                win_type,
                winner_role=player.role,
                dealer_role=self.players[self.dealer_idx].role,
                is_self_draw=is_self_draw,
                extra={'win_tile': win_tile},
                fan_map=self.fan_map,
                locked_yaku=self.locked_yaku,
            )
            self.fan_details = details
            self.total_fan = max(fan, 1)
            return self.total_fan * 2  # 得分 = 番数 * 2
        except Exception as e:
            self.add_log(f'算番异常,使用简单计分: {e}')
        # 回退方案
        if is_self_draw and player.role == PlayerRole.EAST:
            self.total_fan = 8
        elif is_self_draw:
            self.total_fan = 4
        else:
            self.total_fan = 4
        self.fan_details = []
        return self.total_fan

    def add_log(self, msg):
        self.logs.append(msg)

    def _calc_ryuukyoku_scores(self):
        """流局时计算每人得分(组合番×2 与 听算×1 取更高, 听算默认开启)。
        关卡可配置 no_ryuukyoku_score=True 关闭听算/组合算分(流局全体0分)。"""
        self.ryuukyoku_scores = {}
        self.ryuukyoku_details = {}
        if getattr(self, 'no_ryuukyoku_score', False):
            for p in self.players:
                p.score = 0
                self.ryuukyoku_scores[p.role.value] = {'fan': 0, 'score': 0, 'method': '—', 'waiting': 0}
                self.ryuukyoku_details[p.role.value] = []
            self.fan_details = []
            self.total_fan = 0
            self._accumulate_scores()
            return
        for p in self.players:
            try:
                from branches.scoring.ryuukyoku import calculate_ryuukyoku_full
                res = calculate_ryuukyoku_full(p.hand, list(p.melds),
                                               locked_yaku=self.locked_yaku, fan_map=self.fan_map)
                p.score = res['score']
                self.ryuukyoku_scores[p.role.value] = {
                    'fan': res['fan'], 'score': res['score'],
                    'method': res['method'], 'waiting': res['waiting'],
                    'combo_fan': res['combo_fan'], 'tenpai_fan': res['tenpai_fan'],
                }
                self.ryuukyoku_details[p.role.value] = res['details']
            except Exception as e:
                self.add_log(f'流局计分异常 [{p.role.value}]: {e}')
                self.ryuukyoku_scores[p.role.value] = {'fan': 0, 'score': 0, 'method': '组合番', 'waiting': 0}
                self.ryuukyoku_details[p.role.value] = []
        self.fan_details = []
        self.total_fan = 0
        self._accumulate_scores()

    def _accumulate_scores(self):
        """把本局分数累加到累计分(游戏结束时调用, 供结果展示)"""
        if self.winner:
            self.accumulated_scores[self.winner.role] += self.winner.score
        else:
            for p in self.players:
                self.accumulated_scores[p.role] += p.score

    def settle_round(self):
        # 分数已在游戏结束时通过 _accumulate_scores 累加, 这里只推进庄家
        self.dealer_idx = (self.dealer_idx + 1) % 4

    # ---- 冒险 Boss (对家对手): 打完N巡后再摸牌时按概率和牌 ----

    def _choose_bot_discard(self, hand):
        """摸打机器人打牌选择: 85%概率按 字牌 > 幺九(1/9) > 中张(2-8) 优先打出,
        让玩家更容易摸到字牌/幺九(如1-2的五门齐/番牌刻需要); 其余15%按原行为(末张)。
        """
        if not hand:
            return None
        if random.random() < 0.85:
            def prio(t):
                if t.tile_type == TileType.HONOUR:
                    return 0
                if t.rank in (1, 9):
                    return 1
                return 2
            min_p = min(prio(t) for t in hand)
            cands = [t for t in hand if prio(t) == min_p]
            return random.choice(cands)
        return hand[-1]

    def _boss_try_win(self, cp):
        """Boss 摸牌前判定: 本局在 win_between 窗口内的随机巡数和牌(100%)。
        和牌牌由生成器从可用牌池构造(门清 / 门清+1番), 分数不超过 max_score。
        返回 True 表示已和牌(本局结束)。
        """
        boss = getattr(self, 'adventure_boss', None)
        if not boss:
            return False
        if self.players.index(cp) != boss.get('seat', 2):
            return False
        if self.boss_win_turn is None:
            wb = boss.get('win_between', [14, 20])
            self.boss_win_turn = random.randint(int(wb[0]), int(wb[1]))
        if len(cp.discards) < self.boss_win_turn:
            return False  # 还没到本局Boss的和牌巡
        try:
            result = _gen_boss_hand(self, boss_seat=boss.get('seat', 2))
        except Exception:
            return False
        if result is None:
            return False
        hand14, win_tile, fan = result
        max_score = boss.get('max_score', 12)
        if fan * 2 > max_score:
            return False
        cp.hand = list(hand14)
        cp.melds = []
        cp.drawn_tile = win_tile
        cp.status_flag = None
        self.winner = cp
        self.win_type = "标准和"
        # 对手番种不要求主角解锁过: 全程 locked_yaku 为空
        from branches.scoring.scorer import calculate_fan
        f2, details = calculate_fan(cp.hand, [], "标准和", is_self_draw=True,
                                    extra={'win_tile': win_tile}, return_details=True,
                                    locked_yaku=set())
        self.fan_details = details
        self.total_fan = max(f2, 1)
        cp.score = self.total_fan * 2
        self.game_over = True
        self.phase = 'GAME_OVER'
        self.add_log(f'{cp.role.value}(对手) 和牌! {win_tile.to_shorthand()} ({self.total_fan}番)')
        self._accumulate_scores()
        return True


# ---- 冒险 Boss 和牌生成器 ----
# 从"可用牌池"(全牌 - 所有弃牌 - 其它三家手牌)构造一副 门清 / 门清+1番 和牌,
# 保证与场上可见弃牌不矛盾(不太假), 分数 ≤ 12分(≤6番)。

_FULL_TILE_SET = None

def _full_tile_set():
    """全部136张牌(每种4张)"""
    global _FULL_TILE_SET
    from collections import Counter
    if _FULL_TILE_SET is None:
        tiles = []
        for ttype in (TileType.MAN, TileType.PIN, TileType.SOU):
            for r in range(1, 10):
                tiles += [Tile(ttype, r)] * 4
        for r in range(7):
            tiles += [Tile(TileType.HONOUR, r)] * 4
        _FULL_TILE_SET = Counter(tiles)
    return Counter(_FULL_TILE_SET)

def _boss_available_pool(engine, boss_seat):
    """可用牌池 = 全部136张 - 四家弃牌 - 非Boss三家手牌"""
    from collections import Counter
    pool = _full_tile_set()
    for p in engine.players:
        for t in p.discards:
            pool[t] -= 1
    for i, p in enumerate(engine.players):
        if i != boss_seat:
            for t in p.hand:
                pool[t] -= 1
            for m in p.melds:
                for t in (m.tiles if hasattr(m, 'tiles') else m):
                    pool[t] -= 1
    return pool

def _pick_chows(pool, rng, count, forced=None, avoid=None):
    """从牌池随机抽 count 个顺子; forced=必须包含的顺子列表; avoid=需避开的顺子。
    成功返回 (chows, 使用后) ; 失败返回 None
    """
    cands = []
    for ttype in (TileType.MAN, TileType.PIN, TileType.SOU):
        for r in range(1, 8):
            ts = (Tile(ttype, r), Tile(ttype, r + 1), Tile(ttype, r + 2))
            cands.append(ts)
    forced = list(forced or [])
    chosen = []
    for ts in forced:
        if not all(pool[t] > 0 for t in ts):
            return None
        for t in ts:
            pool[t] -= 1
        chosen.append(ts)
    need = count - len(chosen)
    if need > 0:
        rng.shuffle(cands)
        for ts in cands:
            if len(chosen) >= count:
                break
            if any(t == ts for t in chosen) or (avoid and any(t == ts for t in avoid)):
                continue
            if all(pool[t] > 0 for t in ts):
                for t in ts:
                    pool[t] -= 1
                chosen.append(ts)
    if len(chosen) != count:
        return None
    return chosen

def _pick_pair(pool, rng, honour=False):
    """从牌池抽一对子; honour=True 时限定字牌"""
    cands = []
    for ttype in (TileType.HONOUR,) if honour else (TileType.MAN, TileType.PIN, TileType.SOU):
        start, end = (0, 7) if honour else (1, 10)
        for r in range(start, end):
            t = Tile(ttype, r)
            if pool[t] >= 2:
                cands.append(t)
    if not cands:
        return None
    t = rng.choice(cands)
    pool[t] -= 2
    return t

def _gen_boss_hand(engine, boss_seat, max_tries=400):
    """生成 门清 / 门清+1番 和牌。返回 (hand14, win_tile, fan) 或 None"""
    from collections import Counter
    from branches.scoring.scorer import calculate_fan
    rng = random
    base = _boss_available_pool(engine, boss_seat)
    for _ in range(max_tries):
        pool = Counter(base)
        try:
            style = random.random()
            if style < 0.4:
                # 门清 only: 4顺子 + 数牌对
                chows = _pick_chows(pool, rng, 4)
                if chows is None:
                    continue
                pr = _pick_pair(pool, rng, honour=False)
                if pr is None:
                    continue
                win_tile = pr
            elif style < 0.7:
                # 门清+喜相逢: 123m + 123p + 2顺子 + 对
                forced = [(Tile(TileType.MAN, 1), Tile(TileType.MAN, 2), Tile(TileType.MAN, 3)),
                          (Tile(TileType.PIN, 1), Tile(TileType.PIN, 2), Tile(TileType.PIN, 3))]
                avoid = [(Tile(TileType.SOU, 1), Tile(TileType.SOU, 2), Tile(TileType.SOU, 3))]
                chows = _pick_chows(pool, rng, 4, forced=forced, avoid=avoid)
                if chows is None:
                    continue
                pr = _pick_pair(pool, rng, honour=False)
                if pr is None:
                    continue
                win_tile = pr
            else:
                # 门清+单吊字: 4顺子 + 字牌对, 和牌张=字牌
                chows = _pick_chows(pool, rng, 4)
                if chows is None:
                    continue
                pr = _pick_pair(pool, rng, honour=True)
                if pr is None:
                    continue
                win_tile = pr
        except Exception:
            continue
        hand14 = []
        for ts in chows:
            hand14.extend(ts)
        hand14.extend([pr, pr])
        try:
            fan, details = calculate_fan(hand14, [], "标准和", is_self_draw=True,
                                         extra={'win_tile': win_tile}, return_details=True,
                                         locked_yaku=set())
        except Exception:
            continue
        names = [d['name'] for d in details]
        if '门前清' not in names:
            continue
        # 按风格验收: 门清(2番) / 门清+喜相逢(3番) / 门清+单吊字(≤6番, 12分上限内)
        if style < 0.4:
            if fan == 2 and len(names) == 1:
                return hand14, win_tile, fan
        elif style < 0.7:
            if '喜相逢' in names and fan == 3:
                return hand14, win_tile, fan
        else:
            if '单吊字' in names and fan <= 6:
                return hand14, win_tile, fan
    return None
