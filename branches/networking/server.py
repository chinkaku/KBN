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
from branches.networking.auth import register, login, logout, get_user, get_stats, update_stats
from branches.networking import forum_db as fdb

app = FastAPI()
STATIC = os.path.join(_BASE, "static")

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

@app.get("/tester")
async def test(): return FileResponse(os.path.join(STATIC, "tester.html"))

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
    await ws.accept()
    name = ws.query_params.get("user", "") or "玩家"
    from branches.networking.rooms import ClientSlot as CS
    room.slots[0] = CS(idx=0, name=name, connected=True)
    room.slots[0].ws = ws
    # 补齐3个快速机器人(bot_delay 更快)
    async def _solo_bot_advance():
        while not room.engine.game_over:
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
    # 启动游戏
    room.started = True
    for i in range(4):
        if i == 0:
            room.engine.players[i].is_human = True
        else:
            # 自动加机器人
            room.add_bot(i)
            room.engine.players[i].is_human = False
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
            if act == "next_round" and room.engine.game_over:
                room.engine.settle_round()
                _record_round(room, name)
                room.engine.start_round()
                room.engine._auto_advance()
                await room.broadcast()
                if not room.engine.game_over and room._needs_human_input():
                    await room._start_timer()
                else:
                    await _solo_bot_advance()
            else:
                room.engine.do_action(act, stepwise=True, auto_advance=False, **prm)
                room._cancel_timer()
                await _solo_bot_advance()
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
