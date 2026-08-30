# -*- coding: utf-8 -*-
"""组合麻将 — 联机服务器"""
import json, asyncio, os, time, sys
# Add project root (Q:/openai/) to path so branches.* imports work
_BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _BASE)
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from branches.networking.rooms import Room, rooms, create_room, get_room
from branches.networking.auth import register, login, logout, get_user, get_stats, update_stats, get_coins, add_coins
from branches.networking import forum_db as fdb
from branches.networking import adventure as adv

app = FastAPI()
STATIC = os.path.join(_BASE, "static")

# HTML/JS/CSS 禁止缓存(确保每次刷新都拿到最新版; 开发期图片等资源可缓存)
@app.middleware("http")
async def no_cache_html(request: Request, call_next):
    resp = await call_next(request)
    ct = resp.headers.get("content-type", "")
    p = request.url.path
    if ct.startswith("text/html") or p.endswith(".js") or p.endswith(".css"):
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp

# 定期清理断线
async def cleanup_loop():
    while True:
        await asyncio.sleep(5)
        for rid, room in list(rooms.items()):
            try:
                await room.check_disconnects()
                # 自动销毁: 0真人槽 + 超过30秒未活动
                human_slots = sum(1 for s in room.slots.values() if s.name and not room._is_bot_name(s.name))
                if not room.started and human_slots == 0 and time.time() - room.last_activity > 30:
                    del rooms[rid]
                    print(f"[Cleanup] Room {rid} auto-destroyed")
            except: pass

@app.on_event("startup")
async def startup():
    fdb.init_db()
    asyncio.create_task(cleanup_loop())

@app.get("/")
async def index(): return FileResponse(os.path.join(STATIC, "index.html"))

@app.get("/game")
async def game(): return FileResponse(os.path.join(STATIC, "game.html"))

@app.get("/debug")
async def debug_page(): return FileResponse(os.path.join(STATIC, "debug.html"))

@app.get("/adventure")
async def adventure_page(): return FileResponse(os.path.join(STATIC, "adventure.html"))

@app.get("/tester")
async def test(): return FileResponse(os.path.join(STATIC, "tester.html"))

@app.get("/fans")
async def fans_page(): return FileResponse(os.path.join(STATIC, "fans.html"))

@app.get("/lobby")
async def lobby(): return FileResponse(os.path.join(STATIC, "lobby.html"))

@app.get("/wait")
async def wait_room(): return FileResponse(os.path.join(STATIC, "wait.html"))

@app.get("/auth")
async def auth_page(): return FileResponse(os.path.join(STATIC, "auth.html"))

@app.get("/stats")
async def stats_page(): return FileResponse(os.path.join(STATIC, "stats.html"))

@app.get("/global-stats")
async def global_stats_page(): return FileResponse(os.path.join(STATIC, "global-stats.html"))

@app.get("/forum")
async def forum_page(): return FileResponse(os.path.join(STATIC, "forum.html"))

@app.get("/profile")
async def profile_page(): return FileResponse(os.path.join(STATIC, "profile.html"))

@app.get("/api/stats")
async def api_stats(req: Request):
    token = req.headers.get("Authorization","").replace("Bearer ","")
    if not token: token = req.query_params.get("token","")
    user = get_user(token)
    if not user: return {"error": "未登录"}
    s = get_stats(user)
    if not s: return {"error": "无数据"}
    # 计算比率
    rds = max(s.get("rounds",0), 1)
    s["win_rate"] = round(s.get("wins",0)/rds*100, 1)
    s["combo_rate"] = round(s.get("combos",0)/rds*100, 1)
    s["avg_pts"] = round(s.get("total_pts",0)/rds, 1)
    s["avg_win_pts"] = round(s.get("win_pts",0)/max(s.get("wins",1),1), 1)
    s["avg_combo_pts"] = round(s.get("combo_pts",0)/max(s.get("combos",1),1), 1)
    return {"user": user, "stats": s}

@app.get("/api/stats/global")
async def api_global_stats(req: Request):
    token = req.headers.get("Authorization","").replace("Bearer ","")
    if not token: token = req.query_params.get("token","")
    user = get_user(token)
    if user != "chinkaku": return {"error": "无权限"}
    from branches.networking.auth import _load_users
    users = _load_users()
    # 收集所有真人(非伯特)的统计
    all_stats = {}
    for uname, u in users.items():
        if uname.startswith("伯特") or "bot:" in uname: continue
        s = u.get("stats")
        if not s: continue
        all_stats[uname] = s
    # 汇总
    total = {"games":0,"rounds":0,"wins":0,"combos":0,"total_pts":0,"win_pts":0,"combo_pts":0,"fan_wins":{},"fan_combos":{}}
    for uname, s in all_stats.items():
        for k in ["games","rounds","wins","combos","total_pts","win_pts","combo_pts"]:
            total[k] += s.get(k, 0)
        for fn, cnt in s.get("fan_wins",{}).items():
            total["fan_wins"][fn] = total["fan_wins"].get(fn, 0) + cnt
        for fn, cnt in s.get("fan_combos",{}).items():
            total["fan_combos"][fn] = total["fan_combos"].get(fn, 0) + cnt
    rds = max(total["rounds"], 1)
    total["user_count"] = len(all_stats)
    total["win_rate"] = round(total["wins"]/rds*100, 1)
    total["combo_rate"] = round(total["combos"]/rds*100, 1)
    total["avg_pts"] = round(total["total_pts"]/rds, 1)
    total["avg_win_pts"] = round(total["win_pts"]/max(total["wins"],1), 1)
    total["avg_combo_pts"] = round(total["combo_pts"]/max(total["combos"],1), 1)
    # 生成表格: 每人一行
    rows = []
    for uname, s in all_stats.items():
        ur = max(s.get("rounds",0), 1)
        rows.append({
            "user": uname,
            "games": s.get("games",0), "rounds": s.get("rounds",0),
            "win_rate": round(s.get("wins",0)/ur*100, 1),
            "combo_rate": round(s.get("combos",0)/ur*100, 1),
            "avg_pts": round(s.get("total_pts",0)/ur, 1),
            "avg_win_pts": round(s.get("win_pts",0)/max(s.get("wins",1),1), 1),
            "avg_combo_pts": round(s.get("combo_pts",0)/max(s.get("combos",1),1), 1),
        })
    rows.sort(key=lambda r: -r["games"])
    return {"total": total, "users": rows}

def _record_round(room, human_name: str):
    """记录一局数据到玩家账号"""
    if not human_name or human_name.startswith("伯特"): return
    eng = room.engine
    is_win = eng.winner is not None
    # 找人类玩家分数
    score = 0; fans = []
    for i, p in enumerate(eng.players):
        s = room.slots.get(i)
        if s and s.name == human_name:
            if is_win and eng.winner == p:
                score = p.score
                fans = eng.fan_details
            elif not is_win:
                rs = getattr(eng, 'ryuukyoku_scores', {})
                rd = getattr(eng, 'ryuukyoku_details', {})
                score = rs.get(p.role.value, {}).get("score", 0) if rs else 0
                fans = rd.get(p.role.value, []) if rd else []
            break
    update_stats(human_name, {
        "score": score, "is_win": is_win and eng.winner is not None and any(
            s and s.name == human_name and eng.winner == p
            for i, (p, s) in enumerate(zip(eng.players, [room.slots.get(i) for i in range(4)]))
        ),
        "fans": [{"name": f.get("name","")} for f in fans],
        "room_id": room.room_id,
        "round_num": eng.round_num,
    })

# === 冒险模式 API ===

def _adv_user(req: Request):
    """从 header/query 取 token, 返回用户名或 None"""
    token = req.headers.get("Authorization","").replace("Bearer ","")
    if not token: token = req.query_params.get("token","")
    return get_user(token)

@app.get("/api/adventure/config")
async def api_adventure_config():
    """返回章节关卡配置(不含玩家进度)"""
    return {"chapters": adv.CHAPTERS}

@app.get("/api/adventure/progress")
async def api_adventure_progress(req: Request):
    user = _adv_user(req)
    if not user: return {"error": "未登录"}
    progress = adv.get_adventure_progress(user) or adv.default_progress()
    return {"progress": progress, "yaku_table": adv.get_yaku_table()}

@app.post("/api/adventure/progress")
async def api_adventure_save(req: Request):
    user = _adv_user(req)
    if not user: return {"error": "未登录"}
    try: body = await req.json()
    except: return {"error": "无效请求"}
    progress = body.get("progress")
    if not isinstance(progress, dict): return {"error": "无效进度"}
    adv.save_adventure_progress(user, progress)
    return {"ok": True}

@app.get("/api/adventure/story")
async def api_adventure_story(req: Request):
    """返回关卡剧情 (战前/中间段/战后对话列表)"""
    level = req.query_params.get("level", "")
    if not level:
        return {"error": "缺少level参数"}
    story = adv.get_story(level)
    return {"level": level, "before": story["before"], "segments": story["segments"], "after": story["after"]}

# === 金币 API ===

@app.get("/api/coins")
async def api_coins_get(req: Request):
    """获取当前用户金币数"""
    user = _adv_user(req)
    if not user: return {"error": "未登录"}
    return {"coins": get_coins(user)}

@app.post("/api/coins")
async def api_coins_add(req: Request):
    """增加/扣减金币: {"delta": 3000}"""
    user = _adv_user(req)
    if not user: return {"error": "未登录"}
    try:
        body = await req.json()
        delta = int(body.get("delta", 0) or 0)
    except Exception:
        return {"error": "无效请求"}
    return {"ok": True, "coins": add_coins(user, delta)}

# === 算番 API ===

@app.post("/api/score")
async def api_score(request: Request):
    """接收算番输入,返回JSON结果"""
    try:
        body = await request.json()
        inp = body.get('input', '')
    except Exception:
        return {"error": "无效请求"}

    if not inp.strip():
        return {"error": "请输入牌例"}

    try:
        from branches.scoring.tester import parse_input
        hand, melds, seat, win_type, extra = parse_input(inp.strip())
    except Exception as e:
        return {"error": f"解析错误: {e}"}

    all_tiles = list(hand)
    for m in melds:
        all_tiles.extend(m.tiles)

    kong_count = sum(1 for m in melds if len(m.tiles) == 4)
    meld_tiles = sum(len(m.tiles) for m in melds)
    win_expected = 14 + kong_count          # 和牌: 14张 + 每杠多1张(碰/吃副露已含在手牌外)
    ryu_expected = 13 + meld_tiles          # 流局: 13张手牌 + 副露全部牌(碰/吃3张, 杠4张)

    if len(all_tiles) == win_expected:
        # 和牌模式 (番种锁跟随单机模式: 冒险专属番种番牌刻/单吊字不计)
        from branches.scoring.scorer import calculate_fan
        candidates = []
        is_tsumo = bool(extra.get('tsumo', False))
        for wt in ("标准和", "七对", "十三幺"):
            try:
                f, d = calculate_fan(hand, melds, win_type=wt, is_self_draw=is_tsumo, extra=extra,
                                     locked_yaku=set(adv.ADVENTURE_ONLY_YAKU), return_details=True)
                if f > 0:
                    candidates.append((f, d, wt))
            except Exception:
                pass
        if not candidates:
            return {"total": -1, "error": "不能组成和牌型"}
        best = max(candidates, key=lambda x: x[0])
        fan, details, wt = best
        return {
            "parse": {"hand": [t.to_shorthand() for t in hand], "hand_count": len(hand),
                      "melds": [f"{m.meld_type}: {' '.join(t.to_shorthand() for t in m.tiles)}" for m in melds],
                      "total": len(all_tiles)},
            "fan": fan, "score": fan * 2, "total": fan, "win_type": wt, "details": details,
            "mode": "自摸" if is_tsumo else "点炮",
        }
    elif len(all_tiles) == ryu_expected:
        # 流局·组合番+听算 模式 (听算默认开启; 番种锁跟随单机模式)
        from branches.scoring.ryuukyoku import calculate_ryuukyoku_full
        res = calculate_ryuukyoku_full(hand, melds, locked_yaku=set(adv.ADVENTURE_ONLY_YAKU))
        return {
            "parse": {"hand": [t.to_shorthand() for t in hand], "hand_count": len(hand),
                      "melds": [f"{m.meld_type}: {' '.join(t.to_shorthand() for t in m.tiles)}" for m in melds],
                      "total": len(all_tiles)},
            "fan": res['fan'], "score": res['score'], "total": res['fan'],
            "win_type": f"流局·{res['method']}", "details": res['details'],
            "method": res['method'], "waiting": res['waiting'],
        }
    else:
        return {"total": -2, "error": f"牌张数错误: 期望{ryu_expected}张(流局)或{win_expected}张(和牌),实际{len(all_tiles)}张"}

# === 论坛 API ===

def _forum_user(req: Request):
    """从 header/query 取 token, 返回用户名或 None (论坛仅 chinkaku 开放)"""
    token = req.headers.get("Authorization","").replace("Bearer ","")
    if not token: token = req.query_params.get("token","")
    user = get_user(token)
    if user != "chinkaku": return None
    return user

@app.get("/api/forum/sections")
async def api_forum_sections(req: Request):
    if not _forum_user(req): return {"error": "无权限"}
    return {"sections": fdb.get_sections()}

@app.get("/api/forum/posts")
async def api_forum_posts(req: Request):
    user = _forum_user(req)
    if not user: return {"error": "无权限"}
    sid = req.query_params.get("section")
    page = int(req.query_params.get("page", 1))
    sid = int(sid) if sid and sid.isdigit() else None
    result = fdb.list_posts(sid, page)
    # 标记当前用户是否已点赞/收藏
    for p in result["posts"]:
        p["liked"] = fdb.get_like_state(p["id"], user) if user else False
        p["favorited"] = fdb.get_favorite_state(p["id"], user) if user else False
    return result

@app.get("/api/forum/post/{post_id}")
async def api_forum_post(post_id: int, req: Request):
    user = _forum_user(req)
    if not user: return {"error": "无权限"}
    data = fdb.get_post(post_id)
    if not data: return {"error": "帖子不存在"}
    data["post"]["liked"] = fdb.get_like_state(post_id, user) if user else False
    data["post"]["favorited"] = fdb.get_favorite_state(post_id, user) if user else False
    data["post"]["can_edit"] = (user == "admin" or (user is not None and user == data["post"]["author"]))
    return data

@app.post("/api/forum/post")
async def api_forum_create(req: Request):
    user = _forum_user(req)
    if not user: return {"error": "请先登录"}
    try: body = await req.json()
    except: return {"error": "无效请求"}
    title = str(body.get("title","")).strip()
    content = str(body.get("content","")).strip()
    section_id = int(body.get("section_id", 1))
    if not title or not content: return {"error": "标题和内容不能为空"}
    pid = fdb.create_post(section_id, user, title, content)
    fdb.add_points(user, 5)  # 发帖 +5 组合积分(预留)
    return {"ok": True, "post_id": pid}

@app.post("/api/forum/reply/{post_id}")
async def api_forum_reply(post_id: int, req: Request):
    user = _forum_user(req)
    if not user: return {"error": "请先登录"}
    try: body = await req.json()
    except: return {"error": "无效请求"}
    content = str(body.get("content","")).strip()
    if not content: return {"error": "内容不能为空"}
    rid = fdb.add_reply(post_id, user, content)
    fdb.add_points(user, 2)  # 回帖 +2 组合积分(预留)
    return {"ok": True, "reply_id": rid}

@app.post("/api/forum/like/{post_id}")
async def api_forum_like(post_id: int, req: Request):
    user = _forum_user(req)
    if not user: return {"error": "请先登录"}
    return {"state": fdb.toggle_like(post_id, user)}

@app.post("/api/forum/favorite/{post_id}")
async def api_forum_favorite(post_id: int, req: Request):
    user = _forum_user(req)
    if not user: return {"error": "请先登录"}
    return {"state": fdb.toggle_favorite(post_id, user)}

@app.put("/api/forum/post/{post_id}")
async def api_forum_update(post_id: int, req: Request):
    user = _forum_user(req)
    if not user: return {"error": "请先登录"}
    data = fdb.get_post(post_id)
    if not data: return {"error": "帖子不存在"}
    if user != "admin" and user != data["post"]["author"]:
        return {"error": "无权限"}
    try: body = await req.json()
    except: return {"error": "无效请求"}
    title = str(body.get("title","")).strip()
    content = str(body.get("content","")).strip()
    if not title or not content: return {"error": "标题和内容不能为空"}
    fdb.update_post(post_id, title, content)
    return {"ok": True}

@app.delete("/api/forum/post/{post_id}")
async def api_forum_delete(post_id: int, req: Request):
    user = _forum_user(req)
    if not user: return {"error": "请先登录"}
    data = fdb.get_post(post_id)
    if not data: return {"error": "帖子不存在"}
    if user != "admin": return {"error": "只有管理员可以删除"}
    fdb.delete_post(post_id)
    return {"ok": True}

@app.get("/api/forum/profile")
async def api_forum_profile(req: Request):
    user = _forum_user(req)
    if not user: return {"error": "未登录"}
    profile = fdb.get_profile(user)
    stats = get_stats(user)
    return {"user": user, "profile": profile, "stats": stats, "favorites": fdb.get_user_favorites(user)}

# === 账号 API ===

@app.post("/api/auth/register")
async def api_register(req: Request):
    try: body = await req.json()
    except: return {"error": "无效请求"}
    token = register(body.get("user","")[:16], body.get("pass",""))
    if not token: return {"error": "用户名已存在或无效"}
    return {"token": token, "user": get_user(token)}

@app.post("/api/auth/login")
async def api_login(req: Request):
    try: body = await req.json()
    except: return {"error": "无效请求"}
    token = login(body.get("user","")[:16], body.get("pass",""))
    if not token: return {"error": "用户名或密码错误"}
    return {"token": token, "user": get_user(token)}

@app.get("/api/auth/me")
async def api_me(req: Request):
    token = req.headers.get("Authorization","").replace("Bearer ","")
    if not token: token = req.query_params.get("token","")
    user = get_user(token)
    if not user: return {"error": "未登录"}
    return {"user": user}

# === 房间 API ===
@app.post("/api/rooms")
async def api_create(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    name = str(body.get("name", "") or "")[:8]
    rid = create_room(name)
    room = get_room(rid)
    # 房主自动占slot 0
    from branches.networking.rooms import ClientSlot as CS
    room.slots[0] = CS(idx=0, name=name, connected=False)
    return {"room_id": rid, "players": room.player_count if room else 0}

@app.get("/api/rooms")
async def api_list():
    return [{"id": rid, "host": r.host_name, "players": r.player_count} for rid, r in rooms.items()]

@app.post("/api/rooms/{room_id}/bot")
async def api_add_bot(room_id: str, req: Request):
    """房主添加机器人"""
    room = get_room(room_id)
    if not room: return {"error": "房间不存在"}
    try: body = await req.json()
    except: body = {}
    user = str(body.get("user", "") or "")
    if not room.is_host(user):
        return {"error": "只有房主可以添加机器人"}
    slot = int(body.get("slot", -1))
    if not room.add_bot(slot):
        return {"error": "添加失败"}
    return {"ok": True, **room.slot_status()}

@app.post("/api/rooms/{room_id}/start")
async def api_start_game(room_id: str, req: Request):
    """房主开始游戏"""
    room = get_room(room_id)
    if not room: return {"error": "房间不存在"}
    try: body = await req.json()
    except: body = {}
    user = str(body.get("user", "") or "")
    if not room.is_host(user):
        return {"error": "只有房主可以开始游戏"}
    if room.player_count < 4:
        return {"error": "需要4名玩家（空位请添加机器人）"}
    if not room.started:
        room.started = True
        for i in range(4):
            slot = room.slots.get(i)
            if slot:
                room.engine.players[i].is_human = not room._is_bot_name(slot.name)
            else:
                room.engine.players[i].is_human = False
        room.engine.start_round()
        room.engine._auto_advance()
    return {"ok": True}

@app.get("/api/rooms/{room_id}")
async def api_room_status(room_id: str):
    """房间状态(等待页轮询)"""
    room = get_room(room_id)
    if not room: return {"error": "房间不存在"}
    ss = room.slot_status()
    return {"slots": ss["slots"], "host_idx": ss["host_idx"], "started": room.started, "player_count": room.player_count}

# WebSocket: 单机模式(无room_id)自动创建私有房间
@app.websocket("/ws")
async def ws_solo(ws: WebSocket):
    rid = create_room("单机")
    room = get_room(rid)
    room.solo_mode = True  # 单机不限鸣牌时间
    room.debug_mode = (ws.query_params.get("debug") == "1")  # 调试模式不计入数据
    # 番牌刻/单吊字 只在冒险模式生效: 正常单机默认锁定 (冒险模式下方覆盖为关卡配置)
    room.engine.locked_yaku = set(adv.ADVENTURE_ONLY_YAKU)
    await ws.accept()
    name = ws.query_params.get("user", "") or "玩家"
    from branches.networking.rooms import ClientSlot as CS
    room.slots[0] = CS(idx=0, name=name, connected=True)
    room.slots[0].ws = ws
    # 补齐3个快速机器人(bot_delay 更快)
    async def _solo_bot_advance():
        steps = 0
        while not room.engine.game_over and steps < 500:
            steps += 1
            # 杠牌后补牌: 处理 _skip_rest (跳过3家,回到杠牌者摸岭上牌)
            if getattr(room.engine, '_skip_rest', False):
                room.engine._auto_advance(stepwise=True)
                continue
            if room.engine.phase == 'DRAW' and room.engine.players[room.engine.current_player_idx].is_human:
                room.engine._auto_advance(stepwise=True)
                continue
            await room.broadcast()
            if room._needs_human_input():
                break
            await asyncio.sleep(0.35)
            room.engine._auto_advance(stepwise=True)
        await room.broadcast()
        if not room.engine.game_over and room._needs_human_input():
            await room._start_timer()
    # 冒险模式: 读取关卡配置, 设置番种锁/番值/起和线
    adv_level = ws.query_params.get("adventure", "")
    if adv_level:
        room.debug_mode = True  # 冒险模式也不计入数据
        progress = adv.get_adventure_progress(name) or adv.default_progress()
        ch, lv = adv.get_level(adv_level)
        fan_map, unlocked = adv.get_level_effective_config(adv_level, progress)
        if fan_map is not None:
            room.engine.fan_map = fan_map
            room.engine.locked_yaku = adv.compute_locked_yaku(unlocked, level_id=adv_level,
                                                              scored_kinds=(lv or {}).get("scored_kinds"))
            room.engine.min_fan = 1  # 冒险模式无起和限制, 但至少1番
        # 关卡指定手牌(复用调试) + 关卡目标/保证手牌/局数
        if lv:
            fights = lv.get("fights") or []
            f0 = fights[0] if fights else {}   # 多段关卡先打第一段(1-4-1)
            room.engine.adv_fight = 0
            room.engine.adventure_goal = lv.get("win_condition")
            room.engine.adventure_rounds = lv.get("rounds")
            room.engine.guaranteed_pair = f0.get("guaranteed_pair", lv.get("guaranteed_pair"))
            room.engine.guaranteed_hand = f0.get("guaranteed_hand", lv.get("guaranteed_hand"))
            room.engine.no_ryuukyoku_score = lv.get("ryuukyoku_scoring", True) is False
            room.engine.adventure_boss = lv.get("boss")
            # 对手配置: 多对手(1-5 opponents)或单对手(1-4 每段 opponent)
            _f_cfg = f0 or lv
            _opps = lv.get("opponents") or ([_f_cfg.get("opponent")] if _f_cfg.get("opponent") else [])
            room.engine.adventure_opponents = _opps
            room.engine.adventure_opponent = _opps[0] if _opps else None
            room.engine.opponent_deal_bias_map = {int(o.get("seat", 2)): int(o.get("deal_bias", 0)) for o in _opps if o.get("deal_bias")}
            room.engine.adv_no_ron_turn = int(lv.get("no_ron_turn", 0) or 0)
            room.engine.adv_wins = 0
            if lv.get("hand"):
                try:
                    from branches.scoring.tester import parse_remaining_tiles
                    tiles = parse_remaining_tiles(lv["hand"])
                    shs = [t.to_shorthand() for t in tiles]
                    if len(shs) == 13:
                        room.engine.debug_hand = shs
                except Exception:
                    pass
    # 调试模式: 从 query 参数读取指定手牌(开局前设置)
    elif room.debug_mode:
        hand_str = ws.query_params.get("hand", "")
        if hand_str:
            try:
                from branches.scoring.tester import parse_remaining_tiles
                tiles = parse_remaining_tiles(hand_str)
                shs = [t.to_shorthand() for t in tiles]
                if len(shs) == 13:
                    room.engine.debug_hand = shs
            except Exception:
                pass
    # 启动游戏 (冒险模式: 连接后不开局, 先播战前剧情, fight后才真正开局)
    room.started = True
    for i in range(4):
        if i == 0:
            room.engine.players[i].is_human = True
        else:
            # 自动加机器人
            room.add_bot(i)
            room.engine.players[i].is_human = False
    # 关卡级机器人命名 (如 1-3: 上下家=摸打机器人, 对家=对手)
    if adv_level and lv and lv.get("bot_names"):
        for _i, _nm in lv["bot_names"].items():
            _slot = room.slots.get(int(_i))
            if _slot:
                _slot.name = _nm

    adv_round_started = False
    if adv_level:
        story = adv.get_story(adv_level)
        multi = bool(lv and lv.get("fights"))   # 多段战斗关卡(如1-4)
        stage = 0
        if multi:
            stage = int((progress.get("adv_stage") or {}).get(adv_level, 0))
        seen = (adv_level in (progress.get("story_seen") or []))
        print(f"[Adventure] {name} 连接关卡 {adv_level}, 战前{len(story['before'])}句/中间{len(story.get('segments') or [])}段/战后{len(story['after'])}句, 多段={multi}, 已体验段数={stage}, 发送 adventure_ready")
        await ws.send_text(json.dumps({
            "type": "adventure_ready",
            "level": adv_level,
            "story": story,
            "rounds": (lv or {}).get("rounds", 1),
            "goal": (lv or {}).get("win_condition"),
            "seen": seen,
            "multi": multi,
            "stage": stage,
        }, ensure_ascii=False))
    else:
        adv_round_started = True
        room.engine.start_round(); room.engine._auto_advance()
        await room.broadcast()
        if not room.engine.game_over and room._needs_human_input():
            await room._start_timer()
        else:
            await _solo_bot_advance()
    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            act = msg.get("action", "")
            prm = msg.get("params", {})
            try:
                if act == "set_debug_hand":
                    from branches.scoring.tester import parse_remaining_tiles
                    hand_str = str(prm.get("hand", "")).strip()
                    if hand_str:
                        tiles = parse_remaining_tiles(hand_str)
                        shs = [t.to_shorthand() for t in tiles]
                        from collections import Counter
                        if len(shs) != 13:
                            await ws.send_text(json.dumps({"type": "msg", "msg": f"需要13张牌, 当前{len(shs)}张"}, ensure_ascii=False))
                        elif any(c > 4 for c in Counter(shs).values()):
                            await ws.send_text(json.dumps({"type": "msg", "msg": "每种牌最多4张"}, ensure_ascii=False))
                        else:
                            room.engine.debug_hand = shs
                            await ws.send_text(json.dumps({"type": "msg", "msg": f"调试手牌已设置: {hand_str}"}, ensure_ascii=False))
                    else:
                        room.engine.debug_hand = None
                        await ws.send_text(json.dumps({"type": "msg", "msg": "调试手牌已清除"}, ensure_ascii=False))
                elif act == "next_round" and room.engine.game_over:
                    room.engine.settle_round()
                    if not room.debug_mode:
                        _record_round(room, name)  # 调试模式不计入数据
                    room.engine.start_round()
                    room.engine._auto_advance()
                    await room.broadcast()
                    if not room.engine.game_over and room._needs_human_input():
                        await room._start_timer()
                    else:
                        await _solo_bot_advance()
                elif act == "adventure_start" and adv_level and (not adv_round_started or int(prm.get("fight", 0) or 0) == 1):
                    # 战前剧情播放完毕(或选择跳过), fight 后真正开局
                    fight = int(prm.get("fight", 0) or 0)
                    fights = (lv or {}).get("fights") or []
                    if fights and fight == 1 and room.engine.adv_fight == 1 and room.engine.round_num > 0:
                        pass  # 已在第二段进行中: 忽略重复请求
                    elif fights and fight == 1:
                        # ---- 进入第二段(1-4-2): 记录经历过第二个fight节点 + 中间解锁番种(都茂教学) ----
                        stage_map = progress.get("adv_stage") or {}
                        stage_map[adv_level] = max(stage_map.get(adv_level, 0), 2)
                        progress["adv_stage"] = stage_map
                        mid = (lv or {}).get("mid_unlock_yaku") or {}
                        if mid:
                            ul = progress.get("unlocked_yaku") or []
                            for nm in mid:
                                if nm not in ul:
                                    ul.append(nm)
                            progress["unlocked_yaku"] = ul
                            fo = progress.get("fan_overrides") or {}
                            for nm, fan in mid.items():
                                fo[nm] = fan
                            progress["fan_overrides"] = fo
                        adv.save_adventure_progress(name, progress)
                        # 应用第二段配置(保底手牌/对手放水等)
                        f1 = fights[1] if len(fights) > 1 else {}
                        room.engine.adv_fight = 1
                        room.engine.adventure_goal = f1.get("win_condition", (lv or {}).get("win_condition"))
                        room.engine.adventure_rounds = f1.get("rounds", (lv or {}).get("rounds"))
                        room.engine.guaranteed_pair = f1.get("guaranteed_pair", (lv or {}).get("guaranteed_pair"))
                        room.engine.guaranteed_hand = f1.get("guaranteed_hand", (lv or {}).get("guaranteed_hand"))
                        _f1_cfg = f1 or lv
                        _opps1 = (lv or {}).get("opponents") or ([_f1_cfg.get("opponent")] if _f1_cfg.get("opponent") else [])
                        room.engine.adventure_opponents = _opps1
                        room.engine.adventure_opponent = _opps1[0] if _opps1 else None
                        room.engine.opponent_deal_bias_map = {int(o.get("seat", 2)): int(o.get("deal_bias", 0)) for o in _opps1 if o.get("deal_bias")}
                        room.engine.adv_no_ron_turn = int((lv or {}).get("no_ron_turn", 0) or 0)
                        room.engine.adv_wins = 0
                        room.engine.accumulated_scores = {p.role: 0 for p in room.engine.players}
                        room.engine.adv_block_failed = False
                        room.engine.round_num = 0   # 第二段从第1局重新计(避免继续第一段的局数)
                        # 重算番值/番种锁(混全带幺已解锁)
                        fan_map, unlocked = adv.get_level_effective_config(adv_level, progress)
                        if fan_map is not None:
                            room.engine.fan_map = fan_map
                            room.engine.locked_yaku = adv.compute_locked_yaku(unlocked, level_id=adv_level,
                                                                              scored_kinds=(lv or {}).get("scored_kinds"))
                        print(f"[Adventure] {name} 进入第二段(1-4-2): 混全带幺解锁, 对手放水{room.engine.adventure_opponent}")
                        adv_round_started = True
                    else:
                        # ---- 第一段(或单段关卡) ----
                        adv_round_started = True
                        if fights:
                            # 多段关卡: 记录经历过第一个fight节点
                            stage_map = progress.get("adv_stage") or {}
                            stage_map[adv_level] = max(stage_map.get(adv_level, 0), 1)
                            progress["adv_stage"] = stage_map
                        else:
                            # 记录战前剧情已看过(下次可跳过)
                            seen_list = progress.get("story_seen") or []
                            if adv_level not in seen_list:
                                seen_list.append(adv_level)
                                progress["story_seen"] = seen_list
                        adv.save_adventure_progress(name, progress)
                    # 断线重连场景: 局已开过则仅同步状态, 不开新局
                    if room.engine.round_num == 0 or (fights and fight == 1):
                        room.engine.start_round(); room.engine._auto_advance()
                    await room.broadcast()
                    if not room.engine.game_over and room._needs_human_input():
                        await room._start_timer()
                    else:
                        await _solo_bot_advance()
                else:
                    room.engine.do_action(act, stepwise=True, auto_advance=False, **prm)
                    room._cancel_timer()
                    await _solo_bot_advance()
            except Exception as e:
                print(f"[Solo] 动作异常 act={act}: {e}")
                import traceback; traceback.print_exc()
                await room.broadcast()
    except WebSocketDisconnect:
        pass

# WebSocket: 联机模式(有room_id)
@app.websocket("/ws/{room_id}")
async def ws_room(ws: WebSocket, room_id: str):
    room = get_room(room_id)
    if not room:
        await ws.accept(); await ws.send_text(json.dumps({"type": "error", "msg": "房间不存在"})); await ws.close(); return
    await ws.accept()
    # 从URL参数读取用户名(login时存入localStorage, 前端传过来的)
    name = ws.query_params.get("user", "") or ("玩家" + str(len(room.slots) + 1))
    idx = room.join(ws, name)
    if idx < 0:
        await ws.send_text(json.dumps({"type": "error", "msg": "房间已满"})); await ws.close(); return
    try:
        # 等待游戏正式开始(房主通过 /api/rooms/{id}/start 触发)
        if not room.started:
            for _ in range(120):
                if room.started: break
                await asyncio.sleep(1)
            if not room.started:
                await ws.send_text(json.dumps({"type": "error", "msg": "等待超时"})); return
        # 游戏已开始
        if not room.engine.game_over:
            await room._start_timer()
        await room.broadcast()
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            act = msg.get("action", "")
            prm = msg.get("params", {})
            if act == "next_round" and room.engine.game_over:
                room.engine.settle_round()
                for i, sl in room.slots.items():
                    if sl.name and not room._is_bot_name(sl.name):
                        _record_round(room, sl.name)
                room.engine.start_round()
                room.engine._auto_advance()
                await room.broadcast()
                if not room.engine.game_over:
                    await room._start_timer()
            else:
                await room.handle_action(ws, act, prm)
    except WebSocketDisconnect:
        room.disconnect(ws)
    except Exception as e:
        print(f"[WS {room_id}] Error: {e}")
        try: room.disconnect(ws)
        except: pass

app.mount("/static", StaticFiles(directory=STATIC), name="static")

if __name__ == "__main__":
    import uvicorn; uvicorn.run(app, host="0.0.0.0", port=8766)
