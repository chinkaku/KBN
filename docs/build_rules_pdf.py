# -*- coding: utf-8 -*-
"""组合麻将 — 规则手册 PDF 生成器

用法：
    python docs/build_rules_pdf.py            # 生成 docs/组合麻将规则.pdf
    python docs/build_rules_pdf.py --html     # 只生成 docs/rules.html（调试排版）

设计：
- 番种表、冒险关卡表都**直接读代码**（branches/scoring/yaku.py、branches/networking/adventure.py），
  所以规则改了以后重跑本脚本即可，不用担心文档和实现对不上。
- 排版用 HTML + CSS（@page A4），再用本机 Chrome 的无头模式打印成 PDF（中文字体走系统字体）。
"""
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from branches.networking import adventure as adv   # noqa: E402
from branches.scoring import yaku as Y              # noqa: E402

VERSION = "0.0.10"
HTML_PATH = os.path.join(HERE, "rules.html")
PDF_PATH = os.path.join(HERE, "组合麻将规则.pdf")


# ---------------- 数据：番种表 ----------------
def yaku_docs():
    """从 yaku.py 的类 docstring 里取"判定要点"（没有就留空）"""
    src = open(os.path.join(ROOT, "branches", "scoring", "yaku.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    out = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            doc = ast.get_docstring(node) or ""
            out[node.name] = re.sub(r"\s+", " ", doc.strip())
    return out


def yaku_rows():
    docs = yaku_docs()
    group_order = list(dict.fromkeys(g.value for g in Y.YAKU_BY_GROUP.keys()))
    rows = []
    for y in Y.ALL_YAKU:
        rows.append({
            "name": y.name,
            "fan": y.fan,
            "group": y.group.value,
            "doc": docs.get(y.name, ""),
            "seven_pairs": bool(y.applies_to_seven_pairs),
            "std": bool(y.applies_to_standard),
            "kokushi": bool(y.applies_to_thirteen_orphans),
        })
    rows.sort(key=lambda r: (group_order.index(r["group"]) if r["group"] in group_order else 99,
                             -r["fan"], r["name"]))
    return rows


def group_summary(rows):
    out = []
    for r in rows:
        if out and out[-1]["group"] == r["group"]:
            out[-1]["count"] += 1
            out[-1]["max"] = max(out[-1]["max"], r["fan"])
            out[-1]["min"] = min(out[-1]["min"], r["fan"])
        else:
            out.append({"group": r["group"], "count": 1, "max": r["fan"], "min": r["fan"]})
    return out


# ---------------- 数据：冒险关卡 ----------------
def levels_rows():
    rows = []
    chapters = adv.CHAPTERS if isinstance(adv.CHAPTERS, list) else []
    for ch in chapters:
        for lv in ch.get("levels", []):
            cond = lv.get("win_condition") or {}
            t = cond.get("type")
            if t == "win_yaku":
                goal = "和出「%s」" % cond.get("yaku", "")
            elif t == "score":
                goal = "累计得分 ≥ %s 分" % cond.get("target", "")
            elif t == "score_lead":
                goal = "领先对手 ≥ %s 分（须打满局数）" % cond.get("target", "")
            elif t == "block_win":
                goal = "连续阻止对手和牌（对手和牌即失败）"
            elif t == "win_and_score":
                goal = "和牌 ≥ %s 次 且 总分 ≥ %s 分" % (cond.get("wins", ""), cond.get("target", ""))
            else:
                goal = str(cond)
            fights = lv.get("fights")
            if fights:
                goal += "（两段战斗：%s）" % " → ".join(f.get("name", f.get("id", "")) for f in fights)
            reward, seen = [], set()

            def add(s):
                if s not in seen:
                    seen.add(s)
                    reward.append(s)

            if lv.get("coins"):
                add("+%s 金币" % lv["coins"])
            if lv.get("reward_yaku"):
                add("解锁 " + "/".join(lv["reward_yaku"]))
            if lv.get("mid_unlock_yaku"):
                mids = [k for k in lv["mid_unlock_yaku"].keys() if k not in (lv.get("reward_yaku") or [])]
                if mids:
                    add("中段解锁 " + "/".join(mids))
            if lv.get("hidden_unlock"):
                add("隐藏关 " + "/".join(lv["hidden_unlock"]))
            if lv.get("unlock_shop"):
                add("商店系统")
            if not reward:
                reward = ["—"]
            rows.append({
                "id": lv.get("id", ""),
                "name": lv.get("name", ""),
                "rounds": lv.get("rounds", ""),
                "goal": goal,
                "reward": "；".join(reward),
                "lock": "未解锁番种不计分" + ("（本关只计「和牌类」番种）" if lv.get("scored_kinds")
                                            and "组合" in lv.get("scored_kinds", []) and lv.get("id") == "1-1"
                                            else ""),
            })
    return rows


# ---------------- HTML ----------------
CSS = """
@page { size: A4; margin: 15mm 14mm 16mm; }
* { box-sizing: border-box; }
body { font-family: "Microsoft YaHei", "Segoe UI", "PingFang SC", sans-serif; font-size: 10.3pt;
       line-height: 1.62; color: #16202a; margin: 0; }
h1 { font-size: 25pt; margin: 0 0 6px; letter-spacing: 1px; }
h1 .sub { display:block; font-size: 12pt; font-weight: 400; color: #4a6a78; letter-spacing: 3px; margin-top: 8px; }
h2 { font-size: 15pt; margin: 20px 0 8px; padding: 3px 0 3px 10px; border-left: 5px solid #0b9; color: #084f5a;
     page-break-after: avoid; }
h3 { font-size: 11.8pt; margin: 14px 0 6px; color: #0e5d69; page-break-after: avoid; }
p { margin: 6px 0; }
ul, ol { margin: 6px 0 6px 20px; padding: 0; }
li { margin: 3px 0; }
table { width: 100%; border-collapse: collapse; font-size: 8.9pt; margin: 8px 0 12px; }
thead { display: table-header-group; }
th, td { border: 1px solid #cbd6dc; padding: 3.5px 6px; vertical-align: top; }
th { background: #eaf5f7; color: #0b4c57; text-align: left; font-weight: 700; }
tr { page-break-inside: avoid; }
tbody tr:nth-child(even) { background: #f7fbfc; }
td.num { text-align: center; white-space: nowrap; font-weight: 700; color: #0b6b79; }
td.gr { white-space: nowrap; color: #4a6a78; }
.cover { page-break-after: always; padding-top: 30mm; }
.cover .tag { display: inline-block; font-size: 9pt; letter-spacing: 2px; color: #0b6b79;
              border: 1px solid #9fd3dc; border-radius: 12px; padding: 3px 12px; margin-bottom: 14px; }
.cover .meta { margin-top: 16mm; font-size: 10pt; color: #35535f; line-height: 2; }
.cover .meta b { color: #0b4c57; }
.note { background: #f3f9fb; border-left: 3px solid #0b9; padding: 7px 12px; margin: 8px 0;
        font-size: 9.4pt; color: #23414c; }
.warn { background: #fff8e8; border-left: 3px solid #e8a600; padding: 7px 12px; margin: 8px 0;
        font-size: 9.4pt; color: #4a3a12; }
.two { display: flex; gap: 18px; }
.two > div { flex: 1; }
code { font-family: Consolas, monospace; background: #f0f4f6; padding: 0 3px; border-radius: 2px; font-size: 9pt; }
.foot { position: fixed; bottom: -9mm; left: 0; right: 0; text-align: center; font-size: 7.8pt; color: #93a4ad; }
"""


def h(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def build_html():
    rows = yaku_rows()
    groups = group_summary(rows)
    lv = levels_rows()
    total_fan = sum(r["fan"] for r in rows)

    trs = "\n".join(
        '<tr><td class="gr">%s</td><td>%s</td><td class="num">%d</td><td>%s</td></tr>'
        % (h(r["group"]), h(r["name"]), r["fan"], h(r["doc"]) if r["doc"] else "—")
        for r in rows)
    grs = "\n".join(
        '<tr><td class="gr">%s</td><td class="num">%d</td><td class="num">%d</td><td class="num">%d</td></tr>'
        % (h(g["group"]), g["count"], g["min"], g["max"])
        for g in groups)
    lvs = "\n".join(
        '<tr><td>%s</td><td>%s</td><td class="num">%s</td><td>%s</td><td>%s</td></tr>'
        % (h(x["id"]), h(x["name"]), h(x["rounds"]), h(x["goal"]), h(x["reward"]))
        for x in lv)

    today = time.strftime("%Y-%m-%d")
    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>组合麻将 · 规则手册</title><style>{CSS}</style></head>
<body>

<div class="cover">
  <div class="tag">规则手册 · 自动生成</div>
  <h1>组合麻将<span class="sub">COMBINATION MAHJONG</span></h1>
  <p style="font-size:11pt;color:#35535f;margin-top:14px">
    4 人麻将 · {len(rows)} 个番种 / {len(groups)} 个番种组 · 起和 4 番 · 得分 = 总番 × 2
  </p>
  <div class="meta">
    <div><b>版本</b>　v{VERSION}-beta</div>
    <div><b>生成日期</b>　{today}</div>
    <div><b>适用</b>　单机（人机）· 冒险模式 · 联机对战</div>
    <div><b>依据</b>　本仓库 <code>game_engine.py</code> + <code>branches/scoring/</code> 的实际实现</div>
  </div>
  <div class="note" style="margin-top:18mm">
    本文档自代码生成：番种表、番值、冒险关卡目标都直接读 <code>yaku.py</code> 与
    <code>adventure.py</code>，因此与线上对局逻辑一致。规则如有调整，重跑
    <code>python docs/build_rules_pdf.py</code> 即可更新。
  </div>
</div>

<h2>一、牌张与基本流程</h2>
<ul>
  <li><b>牌张</b>：万／筒／条 各 1–9，每种 4 枚（共 108 枚）；字牌 东·南·西·北·中·发·白，每种 4 枚（共 28 枚）。
      合计 <b>136 枚</b>。无花牌、无宝牌、无赤宝牌。</li>
  <li><b>人数与座次</b>：4 人一桌，门风依次为 东／南／西／北；出牌顺序为逆时针（东→南→西→北）。</li>
  <li><b>庄家</b>：每局轮换庄家，<b>不连庄</b>（流局同样轮换）。</li>
  <li><b>配牌</b>：每人 13 张，庄家先摸第 14 张开始打牌。</li>
  <li><b>回合</b>：摸牌 →（可与牌／杠）→ 打出一张。牌墙摸完即流局。</li>
</ul>

<h2>二、鸣牌（吃 / 碰 / 杠）</h2>
<h3>2.1 可以怎么鸣</h3>
<table>
  <thead><tr><th style="width:14%">鸣牌</th><th style="width:26%">条件</th><th>说明</th></tr></thead>
  <tbody>
    <tr><td>吃</td><td>只能用<b>上家</b>打出的牌</td><td>只有出牌者的下家可吃；吃后由吃牌者出牌。</td></tr>
    <tr><td>碰</td><td>手上两张同牌</td><td>任意一家都可碰；碰后由碰牌者出牌。</td></tr>
    <tr><td>明杠</td><td>手上三张同牌 + 别人打出的一张</td><td>杠后从牌墙<b>末尾</b>补一张（岭上牌）。</td></tr>
    <tr><td>暗杠</td><td>手上四张同牌</td><td>不打出、只亮两张；杠后补一张。</td></tr>
    <tr><td>加杠</td><td>已碰的刻子 + 摸到第四张</td><td>杠后补一张；<b>加杠的牌可以被别人抢杠荣和</b>。</td></tr>
  </tbody>
</table>

<h3>2.2 同一张牌的优先级</h3>
<ol>
  <li><b>和牌 > 碰／杠 > 吃</b>。系统先询问所有能和的人，再询问碰杠，最后才轮到吃。</li>
  <li><b>头跳</b>：同一张牌有多家可以荣和时，按座次（从出牌者下家开始）先到先得，<b>只有一家和</b>；
      不支持一炮多响。</li>
  <li><b>抢杠</b>：只有<b>加杠</b>可以被抢（暗杠不可抢）。被抢后，加杠回退成原来的碰，
      被抢的那张牌归和牌者，按荣和计分。</li>
</ol>

<h2>三、和牌与计分</h2>
<h3>3.1 和牌形</h3>
<ul>
  <li><b>标准型</b>：4 个面子（顺子／刻子／杠）+ 1 个雀头，共 14 张（每个杠多 1 张）。</li>
  <li><b>七对子</b>：7 个对子，且不能有副露。</li>
  <li><b>十三幺</b>：六种幺九 + 七种字牌各一张，其中一种成对，且不能有副露。</li>
  <li>另有 <b>九莲宝灯</b>（标准型特殊牌形，{48} 番）。</li>
</ul>

<h3>3.2 起和与得分</h3>
<ul>
  <li><b>起和 {4} 番</b>：不足 4 番不能和牌（冒险关卡会按剧情调整，如 1-1 把「五门齐」设为 1 番）。流局不设番数限制。</li>
  <li><b>得分 = 总番 × 2</b>（自摸与荣和同分）。无庄家加成、无符点、无包牌、无立直。</li>
</ul>

<h3>3.3 计番规则（重要）</h3>
<ol>
  <li>先判定和牌形（标准型／七对／十三幺）。</li>
  <li>标准型会<b>枚举全部合法拆解</b>（面子 + 雀头），每种拆解都完整套一遍所有番种。</li>
  <li>{len(groups)} 个<b>番种组</b>内，<b>每组只取番数最高的一个</b>；同组同番时取更具体的那个
      （例如「番牌刻」优先于「字刻」）。</li>
  <li>各组番数相加 = 该拆解的总番；<b>所有拆解取总番最高者</b>作为最终成绩。</li>
  <li><b>直属番</b>（九莲宝灯 {48} 番、十三幺 {24} 番）单独成立，<b>不再叠加组合番</b>，
      只额外叠加状态类（门前清）、偶然类、听牌类。</li>
  <li><b>门前清</b>：没有吃／碰／明杠／加杠（<b>暗杠不算破坏门前清</b>）。</li>
  <li><b>暗刻家族</b>：自摸时所有刻子都算暗刻；荣和时，只有「和牌张恰好补成该刻子」的那一副不算暗刻
      （手上该牌恰好 3 张），其余刻子仍按暗刻计。</li>
</ol>
<div class="note">
  一句话记住：<b>番种不叠同类</b>——同一组里只认最高的那个；<b>不同组可以叠</b>；
  <b>拆法不同则取总番最大的那种说法</b>。
</div>

<h2>四、流局</h2>
<ul>
  <li>牌墙摸完即流局，四家都要计分（不是 0 分）。</li>
  <li><b>流局得分 = max（组合番 × 2，听算 × 1）</b>，两种算法取高的那个：</li>
  <li><b>组合番</b>：把 13 张手牌拆成「面子（碰／吃／杠）+ 对子 + 余牌」，每种拆法独立计组合番、
      取最高；副露（含暗杠）固定不再拆。余牌不参与番种判定。</li>
  <li><b>听算</b>：全体番（含组合番，但<b>不含门前清、偶然类</b>）加上听牌张数对应的听牌番，按 ×1 计。</li>
  <li>冒险关卡可用 <code>ryuukyoku_scoring:false</code> 关闭流局计分（1-2／1-3／1-5／1-6 关掉了，
      只算和牌得分）。</li>
</ul>

<h2>五、本家自定义规则（与常见日麻／国标不同）</h2>
<table>
  <thead><tr><th style="width:26%">项目</th><th>组合麻将的规则</th></tr></thead>
  <tbody>
    <tr><td>包牌／责任付</td><td><b>没有</b>。点炮与自摸同等计分，无放铳包牌。</td></tr>
    <tr><td>连庄</td><td><b>不连庄</b>。每局轮换庄家，流局也轮换。</td></tr>
    <tr><td>多家和</td><td><b>头跳</b>：只算一家（按座次先到先得）。</td></tr>
    <tr><td>抢杠</td><td>只有<b>加杠</b>能被抢；暗杠不可抢。</td></tr>
    <tr><td>花牌／宝牌／赤牌</td><td>均<b>没有</b>，只有 136 张基本牌。</td></tr>
    <tr><td>立直／符点</td><td>均<b>没有</b>。计分只看总番 × 2。</td></tr>
    <tr><td>王牌／岭上牌堆</td><td>不单设王牌；杠后直接摸牌墙<b>末尾</b>那一张。</td></tr>
    <tr><td>番种上限</td><td>不封顶。{len(rows)} 个番种、{len(groups)} 个组，理论上限每番种按最高组合累计。</td></tr>
  </tbody>
</table>

<h2>六、三种玩法</h2>
<h3>6.1 单机模式</h3>
<p>1 名真人 + 3 个「摸打机器人」。机器人只按「摸切」策略出张（前 10 巡优先打字牌 > 幺九 > 中张，
之后改为偏摸切），<b>不鸣牌、不自摸和被点炮</b>。不限时，适合熟悉番种与流程。</p>

<h3>6.2 冒险模式（章节 1-1 ~ 1-6）</h3>
<p>每关有剧情、番种锁和过关目标。<b>番种锁</b>：没解锁的番种不计分。开局只解锁「五门齐」，
第一章只计「和牌类」番种，从 1-2 关卡起「组合类／听牌类」也一并计分。通关会解锁新番种。</p>
<table>
  <thead><tr><th style="width:8%">关卡</th><th style="width:18%">名称</th><th style="width:7%">局数</th>
             <th style="width:37%">过关条件</th><th>奖励</th></tr></thead>
  <tbody>{lvs}</tbody>
</table>

<h3>6.3 联机对战</h3>
<ul>
  <li><b>公开大厅</b>：创建房间（局数 4／8／16，三档计时可调）→ 其他玩家加入 → 全员准备 → 房主开局。
      房主可以在等待房里补「摸打机器人」（最多 3 个），方便单人练手。</li>
  <li><b>三档计时（默认）</b>：本人回合 <b>7 秒</b>（可调 3–15 秒）／鸣牌决策 <b>4 秒</b>（可调 3–15 秒）／
      兜底 <b>12 秒</b>（可调 0–45 秒）。超时自动代打。</li>
  <li><b>掉线与返回</b>：点牌桌左上「返回」或关掉页面，只算<b>离桌掉线</b>——座位和牌局都保留；
      大厅会出现「你有一局正在进行 → 回到对局」的入口，<b>60 秒内</b>回桌可以继续自己打，
      超时则由服务器代打。</li>
  <li><b>托管</b>：局内随时可以打开托管，由服务器代打；取消托管即恢复手动。</li>
  <li><b>观战与回放</b>：进行中的对局可以被观战（只读）；结束后可在大厅「回放」里逐阶段复盘。</li>
  <li><b>计分</b>：与单机完全一致（起和 4 番、得分 = 总番 × 2），对局战绩计入个人统计。</li>
</ul>

<h2>七、番种总表（{len(rows)} 项）</h2>
<p>下面按番种组排列，「判定要点」取自代码里的定义注释；空白表示该番种没有额外注释，
具体牌例可在游戏的「番种表」页与「算番测试」页对照（三处同源，都来自 <code>yaku.py</code>）。</p>
<table>
  <thead><tr><th style="width:12%">组</th><th style="width:15%">番种</th><th style="width:7%">番数</th>
             <th>判定要点</th></tr></thead>
  <tbody>{trs}</tbody>
</table>
<div class="warn">
  <b>注</b>：偶然类的 4 个番种（天地和 12 番、岭上开花 3 番、枯木逢春 3 番、金鸡夺食 3 番）目前只在
  「算番测试」里可手动标记触发，<b>实战对局尚未接入</b>——对局中不会出现这几项番。
  「番牌刻」「单吊字」是冒险模式专属番种，单机／联机不启用。
</div>

<h3>7.1 番种组一览</h3>
<table>
  <thead><tr><th style="width:24%">番种组</th><th style="width:16%">番种数</th><th style="width:16%">最低番</th>
             <th>最高番</th></tr></thead>
  <tbody>{grs}</tbody>
</table>
<div class="note">
  同组番种互相<b>不叠加</b>（只取最高的一个），所以一个和牌的实际总番 = 各命中组的番数之和。
  全部 {len(rows)} 个番种的番值合计 {total_fan} 番。
</div>

<h2>八、常见问题</h2>
<ul>
  <li><b>为什么 3 番不能和？</b> 起和是 4 番。手上牌型不够 4 番时不能和，需要继续做牌（或流局按听算计分）。</li>
  <li><b>七对子能叠暗刻番吗？</b> 不能。七对是独立和牌形，只走「同对类」「色形类」等适用七对的番种。</li>
  <li><b>暗杠会破坏门前清吗？</b> 不会，暗杠不破坏门前清。</li>
  <li><b>荣和的刻子算暗刻吗？</b> 只有当和牌张恰好补成该刻子时才不算暗刻，其余刻子照算。</li>
  <li><b>流局还要计分吗？</b> 要，按「组合番 × 2」与「听算 × 1」中较高的那一种。</li>
</ul>

<div class="foot">组合麻将 · 规则手册 v{VERSION}-beta · 本文档由 docs/build_rules_pdf.py 自动生成 · {today}</div>
</body></html>
"""
    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    return HTML_PATH


def find_chrome():
    cands = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for p in cands:
        if os.path.exists(p):
            return p
    return None


def build_pdf(html_path):
    chrome = find_chrome()
    if not chrome:
        print("找不到 Chrome/Edge，无法打印 PDF（HTML 已生成：" + html_path + "）")
        return None
    tmp_pdf = os.path.join(tempfile.gettempdir(), "_cmj_rules.pdf")
    if os.path.exists(tmp_pdf):
        os.remove(tmp_pdf)
    url = "file:///" + html_path.replace("\\", "/")
    cmd = [chrome, "--headless=new", "--disable-gpu", "--no-first-run",
           "--no-pdf-header-footer", "--virtual-time-budget=6000",
           "--print-to-pdf=" + tmp_pdf, url]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if not os.path.exists(tmp_pdf):
        print("打印失败：", (r.stderr or r.stdout)[-600:])
        return None
    if os.path.exists(PDF_PATH):
        os.remove(PDF_PATH)
    shutil.move(tmp_pdf, PDF_PATH)
    return PDF_PATH


def main():
    html_path = build_html()
    print("HTML:", html_path)
    if "--html" in sys.argv:
        return 0
    pdf = build_pdf(html_path)
    if not pdf:
        return 1
    kb = os.path.getsize(pdf) / 1024.0
    print("PDF :", pdf, "(%.0f KB)" % kb)
    return 0


if __name__ == "__main__":
    sys.exit(main())
