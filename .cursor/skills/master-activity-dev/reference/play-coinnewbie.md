<!--
参考代码文件:
- lua/framework/components/game_module/module_impl/master_play_module/master_play_coin_newbie_module.lua
最后参考时间: 2026-04-16
-->
================================================================================
                        新手金币（MasterCoinNewBie / Coin V2）玩法说明
================================================================================
                           版本: 2026-04-16
================================================================================

1. 适用场景与需求匹配

### 核心玩法模式
在 **MasterCoin** 家族协议 **`MasterCoinV2*`** 上实现 **扁平任务表** `task[task_id]` 与 **`coin_pre` 占位结构**（后端为与任务层数对齐）；支持 **按天解锁任务**（`task_unlock_time`）、最后一天判断、以及 **完成后关闭主界面**。

### 典型需求场景
新手期金币福利、简化 UI、强引导；需要 **明确的「是否还有下一档金币」** 作为完成条件。

### 能力标签
新手向、Coin V2 协议、任务解锁链、`CheckComplete`、与 V1 共享 `MasterCoinTaskState` 语义。

### 与相似玩法的区别
相对 **MasterCoin（V1）**：V2 **无按日 `task[day_str]` 嵌套**；使用 `MasterCoinV2ClaimTaskReward` 等协议；**有 `CheckComplete`**（`coin_pre.coin.next_chip`）；跨天数据无效时 `IsDataInvalidOnNewDay` 返回 `true` 需重拉。

---

2. 玩法概述
注册 V2 三类下行；`OnClaimReward` 在领「第二份」时直接 `ShowYieldResult`，领「第一份」时缓存至 `cache_yield_result_msgs[master_id]` 并在合适的对话框时机 `TryPlayCachedRewardMessageBox`。`CheckComplete` 成功后派发 `MasterPlayComplete`。

### 关键时序（摘要）
1. 任务进度推送 → 扁平写入 `info.task[task_id].p` → `MasterCoinV2ProgressUpdate`。
2. 领第一份金币 → 缓存恭喜获得 → 若主界面已关则立刻尝试播放。
3. 领第二份 → 直接走 `ShowYieldResult`，并刷新 `coin_pre`。

### 解锁与最后一天
`GetUnlockTaskConf` 假定 **配置顺序=时间顺序**；`IsLastDay` 给 UI 做最后一天提示（带 2 秒容错）。

---

3. 玩法类型定义
- **类名（概念）**：`MasterCoinNewBie`（代码模块名 `MasterPlayCoinNewBieModule`）
- **模块**：`MasterPlayCoinNewBieModule`
- **基类**：`MasterPlayModuleBase`
- **任务状态**：复用 **`MasterCoinTaskState`**（定义于 `master_play_coin_module.lua`）

---

4. 核心模块说明
- **解锁任务列表**：`GetUnlockTaskConf` — 仅返回已解锁的 `task` 子集（配置顺序须由早到晚）。
- **任务是否解锁**：`IsTaskUnlock` — 活动开始时间 + `(task_unlock_time-1)` 天。
- **今日数据**：`GetTodayMainData` / `CalcPoint` — 与 V1 类似处理超能膨胀在 **point** 上。
- **命名说明**：模块注释 — `group_idx` 实为 **task 序号**；`coin_pre` 为后端占位层级。

---

5. 数据结构
- **`info.task[task_id]`**：`p`、`ct`。
- **`info.coin_pre`**：含 `coin.next_chip`、`coin.cur_chip`、`coin.point` 等（完成判定看 **`next_chip`**）。
- **`cache_yield_result_msgs[master_id]`**：与 V1 单消息不同，按 **master_id** 分桶缓存。

---

6. 协议与接口
| 方向 | MessageType | 回调 | 说明 |
|------|-------------|------|------|
| 下行 | `MasterCoinV2ClaimTaskReward` | `OnClaimTaskReward` | 单任务领奖 |
| 下行 | `MasterCoinV2ClaimReward` | `OnClaimReward` | 第一份/第二份金币领奖 |
| 下行 | `MasterCoinV2PushInfo` | `OnPushInfo` | 任务进度推送 |

**对外**：`RequestClaimSingleTaskReward`、`RequestClaimTaskReward`、`RequestClaimTheSecondReward`。

### 参数约定
- `MasterCoinV2ClaimReward`：`params.today_reward` — 1 第一份 / 0 第二份（与 V1 昨日/今日语义不同，勿混用文档）。

---

7. 红点系统
- **Key**：`MasterCoinV2RedDot_{master_play_id}`。
- **逻辑**：与 V1 类似 — 存在可 `Claim` 任务 **或** `can_claim_coin > 0`（此处用 `cur_base_coin * (cur_multi_num/100) - cur_claimed_coin`，未使用 `ChipMultipledBy`）。

---

8. 完成条件
若存在 `info.coin_pre` 且非空：**`info.coin_pre.coin.next_chip > 0`** 视为完成（与 **「还有下一档待领」** 语义一致；缺字段时返回 **nil/false**）。

---

9. 开发注意事项
- **监听**：`BreakGrowthChipInflationValueChanged`、`WeaponBetInflationChanged`。
- **派发**：`MasterCoinV2ClaimTaskReward`、`ShowYieldResult`、`MasterCoinV2ClaimReward`、`MasterPlayComplete`、`MasterCoinV2ProgressUpdate`。
- **恭喜获得**：`TryPlayCachedRewardMessageBox` 用 `CallEvent(ShowYieldResult,...)` 取 `popup_id` 做追踪。
- **Push 竞态**：同 V1，`OnPushInfo` 需 `play_info` 判空。
- **GetTaskState 循环**：`GetTaskState` 仍遍历完整 `group.task`，但判定状态时应以 **`GetUnlockTaskConf` 子集** 为准，否则未解锁任务会误判为 Doing。
- **跨天**：`IsDataInvalidOnNewDay` 为 true，Master 框架侧应触发数据重拉，勿只依赖本地缓存。
- **完成语义**：`next_chip > 0` 表示「仍有下一档金币可领」，与「任务全清」不是同一概念，策划文案需区分。

---

10. 配表结构（MasterCoinNewBie.xls）

### Sheet: MasterCoinNewBie

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一 id |
| comment | string | - | 自己看的备注 |
| basic_type | string | - | 金币基数类型 / bet：以炮倍为基数 / vip：以vip指定的金币为基数 |
| basic_chip | BasicChip | array | 金币基数类型，1炮倍=1金币；vip分级算金币。引用 BasicChip 子表 |
| point | string | - | 积分id |
| task_group | TaskGroup | array | 任务组，引用 TaskGroup 子表 |
| reward_return_mail | string | - | 奖励补发邮件 |

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
| task | AllTask | array | 任务组，引用 AllTask 子表 |

### Sheet: AllTask

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 任务id |
| comment | string | - | 相当于备注名，自己看的 |
| task_unlock_time | int | - | N，解锁的自然天数 |
| is_unlock | int | - | 是否解锁（完成前置任务且达到解锁天数）后计数 / 1：是 / 0或空：否，接到活动后开始计数 |
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
| coin_newbie_day1 | coin_newbie_day2 | - | coin_newbie_day3 |
