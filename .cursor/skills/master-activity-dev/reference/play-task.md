<!--
参考代码文件:
- lua/framework/components/game_module/module_impl/master_play_module/master_play_task_module.lua
最后参考时间: 2026-04-16
-->
================================================================================
                        任务（MasterTask）玩法说明
================================================================================
                           版本: 2026-04-16
================================================================================

1. 适用场景与需求匹配

### 核心玩法模式
按 **总任务 / 日 / 周 / 月** 维度维护任务进度与领奖状态，完成任务获得 Master 积分；支持付费解锁任务线（`paid_task_charge` + `info.is_buy`），形成「免费线 + 付费线」组合。

### 典型需求场景
活动每日任务、周常、月常、累计任务与积分进度展示；需要四类周期红点独立控制的 HUD。

### 能力标签
周期任务、积分奖励、付费任务解锁、多周期红点聚合、`HasTaskRedDot` 合成。

### 与相似玩法的区别
相对 **MasterMission**：Task 以 **日/周/月 + total** 的简单分类为主；Mission 通常具备更复杂的分组、解锁链与大奖逻辑。具体选型以配表 `class_type` 与策划文档为准。

---

2. 玩法概述
`MasterPlayTaskModule` 注册 `GetMasterTaskReward` 与 `PushMasterTask`，在领奖与推送刷新时更新 `info.task` 映射并重算四类红点 key；购买付费线后依赖 `ShopBuyReturn` 刷新 `is_buy` 与任务列表。

**领奖流（概念）**
1. UI 请求领取 → `GetMasterTaskReward`。
2. 下行/推送更新 `info.task` 与积分。
3. `RefreshTaskRedDot` 或等价逻辑刷新 `mpt_*` 四类 key。

---

3. 玩法类型定义
- **类名**：`MasterTask`
- **模块**：`MasterPlayTaskModule`

---

4. 核心模块说明
| 职责 | 说明 |
|------|------|
| 领奖 | `GetMasterTaskReward`（出站）；`OnGetMasterTaskReward` 处理下行 |
| 数据拉取 | `GetMasterTaskData` |
| 状态 | `GetResTask`、`HasUnCompleteTask`、`HasTaskReward`、`HasTaskRedDot` |
| 积分展示 | `GetTaskRewardPointNum`、`GetTaskPointProgress` |
| 事件 | 监听 `ShopBuyReturn`、`ANewDay`；派发 `MasterTaskChargeRefresh`、`MasterTaskReward`、`MasterTaskRefresh` |

---

5. 数据结构
- **`info.task`**：`task_id → { p, s }`（进度与领奖状态，字段以源码为准）
- **`conf`**：`total_tasks`、`daily_tasks`、`weekly_tasks`、`monthly_tasks`、`paid_task_charge` 等
- **`info.is_buy`**：付费线是否已购；与商店购买结果联动

---

6. 协议与接口
- **RegisterPushHandler**：`GetMasterTaskReward` → `OnGetMasterTaskReward`；`PushMasterTask` → `OnPushMasterTask`
- **出站**：`GetMasterTaskReward`、`GetMasterTaskData`
- **说明**：推送用于服务端主动改任务进度或状态，客户端需与主动拉取结果一致处理

---

7. 红点系统
- `GetRedDotKey` 委托 `GetRedDotKey_Reward`，由 **总/日/周/月** 四类 key **管道** 拼接：
  - `mpt_ttk_`、`mpt_dtk_`、`mpt_wtk_`、`mpt_mtk_` + `master_play_id`
- 各周期任务在刷新时分别 `RefreshRedDotInfoByEnum`（总任务、日、周、月独立）

---

8. 完成条件
**覆写 `CheckComplete`**：
- 若 `task_data.info.task` 不存在有效结构 → 返回 `true`
- 否则：当 **无 `HasTaskRedDot`** 且 **四类任务列表均无 `HasUnCompleteTask`** 时返回 `true`；否则 `false`

---

9. 开发注意事项
- 付费解锁与 `ShopBuyReturn` 强耦合，改内购流程时验证 `MasterTaskChargeRefresh` 是否仍触发。
- `ANewDay` 会重置日任务与红点，入口倒计时需与 `GetTaskPointProgress` 一致。
- 与 Mission 并存时，避免任务 ID 与事件名在 UI 层混用。
- 管道红点任一子 key 为真时，聚合层应显示红点——修改 `GetRedDotKey_Reward` 时全量回归四类任务。

**联调与测试建议**
- `CheckComplete` 在 `info.task` 缺失时返回 `true`，若活动依赖「无任务数据=未完成」需服务端保证下发结构。
- 领奖后积分变化路径与 `MasterPointChanged` 一致，便于 HUD 同步。
- 周/月界切换时，`HasUnCompleteTask` 应对新周期任务重新计算，避免沿用上周期状态。

**配表提示**
- `paid_task_charge` 与商店 `charge_id` 对应关系变更时，同步验证购买成功回调与 `is_buy` 写入顺序。

10. 配表结构（MasterTask.xls）

### Sheet: Main

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 玩法id |
| comment | string | - | 自己看的备注 |
| paid_task_charge | string | - | 用于解锁总任务的charge |
| daily_task_reward_mail | string | - | 每日任务奖励补发邮件 |
| total_task_reward_mail | string | - | 总任务奖励补发邮件 / #R:SystemMail |
| total_tasks | AllTask | array | 一次活动不用刷新的总任务，引用 AllTask 子表 |
| daily_tasks | AllTask | array | 每日刷新任务，外层list是任务坑，引用 AllTask 子表 |
| weekly_tasks | AllTask | array | 每周刷新的任务，外层list是任务坑，引用 AllTask 子表 |
| weekly_type | string | - | monday：周一刷新 / 7days：接取后7天刷新 |
| monthly_tasks | AllTask | array | 每月刷新的任务，引用 AllTask 子表 |
| monthly_type | int | - | 编辑几就是每月几号0点刷新 |
| umg | string | - | 主页umg |
| umg_class | string | - | UMG逻辑class配置 |
| umg_item | string | - | 任务条的item |
| tab_title | string | - | 作为玩法tab的多语言 |
| congratulations_umg | string | - | 恭喜获得的umg，为空表示使用通用的 |

### Sheet: AllTask

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 任务id |
| comment | string | - | 相当于备注名，自己看的 |
| comment | string | - | 相当于备注名，自己看的 |
| weight | int | - | 随机权重 |
| description | string | - | 任务描述 |
| task_action | string | - | 具体的任务条件类型 |
| task_filters | object | array | 过滤事件 |
| task_value | object | - | 如何累加值 |
| go_now | object | - | 跳转配置，如果不为空，任务没完成时显示“前往”按钮，点击跳转到配置的界面 |
| rewards | yield | array | 完成本任务可领的奖励 |

### Sheet: Draft

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| regression_daily_task_1 | regression_daily_task_2 | - | regression_daily_task_3 |
| regression_daily_task_1,regression_daily_task_2,regression_daily_task_3,regression_daily_task_4,regression_daily_task_5,regression_daily_task_6, |  | - | - |
| regression_daily_task_1,regression_daily_task_2,regression_daily_task_3,regression_daily_task_4,regression_daily_task_5,regression_daily_task_6, | regression_total_task_1 | - | - |
