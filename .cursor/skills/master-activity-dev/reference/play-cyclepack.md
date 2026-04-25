<!--
参考代码文件:
- lua/framework/components/game_module/module_impl/master_play_module/master_play_cycle_pack_module.lua
最后参考时间: 2026-04-16
-->
================================================================================
                        周期礼包（MasterCyclePack）玩法说明
================================================================================
                           版本: 2026-04-16
================================================================================

1. 适用场景与需求匹配

### 核心玩法模式
在活动周期内 **触发限时礼包**，并叠加 **里程碑进度奖励**：玩家购买付费档位、领取进度奖；客户端维护 `last_trigger_time`、`tier_id`、`charge_status`、`pg_reward` 等与活动周期一致的状态。

### 典型需求场景
限时打折礼包、多档位付费、累计进度领大奖、周期重置；需要与 Master 积分进度联动的付费活动。

### 能力标签
限时礼包、周期触发、里程碑、付费档位、积分联动、`MasterCyclePackClose` 关闭通知。

### 与相似玩法的区别
与纯 **Package** 页不同：本玩法把 **积分**、**触发时间**、**tier** 与 **里程碑** 绑在同一 `master_play_info.info` 生命周期内。与 **Milestone** 纯进度相比，更强调 **礼包触发 + charge 回执**。

---

2. 玩法概述
`MasterPlayCyclePackModule` 同步服务端下发的 `msg.res.info` 至 `play_info.info`，处理触发、充值结果与进度领奖；监听 `MasterPointChanged` 与 `AskNeedCancelBuy` 以处理积分变化与取消购买询问。

**典型流程**
1. 活动开放 → 服务端触发或客户端请求 → `MasterCyclePackTrigger` 更新 `last_trigger_time` / `tier_id`。
2. 玩家购买 → `MasterCyclePackCharge` → 更新 `charge_status`。
3. 进度达标 → `MasterCyclePackTakeProgressReward` → 更新 `pg_reward`。
4. 周期结束或关闭 → `MasterCyclePackClose`（以实际派发为准）。

---

3. 玩法类型定义
- **类名**：`MasterCyclePack`
- **模块**：`MasterPlayCyclePackModule`

---

4. 核心模块说明
| 职责 | 说明 |
|------|------|
| 推送 | `MasterCyclePackTrigger`、`MasterCyclePackCharge`、`MasterCyclePackTakeProgressReward`（绑定名以源码为准） |
| 出站 | `MasterCyclePackTakeProgressReward`、`MasterCyclePackSettlement` |
| 业务 | `CheckPointRegistered`、`IsActive`、`TryClearData`、`GetTierInfoByTierId`、`GetAnyActiveInfo`、`GetMilestoneTotalChipCount`、`GetMilestoneCanClaim`、`GetHaveBuy`、`IsAllMilestoneClaimed`、`IsAnyMilestoneCanClaime`、`IsMilestoneProgressFull` |

---

5. 数据结构
- **`play_info.info`**：`last_trigger_time`、`tier_id`、`charge_status`、`pg_reward` 等（以下行推送为准）
- **`conf`**：`duration`、`paid_tiers`、`point` 等 —— `point` 与 `CheckPointRegistered` 一致

---

6. 协议与接口
- **RegisterPushHandler**：触发、充值结果、领取进度奖 —— 成功后更新本地 info 并 `DispatchEvent`（如 `MasterCyclePackTrigger`、`MasterCyclePackProgressReward`、`PointChanged`）
- **监听**：`AskNeedCancelBuy` —— 与商店取消订单/关闭弹窗协作
- **Settlement**：`MasterCyclePackSettlement` 用于结算或收尾（以产品逻辑为准）

---

7. 红点系统
- `GetRedDotKey`：`"MasterCyclePack_Common_" .. master_play_id`
- 红点含义：通常聚合「可买」「可领里程碑」等 —— 以 `CalcRedDotNumber` 实现为准

---

8. 完成条件
模块内 **未** 覆写 `CheckComplete`，以 `MasterPlayModuleBase` 默认为准；若活动需「买空+领完」才算完成，应在策划文档中明确是否由服务端标记。

---

9. 开发注意事项
- **积分注册**：`CheckPointRegistered` 与 `MasterPointChanged` 联动，改 `conf.point` 时全量回归里程碑进度条。
- 关闭事件 `MasterCyclePackClose` 与 UI 弹层队列协作时，遵守项目 **弹窗顺序** 与 `UIQueueManager` 约定。
- 里程碑判断以 `GetMilestoneCanClaim` / `IsAllMilestoneClaimed` 为准，避免客户端重复领奖。
- `TryClearData` 可能在活动切换或重进时调用，UI 需容忍短暂空数据态。

**联调与测试建议**
- 触发时间与 `duration`：在服务器时间跳变（维护、校时）场景下验证 `IsActive` 不翻转异常。
- 多档位 `paid_tiers`：购买低档位后高档位展示与红点是否符合策划表。
- `MasterCyclePackSettlement` 调用时机与活动结束弹窗是否重复——避免二次领奖提示。

**与 Business 模块**
- 充值结果以推送为准，客户端本地勿缓存「已付」作为唯一真理源；断线重连以 `charge_status` 同步。

10. 配表结构（MasterCyclePack.xls）


### Sheet: MasterCyclePack（主表）

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一ID |
| comment | string | - | 注释 |
| action_trigger_events | TriggerEvent | - | 触发礼包的行为条件；该条件在unlock_requirements、register之后开始计数，多个条件之间是and的关系，引用 TriggerEvent 子表 |
| duration | duration | - | 触发后的持续时间 |
| action_cd | duration | - | 当日两次触发礼包之间的CD |
| paid_tiers | PaidTier | array | 根据付费金额推送的产出，根据rec_tier_type决定用哪个属性来区分，引用 PaidTier 子表 |
| trigger_type | string | - | daily，weekly，monthly（周、月还没开发） |
| count_limit | int | - | 触发次数，-1不限制次数 |
| trigger_count_type | string | - | count_limit的消耗类型，触发就消耗trigger，购买才消耗buy |
| entry_icon | string | - | 入口图标配置 |
| inflation_type | int | - | 进度奖励中金币的膨胀属性 / 不膨胀：0 / 付费膨胀：1 / 免费膨胀：2 |
| boost_available | int | - | 进度奖励中金币产出是否受charge_chip_bonus影响，1为是，不配则不受影响 |
| reward_return_mail | string | - | 进度奖补发邮件 / #R:SystemMail |
| point | string | - | 进度奖使用的积分id |
| fish_drop | string | - | 掉落id |

### Sheet: PaidTier（子表：PaidTier）

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一ID |
| comment | string | - | 备注名 |
| charge | object | array | 计费点id |
| condition_1 | string | - | 条件1类型 / 累充：vip_exp / 30天内：30_days_paid_amount |
| c1_min | int | - | 条件1小值 / -1无穷小 |
| c1_max | int | - | 条件1大值 / -1无穷大 |
| condition_2 | string | - | 条件2类型 |
| c2_min | int | - | 条件2小值 / -1无穷小 |
| c2_max | int | - | 条件2大值 / -1无穷大 |
| reward | Reward | array | 对应的奖励，引用 Reward 子表 |

### Sheet: TriggerEvent（子表：TriggerEvent）

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一ID |
| comment | string | - | 备注名 |
| task_action | string | - | 具体的任务条件类型 |
| task_filters | object | array | 过滤事件 |
| require | object | - | 玩家属性要求 |

### Sheet: Reward（子表：Reward）

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 进度奖id |
| comment | string | - | 自己看的备注 |
| points | int | - | 达到本阶段所需积分/需要完成的任务条数 |
| rewards | yield | array | 奖励 |
