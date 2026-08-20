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
                "rounds": 1,                    # 关卡局数(可多局)
                "unlock_yaku": ["五门齐"],       # 进入关卡前解锁
                "fan_overrides": {"五门齐": 1},  # 番值动态调整
                "hand": None,                    # 指定起始手牌(可复用调试)
                "hand_bias": None,               # 未来: 概率调高某种牌
                "story_before": [
                    {"type": "dialog", "speaker": "旁白", "text": "五门齐，是一道入门课……", "bg": None}
                ],
                "story_after": [
                    {"type": "dialog", "speaker": "旁白", "text": "你学会了五门齐。", "bg": None}
                ],
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

def compute_locked_yaku(unlocked):
    """根据已解锁番种, 返回未解锁(锁定)番种集合"""
    all_yaku = _load_all_yaku()
    return set(all_yaku.keys()) - set(unlocked)


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
    }


GROUP_MAP = {
    'JHIHO': '直属', 'COLOR': '色形类', 'FREE': '自由类', 'CLUSTER': '数聚类',
    'NUMFORM': '数形类', 'TERMINAL': '幺九类', 'PAIR': '对子类',
    'TRIPLET': '刻子类', 'CONCEALED': '暗刻类', 'MIXED_TRIP': '杂刻类',
    'SEQ_TRIP': '连刻类', 'MIXED_SEQ': '杂顺类', 'SEQ_SEQ': '连顺类',
    'DRAGON': '龙顺类', 'SAME_SEQ': '同顺类', 'RETURN': '归子类',
    'KONG': '杠子类', 'ALL_HONOR': '全字类', 'HONOR_TRIP': '字刻类',
    'HONOR_PAIR': '字对类', 'SAME_PAIR': '同对类', 'STATE': '状态类', 'CHANCE': '偶然类',
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
