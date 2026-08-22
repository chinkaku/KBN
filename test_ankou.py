#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""暗刻家族(四暗刻/三暗刻/双暗刻)回归测试 — 自包含, 无需服务器。

用法: python test_ankou.py
覆盖: 荣牌补刻/进顺子/进雀头、副露(碰/吃/明杠/暗杠)、自摸与点炮差异、
      副露同点牌不干扰判断、及历史回归用例。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from branches.scoring.tester import parse_input
from branches.scoring.scorer import calculate_fan
from branches.networking.adventure import ADVENTURE_ONLY_YAKU


def calc(input_str):
    """返回 (mode, total_fan, 暗刻名集合)"""
    hand, melds, seat, wt, extra = parse_input(input_str)
    is_tsumo = bool(extra.get('tsumo', False))
    best = 0
    ankou = set()
    for w in ("标准和", "七对", "十三幺"):
        f, d = calculate_fan(hand, melds, win_type=w, is_self_draw=is_tsumo,
                             extra=extra, locked_yaku=set(ADVENTURE_ONLY_YAKU),
                             return_details=True)
        if f > best:
            best = f
            ankou = {x['name'] for x in d if '暗刻' in x['name']}
    return ("自摸" if is_tsumo else "点炮", best, ankou)


# (输入, 期望点炮暗刻, 期望自摸暗刻, 说明)
CASES = [
    ("111222333m999s55m",       {"四暗刻"}, {"四暗刻"}, "荣牌5m进雀头, 四刻全暗(四暗刻単騎)"),
    ("111222333m55m99s9s",      {"三暗刻"}, {"四暗刻"}, "荣9s补成999s刻 -> 点炮降级"),
    ("111222333m55m45m3m",      {"三暗刻"}, {"三暗刻"}, "荣3m进顺子, 333m仍暗(手牌3m共4张)"),
    ("(111m)222333m999s55m",    {"三暗刻"}, {"三暗刻"}, "副露碰111m, 剩222/333/999三暗"),
    ("[1111m]222333m999s55m",   {"四暗刻"}, {"四暗刻"}, "暗杠1111m算暗刻, 共4个"),
    ("(1111m)222333m999s55m",   {"三暗刻"}, {"三暗刻"}, "明杠1111m破坏, 剩3暗"),
    ("(111m)(222m)333m999s55m", {"双暗刻"}, {"双暗刻"}, "两个副露, 只剩333/999暗"),
    ("111222333m777sPP",        {"四暗刻"}, {"四暗刻"}, "荣P进雀头(单吊字场景), 四刻全暗"),
    ("111222333m55m66m6m",      {"三暗刻"}, {"四暗刻"}, "荣6m补成666m刻 -> 点炮降级"),
    ("44456666m777s99p4m",      {"三暗刻"}, {"三暗刻"}, "回归: 荣4m进顺子, 444m仍暗"),
    ("(456m)44666m66888s4m",    {"双暗刻"}, {"三暗刻"}, "回归: 副露4m不计入, 荣4m补成444m"),
    ("1112225557788m7m",        {"三暗刻"}, {"四暗刻"}, "回归: 荣7m补成777m"),
    ("11122255577788m",         {"四暗刻"}, {"四暗刻"}, "回归: 荣8m进雀头, 四暗刻"),
]

# 非法输入: 每种牌最多4张, 应抛 ValueError
ILLEGAL = [
    "[1111m][1111m][1111m][1111m]11m",  # 18张1m
    "[EEEE][EEEE]123456789m",           # 8张E
]
# 每种≤4但总张数超的, 不该被"每种4张"拦截(交给张数检查)
NOT_ILLEGAL = [
    "11115555m2222m3333m4444m",  # 20张, 每种恰好4张
]


def main():
    passed = failed = 0
    for inp, exp_ron, exp_tsu, note in CASES:
        mode, fan, ankou = calc(inp)
        ron_ok = exp_ron.issubset(ankou) if mode == "点炮" else None
        mode2, fan2, ankou2 = calc(inp + "%")
        tsu_ok = exp_tsu.issubset(ankou2) if mode2 == "自摸" else None
        ok = bool(ron_ok and tsu_ok)
        passed += ok
        failed += (not ok)
        print(f"{'PASS' if ok else 'FAIL'}  {inp:28s} {note}")
        if not ok:
            print(f"       点炮: {ankou or '无'} (期望 {exp_ron}) | 自摸: {ankou2 or '无'} (期望 {exp_tsu})")
    for inp in ILLEGAL:
        try:
            parse_input(inp)
            ok = False
            print(f"FAIL  {inp:28s} 非法输入未拦截")
        except ValueError as e:
            ok = True
            print(f"PASS  {inp:28s} 非法输入已拦截 ({e})")
        passed += ok
        failed += (not ok)
    for inp in NOT_ILLEGAL:
        try:
            parse_input(inp)
            print(f"PASS  {inp:28s} 每种<=4不误拦")
            passed += 1
        except ValueError as e:
            print(f"FAIL  {inp:28s} 被误拦截 ({e})")
            failed += 1
    print(f"\n{passed} 通过 / {failed} 失败")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
