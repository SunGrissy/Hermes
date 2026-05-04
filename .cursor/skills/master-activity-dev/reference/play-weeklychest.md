<!--
参考代码文件:
- lua/framework/components/game_module/module_impl/master_play_module/master_play_weekly_chest_module.lua
最后参考时间: 2026-04-16
-->
================================================================================
                        MasterWeeklyChest（周宝箱）玩法说明
================================================================================
                           版本: 2026-04-16
================================================================================

1. 适用场景与需求匹配
2. 玩法概述
3. 玩法类型定义
4. 核心模块说明
5. 数据结构
6. 协议与接口
7. 红点系统
8. 完成条件
9. 开发注意事项

================================================================================
1. 适用场景与需求匹配
================================================================================

**核心玩法模式**  
按周推进的 **多组每日任务 + 日/组宝箱奖励**；支持 **海螺（conch）消耗** 与任务 **补签/补齐** 表现（`HasRepaired` / `ShowRepair`）。

**典型需求场景**  
周循环活动宝箱、海螺收集与消耗、错过任务后的补齐引导。

**能力标签**  
每周任务、多 group、海螺消耗、任务推送、日组奖励记录、补齐动画。

**与相似玩法的区别**  
- **MasterChest（宝箱）**：以 **钥匙 point + 抽奖 draw_times==7** 与 `task_group` 日结为主；本玩法为 **WeeklyChest 专用协议**、`consume_conch`、`big_reward` 组奖，无 Chest 的 `draw_pos/draw_reward` 同一套逻辑。

================================================================================
2. 玩法概述
================================================================================

玩家在周期内完成各组每日任务领取进度；达成条件可领日组奖励、大组奖励；服务端可推送海螺消耗变化。跨天数据失效（`IsDataInvalidOnNewDay`）。登录时若 info 未就绪，任务推送先入 `loginMsg`。

================================================================================
3. 玩法类型定义
================================================================================

- `MasterPlayType.WeeklyChest = "MasterWeeklyChest"`
- 模块：`MasterPlayWeeklyChestModule` → `master_play_weekly_chest_module.lua`

================================================================================
4. 核心模块说明
================================================================================

- **继承**：`MasterPlayWeeklyChestModule` extends `MasterPlayModuleBase`
- **Init**：注册 `MasterWeeklyChestTaskReward`、`MasterWeeklyChestTaskInfoChange`、`MasterWeeklyChestTaskGroupReward`、`MasterWeeklyChestClaimDrawReward`、`MasterWeeklyChestConchCostChange`
- **OnMasterPlayInfoRefresh**：同步各组任务进度并派发 `PointChanged`、`MasterWeeklyChestRefresh`
- **功能方法**：`GetDayIndex`、`IsTaskComplete`、`CanDailyRewardClaime`、`CanGroupRewardClaime`、`HasRepaired`、`ShowRepair` 等

================================================================================
5. 数据结构
================================================================================

- **info.task[day_str][task_id]**：任务进度 `.p`、领取状态 `.s`
- **info.task_group**：已领日组奖励的 **day_str 列表**（数组追加）
- **info.big_reward**：已领取的 **group_id** 列表
- **info.consume_conch**：海螺消耗（`OnCouchCostChange` 同步，命名保留源码拼写）
- **conf.groups**：每组 `daily_mission`、`point`、阈值等

================================================================================
6. 协议与接口
================================================================================

| 推送 / 协议 | 处理函数 |
|-------------|----------|
| MasterWeeklyChestTaskReward | ReceivTaskReward（源码函数名） |
| MasterWeeklyChestTaskInfoChange | OnTaskInfoChange |
| MasterWeeklyChestTaskGroupReward | ReceiveDailyReward |
| MasterWeeklyChestClaimDrawReward | ReceiveGroupReward |
| MasterWeeklyChestConchCostChange | OnCouchCostChange |

**请求**：`RequestTaskReward`、`RequestDailyReward`、`RequestGroupReward`

**派发事件（节选）**：`MasterWeeklyChestTaskRewardClaimed`、`MasterWeeklyChestDailyRewardClaimed`、`MasterWeeklyChestGroupRewardClaimed`、`MasterWeeklyTaskInfoChange`、`MasterWeeklyChestRefresh`、`MasterWeeklyChestConsumeChange`、`PointChanged`

================================================================================
7. 红点系统
================================================================================

`GetRedDotKey` 复合：**Common | Reward | Bubble**（以 `"|"` 连接）。

| Key | 格式 |
|-----|------|
| Common | `"WeeklyChestRedDotKey_Common_"..master_play_id`（可完成任务数） |
| Reward | `"WeeklyChestRedDotKey_Reward_"..master_play_id`（可领奖励） |
| Bubble | `"WeeklyChestRedDotKey_Bubble_"..master_play_id`（与本地 `WeeklyChestData` 等私有数据配合） |

`CalcRedDotNumber` → `CalcCommonRedDotNumber` + `CalcRewardRedDotNumber` + `CalcBubbleKeyRedDotNumber`。

================================================================================
8. 完成条件
================================================================================

模块内 **未实现** `CheckComplete`（与 MasterChest 不同）；活动是否结束依赖 Master 活动周期与配表，客户端以入口与数据刷新为准。

================================================================================
9. 开发注意事项
================================================================================

- **补齐**：`ReceivTaskReward` 中在加点数前记录 `before_repair_state`，满足条件时 `ShowRepair` 播表现。
- **任务推送**：`master_play_info` 不存在时缓存到 `loginMsg`，在 `OnMasterPlayInfoRefresh` 补处理。
- **海螺**：消耗变化会刷新红点并派发 `MasterWeeklyChestConsumeChange`。
- 弹窗：`MasterPlayWeeklyChestRepairMessageBox` 用于补齐相关提示。

================================================================================
10. 配表结构（MasterWeeklyChest.xls）
================================================================================

### Sheet: MasterChest

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 活动的id |
| comment | string | - | 备注名，自己看的 |
| groups | Group | array | 每日任务组，引用 Group 子表 |
| first_daily_reward | Yeild | array | 首次领取每日奖励的内容 |
| first_daily_reward_comment | yield | array | 首次领取每日奖励数字（客户端用） |
| daily_reward | Yeild | array | 常规每日完成任务组的奖励 |
| first_daily_reward_comment | yield | array | 常规领取每日奖励数字（客户端用） |
| return_dailyreward | string | - | 补发邮件-每日奖励 |
| return_reward | string | - | 补发邮件-大奖 |
| reward_unlock_days | int | - | 活动第n天开启补齐功能，同时可以开启领取奖励 |

### Sheet: Group

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 任务的id |
| comment | string | - | 备注名，自己看的 |
| daily_mission | Mission | array | 每天的任务，引用 Mission 子表 |
| point | string | - | 任务大奖对应积分 |
| point_min | int | - | 领取大奖所需积分数量 |
| reward | yield | array | 该组任务大奖内容 |
| repair_point | int | - | 补齐消耗点券数 |
| catch_up_min_days | int | - | 补齐钥匙要求最小天数 |
| repair_point_gonow | object | - | 跳转配置，点击跳转到配置的界面 |

### Sheet: Mission

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 任务ID |
| comment | string | - | 任务描述 |
| description | string | - | 任务描述 |
| description_way | string | - | 获得方式描述 |
| task_action | string | - | 具体的任务条件类型 |
| task_filters | object | array | 过滤事件 |
| task_value | object | - | 如何累加值 |
| go_now | object | - | 跳转配置，如果不为空，任务没完成时显示“前往”按钮，点击跳转到配置的界面 |
| reward_draw_point | yeild | array | 完成任务获得的积分 |
| task_img | string | - | 任务图片 |

================================================================================
                               文档结束
================================================================================

