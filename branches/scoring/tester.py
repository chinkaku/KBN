#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""组合麻将 算番测试器 v0.1.0

  输入格式（紧凑，空格分隔）:
    ┌─────────────────────────────────────────┐
    │ 牌张: 数牌 123456789 + 花色 m/p/s       │
    │       数牌可合并: 12345568m             │
    │       字牌: E(东) S(南) W(西) N(北)     │
    │             C(中) F(发) P(白)           │
    │                                         │
    │ 和牌: %(自摸) 默认点炮, 加%才是自摸     │
    │       ^(岭上/抢杠) &(海底/河底)         │
    │       *(天和/地和)                      │
    │                                         │
    │ 副露: [1111m] = 暗杠1m (方括号=暗杠)    │
    │       (123m) = 顺子1m2m3m (圆括号=碰/吃)│
    │       (111m) = 碰1m                     │
    │       (EEE)  = 碰东   [EEEE]=暗杠东     │
    └─────────────────────────────────────────┘

  示例: 123456789m 11m !%  = 清一色+一气贯通 东位 自摸
        123456789m 222m 33m !% = 同上
        11223344556677p !%     = 七对子 清一色
"""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from game_engine import Tile, TileType, PlayerRole

def parse_input(text: str):
    """解析紧凑输入,返回 (hand, melds_outside, seat_wind, win_type, extra)"""
    text = text.strip()
    
    seat_wind = PlayerRole.EAST
    win_type = "标准和"
    extra = {}
    
    # 分离特殊符号
    pure = ""
    for ch in text:
        if ch == '!': seat_wind = PlayerRole.EAST
        elif ch == '@': seat_wind = PlayerRole.SOUTH
        elif ch == '#': seat_wind = PlayerRole.WEST
        elif ch == '$': seat_wind = PlayerRole.NORTH
        elif ch == '%':
            extra['tsumo'] = True  # 自摸 (默认是点炮, 加%才是自摸)
        elif ch == '^':
            extra['rinshan'] = True
            extra['tsumo'] = True  # 岭上开花本质是自摸
        elif ch == '&':
            extra['haitei'] = True
        elif ch == '*':
            extra['tenhou_chiho'] = True
            extra['tsumo'] = True  # 天和/地和本质是自摸
        else:
            pure += ch

    hand_tiles = []
    melds_outside = []
    
    # Parse melds: [1111m] / [EEEE] = 暗杠, (111m) / (123m) / (EEE) = 碰/吃
    # 新格式: 花色字母在括号内, 字牌无花色
    meld_pattern = re.compile(r'\[([^\]]+)\]|\(([^)]+)\)')
    for m in meld_pattern.finditer(pure):
        pure = pure.replace(m.group(0), '')
        is_kong = (m.group(0)[0] == '[')
        content = m.group(1) or m.group(2)  # 去掉括号后的内容: "1111m" / "EEE" / "123m" / "111m"

        if is_kong:
            meld_type = 'DARK_KONG'
        else:
            # 判断碰/吃/明杠: 四张相同=明杠, 三张相同/纯字牌=碰, 否则=吃
            digits_only = re.sub(r'[A-Za-z]', '', content)
            has_digit = bool(digits_only)
            # 数牌: 4位相同=明杠, 3位相同=碰
            if has_digit:
                if len(digits_only) == 4:
                    meld_type = 'KONG'
                elif len(digits_only) == 3 and len(set(digits_only)) == 1:
                    meld_type = 'PUNG'
                else:
                    meld_type = 'CHOW'
            else:
                # 字牌: 4张=明杠, 3张=碰
                if len(content) == 4:
                    meld_type = 'KONG'
                else:
                    meld_type = 'PUNG'

        tiles = parse_tile_group_inline(content)
        from game_engine import MeldSet
        melds_outside.append(MeldSet(tiles, meld_type, hidden_count=(2 if is_kong else 0)))
    
    # Parse remaining tiles
    hand_tiles = parse_remaining_tiles(pure)

    # 合法性校验: 每种牌最多4张(整副麻将同牌封顶), 防止 [1111m][1111m]… 这类非法输入
    from collections import Counter
    _all = list(hand_tiles)
    for _m in melds_outside:
        _all.extend(_m.tiles)
    _cnt = Counter(t.to_shorthand() for t in _all)
    _over = sorted(sh for sh, c in _cnt.items() if c > 4)
    if _over:
        raise ValueError(f"每种牌最多4张: {' '.join(_over)}")

    # 和牌张判定: 最后一张牌是和牌张(14+杠张时), 供暗刻家族/单吊字等番种使用
    # 点炮时含和牌张的刻子不算暗刻; 自摸(% / ^ / *)时全部算暗刻
    all_count = len(hand_tiles) + sum(len(m.tiles) for m in melds_outside)
    kong_count = sum(1 for m in melds_outside if len(m.tiles) == 4)
    if all_count == 14 + kong_count and hand_tiles:
        extra['win_tile'] = hand_tiles[-1]

    return hand_tiles, melds_outside, seat_wind, win_type, extra

def parse_tile_group(content, suit):
    """旧格式: 内容+花色字母分离, 如 content='111', suit='m'"""
    tiles = []
    suit_map = {'m': TileType.MAN, 'p': TileType.PIN, 's': TileType.SOU}
    honour_map = {'E': 0, 'S': 1, 'W': 2, 'N': 3, 'C': 4, 'F': 5, 'P': 6}
    first_ch = content[0] if content else ''
    if first_ch in honour_map:
        for ch in content:
            if ch in honour_map:
                tiles.append(Tile(TileType.HONOUR, honour_map[ch]))
    elif suit in suit_map:
        ttype = suit_map[suit]
        for ch in content:
            if ch == '0': continue
            rank = int(ch)
            tiles.append(Tile(ttype, rank))
    return tiles

def parse_tile_group_inline(content):
    """新格式: 内容内含花色, 如 '111m', '123m', 'EEE', 'EEEE'"""
    tiles = []
    suit_map = {'m': TileType.MAN, 'p': TileType.PIN, 's': TileType.SOU}
    honour_map = {'E': 0, 'S': 1, 'W': 2, 'N': 3, 'C': 4, 'F': 5, 'P': 6}

    # 判断内容是否为数字牌: 至少包含一个数字 + 末尾花色字母
    has_digit = any(ch.isdigit() for ch in content)
    match = re.search(r'[mps]$', content, re.IGNORECASE)
    if has_digit and match:
        suit_ch = match.group().lower()
        ttype = suit_map[suit_ch]
        digits = content[:-1]
        for ch in digits:
            if ch == '0': continue
            rank = int(ch)
            tiles.append(Tile(ttype, rank))
    elif not has_digit:
        # 字牌: 全大写字母, 无花色后缀
        for ch in content.upper():
            if ch in honour_map:
                tiles.append(Tile(TileType.HONOUR, honour_map[ch]))
    return tiles

def parse_remaining_tiles(pure: str):
    """解析剩余的手牌字符串,如 '123456789m11mESWN'"""
    tiles = []
    i = 0
    suit_map = {'m': TileType.MAN, 'p': TileType.PIN, 's': TileType.SOU}
    honour_set = set('ESWNCFP')
    honour_map = {'E': 0, 'S': 1, 'W': 2, 'N': 3, 'C': 4, 'F': 5, 'P': 6}
    
    while i < len(pure):
        j = i
        # collect consecutive digits
        while j < len(pure) and pure[j].isdigit():
            j += 1
        if j > i:
            digits = pure[i:j]
            if j < len(pure) and pure[j] in suit_map:
                suit = pure[j]
                ttype = suit_map[suit]
                for d in digits:
                    if d == '0': continue
                    tiles.append(Tile(ttype, int(d)))
                i = j + 1
                continue
            else:
                # digits without suit = error
                i = j
                continue
        
        if pure[i] in honour_set:
            tiles.append(Tile(TileType.HONOUR, honour_map[pure[i]]))
            i += 1
            continue
        i += 1
    
    return tiles

# ========== Main ==========

def main():
    from branches.scoring.scorer import calculate_fan
    print("=" * 60)
    print("  组合麻将 算番测试器")
    print("  格式: 牌张+门风+和牌方式+副露")
    print("  示例: 123456789m11m!%=清一色+一气贯通 自摸")
    print("=" * 60)

    while True:
        try:
            inp = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if inp.lower() in ('q', 'quit', 'exit'):
            break
        if not inp:
            continue

        try:
            hand, melds, seat, win_type, extra = parse_input(inp)
        except Exception as e:
            print(f"  解析错误: {e}")
            import traceback
            traceback.print_exc()
            continue

        if not hand:
            print("  未解析到手牌")
            continue

        all_tiles = list(hand)
        for m in melds:
            all_tiles.extend(m.tiles)

        print(f"  手牌({len(hand)}): {' '.join(t.to_shorthand() for t in hand)}")
        if melds:
            for m in melds:
                print(f"  副露({m.meld_type}): {' '.join(t.to_shorthand() for t in m.tiles)}")
        print(f"  门风: {seat.value}  和牌方式: {'自摸' if extra.get('tsumo') else '点炮'}  extra: {extra}")
        print(f"  总牌数: {len(all_tiles)}")


        # 牌张数校验
        kong_count = sum(1 for m in melds if len(m.tiles) == 4)
        meld_tiles = sum(len(m.tiles) for m in melds)
        win_expected = 14 + kong_count          # 和牌: 14张 + 每杠多1张
        ryu_expected = 13 + meld_tiles          # 流局: 13张手牌 + 副露全部牌

        if len(all_tiles) == win_expected:
            # 和牌模式 (番种锁跟随单机模式: 番牌刻/单吊字不计)
            from branches.networking.adventure import ADVENTURE_ONLY_YAKU
            candidates = []
            for wt in ("标准和", "七对", "十三幺"):
                f, d = calculate_fan(hand, melds, win_type=wt, is_self_draw=extra.get('tsumo', False),
                                     extra=extra, locked_yaku=set(ADVENTURE_ONLY_YAKU), return_details=True)
                if f > 0: candidates.append((f, d, wt))
            if candidates:
                best = max(candidates, key=lambda x: x[0])
                fan, details, win_type = best
                score = fan * 2
                print(f"\n  ==== 结果 (和牌) ====")
                print(f"  和牌型: {win_type}")
                print(f"  总番: {fan}番  得分: {score}分")
                for d in details:
                    print(f"  {d['group']:8s} {d['name']:10s} {d['fan']:3d}番")
            else:
                print(f"\n  ==== 不能组成和牌型，牌型无效 ====")
        elif len(all_tiles) == ryu_expected:
            # 流局模式(组合番) (番种锁跟随单机模式)
            from branches.scoring.ryuukyoku import calculate_ryuukyoku
            from branches.networking.adventure import ADVENTURE_ONLY_YAKU
            fan, details = calculate_ryuukyoku(hand, melds, locked_yaku=set(ADVENTURE_ONLY_YAKU))
            score = fan * 2
            print(f"\n  ==== 结果 (流局·组合番) ====")
            print(f"  总番: {fan}番  得分: {score}分")
            for d in details:
                print(f"  {d['group']:8s} {d['name']:10s} {d['fan']:3d}番")
        else:
            print(f"\n  ==== 牌张数错误 ====")
            print(f"  期望: {ryu_expected}张(流局) 或 {win_expected}张(和牌), 实际: {len(all_tiles)}张")
        print()

if __name__ == '__main__':
    main()
