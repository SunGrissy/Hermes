<!--
参考代码文件:
- lua/framework/components/game_module/module_impl/master_play_module/master_play_charge_reward_module.lua
最后参考时间: 2026-04-16
-->
================================================================================
                        充值奖励（MasterChargeReward）玩法说明
================================================================================
                           版本: 2026-04-16
================================================================================

1. 适用场景与需求匹配

### 核心玩法模式
按 **累计充值进度 `process`** 解锁 **分档奖励 `stages`**；客户端用 `info.tasks[stage.id]` 记录是否已领（协议返回 `take_stages` 批量标记为 1）；进度变化可由 **`MasterChargeRewardProcessChange`** 推送。

### 典型需求场景
累计充值返利、分段领奖、进度条展示；通常 **不需要** 注册 Master 积分点（模块 `IsRegisterPointRequired` 为 false）。

### 能力标签
充值进度、分档领取、红点仅看「已达档且未领」、与商店/充值系统解耦（仅消费服务端 `process`）。

### 与相似玩法的区别
相对 **任务/里程碑类**：本玩法 **无独立任务进度条客户端计算**，以服务端 `process` 与 `tasks` 为准；配置路径为 **`conf.groups[1].stages`**。

---

2. 玩法概述
注册领取与进度变更两条下行；领奖成功后遍历 `msg.res.take_stages` 将对应 `info.tasks[id]` 置 1；进度推送覆盖 `info.process` 并重算红点。

### 关键时序（摘要）
1. 充值行为 → 服务端更新 `process` → 可能下发 `MasterChargeRewardProcessChange`。
2. 玩家点一键领奖 → `MasterChargeRewardClaim` → 返回 `take_stages` 批量标记已领。
3. 红点刷新 → 仅统计 **已达档且 tasks 未置 1** 的 stage。

### 与商店模块边界
客户端 **不计算** 充值金额；仅展示 `process` 与档位 `target` 比较结果，实际以服务端校验为准。

---

3. 玩法类型定义
- **类名（概念）**：`MasterChargeReward`
- **模块**：`MasterPlayChargeRewardModule`
- **基类**：`MasterPlayModuleBase`
- **枚举**：`MasterChargeRewardState`（`Unavailable` / `Available` / `Claimed`，供 UI 语义）

---

4. 核心模块说明
- **领奖**：`RequestClaimRewards` 无额外参数，一次性按服务端逻辑处理可领档（以返回 `take_stages` 为准）。
- **红点数量**：对 `conf.groups[1].stages` 遍历，若 `stage.target <= info.process` 且 `info.tasks[stage.id] ~= 1` 则计数 +1。

---

5. 数据结构
- **`info.process`**：当前累计充值进度（服务端权威）。
- **`info.tasks[id]`**：阶段是否已领奖（1 表示已领）。
- **配置**：`conf.groups[1].stages` — 每档 `target`、`id` 等。

---

6. 协议与接口
| 方向 | MessageType | 回调 | 说明 |
|------|-------------|------|------|
| 下行 | `MasterChargeRewardClaim` | `OnRecieveClaimRewards` | 领取成功更新 `tasks` |
| 推送 | `MasterChargeRewardProcessChange` | `OnProcessChange` | 更新 `process` |

### 回调命名
`OnRecieveClaimRewards` 为历史拼写（`Recieve`），全局搜索时保留原样。

---

7. 红点系统
- **`GetRedDotKey`**：等同 `GetRedDotKey_Reward` → **`MasterChargeReward_RewardRedDot_{master_play_id}`**。
- **数值**：可领档位数（多档可领时红点计数累加）。

---

8. 完成条件
模块内 **未实现** `CheckComplete`（是否「充到最高档并领完」由产品决定，可在 UI 或活动层判断）。

---

9. 开发注意事项
- **派发**：`MasterChargeRewardReceiveClaimReward`、`MasterChargeRewardProcessChange`。
- **积分注册**：`IsRegisterPointRequired` → **false**，勿在 Master 积分管线强行依赖本玩法。
- **配置约束**：红点逻辑 **写死** 使用 `conf.groups[1]`，若配表改为多 group 需同步改模块（契约变更）。
- **多档可领**：红点数为 **可领档位数之和**，UI 若只显示圆点不显示数字，需确认 `GetCommonTypeDict` 行为是否符合设计。
- **进度回退**：若服务端 `process` 因异常回退，客户端以新值为准；UI 需容错 **已领标记仍存在** 的短暂不一致（依赖下次全量数据）。
- **领奖请求**：`RequestClaimRewards` 无参数，若未来扩展为「单档领取」需 **新增协议/参数** 并全量搜调用方。

10. 配表结构（MasterChargeReward.xls）


### Sheet: MasterChargeReward（主表）

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一id |
| comment | string | - | 备注名 |
| groups | Group | array | 分组列表，引用 Group 子表 |
| cycle_type | string | - | 为空表示 start_time到end_time为一次周期，daily表示天为周期刷，weekly表示周，monthly表示月 |
| type | string | - | 区分累充和点券消耗两个功能，累充:currency；累消：conch |
| go_now | object | - | 跳游戏内界面 Go Now（界面跳转）规则 |
| system_mail | string | - | 补发奖励邮件，对应的邮件id |
| umg | string | - | UMG配置 |
| special_reward | yield | array | 特殊奖励，需要单独汇总和特殊展示,奖励数量配1 |

### Sheet: Group（子表：Group）

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一id |
| comment | string | - | 备注名 |
| stages | Stage | array | 组里包含的充值档位，引用 Stage 子表 |
| stage_unlock_next_group | int | - | 玩家完成本组的第几档次才能看到下一组的条件和奖励 |

### Sheet: Stage（子表：Stage）

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一id |
| target | int | - | 需要达到的充值金额 |
| rewards | yield | array | 该档次的奖励 |
| comment | string | - | 差额 |
| image | string | - | 档位底图配置 |
