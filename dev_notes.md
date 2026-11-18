# dev_notes.md — 组合麻将 部署架构说明（< 100 行）

## 1. 技术栈与进程模型

- **单进程** Python 3 + **FastAPI + uvicorn**（部署时替掉原 aiohttp 占位应用，入口仍叫 `server.py`）。
- 并发模型：**asyncio 单线程**；每桌对局是一个协程推进（`ActiveSession`），无线程池、无多 worker。
- 端口：`PORT` 环境变量（部署 = **8100**；本地默认 8766）；`/api/health` 恒返回 `{"ok":true}`。
- 启动：`/home/ubuntu/comb/app/server.py` → `uvicorn.run(app, port=$PORT)`；systemd `comb.service` 拉起，
  `Environment` 注入 `PORT=8100`、`CMJ_DATA_DIR=/home/ubuntu/comb/data`。

## 2. 分层

```
game_engine.py          纯逻辑引擎（牌墙/鸣牌/计番/结算/累计分，无 I/O）
branches/scoring/       算番模块（yaku/scorer/ryuukyoku/hand_decomp/tester）
branches/networking/
  server.py             FastAPI 路由 + WebSocket（单机 /ws、联机 /ws/lobby /ws/game /ws/spectate）
  hub.py                GameHub：按 player_id 身份路由（socket 只是通道）、会话表、GC
  session.py            PendingSession（等待房）/ ActiveSession（对局：stage 幂等、三档计时、快照、观战、回放）
  protocol.py           联机信封协议 {version,type,payload,requestId} + 错误码 + 路由表
  auth.py               账号（users.json + player_seq.txt 递增水位线）
  adventure.py          冒险模式关卡配置
  replay.py             回放（replays.db，保留上限 1000 场）
static/                 前端（index/game/adventure/lobby/replay/... + main.js + mp.js）
story/                  冒险剧情文本
```

## 3. 状态机（引擎）

`IDLE → DRAW → SELF_MELD → DISCARD → CLAIM_PK → CLAIM_CHOW → (下一家 DRAW) … → GAME_OVER`

- 每局 `start_round()` 洗牌发牌；`settle_round()` 只推进庄家；`_accumulate_scores()` 在局终累加累计分。
- 人类决策点：`SELF_MELD`（自摸/暗杠/加杠/跳过）、`DISCARD`（出牌）、`CLAIM_PK`（和/碰/杠/过）、
  `CLAIM_CHOW`（吃/过）。其余全部由 `_auto_advance(stepwise=True)` 自动推进。

## 4. 联机关键机制（照搬 mmcr14.online 的架构）

- **身份路由**：`hub.connections[player_id] = ws`，发消息只认人；新连接自动顶掉旧连接（根治旧槽位竞态）。
- **stage_counter 幂等**：每次推进自增，输入带阶段号，过期输入丢弃回 `stale_input`。
- **三档计时**：本人回合 7s / 鸣牌 4s / 兜底 12s；`set_timer(delay, stage, cb)` 到期先校验阶段号，不匹配即 no-op；
  超时与断线超 60s 均自动代打。
- **全量快照**：`session.snapshot`（含 viewer.hand / available_actions / timer），重连即恢复。
- **可见性**：可用操作只发给当前决策者；别人刚摸的牌不下发；观战者看不到任何手牌。
- **安全网**：90s 无进展的对局强制收尾；空等待房 15s 回收；已结束对局 120s 后移除。

## 5. 数据文件（`CMJ_DATA_DIR`，部署 = /home/ubuntu/comb/data）

| 文件 | 内容 | 增长控制 |
|---|---|---|
| users.json | 账号、金币、冒险进度、统计 | 小（KB 级） |
| player_seq.txt | player_id 递增水位线（不复用） | 常量 |
| forum.db | 论坛 | 小 |
| replays.db | 联机回放（每场 JSON blob） | 保留最近 **1000** 场，超出自动删最旧 |

数据目录体积上限目标 ≤ 5 GB（按当前单场回放 ~几十 KB 估算，1000 场 ≈ 数十 MB，远低于上限）。

## 6. 日志与排障

- 日志：`/home/ubuntu/comb/logs/app.log`（logrotate 每日切分保留 7 天）；正常对局不打 DEBUG。
- 排障：`systemctl status comb.service`、`journalctl -u comb.service -n 50`、`curl localhost:8100/api/health`。

## 7. 自测

- 本地回归：`test_online.py`（联机 53 项）、`test_ws_smoke.py`（真实 WebSocket 9 项/38 子断言）、
  `test_1_4.py` / `test_1_5.py` / `test_ankou.py`（规则回归）。
- 部署后：`/api/health` 200、打开 `http://49.233.87.144:8100/` 能开一局、连续 10 局无重启/无内存增长。
