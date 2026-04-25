<!--
参考代码文件:
- lua/framework/components/game_module/module_impl/master_play_module/master_play_boss_rush_module.lua
最后参考时间: 2026-04-16
-->
================================================================================
                        Boss冲刺（MasterBossRush）玩法说明
================================================================================
                           版本: 2026-04-16
================================================================================

1. 适用场景与需求匹配

### 核心玩法模式
**多轮 Boss 匹配对战**：玩家在 `group_info` 内与多名玩家比拼积分/完成时间；每轮结束可能弹出轮次结算，全部轮次完成后视为玩法完成。

### 典型需求场景
竞技向 Boss 战、淘汰赛式多轮推进、排名变化提示；需处理 **赛中** 与 **轮次结束** 两种 UI 队列时机。

### 能力标签
Boss 对战、多轮 `rounds`、匹配中状态、稳定排名 `stable_match_info`、红点提示可开战/可结算。

### 与相似玩法的区别
相对 **Boss Challenge**：本玩法为 **PVP 轮次 + 匹配信息**，无全服任务组/VIP 金币线；协议与数据模型独立。

---

2. 玩法概述
模块注册开局、刷新赛况、排名变化三类下行；`MakeStableMatchInfo` 在「在赛中」时推导逻辑胜负与排名；`OnRefreshMatchInfo` 在 `end_res` 时合并 `yield_result` 弹出 `UIMasterBossRushRoundResultMessageBox`，并用 `AroundWithUIQueueHolder` 包裹事件派发。

### 关键时序（摘要）
1. `RequestStartMatch` → `OnStartMatch` 写入 `info`，若在赛中则 `MasterBossRushStartMatchReturn(true)`。
2. 局中轮询/推送 → `RequestRefreshMatchInfo` → 可能弹出轮次结算或仅刷新 HUD。
3. 排名变化 → `OnRankChange` 校验 `stable_match_info.rank` 与 `msg.res.new_rank` 一致后，排名 **上升** 时额外派发 `MasterBossRushRankChange`。

### stable_match_info 语义
`logic_result` 表示在 **当前轮规则下** 是否已可判定胜负；`result` 表示是否已收到 **带 yield 的轮次结算**；二者配合 `CurrRound` / `CurrRoundEnd` 给 UI 使用。

---

3. 玩法类型定义
- **类名（概念）**：`MasterBossRush`
- **模块**：`MasterPlayBossRushModule`
- **基类**：`MasterPlayModuleBase`
- **枚举**：`BossRushMatchResult`（`Unknown` / `Lose` / `Win`）

---

4. 核心模块说明
- **静态工具**：`MakeStableMatchInfo`、`IsInMatch`、`CurrRound`、`CurrRoundEnd`、`AllRoundPass`（`AllRoundPass`：`info.cur_round == #conf.rounds`）。
- **赛中推导**：`stable_match_info.logic_result` 与 `result` 区分「逻辑上是否已分出胜负」与「是否已收到结算奖励」等（见 `OnRefreshMatchInfo` 对 `end_res` 的处理）。
- **完成**：`FinishMatch` 清空 `group_info` 与 `stable_match_info`，若未完成则重算红点；若 `CheckComplete` 则 `MasterPlayComplete` + `MasterTestCloseMainUI`。
- **匹配判定**：`IsInMatch` 仅看 `group_info.group_start_time` 是否存在，UI 应用该函数而非自行猜字段。
- **积分与平局**：`MakeStableMatchInfo` 内同分比 `finish_time`，先完成者排名更靠前（见模块内比较顺序）。

---

5. 数据结构
- **`master_play_info.info`**：服务端下发的 `group_info`（`player_infos`、`player_scores`、`cur_round` 等）。
- **`master_play_info.stable_match_info`**：`logic_result`、`result`、`rank` — 客户端推导的稳定展示数据。
- **`conf.rounds`**：每轮 `win_condition` 等配置。

---

6. 协议与接口
| 方向 | MessageType | 回调 | 说明 |
|------|-------------|------|------|
| 下行 | `MasterBossRushStartMatch` | `OnStartMatch` | 开局返回 `info`，可能派发 `MasterBossRushStartMatchReturn` |
| 下行 | `MasterBossRushRefreshMatchInfo` | `OnRefreshMatchInfo` | 赛况刷新，可能触发轮次结束弹窗 |
| 下行 | `MasterBossRushRankChange` | `OnRankChange` | 排名变化，断言与 `msg.res.new_rank` 一致 |

**对外**：`RequestStartMatch`、`RequestRefreshMatchInfo`、`FinishMatch`。

### 失败分支
`OnStartMatch` / `OnRefreshMatchInfo` 在 `status ~= 0` 或数据不完整时仍会派发 `*Return(..., false)`，UI 必须处理 **false** 路径避免卡在加载态。

---

7. 红点系统
- **Key**：`MasterBossRushRedDot_{master_play_id}`。
- **语义**（`CalcRedDotNumber`）：未开赛且未通全关 → 1；赛中且逻辑结果已出但结果未决 → 2；其余 0。具体数值以 `RefreshRedDotInfoByEnum` 调用为准。

---

8. 完成条件
`CheckComplete` → `AllRoundPass`：`info.cur_round == #conf.rounds`。

---

9. 开发注意事项
- **UI 队列**：轮次结束分支使用 `AroundWithUIQueueHolder("BossRushRoundEnd", ...)`，避免与其它弹窗抢队列。
- **排名推送**：`new_rank < old_rank` 时派发 `MasterBossRushRankChange`。
- **奖励追踪**：轮次结算弹窗处 `YieldRewardShowTrace_BeginTrace`。
- 派发事件：`MasterPlayComplete`、`MasterBossRushStartMatchReturn`、`MasterBossRushRefreshMatchInfoReturn`、`MasterBossRushRankChange`。
- **断言**：`OnRankChange` 内对排名做了 `assert`，若服务端与客户端推导不一致会直接报错，版本升级时需关注协议字段变更。
- **红点语义**：值为 **0/1/2** 三档，勿与「布尔」混淆；改 UI 表现前先读 `CalcRedDotNumber` 全部分支。
- **赛后清理**：`FinishMatch` 会置空 `group_info`，断线重连若只收到不完整 info，需依赖后续刷新协议恢复。

---

10. 配表结构（MasterBossRush.xls）

### Sheet: MasterBossRush

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 活动id |
| comment | string | - | 备注 |
| rounds | Round | array | 比赛轮数，引用 Round 子表 |
| min_bet | int | - | 参赛炮倍限制，低于该炮倍不计分 |
| target_type | string | - | fish：某一个id的鱼，fishtype：鱼类型，比如黄金鱼/Boss |
| target_param | string | array | 根据target不同填写不同的参数，fish：填写Fish的base id / fishtype：下面的id填写FishType的value值 |
| player_num | int | - | 小组赛人数（含玩家） |
| add_point | string | array | 活动结束后的奖励补发中，需要加到玩家身上的Point_id / #R:Point |
| rules_umg | string | - | 规则说明UMG |
| return_mail | string | - | 补发邮件 / #R:SystemMail |

### Sheet: Round

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 轮数id |
| comment | string | - | 备注 |
| score | int | - | 积分要求，完赛所需捕获倍数 |
| reward | Reward | array | 排名奖励，引用 Reward 子表 |
| win_condition | int | - | 前x名进入下一轮 |
| robot_pool | Pool | array | 填充的机器人池=数量等于小组赛人数-1，引用 Pool 子表 |

### Sheet: Reward

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | robot_id |
| comment | string | - | 备注 |
| rank | int | - | 排名（上一个数到该数之间的排名，左开右闭） |
| reward | yield | array | 奖励 |

### Sheet: Pool

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | poolid |
| comment | string | - | 备注 |
| robot_id | Robot | array | 从以下机器人中随机挑选1个机器人行为，引用 Robot 子表 |
| avatar | string | array | 从以下头像头随机挑选1个作为头像 |

### Sheet: Robot

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | robot_id |
| comment | string | - | 备注 |
| join_time | int | - | 第几秒加入小组 |
| score_time | int | array | 积分增长时间，差值 |
| score_number | int | array | 积分增长数量，差值【最小倍数,最大倍数】 |
| follow_time_delay | int | array | 积分增长时间，差值 |
| follow_score | int | array | 积分增长数量，百分数 |
