<!--
参考代码文件:
- lua/framework/components/game_module/module_impl/master_play_module/master_play_chest_module.lua
最后参考时间: 2026-04-16
-->
================================================================================
                        MasterChest（宝箱）玩法说明
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
每日任务产出钥匙（point），钥匙用于多组宝箱抽奖；周期按活动起算 **7 天一周**，与日历周对齐展示（`MasterPlayChestWeekStr`）。

**典型需求场景**  
每日宝箱、钥匙收集、多档宝箱连开、周循环进度展示。

**能力标签**  
每日任务、钥匙收集、宝箱抽奖、周循环、任务进度推送、补钥匙表现。

**与相似玩法的区别**  
- **MasterWeeklyChest（周宝箱）**：本玩法以 **钥匙 + 每日任务组 + 抽奖** 为主；周宝箱侧重 **海螺消耗、补签/补齐** 与 `consume_conch` 等逻辑，协议与红点 key 均不同。

================================================================================
2. 玩法概述
================================================================================

玩家在周期内完成每日任务领取钥匙，消耗钥匙在对应组进行开箱抽奖；支持日奖励组领取、抽奖结果暂存与领奖清空；跨天数据失效（`IsDataInvalidOnNewDay` 为 true）。可与签到等系统联动（`AfterShowDialog` 飞钥匙表现）。

================================================================================
3. 玩法类型定义
================================================================================

- `MasterPlayType.Chest = "MasterChest"`（定义于 `master_play_module_base.lua`）
- 模块类：`MasterPlayChestModule` → `master_play_chest_module.lua`
- 枚举：`_enum("MasterPlayChestKeyState", ...)`、`_enum("MasterPlayChestWeekStr", ...)`

================================================================================
4. 核心模块说明
================================================================================

- **继承**：`MasterPlayChestModule` extends `MasterPlayModuleBase`
- **Init**：注册推送 `MasterChestTaskReward`、`MasterChestTaskGroupReward`、`MasterChestTaskInfoChange`、`MasterChestDoDraw`、`MasterChestClaimDrawReward`
- **事件监听**：`AfterShowDialog`、`MasterChestOpenAndGoDrawPanel`、`MasterChestRepairKeyReceive`、`ANewDay`
- **tempData[mpid]**：延迟打开抽奖页（`goDraw` / `goLevel`）；**loginMsg[mpid]**：登录时尚无 `master_play_info` 时暂存任务推送

================================================================================
5. 数据结构
================================================================================

- **info**：`draw_pos[group_id]`（已开位置）、`draw_reward`（待领抽奖结果列表）、`draw_times[group_id]`、`draw_status[group_id]`、`task[day_str][task_id].p/.s`、`task_group[day_str]`、`point`（各钥匙类型数量）等（以服务端为准）
- **conf.groups**：每组含 `daily_mission`、`draw_point` 等
- 刷新：`OnMasterPlayInfoRefresh` 内按组派发 `PointChanged`（展示剩余可抽次数相关）

================================================================================
6. 协议与接口
================================================================================

| 推送 / 协议 | 处理函数 |
|-------------|----------|
| MasterChestTaskReward | ReceiveKey（领钥匙） |
| MasterChestTaskGroupReward | ReceiveDailyReward（日组奖励） |
| MasterChestTaskInfoChange | OnTaskInfoChange |
| MasterChestDoDraw | ReceiveDrawResult |
| MasterChestClaimDrawReward | ReceiveDrawReward |

**请求封装**：`RequestKey`、`RequestDailyReward`、`RequestDraw`、`RequestDrawReward`（见源码）

**派发事件（节选）**：`MasterChestClaimKey`、`MasterChestClaimDailyReward`、`MasterChestReceiveDrawResult`、`MasterChestReceiveDrawReward`、`PointChanged`、`MasterPlayComplete`、`MasterChestGoDrawPanel`、`MasterChestNewDayRefresh` 等

================================================================================
7. 红点系统
================================================================================

复合逻辑：**Tab 钥匙数（tab 0~2）| 入口奖励 | 未领钥匙数**，另独立 **Bubble** key。

| Key | 规则 |
|-----|------|
| GetRedDotKey_TabKeyNum | `"GetRedDotKey_TabKeyNum_"..id.."_"..tabId`（第 6 天起按组刷新钥匙数） |
| GetRedDotKey_Reward | `"GetRedDotKey_EntryReward_"..id` |
| GetRedDotKey_UnclaimedKeyNum | `"GetRedDotKey_UnclaimedKeyNum_"..id` |
| GetRedDotKey_Bubble | `"GetRedDotKey_Bubble_"..id`（周期第 7 天显示） |

`GetRedDotKey` 汇总多段 key；`CalcRedDotNumber` 会计算钥匙/奖励/未领钥匙/Bubble。

================================================================================
8. 完成条件
================================================================================

`CheckComplete(master_play_id)`：

1. **所有组** `info.draw_times[group.id] == 7`（每组抽满 7 次）
2. 当日 `dayStr`：`task_group[dayStr] == 1` 且 `#draw_reward == 0`

满足后领奖流程中可派发 `MasterPlayComplete` + `MasterTestCloseMainUI`。

================================================================================
9. 开发注意事项
================================================================================

- 第二组每日任务进度满时会触发 `OnTaskComplete` → 飞钥匙表现。
- 任务变更在 `master_play_info` 未就绪时写入 `loginMsg`，避免丢推送。
- 打开主界面抽奖：`MasterChestOpenAndGoDrawPanel` 与 `tempData` 配合，避免未打开主 UI 时跳转失败。
- 红点与 **周期第几天**（`GetDayIndex == 6` 等为“第 7 天”逻辑）强相关，改 UI 勿忽略。

================================================================================
10. 配表结构（MasterChest.xls）
================================================================================

### Sheet: MasterChest

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 活动的id |
| comment | string | - | 备注名，自己看的 |
| groups | Group | array | 每日任务组，引用 Group 子表 |
| daily_reward | Yeild | array | 每日完成任务组的奖励 |
| return_dailyreward | string | - | 补发邮件-每日奖励 |
| recycle_drawpoint | string | - | 抽奖币回收邮件 |
| return_reward | string | - | 补发邮件-大奖 |

### Sheet: Group

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 任务的id |
| comment | string | - | 备注名，自己看的 |
| daily_mission | Mission | array | 每天的任务，引用 Mission 子表 |
| reward | Reward | array | 奖池奖励，当奖池中只有一个奖励时，该奖励的在奖池中的权重为1，引用 Reward 子表 |
| draw_point | string | - | 抽奖币 |
| repair_draw_point | int | - | 补齐消耗点券数 |
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
| reward_draw_point | yeild | array | 完成任务获得的抽奖币 |
| task_img | string | - | 任务图片 |

### Sheet: Reward

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一ID |
| comment | string | - | 注释 |
| reward | yield | array | 奖池奖励，当奖池中只有一个奖励时，该奖励的在奖池中的权重为1 |
| weight | int | - | 抽奖权重 |
| min_times | int | - | 至少多少次才能抽到，-1不限制 |
| is_big_reward | int | - | 是否是大奖，1-是，0或为空-不是 |
| probability_show | string | - | 奖励概率（显示用） |
| total_user_cap | int | - | 一次活动每人获得数量上限，-1不限制 |
| big_rewards_max_times | int | - | 大奖最多多少抽抽到（真保底） / 各奖池的保底进度独立，抽到该奖池对应的大奖时重置保底进度 |

================================================================================
                               文档结束
================================================================================

