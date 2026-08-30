# -*- coding: utf-8 -*-
"""组合麻将 — 冒险模式 (章节/关卡/进度/番种解锁)"""

# 章节关卡配置 (番值动态, 剧情占位)
CHAPTERS = [
    {
        "id": 1,
        "name": "五门齐",
        "levels": [
            {
                "id": "1-1",
                "name": "五门齐·入门",
                "rounds": 3,                    # 关卡局数(可多局)
                "win_condition": {"type": "win_yaku", "yaku": "五门齐"},  # 3局内和出至少1把五门齐(必须实际和牌)
                "guaranteed_pair": "honour",    # 起始手牌必然含一对字牌, 其余随机
                "reward_yaku": ["番牌刻", "单吊字"],  # 过关后解锁的番种(随进度保存)
                "unlock_yaku": ["五门齐"],       # 进入关卡前解锁
                "fan_overrides": {"五门齐": 1},  # 番值动态调整
                "hand": None,                    # 指定起始手牌(可复用调试)
                "hand_bias": None,               # 未来: 概率调高某种牌
                "story_file": "1-1.txt",         # 剧情文件名(缺省取 关卡id.txt)
                # 战斗配置(对手/目标番种/强度等)逐关补充
                "battle": None,
            },
            {
                "id": "1-2",
                "name": "18分挑战",
                "rounds": 4,                    # 关卡局数(可多局)
                "win_condition": {"type": "score", "target": 18},  # 4局内累计得分达到18分(和牌=番数×2)
                "guaranteed_hand": {"honour_pair": True, "loose_honours": 2, "suit_min": {"m": 2, "p": 2, "s": 2}},  # 起始手牌: 一对字牌+两张散张字牌+万/条/筒各2张(点数随机不固定)
                "ryuukyoku_scoring": False,     # 流局不算分: 关闭听算/组合算分, 只有和牌才能得分
                "reward_yaku": ["字刻", "门前清", "双字刻", "字对"],  # 过关后解锁的番种
                "replace_yaku": {"番牌刻": "字刻"},  # 过关后替换: 番牌刻升级为字刻(退役番牌刻)
                "unlock_yaku": ["五门齐", "番牌刻", "单吊字"],   # 进入关卡前解锁(1-1奖励已含, 这里兜底)
                "fan_overrides": {"五门齐": 2},  # 番值动态调整: 五门齐 1->2番
                "scored_kinds": {"和牌", "组合", "听牌"},  # 本关可计分的大类(默认按章节策略; 1-2起组合/听牌也计分)
                "hand": None,
                "hand_bias": None,
                "story_file": "1-2.txt",
                "battle": None,
            },
            {
                "id": "1-3",
                "name": "正式比赛",
                "rounds": 4,
                "win_condition": {"type": "score_lead", "target": 5, "opponent_seat": 2},  # 4局内累计领先对手(对家)至少5分
                "guaranteed_hand": {"honour_pair": True, "loose_honours": 1, "suit_min": {"m": 2, "p": 1, "s": 1}},  # 至少一对字牌+一张单张字牌+2万+1筒+1条
                "ryuukyoku_scoring": False,     # 流局不算分, 只有和牌能得分
                "boss": {"seat": 2, "win_between": [14, 20], "max_score": 12},
                #   对家(座2)花桥上田: 每局在14~20巡之间的随机巡数和牌;
                #   和牌由生成器从剩余牌池构造(门清/门清+喜相逢/门清+单吊字, 灵活兜底;
                #   池含两个摸打机器人的不可见手牌, 保证高巡数也能生成), 分数≤12分;
                #   对手番种不要求主角解锁过。
                "bot_names": {"1": "摸打机器人", "2": "花桥上田", "3": "摸打机器人"},
                "reward_yaku": [],              # 过关奖励待定
                "unlock_yaku": ["五门齐", "单吊字", "字刻", "门前清", "双字刻", "字对"],
                "fan_overrides": {"五门齐": 2, "门前清": 3},  # 我方门前清价值3番
                "scored_kinds": {"和牌", "组合", "听牌"},
                "hand": None,
                "hand_bias": None,
                "story_file": "1-3.txt",
                "battle": None,
            },
            {
                "id": "1-4",
                "name": "染手流·法衣双",
                "rounds": 5,                    # 每段5局
                "win_condition": {"type": "block_win", "target": 5, "opponent_seat": 2},
                #   新目标类型 block_win: 连续5局阻止对手(对家)和牌——玩家和牌/流局都算阻止成功;
                #   对手和过任意一局即本段失败; 必须打完5局才结算。
                "fights": [
                    # 第一段 (1-4-1) 剧情杀: 初始手牌完全随机, 染手流bot全强度(正常吃碰杠和)
                    {
                        "id": "1-4-1",
                        "name": "第一段·剧情杀",
                        "guaranteed_hand": None,    # 完全随机
                        "opponent": {"seat": 2, "style": "flush", "no_claim_rounds": 0, "deal_bias": 6},
                        #   染手流bot(法衣双): 开局按 花色张数>中张数>顺子潜力 选目标花色,
                        #   优先打出非目标花色数牌、保留字牌打混一色, 会正常吃碰杠和(荣和/自摸);
                        #   deal_bias=6: 起手偏科(先发6张同花色), 保证剧情杀强度。
                    },
                    # 第二段 (1-4-2) 正式挑战: 保底手牌 + bot前3局放水(不吃碰杠, 自摸照和)
                    {
                        "id": "1-4-2",
                        "name": "第二段·正式挑战",
                        "guaranteed_hand": {"honour_pair": True, "loose_honours": 2,
                                            "partials": {"m": 1, "p": 1, "s": 1}},
                        #   至少一对字牌 + 两张单张字牌 + 万/筒/条各一副 12/56/89(三选一随机),
                        #   共10张保底, 其余3张随机。
                        "opponent": {"seat": 2, "style": "flush", "no_claim_rounds": 3},
                    },
                ],
                "ryuukyoku_scoring": True,      # 流局算阻止成功, 正常流局计分
                "bot_names": {"1": "摸打机器人", "2": "法衣双", "3": "摸打机器人"},
                "reward_yaku": ["混全带幺"],     # 通关后保留(第一段打赢跳关也照给)
                "mid_unlock_yaku": {"混全带幺": 3},  # 第一段结束(进入第二段)时解锁: 都茂教学
                "unlock_yaku": ["五门齐", "单吊字", "字刻", "门前清", "双字刻", "字对"],
                "fan_overrides": {"五门齐": 2, "门前清": 3, "混全带幺": 3},
                "scored_kinds": {"和牌", "组合", "听牌"},
                "coins": 3000,                  # 通关金币(1-4-1打赢跳关也照给)
                "hidden_unlock": ["1-6"],       # 打赢第一段(1-4-1)解锁的隐藏关(解锁前不可见)
                "hand": None,
                "hand_bias": None,
                "story_file": "1-4.txt",
                "battle": None,
            },
            {
                "id": "1-5",
                "name": "最终章·公会考核",
                "rounds": 5,
                "win_condition": {"type": "win_and_score", "wins": 3, "target": 18},
                #   5局内和牌3次及以上 且 总分≥18分(得分=番数×2, 只有和牌能得分), 提前达标即通关
                "guaranteed_hand": {"honour_pair": True, "loose_honours": 2,
                                    "suit_min": {"m": 1, "p": 1, "s": 1}, "terminals": 3},
                #   必然一对字牌 + 两张单张字牌 + 每种花色各一张(点数随机) + 至少3张幺九(1/9, 可与花色保底重叠),
                #   其余随机补(如 1p9s9m 可同时满足后两条, 但点数/花色全随机, 不固定)
                "ryuukyoku_scoring": False,     # 流局不算分, 只有和牌能得分
                "opponents": [
                    # 星井(聚数流): 下家(1号位), 选4个(或3个)连续序数做四聚/三聚, 优先切字牌,
                    # 吃碰杠必须完全落在自己选的连续点数窗口内(如窗口5678不会用78吃9)
                    {"seat": 1, "style": "cluster"},
                    # 佐佐木(法衣双, 染手流): 对家(2号位), 沿用1-4配置——第一局放水(不吃碰杠), 第二局起全强度(起手偏科6张)
                    {"seat": 2, "style": "flush", "deal_bias": 6, "no_claim_rounds": 1},
                ],
                "no_ron_turn": 13,              # 两个对手每局出牌<13张不接点炮和牌(可自摸), ≥13张放开
                "bot_names": {"1": "星井", "2": "佐佐木", "3": "摸打机器人"},
                "reward_yaku": ["混一色", "双字刻", "三字刻", "四字刻", "一气通贯"],  # 战后佐佐木教学解锁(双字刻已有, 幂等)
                "unlock_yaku": ["五门齐", "单吊字", "字刻", "门前清", "双字刻", "字对", "混全带幺"],
                "fan_overrides": {"五门齐": 2, "门前清": 3, "混全带幺": 3},
                "scored_kinds": {"和牌", "组合", "听牌"},
                "coins": 0,                     # 1-5不给金币
                "unlock_shop": True,            # 通关解锁商店系统(第2章细说)
                "hand": None,
                "hand_bias": None,
                "story_file": "1-5.txt",
                "battle": None,
            },
            {
                "id": "1-6",
                "name": "隐藏关",
                "rounds": 3,
                "win_condition": {"type": "win_yaku", "yaku": "混全带幺"},
                "guaranteed_hand": {"honour_pair": True, "loose_honours": 1, "suit_min": {"m": 2, "p": 2, "s": 2}},
                "hidden": True,                 # 隐藏关: 解锁前在冒险页完全不可见
                "ryuukyoku_scoring": False,
                "reward_yaku": [],
                "unlock_yaku": ["混全带幺"],
                "fan_overrides": {"五门齐": 2, "门前清": 3, "混全带幺": 3},
                "scored_kinds": {"和牌", "组合", "听牌"},
                "hand": None,
                "hand_bias": None,
                "story_file": "1-6.txt",        # 剧情待定
                "battle": None,
            }
        ]
    }
]

# 所有番种默认番值(照抄原表, 后续动态覆盖)
DEFAULT_FAN = {}

def _load_all_yaku():
    """从 yaku.py 读取全部番种及默认番值"""
    global DEFAULT_FAN
    if DEFAULT_FAN:
        return DEFAULT_FAN
    import re, sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scoring", "yaku.py"), encoding="utf-8") as f:
        content = f.read()
    for name, fan in re.findall(r'name\s*=\s*"([^"]+)"[^}]*?fan\s*=\s*(\d+)', content):
        DEFAULT_FAN[name] = int(fan)
    return DEFAULT_FAN

def get_level(level_id):
    """根据关卡ID返回关卡配置"""
    for ch in CHAPTERS:
        for lv in ch["levels"]:
            if lv["id"] == level_id:
                return ch, lv
    return None, None

def get_story(level_id):
    """加载关卡剧情 (story/<文件名>.txt), 返回 {'before': [...], 'segments': [...], 'after': [...]}"""
    ch, lv = get_level(level_id)
    fname = (lv or {}).get("story_file") or (level_id + ".txt")
    from . import story
    return story.get_story(fname)

def next_level_id(level_id):
    """按章节顺序返回下一关ID (无则返回None)"""
    all_ids = [lv["id"] for ch in CHAPTERS for lv in ch["levels"]]
    try:
        i = all_ids.index(level_id)
    except ValueError:
        return None
    if i + 1 < len(all_ids):
        return all_ids[i + 1]
    return None

def get_level_effective_config(level_id, progress):
    """计算关卡的生效配置: 番值覆盖 + 已解锁番种"""
    ch, lv = get_level(level_id)
    if not lv:
        return None, None
    # 番值覆盖 = 全局进度覆盖 + 关卡覆盖
    fan_overrides = dict(progress.get("fan_overrides", {}))
    fan_overrides.update(lv.get("fan_overrides", {}))
    # 解锁番种 = 进度已解锁 + 本关卡解锁
    unlocked = set(progress.get("unlocked_yaku", []))
    unlocked.update(lv.get("unlock_yaku", []))
    return fan_overrides, unlocked

def compute_locked_yaku(unlocked, level_id=None, scored_kinds=None):
    """根据已解锁番种, 返回未解锁(锁定)番种集合。

    level_id 提供时按章节计分策略过滤: 已解锁但该章不计分的大类(如第一章的
    组合番/听牌类)仍计入锁定, 即"解锁≠该章可计分"。
    scored_kinds 提供时覆盖章节策略(关卡级配置, 如 1-2 起组合/听牌也计分)。
    """
    all_yaku = _load_all_yaku()
    if level_id:
        ch = level_id.split("-")[0]
        kinds = scored_kinds if scored_kinds is not None else CHAPTER_SCORED_KINDS.get(ch, set())
        scored = set(y for y in unlocked if YAKU_KIND.get(y, "组合") in kinds)
        return set(all_yaku.keys()) - scored
    # 非关卡(正常单机)上下文: 冒险专属番种(番牌刻/单吊字)即使出现在解锁列表也保持锁定
    return set(all_yaku.keys()) - (set(unlocked) - ADVENTURE_ONLY_YAKU)


def get_adventure_progress(username):
    """获取玩家冒险模式进度(跟随账号)"""
    from . import auth
    users = auth._load_users()
    u = users.get(username)
    if not u:
        return None
    p = u.get("adventure")
    if not p:
        return default_progress()
    # 老存档兼容: 确保初始解锁/番值存在
    p = dict(p)
    p["unlocked_yaku"] = list(set(p.get("unlocked_yaku", [])) | set(default_progress()["unlocked_yaku"]))
    fan = dict(p.get("fan_overrides", {}))
    for k, v in default_progress()["fan_overrides"].items():
        fan.setdefault(k, v)
    p["fan_overrides"] = fan
    p.setdefault("current_level", "1-1")
    p.setdefault("completed_levels", [])
    p.setdefault("story_seen", [])  # 已看过战前剧情的关卡列表 (下次可跳过)
    p.setdefault("adv_stage", {})   # 多段战斗关卡: {关卡id: 已体验过的最高段数(1=第一段, 2=第二段)}
    p.setdefault("unlocked_hidden", [])  # 已解锁的隐藏关列表(如 1-6, 解锁前不可见)
    p.setdefault("unlocked_shop", False)  # 商店系统解锁(1-5通关, 第2章细说)
    return p

def save_adventure_progress(username, progress):
    """保存玩家冒险模式进度"""
    from . import auth
    users = auth._load_users()
    u = users.get(username)
    if not u:
        return False
    u["adventure"] = progress
    auth._save_users(users)
    return True

def default_progress():
    # 冒险一开始即解锁第一章主题番种: 五门齐 (1番)
    return {
        "unlocked_yaku": ["五门齐"],
        "fan_overrides": {"五门齐": 1},
        "current_level": "1-1",
        "completed_levels": [],
        "story_seen": [],
        "adv_stage": {},
        "unlocked_hidden": [],
        "unlocked_shop": False,
    }


GROUP_MAP = {
    'JHIHO': '直属', 'COLOR': '色形类', 'FREE': '自由类', 'CLUSTER': '数聚类',
    'NUMFORM': '数形类', 'TERMINAL': '幺九类', 'PAIR': '对子类',
    'TRIPLET': '刻子类', 'CONCEALED': '暗刻类', 'MIXED_TRIP': '杂刻类',
    'SEQ_TRIP': '连刻类', 'MIXED_SEQ': '杂顺类', 'SEQ_SEQ': '连顺类',
    'DRAGON': '龙顺类', 'SAME_SEQ': '同顺类', 'RETURN': '归子类',
    'KONG': '杠子类', 'ALL_HONOR': '全字类', 'HONOR_TRIP': '字刻类',
    'HONOR_PAIR': '字对类', 'SAME_PAIR': '同对类', 'STATE': '状态类', 'CHANCE': '偶然类',
    'TENPAI': '听牌类',
}

# ---- 冒险专属番种 ----
# 以下番种只在冒险模式中生效, 正常单机模式不启用(始终锁定)。
ADVENTURE_ONLY_YAKU = {"番牌刻", "单吊字"}

# ---- 章节计分策略 ----
# 番种大类: 和牌 / 组合 / 听牌
# 第一章(1-X): 组合番与听牌类都不计分, 只有和牌类计分;
# 组合番/听牌类算分留到第二章解锁。 (未列出的番种默认按组合番处理)
YAKU_KIND = {
    "五门齐": "和牌",
    "混全带幺": "和牌",
    "番牌刻": "组合",
    "单吊字": "听牌",
}
# 每章可计分的番种大类
CHAPTER_SCORED_KINDS = {
    "1": {"和牌"},                              # 第一章只计和牌
    "2": {"和牌", "组合", "听牌"},               # 第二章解锁组合番/听牌类算分
}

def get_yaku_table():
    """返回番种表: [{'group':分类, 'name':番种名, 'fan':默认番值}]"""
    import re, sys, os
    _BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if _BASE not in sys.path:
        sys.path.insert(0, _BASE)
    yaku_path = os.path.join(_BASE, "branches", "scoring", "yaku.py")
    with open(yaku_path, encoding="utf-8") as f:
        content = f.read()
    result = []
    for g, name, fan in re.findall(r'group\s*=\s*YakuGroup\.(\w+)[^}]*?name\s*=\s*"([^"]+)"[^}]*?fan\s*=\s*(\d+)', content):
        result.append({'group': GROUP_MAP.get(g, g), 'name': name, 'fan': int(fan)})
    return result
