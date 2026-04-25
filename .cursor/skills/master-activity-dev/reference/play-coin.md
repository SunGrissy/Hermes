<!--
参考代码文件:
- lua/framework/components/game_module/module_impl/master_play_module/master_play_coin_module.lua
最后参考时间: 2026-04-16
-->
================================================================================
                        金币活动（MasterCoin）玩法说明
================================================================================
                           版本: 2026-04-16
================================================================================

1. 适用场景与需求匹配

### 核心玩法模式
**按自然日（`day_str`）** 维护多组任务进度与领取次数；完成进度推进与 **金币翻倍领取**（`coin` 段）；支持 **跨天邮件补偿** 协议拉取最新 `task`/`coin`。

### 典型需求场景
每日金币福利、活跃任务链、炮倍/VIP 对应基础金币档；需处理 **进房强弹**、**恭喜获得缓存** 与 **服务器日期未就绪** 时不发协议。

### 能力标签
每日循环、任务状态机 `MasterCoinTaskState`、金币可领红点、跨天 `MasterCoinNewDayMail`。

### 与相似玩法的区别
相对 **MasterCoinNewBie（Coin V2）**：V1 数据结构为 **`task[day_str][task_id]`** 的按日嵌套；V2 为扁平 `task[task_id]` + `coin_pre`，且 V2 **有 CheckComplete**（新手向「领完即结束」）。

---

2. 玩法概述
模块注册四类协议：单任务领奖、合并领奖（今日/昨日）、进度推送、跨天邮件。`CanRequest` 要求 `today_date_str` 与当前服务器日期一致，避免 `19700101` 等无效日期乱发请求。`Dispose` 时尝试播放缓存的恭喜获得。

### 关键时序（摘要）
1. 登录/同步时间 → `UpdateTodayDateStr`，无效日期则 `CanRequest` 为 false，点击领奖会 Tip。
2. 跨天 → `ANewDay` 对活跃活动推 `MasterCoinNewDayMail` → 可能整体替换 `coin`/`task`。
3. 合并领奖（今日）→ 缓存 `cache_yield_result_msg`，若主界面未打开则 `TryPlayCachedRewardMessageBox` 立即播，否则等 `Dispose`。

### 与 V2 的共享点
`SetNoPopToday` / `IsNoPopToday` 挂在 `MasterModule` 私有数据，**注释要求** V2 仅依赖 `master_id`，勿耦合 V1 任务结构。

---

3. 玩法类型定义
- **类名（概念）**：`MasterCoin`
- **模块**：`MasterPlayCoinModule`
- **基类**：`MasterPlayModuleBase`
- **枚举**：`MasterCoinTaskState`（`Claim` / `Doing` / `Done`）

---

4. 核心模块说明
- **任务状态**：`GetTaskState` / `GetTaskStateByData` 结合 `task_group` 配置与当日 `task[date_str][task_id].p`、`.ct`。
- **今日展示数据**：`GetTodayMainData` — 基础金币、加成 point、已领 `cur_chip`；超能膨胀算在 **point** 上（见模块内注释）。
- **跨天**：`ANewDay` 对活跃活动推 `MasterCoinNewDayMail`；返回里可能按 `MasterPlayClassID` 合并多玩法 class 数据。
- **模块字段**：`can_pop_when_enter_room`、`today_date_str`、`cache_yield_result_msg`。

---

5. 数据结构
- **`info.task[day_str][task_id]`**：`p` 进度，`ct` 已领次数。
- **`info.coin[day_str]`**：`point`、`cur_chip` 等金币线数据。
- **私有数据**：`NoPopToday`（`SetNoPopToday` / `IsNoPopToday`，供 V2 等复用接口）。

---

6. 协议与接口
| 方向 | MessageType | 回调 | 说明 |
|------|-------------|------|------|
| 下行 | `MasterCoinClaimTaskReward` | `OnClaimTaskReward` | 单任务领奖 |
| 下行 | `MasterCoinClaimReward` | `OnClaimReward` | 今日连领或昨日补领 |
| 下行 | `MasterCoinPushInfo` | `OnPushInfo` | 任务进度推送 |
| 下行 | `MasterCoinNewDayMail` | `OnNewDayMail` | 跨天数据对齐 |

**对外**：`RequestClaimSingleTaskReward`、`RequestClaimTaskReward`（今日）、`RequestClaimYesterdayReward`。

### 参数约定
- `MasterCoinClaimTaskReward`：`params.group_index`、`params.task_id`。
- `MasterCoinClaimReward`：`params.today_reward` — 1 今日 / 0 昨日补领。

---

7. 红点系统
- **Key**：`MasterCoinRedDot_{master_play_id}`。
- **条件**：任一任务为 `Claim` **或** 当前可领金币量 `can_claim_coin > 0`（`GetTodayMainData` + `UIHelper.ChipMultipledBy`）。

---

8. 完成条件
模块内 **未实现** `CheckComplete`（长期每日活动，无统一「毕业」判定）。

---

9. 开发注意事项
- **监听**：`ANewDay`、`SynchronizeServerTime`、`BreakGrowthChipInflationValueChanged`、`WeaponBetInflationChanged`。
- **派发**：`MasterCoinClaimTaskReward`、`ShowYieldResult`、`MasterCoinClaimReward`、`MasterCoinProgressUpdate`、`MasterCoinNewDay`。
- **竞态**：`OnPushInfo` 注释 — 付费礼包解锁可能导致 **推送早于活动解锁协议**，需 `play_info` 判空。
- **Dispose**：离开模块时 `TryPlayCachedRewardMessageBox` 防止缓存丢失。
- **跨天邮件**：`OnNewDayMail` 内可能 `SyncMasterPointCountByType`，改 point 配置需防 **重复同步** 副作用。
- **昨日领奖**：`OnClaimReward` 今日_reward==0 分支会清空当日 `task`/`coin`，UI 切换日期入口需防抖。
- **进房强弹**：配合 `can_pop_when_enter_room` 与业务 HUD，勿在模块内直接写死渔场逻辑。

---

10. 配表结构（MasterCoin.xls）

### Sheet: MasterCoin

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一 id |
| comment | string | - | 自己看的备注 |
| basic_type | string | - | 金币基数类型 / bet：以炮倍为基数 / vip：以vip指定的金币为基数 |
| basic_chip | BasicChip | array | 金币基数类型，1炮倍=1金币；vip分级算金币。引用 BasicChip 子表 |
| point | string | - | 积分id |
| task_group | TaskGroup | array | 任务组，引用 TaskGroup 子表 |
| reward_today_mail | string | - | 今日金币补发邮件 |
| reward_tomorrow_mail | string | - | 明日奖励补发邮件 |

### Sheet: BasicChip

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一 id |
| comment | string | - | 自己看的备注 |
| number | int | - | 不同地方意思不一样 / 炮倍代表炮倍对应的id / vip代表vip等级 |
| chip | yield | array | 基础金币 |

### Sheet: TaskGroup

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一 id |
| comment | string | - | 自己看的备注 |
| task | AllTask | array | 金币基数类型，引用 AllTask 子表 |

### Sheet: AllTask

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 任务id |
| comment | string | - | 相当于备注名，自己看的 |
| display_name | string | - | i18n key |
| task_action | string | - | 具体的任务条件类型 |
| task_filters | object | array | 过滤事件 |
| task_value | object | - | 如何累加值 |
| rewards | yield | array | 完成本任务可领的奖励 |
| claim_times | int | - | 本条子任务可重复领取的总次数 |
| go_now | object | - | 跳转配置，如果不为空，任务没完成时显示“前往”按钮，点击跳转到配置的界面 |

### Sheet: Draft

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| 10 | 20 | - | 30 |
| [{User:Chip:10}] | User:Chip:20 | array > dict | [{User:Chip:30}] |
| [{User:Chip: | - | - | - |
| }] | - | - | - |
