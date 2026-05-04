<!--
参考代码文件:
- lua/framework/components/game_module/module_impl/master_play_module/master_play_boss_challenge_module.lua
最后参考时间: 2026-04-16
-->
================================================================================
                        Boss挑战（MasterBossChallenge）玩法说明
================================================================================
                           版本: 2026-04-16
================================================================================

1. 适用场景与需求匹配

### 核心玩法模式
以 **任务组（task group）** 为单位推进：含 **全服/全局任务** 与 **个人任务**；个人线支持 **VIP 档位金币加成**（`coin_mul`），领取奖励时对比 `reward_state` 与 VIP 档位刷新红点。

### 典型需求场景
Boss 战斗主题活动、分组挑战、全服进度条 + 个人领奖；需在打开界面时 **节流刷新全服进度**（`GLOBALTASKREFRSHTIMESPAN`）。

### 能力标签
Boss 挑战、分组任务、全局进度刷新、VIP 金币气泡、任务组级红点。

### 与相似玩法的区别
相对 **Boss Rush（MasterBossRush）**：本玩法侧重 **任务组 + 全服进度 + VIP 加成**；Boss Rush 为 **多轮匹配对战、排名与轮次结算**，模块与协议完全不同。

---

2. 玩法概述
`MasterPlayBossChallengeModule` 注册领取、刷新全服进度与任务进度推送；`ClaimTaskReward` 带本地防连点；领奖后弹标准恭喜获得并派发资金展示锁/解锁事件。全局进度未满时按时间戳节流请求 `MasterBCRefreshGlobalTaskProgress`。

### 关键时序（摘要）
1. 活动数据就绪 → `OnMasterPlayInfoRefresh` 初始化各任务组红点字典，并写入 `global_task_refresh_timestamp`。
2. UI 打开或需要最新全服进度 → `RefreshGlobalTaskProgress`，满足间隔才发包。
3. 玩家点击领取 → `ClaimTaskReward` → 下行更新 `reward_state` / `p` → 弹窗与资金事件 → `CalcRedDotNumber_Reward`。

### 与入口/HUD 的协作
任务组红点 key 在刷新时即注册，HUD Tab 常用 `GetRedDotKey_Reward_By_TabIndex` 聚合多个任务组；**「新」红点**与 **总奖励红点** 管道拼接在 `GetRedDotKey`。

---

3. 玩法类型定义
- **类名（概念）**：`MasterBossChallenge`
- **模块**：`MasterPlayBossChallengeModule`
- **基类**：`MasterPlayModuleBase`
- **任务组类型**：`BossChallengeTaskGroupType`（`Num` 捕获数量 / `Coin` 捕获金币）

---

4. 核心模块说明
- **进度**：`RefreshTaskGroupProgress` 写入 `info.task[task_group_id].p`，进度变化时 `DispatchEvent(MasterBCTaskGroupProgressChange)` 并重算红点。
- **全服进度是否已满**：`CheckGlobalTaskProgressFull` 用于决定是否还需请求刷新。
- **VIP**：`GetVIPMulti` / `GetVIPCoin`；VIP 变化时 `VIPInfoChanged` 触发奖励红点重算。
- **常量**：`GLOBALTASKREFRSHTIMESPAN = 5*60`（秒），注释说明活动末尾可能存在刷新窗口限制。
- **领奖状态读取**：`GetTaskRewardClaimState(master_play_info, task_group_id, task_id)` 返回 0 表示未领或可领（与红点遍历一致）。
- **展示辅助**：`GetFirstFishName` 从 `task_filter` 取鱼名，供 UI 文案。

---

5. 数据结构
- **`master_play_info.global_task_refresh_timestamp`**：上次刷新全服/推送对齐后的服务端时间戳，用于节流。
- **`master_play_info.info.task[task_group_id]`**：`p` 进度；`reward_state` / `last_reward_state` 领奖同步用。
- **配置**：`conf.global_task`、`conf.personal_task`、`conf.task_filter` 等。

---

6. 协议与接口
| 方向 | MessageType | 回调 | 说明 |
|------|-------------|------|------|
| 下行 | `MasterBCClaimTaskReward` | `OnClaimTaskRewardReturn` | 领取任务组奖励，更新 task 与弹窗 |
| 下行 | `MasterBCRefreshGlobalTaskProgress` | `OnRefreshGlobalTaskProgressReturn` | 批量刷新全服相关进度 |
| 推送 | `MasterBCPushTaskProgress` | `OnPushTaskProgress` | 任务进度推送 |

**对外调用示例**：`ClaimTaskReward(master_play_id, task_group_id, is_auto_vip_reward)`；`RefreshGlobalTaskProgress(master_play_id)`（内部判断节流）。

### 参数约定
- `MasterBCClaimTaskReward`：`params.task_id` 传 **任务组 id**；`params.is_auto` 表示是否自动领 VIP 相关奖励（0/1）。

---

7. 红点系统
- **聚合**：`GetRedDotKey` = `GetRedDotKey_Reward` | `GetRedDotKey_New`。
- **总奖励**：`master_bc_r_all_{master_play_id}`。
- **按任务组**：`master_bc_r_{master_play_id}_{task_group_id}`（`InitRedDot` 在 `OnMasterPlayInfoRefresh` 为每个 global/personal 组注册）。
- **VIP 气泡**：`master_bc_vipb_{master_play_id}`（`RefreshVipRewardRedDot`）。
- **新内容**：`master_bc_n_{master_play_id}`。
- **Tab 组合**：`GetRedDotKey_Reward_By_TabIndex` 按 Tab 拼接各任务组 key。

---

8. 完成条件
模块内 **未实现** `CheckComplete`（无统一「活动完成」判定，按策划/UI 需求在其他层处理）。

---

9. 开发注意事项
- 领奖链：`MasterBCLockCapitalShow` → 恭喜获得 → `MasterBCReleaseCapitalShow`（注意与 UI 资金条表现配合）。
- 防连点：`ClaimTaskReward` 内 2 秒窗口，与 HoldUIQueue 并存时仍可能需 UI 侧兜底。
- 全服进度：活动 **最后约 5 分钟** 可能因节流无法频繁拉取，策划需知（见模块内注释）。
- 监听：`VIPInfoChanged`。派发：`MasterBCTaskGroupRewardClaimReturn`、`MasterBCLockCapitalShow`、`MasterBCReleaseCapitalShow`、`MasterBCTaskGroupProgressChange`。
- 恭喜获得：`StandardRewardMessageBoxName` + `YieldRewardShowTrace_BeginTrace`，与全局 Master 奖励追踪规范一致。
- 任务组维度：任意任务组进度或 VIP 档变化都可能改变 **总红点** `master_bc_r_all_*`，UI 勿只监听单 key。
- 调试：下行失败分支会 `Log.error` 打 status，定位时优先对齐 **任务组 id** 与 **msg.res.task** 是否单组返回。

---

10. 配表结构（MasterBossChallenge.xls）

### Sheet: Main

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 每个id对应一期boss挑战 |
| comment | string | - | 自己看的备注 |
| umg | UMG | - | ui/UMG / 风格资源预设，引用 UMG 子表 |
| feature | string | - | 主推boss立绘资源 / 这三个资源配在MasterAct里 / parm_1=标题 / parm_2=立绘（带名签） / parm_3=slogan广告 |
| title | string | - | 当期标题资源 |
| boss_info | string | - | 捕获赏金右侧 / slogan& / 出没信息资源 |
| task_filter | object | array | 主题boss的filter |
| target_details | int | - | 0是不展示详情，1展示 / 主题boss有多个时配1 |
| global_task | TaskGroup | array | 全服任务，引用 TaskGroup 子表 |
| personal_task | TaskGroup | array | 个人任务，引用 TaskGroup 子表 |
| post_go_now | object | - | 前往捕获直跳 |
| point_id | string | - | 同期的兑换积分 / Point_id |
| reward_mail | string | - | 补发邮件 |

### Sheet: UMG

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | id |
| comment | string | - | 自己看的备注 |
| dashtask_umg | string | - | 冲刺任务umg |
| numtask_umg | string | - | 捕获赏金umg |

### Sheet: TaskGroup

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | id |
| comment | string | - | 备注 |
| type | string | - | 类型 / num-按捕获数量计数 / coin-按捕获金币计数 |
| task_action | string | - | 具体的任务条件类型 |
| count | string | - | 如何累加值 |
| tasks | AllTask | array | 本任务组包含哪些子任务，列表顺序代表默认显示顺序，引用 AllTask 子表 |
| coin_mul | VipMul | array | 奖励金币是否根据relic_vip膨胀 / 若为空则没有膨胀 / *活动结束的奖励补发，仅补发coin_mul不为空的任务组，引用 VipMul 子表 |

### Sheet: AllTask

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 任务id |
| comment | string | - | 相当于备注名，自己看的 |
| value | int | - | 奖励对应的累计进度 / 最大值 / 922337203685477 |
| rewards | yield | array | 完成本任务可领的奖励 |

### Sheet: VipMul

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | id |
| comment | string | - | 备注 |
| level | int | - | VIP等级下限 |
| mul | int | - | 领取倍率（总值，非增量） |

### Sheet: Draft

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| MasterBoss挑战配置说明 | - | - | 1. 活动涉及MasterAct、MasterBossChallenge、MasterSignIn、MasterExchange、Point四个表。 |
