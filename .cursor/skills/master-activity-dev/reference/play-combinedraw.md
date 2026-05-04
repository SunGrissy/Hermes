<!--
参考代码文件:
- lua/framework/components/game_module/module_impl/master_play_module/master_play_combine_draw_module.lua
最后参考时间: 2026-04-16
-->
================================================================================
                        组合抽奖（MasterCombineDraw）玩法说明
================================================================================
                           版本: 2026-04-16
================================================================================

1. 适用场景与需求匹配

- **核心模式**：消耗**门票**进行组合式抽奖，并维护**掉落计数器**（按系列/池累计）。
- **典型需求**：门票抽奖、组合掉落类运营活动、需展示「再抽几次必出」类计数的玩法。
- **能力标签**：随机奖励、门票消耗、掉落计数。

与纯积分单池抽奖（MasterDraw）不同：本玩法强调**门票**与**系列/掉落进度**两条线。

2. 玩法概述

`MasterPlayCombineDrawModule` 处理组合抽奖请求、积分/门票推送，并将结果以恭喜获得等形式展示。`draw_series` 与 `drop_counts` 用于驱动 UI 展示进度与池状态。

3. 玩法类型定义

- **模块类**：`MasterPlayCombineDrawModule`
- **基类**：`MasterPlayModuleBase`
- **实现文件**：`master_play_combine_draw_module.lua`

4. 核心模块说明

模块封装：发起 `RequestCombineDraw`、合并/清理缓存的奖励展示、查询门票顺序与石质/特殊奖池的 Yield 信息、读取掉落计数。道具或门票变化时通过事件通知界面刷新。

5. 数据结构

- **`info`**：由 `msg.res.info` 赋值，含当前玩法快照。
- **`draw_series`**：抽奖系列/轮次相关数据（用于组合逻辑或展示）。
- **`drop_counts`**：各维度掉落计数，用于进度条或保底提示。

6. 协议与接口

**下行推送（RegisterPushHandler）**

- `MessageType.MasterCombineDraw` → `OnMasterCombineDraw`
- `MasterCombineDrawPushPoint` → `OnMasterCombineDrawPushPoint`

**上行请求**

- `MessageType.MasterCombineDraw`（具体方法与参数见模块内封装）

**常用对外方法**

- `RequestCombineDraw`
- `ShowRewardsCongradulation`、`ClearCachedRewards`
- `GetOrderTickets`
- `GetStoneRewardPoolYieldInfo`、`GetStoneDropCounts`

7. 红点系统

- **Key**：`"Master_CombineDraw_RedDot_" .. play_id`

注意变量名为 `play_id`（与部分模块 `master_play_id` 命名并存），绑定时与红点注册处保持一致。

8. 完成条件（CheckComplete）

- **未实现**；继承基类 → 默认不自动完成。

9. 开发注意事项

**事件**

- **派发**：`MasterCombineDrawResult`、`ItemDataChangeReceiveEvent`、`CombineDrawTicketChanged`

门票与背包道具联动时，务必监听 `ItemDataChangeReceiveEvent` 与 `CombineDrawTicketChanged`，避免按钮可点状态与服务器不一致。展示恭喜获得前可使用 `ClearCachedRewards` 防止重复叠加。新增系列时需同步 `draw_series` / `drop_counts` 的解析与 BI 上报（若存在）。

**推送与刷新**

- `OnMasterCombineDraw`：主抽奖结果；更新 `info`、`draw_series`、`drop_counts` 后再弹恭喜。
- `OnMasterCombineDrawPushPoint`：积分/门票类推送；用于中间态同步（具体字段以协议为准）。

**对外方法分工（摘要）**

- `GetOrderTickets`：门票排序与展示顺序（多门票类型并存时优先读模块而非本地拼表）。
- `GetStoneRewardPoolYieldInfo` / `GetStoneDropCounts`：石质奖池与掉落计数成对使用，避免只显示其一导致进度条错误。

**与其它 Draw 玩法差异**

| 维度 | CombineDraw | MasterDraw |
|------|-------------|------------|
| 消耗 | 门票为主 | 积分 / 免费次数 |
| 进度 | `drop_counts` + 系列 | 幸运值 / 保底等 |
| 红点 key | 单 key，`play_id` | Normal / Free / Remind |

**测试关注点**

- 门票道具增减时 UI 与 `CombineDrawTicketChanged` 是否同步。
- `ClearCachedRewards` 调用时机，避免连续两次抽奖合并展示。

10. 配表结构（MasterCombineDraw.xls）

### Sheet: MasterCombineDraw

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 活动id |
| comment | string | - | 备注 |
| stone_settings | Stone | array | 宝石设置，引用 Stone 子表 |
| stone_cost_num | int | - | 单次消耗数量 |
| stone_recycle_mail_id | string | - | 活动结束宝石补发邮件 |
| feature_cannon_id | string | - | 展示的战魂id |
| feature_cannon_level | int | - | 战魂等级达到x级后，奖池替换 |
| draw_reward_pool | Reward | array | 活动内包含奖励，引用 Reward 子表 |
| reward_limit | object | - | 在抽奖中获得的战魂碎片上限，格式为 starp:上限 |
| cannon_shard_limit | object | - | 在抽奖中获得的战魂碎片上限，格式为 item_id:上限 |

### Sheet: Stone

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 宝石ID |
| comment | string | - | 注释 |
| point_id | string | - | 对应的积分/道具id |
| draw_reward | object | array | 奖池奖励 |
| reward_weight | int | array | 奖励权重 |
| draw_reward_2 | object | array | 战魂满级后奖池 |
| reward_weight_2 | int | array | 满级后奖励权重 |
| reward_pool | Reward | array | 奖池奖励，引用 Reward 子表 |
| point_reward | yield | array | 消耗宝石的积分奖励 |

### Sheet: Reward

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一ID |
| comment | string | - | 注释 |
| reward | yield | array | 奖励 |
| is_big_reward | int | - | 是否为大奖 |
