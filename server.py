# -*- coding: utf-8 -*-
"""麻将网页版服务器 - FastAPI + WebSocket"""
import json
import asyncio
import os
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from game_engine import GameEngine

# 确保 cord 文件夹存在
os.makedirs('cord', exist_ok=True)

app = FastAPI()

# 游戏会话
class GameSession:
    def __init__(self):
        self.engine = GameEngine(num_humans=1)
        self.websocket = None
        self.started = False

    async def send_state(self):
        """发送完整游戏状态到客户端"""
        if self.websocket:
            state = self.engine.get_state()
            # 附加人类玩家手牌
            state['human_hand'] = self.engine.get_human_hand(0)
            await self.websocket.send_text(json.dumps({
                'type': 'state',
                'data': state
            }, ensure_ascii=False))

    def process_ai_turns(self):
        """推进 AI 回合直到需要人类输入或游戏结束"""
        self.engine._auto_advance()


def _save_logs(engine):
    """保存本盘日志到 cord 文件夹"""
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    fname = f'cord/round_{engine.round_num:02d}_{ts}.txt'
    with open(fname, 'w', encoding='utf-8') as f:
        f.write(f'盘 #{engine.round_num}\n')
        f.write(f'{"="*40}\n')
        winner = engine.winner.role.value if engine.winner else '流局'
        f.write(f'结果: {winner}')
        if engine.winner:
            f.write(f' ({engine.win_type} 得{engine.winner.score}分)')
        f.write('\n\n日志:\n')
        for log in engine.logs:
            f.write(f'  {log}\n')
        f.write(f'\n累计分数:\n')
        for role, score in engine.accumulated_scores.items():
            f.write(f'  {role.value}: {score}\n')

session = GameSession()

# ==================== WebSocket ====================

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    global session
    await ws.accept()
    session.websocket = ws
    session.engine = GameEngine(num_humans=1)

    # 开始第一盘
    session.engine.start_round()
    session.engine._auto_advance()
    await session.send_state()

    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            action_type = msg.get('action', '')
            params = msg.get('params', {})

            # 下一局：在游戏结束后手动触发
            if action_type == 'next_round':
                if session.engine.game_over:
                    if not getattr(session.engine, '_settled', False):
                        session.engine.settle_round()
                        _save_logs(session.engine)
                        session.engine._settled = True
                    session.engine.start_round()
                    session.engine._auto_advance()
                    session.engine._settled = False
                await session.send_state()
                continue

            # 执行操作
            session.engine.do_action(action_type, **params)

            # 如果游戏结束，结算并停住
            if session.engine.game_over:
                if not getattr(session.engine, '_settled', False):
                    session.engine.settle_round()
                    _save_logs(session.engine)
                    session.engine._settled = True

            # 发送新状态
            await session.send_state()

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"WebSocket error: {e}")
        try:
            await ws.close()
        except:
            pass

# ==================== 静态文件 ====================

@app.get("/")
async def index():
    return FileResponse("static/index.html")

@app.get("/game")
async def game():
    return FileResponse("static/game.html")

@app.get("/tester")
async def tester():
    return FileResponse("static/tester.html")

app.mount("/static", StaticFiles(directory="static"), name="static")

# ==================== 算番 API ====================

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
        from branches.scoring.scorer import calculate_fan
        hand, melds, seat, win_type, extra = parse_input(inp.strip())
    except Exception as e:
        return {"error": f"解析错误: {e}"}

    all_tiles = list(hand)
    for m in melds:
        all_tiles.extend(m.tiles)

    kong_count = sum(1 for m in melds if len(m.tiles) == 4)
    win_expected = 14 + kong_count
    ryu_expected = 13 + kong_count

    if len(all_tiles) == win_expected:
        # 和牌模式
        from branches.scoring.scorer import calculate_fan
        candidates = []
        for wt in ("标准和", "七对", "十三幺"):
            try:
                f, d = calculate_fan(hand, melds, win_type=wt, return_details=True)
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
        }
    elif len(all_tiles) == ryu_expected:
        # 流局·组合番模式
        from branches.scoring.ryuukyoku import calculate_ryuukyoku
        fan, details = calculate_ryuukyoku(hand, melds)
        return {
            "parse": {"hand": [t.to_shorthand() for t in hand], "hand_count": len(hand),
                      "melds": [f"{m.meld_type}: {' '.join(t.to_shorthand() for t in m.tiles)}" for m in melds],
                      "total": len(all_tiles)},
            "fan": fan, "score": fan * 2, "total": fan,
            "win_type": "流局·组合番", "details": details,
        }
    else:
        return {"total": -2, "error": f"牌张数错误: 期望{ryu_expected}张(流局)或{win_expected}张(和牌),实际{len(all_tiles)}张"}

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8766)
