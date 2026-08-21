# 组合麻将 (Combination Mahjong)

## 项目概述

基于 FastAPI + WebSocket 的四人麻将对战游戏。当前版本 **beta 0.0.1**：单机模式（1 真人 + 3 机器人）、冒险模式（章节/剧情/番种解锁）与联机对战均可用。含账号系统、数据统计、论坛（仅 chinkaku 开放）。

## 目录结构

```
Q:/openai/
├── game_engine.py          # 纯逻辑层：牌墙、鸣牌、计番、结算、累计分
├── branches/
│   ├── networking/
│   │   ├── server.py       # FastAPI 服务器（API + WebSocket + 单机端点 + 论坛/统计）
│   │   ├── rooms.py        # 房间管理（槽位、房主、定时器、bot推进）
│   │   ├── auth.py         # 账号系统（JSON 文件持久化 + 统计）
│   │   ├── forum_db.py     # 论坛数据库（SQLite）
│   │   ├── forum.db        # 论坛数据（gitignore）
│   │   └── users.json      # 用户数据（gitignore）
│   └── scoring/            # 算番模块（scorer/yaku/ryuukyoku/hand_decomp）
└── static/
    ├── index.html          # 首页（单机可用，联机已锁定）
    ├── game.html           # 游戏主界面（牌桌 + 七段数码管计时器）
    ├── lobby.html          # 大厅（保留供调试）
    ├── wait.html           # 等待室（保留供调试）
    ├── auth.html           # 登录/注册页
    ├── stats.html          # 个人数据统计
    ├── global-stats.html   # 全局统计（仅 chinkaku）
    ├── forum.html          # 论坛（仅 chinkaku）
    ├── profile.html        # 个人主页
    ├── fans.html           # 番种表
    ├── tester.html         # 算番测试
    ├── animation-test.html # 打牌动画独立测试页
    ├── main.js             # 游戏前端逻辑（渲染、计时器、动画、副露横置）
    ├── style.css           # 牌桌样式
    └── tiles/              # 牌面图片素材
```

## 核心架构

- **后端**：Python FastAPI，端口 8766
- **单机模式**：`/ws` 自动创建私有房间 + 3 机器人（不限时）
- **联机模式**：REST API + WebSocket `/ws/{room_id}`
- **游戏引擎**：`game_engine.py`，`do_action(auto_advance=False)` 不自动推进，交给 Room 统一控制节奏
- **逐帧 bot 推进**：`_auto_advance(stepwise=True)` 每处理一个 bot 即返回，Room 循环 广播→延时→推进
- **账号**：注册/登录，token 持久化，浏览器 `localStorage`
- **机器人**：名字以 `伯特` 开头，`is_human=False`
- **房主权限**：创建者自动房主（槽 0，👑），可开始游戏/加 bot，离开自动转移
- **累计分**：`_accumulate_scores()` 在游戏结束瞬间累加，跨盘累计到退出

## 当前功能

- Bot 逐帧延迟（单机 0.35s / 联机 1s）
- 七段数码管计时器，客户端 200ms 自驱
- 牌河弃牌浅红高亮（联机模式）
- 两段式打牌动画
- 副露区横置牌（吃/碰/明杠/暗杠/加杠）
- 数据统计（个人 + 全局）
- 论坛（发帖/回帖/点赞/收藏）
- 番种表 + 算番测试
- 主界面最多重连 5 次

---

## 版本历史

> **版本阶段约定**：alpha → **beta** → rc → 正式版（依次递增）。beta 在 alpha **之后**，代表进入公开测试阶段。命名格式 `vX.Y.Z-阶段`（如 `v0.0.1-beta`）；页面版本号同步显示当前阶段。

### v0.0.1-beta — 进行中 (关卡1-2 番种规格)

- **新番种·番牌刻**（组合番/字刻类，1番）：和牌中含至少一个 中发白 或 东 的刻子（南西北不算）。类 `番牌刻(Yaku)`，group=HONOR_TRIP，判定 `meld_is_pung` 且 `rank in (0,4,5,6)`
- **新番种·单吊字**（特殊番/听牌类·新类，1番）：听单吊某一张字牌而和牌，即和牌张为字牌且落在雀头。类 `单吊字(Yaku)`，group=**TENPAI（听牌类，新 YakuGroup）**，check 需 `extra['win_tile']`（和牌张）
- **和牌张追踪**：`GameEngine` 新增 `_ron_tile`（荣和牌，开局重置）；`_calc_score` 以 `win_tile = drawn_tile(自摸) / _ron_tile(荣和)` 传入 `extra`；`_check_win_fan(extra=...)` 透传，快速算番与结算共用同一和牌张
- **章节计分策略**：第一章(1-X) 组合番与听牌类**都不计分**，只有和牌类计分；组合/听牌算分在**第二章**解锁。实现于 `adventure.py`：`YAKU_KIND`（番种→和牌/组合/听牌，未列出默认组合）+ `CHAPTER_SCORED_KINDS`（第1章={和牌}，第2章={和牌,组合,听牌}）；`compute_locked_yaku(unlocked, level_id)` 按章过滤，已解锁但该章不计分的大类仍进锁定集合
- **冒险专属番种**：`番牌刻`/`单吊字` **只在冒险模式生效**，正常单机不启用。`adventure.py` 定义 `ADVENTURE_ONLY_YAKU={"番牌刻","单吊字"}`；`server.py` 单机 `/ws` 开局前对非冒险模式注入 `engine.locked_yaku=set(ADVENTURE_ONLY_YAKU)`（冒险模式被关卡配置覆盖）
- **同组同番优先更具体番种**：`番牌刻`(字刻类1番) 是 `字刻`(字刻类1番) 的子集，group_best 同组取最高番平手时旧实现保留先注册的 `字刻`，导致 `番牌刻` 永远不进 `fan_details`（冒险 win_yaku 目标检测会失败）。`scorer.py` 平手时优先 `prefer_on_tie=True` 的番种（`番牌刻` 已标记），其余同组平手番种不受影响
- 关卡1-1 已把 `reward_yaku: ["番牌刻", "单吊字"]` 写进配置；**1-2 剧情与过关条件待用户提供**，暂不建关

### v0.0.1-beta — 首个公开测试版（冒险关卡1-1：五门齐·入门）

- **第一关获胜条件**：3 局内和出（必须实际和牌，听牌/流局不算）至少 1 把五门齐；关卡配置 `win_condition: {type:win_yaku, yaku:五门齐}`
- **起始手牌保证**：玩家(0) 起始 13 张必含一对字牌（其余随机），关卡配置 `guaranteed_pair:'honour'`，引擎 `_deal_normal` 先抽对子再发牌
- **多局流程**：`adventure_rounds`（关卡局数）注入引擎并随状态下发；局末未达成目标且有剩余局→"再来一局"发 `next_round`；打满局数未达成→"你输了"
- **目标检测**：`GameEngine.check_goal_met()`（`adv_goal_met` 随状态下发），判定玩家(0) 和出且 `fan_details` 含目标番种
- **战前剧情跳过**：进度新增 `story_seen`（看过战前剧情的关卡列表）；`adventure_ready` 带 `seen` 标记，已看过则弹「跳过/重看」，跳过→直接播获胜条件一句后开局
- **死锁修复**：`_has_any_claim` 的荣和判定与 `get_available_actions` 对齐（补 `_check_win_fan >= min_fan`），避免"无有效操作却被要求输入"的卡死（如九莲宝灯被锁番时）
- 剧情存于 `story/<关卡id>.txt`（`story_file` 可指定其它文件名）；格式「角色 内容」，无空格继承角色，`fight` 分界前=战前/后=战后
- 解析器 `branches/networking/story.py`；WS 冒险模式连接后先发 `adventure_ready`（含 story），播完战前剧情发 `adventure_start` 才开局
- 战后：达成目标→播战后剧情+标记完成(completed_levels/推进current_level/reward_yaku解锁)；未达成且局数已满→"你输了，再接再厉吧！"

### v0.6.0 — 冒险模式 & 联机解锁 & 听算

- **冒险模式**：`/adventure` 章节关卡页 + mini 番种图鉴（未解锁黑框🔒遮挡），进度跟随账号（users.json）
- 番种锁：未解锁番种不计分；番值动态可调（`fan_map`/`locked_yaku`）；无起和限制但需≥1番；初始解锁"五门齐"(1番)
- 关卡预定手牌（复用调试模式）、剧情占位（story_before/after）
- **联机对战解锁**：首页入口开通（大厅→等待室→加机器人→房主开局），权限校验（仅房主可加bot/开局，需满4人）
- **联机视角旋转**：按 `my_idx` 把各玩家视角旋转到自己的座位（门风/手牌/副露/牌河标红/结果表全跟随）
- **七段码计时器修复**：两位数字并排显示（不再被覆盖只剩个位），尺寸缩小到 70×66px
- 算番接口 `/api/score` 移植到 branches 服务器（原 404）
- **番种调整**：取消"无番和"；混一色 6→4番；混全带幺 4→3番（总数 73→72）
- **听算**：流局时取 [组合番×2] 与 [听算(全体番+组合番, 不含门前清/偶然番)×1] 更高者；结果表显示"听算/组合番"及听牌张数

### v0.5.3 — 副露区优化 & 累计分修复

- **副露区横置牌**：鸣出的那张横置（逆时针90°），吃固定最左；碰按来源（上家左/对家中/下家右）；明杠对家第2张；暗杠第1、4张扣牌背；加杠新牌叠在原横置牌上方
- `MeldSet` 新增 `claimed_from`/`claimed_tile`/`added_tile`，`_player_state` 暴露给前端
- 修复加杠/暗杠后没摸牌（`_skip_rest` 未处理）、幽灵牌（`drawn_tile` 未清）、暗杠不暗置
- 单机模式不限时兜底（`_timer_tick` 加 solo_mode 保护）
- **累计分修复**：`_accumulate_scores()` 在游戏结束瞬间累加，`settle_round` 只推进庄家
- 番种修复：三同对误判、龙对和牌、门清计暗杠、间数缺级、七对计连数、双相逢/镜同/双龙会副露复计、全带幺副露、三色贯通假阳性、字对误判、流局副露重复计数

### v0.5.0 — 副露区横置

- 副露区鸣牌横置显示（吃/碰/明杠/暗杠/加杠）

### v0.4.0 — 版本统一

- 全部页面版本号统一

### v0.3.0 — 数据统计 & 论坛

- **数据统计**：每局结束记录战绩（局数/和牌率/组合率/均点/番种明细），`/stats` 个人页 + `/global-stats` 全局页（仅 chinkaku）
- **论坛**：SQLite 存储，发帖/回帖/点赞/收藏/板块，`/forum` + `/profile`，仅 chinkaku 开放
- 起和限制 `MIN_FAN=4`（和牌需4番，流局不限）
- 番种表页面 `/fans`（从 yaku.py 提取73番种）
- 牌例表补全

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
