# -*- coding: utf-8 -*-
"""组合麻将 — 账号系统 (JSON文件存储 + 内存session)"""
import os, json, hashlib, secrets, time
from typing import Optional, Dict
from dataclasses import dataclass, field

AUTH_DIR = os.path.dirname(os.path.abspath(__file__))
USERS_FILE = os.path.join(AUTH_DIR, "users.json")

def _load_users() -> Dict:
    if not os.path.exists(USERS_FILE): return {}
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except: return {}

def _save_users(data: Dict):
    os.makedirs(AUTH_DIR, exist_ok=True)
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _hash(pw: str, salt: str) -> str:
    return hashlib.sha256((salt + pw).encode()).hexdigest()

def register(username: str, password: str) -> Optional[str]:
    """注册新用户, 返回token或None. token持久化在users.json中, 永不过期."""
    if not username or len(username) < 2 or len(username) > 16: return None
    if not password or len(password) < 1: return None
    users = _load_users()
    if username in users: return None
    salt = secrets.token_hex(8)
    token = secrets.token_hex(16)
    users[username] = {
        "hash": _hash(password, salt), "salt": salt,
        "created": time.strftime("%Y-%m-%d %H:%M"),
        "token": token  # token 存在文件里, 不依赖内存
    }
    _save_users(users)
    return token

def login(username: str, password: str) -> Optional[str]:
    """登录, 返回持久token或None"""
    users = _load_users()
    if username not in users: return None
    u = users[username]
    if _hash(password, u["salt"]) != u["hash"]: return None
    # 每次登录重新生成token(旧token作废)
    token = secrets.token_hex(16)
    u["token"] = token
    _save_users(users)
    return token

def get_user(token: str) -> Optional[str]:
    """根据token查找用户名. 遍历users.json, 找到匹配的token即返回."""
    if not token: return None
    users = _load_users()
    for username, u in users.items():
        if u.get("token") == token:
            return username
    return None

def logout(token: str):
    """登出: 清除token"""
    if not token: return
    users = _load_users()
    for u in users.values():
        if u.get("token") == token:
            u["token"] = ""
            _save_users(users)
            return

def get_stats(username: str) -> Optional[dict]:
    """获取用户统计数据"""
    users = _load_users()
    u = users.get(username)
    if not u: return None
    return u.get("stats", {
        "games": 0, "rounds": 0, "wins": 0, "combos": 0,
        "total_pts": 0, "win_pts": 0, "combo_pts": 0,
        "fan_wins": {}, "fan_combos": {}
    })

def update_stats(username: str, round_data: dict):
    """更新用户统计: round_data 含有 winner, score, is_win, fan_details 等"""
    users = _load_users()
    u = users.get(username)
    if not u: return
    if "stats" not in u:
        u["stats"] = {"games": 0, "rounds": 0, "wins": 0, "combos": 0,
                       "total_pts": 0, "win_pts": 0, "combo_pts": 0,
                       "fan_wins": {}, "fan_combos": {}}
    s = u["stats"]
    s["rounds"] = s.get("rounds", 0) + 1
    pts = round_data.get("score", 0)
    is_win = round_data.get("is_win", False)
    fans = round_data.get("fans", [])
    s["total_pts"] = s.get("total_pts", 0) + pts
    if is_win:
        s["wins"] = s.get("wins", 0) + 1
        s["win_pts"] = s.get("win_pts", 0) + pts
        for f in fans:
            n = f.get("name", "")
            s["fan_wins"][n] = s["fan_wins"].get(n, 0) + 1
    else:
        s["combos"] = s.get("combos", 0) + 1
        s["combo_pts"] = s.get("combo_pts", 0) + pts
        for f in fans:
            n = f.get("name", "")
            s["fan_combos"][n] = s["fan_combos"].get(n, 0) + 1
    # 标记本局开始(跨局重置)
    last_rid = round_data.get("room_id", "")
    last_rn = round_data.get("round_num", 0)
    if last_rn <= 1 and last_rid != s.get("_last_room", ""):
        s["games"] = s.get("games", 0) + 1
        s["_last_room"] = last_rid
    _save_users(users)

def change_password(username: str, old_pw: str, new_pw: str) -> bool:
    users = _load_users()
    if username not in users: return False
    u = users[username]
    if _hash(old_pw, u["salt"]) != u["hash"]: return False
    u["salt"] = secrets.token_hex(8)
    u["hash"] = _hash(new_pw, u["salt"])
    _save_users(users)
    return True
