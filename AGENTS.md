# 组合麻将 (Combination Mahjong)

## 项目概述

基于 FastAPI + WebSocket 的四人麻将对战游戏。当前**单机模式可用**（1 真人 + 3 机器人），联机模式仍在开发中。

## 目录结构

```
Q:/openai/
├── game_engine.py          # 纯逻辑层：牌墙、鸣牌、计番、结算
├── branches/networking/
│   ├── server.py           # FastAPI 服务器（API + WebSocket + 单机端点）
│   ├── rooms.py            # 房间管理（槽位、房主、定时器、bot推进）
│   ├── auth.py             # 账号系统（JSON 文件持久化）
│   └── users.json          # 用户数据
└── static/
    ├── index.html          # 首页（单机可用，联机已锁定）
    ├── lobby.html          # 大厅（保留供调试）
    ├── wait.html           # 等待室（保留供调试）
    ├── game.html           # 游戏主界面（牌桌 + 七段数码管计时器）
    ├── auth.html           # 登录/注册页
    ├── main.js             # 游戏前端逻辑（渲染、计时器、动画、牌河标红）
    ├── style.css           # 牌桌样式
    ├── animation-test.html # 打牌动画独立测试页
    └── tiles/              # 牌面图片素材
```

## 核心架构

- **后端**：Python FastAPI，端口 8766
- **单机模式**：`/ws` 自动创建私有房间 + 3 机器人
- **联机模式**：REST API + WebSocket `/ws/{room_id}`
- **游戏引擎**：`game_engine.py`，`do_action(auto_advance=False)` 不自动推进，交给 Room 统一控制节奏
- **逐帧 bot 推进**：`_auto_advance(stepwise=True)` 每处理一个 bot 即返回，Room 循环 广播→延时→推进
- **账号**：注册/登录，token 持久化，浏览器 `localStorage`
- **机器人**：名字以 `伯特` 开头，`is_human=False`
- **房主权限**：创建者自动房主（槽 0，👑），可开始游戏/加 bot，离开自动转移

## 当前功能

- Bot 逐帧延迟（单机 0.35s / 联机 1s）
- 七段数码管计时器，客户端 200ms 自驱
- 牌河弃牌浅红高亮（联机模式）
- 两段式打牌动画（见 v0.2.6）
- 牌河弹入动画
- 主界面最多重连 5 次

---

## 版本历史

### v0.2.7 — 摸牌空档 & 起和限制

- **摸牌空档**：`Player.drawn_tile` 服务端追踪刚摸的牌，手牌最右留 12px 空档（牌宽 25%）
- **理牌**：弃牌后状态更新自然重排，摸牌归位、新摸牌留空档
- **飞行动画**：`act("discard")` 延迟到动画 `onfinish`，动画期间 `FLY_ID` 防连点
- **飞行时长**：两阶段各 113ms（总计 226ms），比 v0.2.6 快 50%
- **起和限制**：`MIN_FAN=4`，不足 4 番不显示"和"/"自摸"按钮，吃碰杠不受影响
- `_check_win_fan()` 快速算番，不写游戏状态
- `tile()` 设 `dataset.sh`，修复元素查找失败
- 移除 hand `.tile` CSS transition，消除 DOM 重排闪烁

### v0.2.6 — 打牌动画

- **两段式打牌动画**：阶段1 (150ms 线性) 手牌原地缩至牌河大小；阶段2 (150ms 线性) 三帧飞移→过冲→回弹
- 过冲偏移：右偏 ~4px / 下偏 ~8px，±15% 随机抖动
- 动画开始时原牌立即隐藏，牌画全程跟随（`getComputedStyle` 兜底）
- 牌河弹入触发条件修正：只有 `last_discard_by !== LAST_POP_BY` 时才弹入，防止逐帧广播反复闪烁
- 新增 `animation-test.html` 独立测试页

### v0.2.5 — 动作栏 & 牌河修正

- CLAIM_PK 无鸣牌选项时不再返回空的 `[{type:'pass'}]`，消去错误"过"按钮
- `flyDiscard` 只在 DISCARD 阶段触发
- 过牌/鸣牌不再触发错误的牌河闪烁
- 牌河弹入目标改为玩家对应牌河而非盘面中央

### v0.2.4 — 逐帧 bot & 单机模式

- `_auto_advance(stepwise=True)`：bot 逐帧推进，每步广播+延时
- `_needs_human_input()`：精准判断人类决策时机（DRAW 秒过）
- 新增 `/ws` 单机端点：自动房间 + 3 bot，bot 延迟 0.35s
- `do_action(auto_advance=False)`：推进权完全交 bot 循环
- 左右座位外推 180px，牌河 4 排不遮挡信息

### v0.2.3 — UI 锁定 & 七段管

- 首页联机按钮锁定 🔒（灰色不可点击）
- 七段数码管 SVG 计时器，客户端 `setInterval` 自驱
- 牌河弃牌浅红高亮，下一张自动取消
- 中央弃牌区联机模式隐藏

### v0.2.1 — 房主系统 & Bug 修复

- 房主权限：创建者房主，离开自动转移，👑 标识
- 房间 4 人限制（可加 bot 补齐）
- Bug 修复：
  - 机器人座位被新玩家抢占 → `join()` 跳过 bot 槽
  - 房主页面跳转后无法操作 → `join()` 匹配断线槽 + 按名强回收
  - 局内无法分辨玩家 → 昵称标签动态渲染
  - 双重定时器弃牌 → `_start_timer()` 首行 `_cancel_timer()`

### v0.2.0 — 初始联机版本

- FastAPI 服务器 + WebSocket
- REST API：房间 CRUD、添加机器人、开始游戏
- 账号系统：注册/登录/token 持久化
- 游戏引擎：牌墙、鸣牌、计番、结算

---

## 待完成 — 联机模式

> ⚠️ 联机模式存在竞态条件，暂不可用。首页按钮已锁定。

- **WS 竞态**：新 WS 连接可能比旧 WS 断开先到达，兜底按名回收仍不稳定
- **状态同步**：断线重连丢失中间状态
- **建议**：等待页改用轮询，或改为单页不跳转
- **建议**：加房间级消息队列补发
