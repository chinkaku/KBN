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
                "rounds": 3,
                "win_condition": {"type": "score", "target": 8},  # 3局内累计得分达到8分(对手Boss会抢分, 需尽快和牌)
                "guaranteed_hand": {"honour_pair": True, "loose_honours": 2, "suit_min": {"m": 2, "p": 2, "s": 2}},
                "ryuukyoku_scoring": False,     # 流局不算分, 只有和牌能得分
                "boss": {"seat": 2, "win_after_turns": 14, "win_chance": 0.6, "max_score": 12},
                #   对家(座2)打完14张后再摸牌时, 每次按60%概率和牌;
                #   和牌由生成器从剩余牌池构造(门清/门清+喜相逢/门清+单吊字), 分数≤12分;
                #   对手番种不要求主角解锁过。
                "bot_names": {"1": "摸打机器人", "2": "对手", "3": "摸打机器人"},
                "reward_yaku": [],              # 过关奖励待定
                "unlock_yaku": ["五门齐", "单吊字", "字刻", "门前清", "双字刻", "字对"],
                "fan_overrides": {"五门齐": 2},
                "scored_kinds": {"和牌", "组合", "听牌"},
                "hand": None,
                "hand_bias": None,
                "story_file": "1-3.txt",        # 剧情待提供
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
    """加载关卡剧情 (story/<文件名>.txt), 返回 {'before': [...], 'after': [...]}"""
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
