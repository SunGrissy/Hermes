<!--
参考代码文件:
- lua/framework/components/game_module/module_impl/master_play_module/master_play_bank_module.lua
最后参考时间: 2026-04-16
-->
================================================================================
                        银行（MasterBank）玩法说明
================================================================================
                           版本: 2026-04-16
================================================================================

1. 适用场景与需求匹配

### 核心玩法模式
活动期分为 **购买阶段（pay_time）** 与 **领取大奖阶段**：玩家先购 **档位 tier** 与礼包，用 **福利金（MasterPoint）** 等累积；最终在 Claim 阶段领取 **终极大奖**；支持 **免费礼包每日刷新** 红点。

### 典型需求场景
金库/银行类长线付费、定时开放领奖、免费与付费档并存；需要清晰区分 **Buy / Claim / None** 三态用于 UI 与红点。

### 能力标签
`MasterBankState`、终极大奖协议、跨天刷新免费红点、完成条件综合 **结束时间 / 已领大奖 / 无剩余福利金**。

### 与相似玩法的区别
相对 **Piggy（存钱罐）**：银行强调 **阶段状态机 + 福利金 point_id + 终极大奖**；存钱罐侧重 **多档 piggy 累积与破罐**，协议与完成判定不同。

---

2. 玩法概述
仅注册 **`MasterBankClaimBigReward`**；成功后将 `info.big_reward` 置 1，缓存 `yield_result` 供 `PlayCachedRewardMessageBox` 播放，并 `CheckAndComplete`。`GetMasterBankState` 用活动 `start_time`、`end_time` 与 `pay_time` 划分阶段。

### 关键时序（摘要）
1. 活动数据刷新 → `OnMasterPlayInfoRefresh` → `CheckAndComplete`（可能一上来就 `MasterPlayComplete`）。
2. 玩家领终极大奖 → `OnClaimBigRewardReturn` → `big_reward=1` → 派发事件 → 播缓存恭喜获得 → 延迟关主 UI。
3. 跨天 → `OnNewDay` 仅 **重算红点**，不自动领大奖。

### 阶段与 UI
- **Buy**：付费期，关注免费礼包红点 `FreeRedDot`。
- **Claim**：付费期结束后的领奖期，气泡红点常亮提示可前往领大奖（具体交互由 UI 决定）。

---

3. 玩法类型定义
- **类名（概念）**：`MasterBank`
- **模块**：`MasterPlayBankModule`
- **基类**：`MasterPlayModuleBase`
- **枚举**：`MasterBankState`（`None` / `Buy` / `Claim`）

---

4. 核心模块说明
- **档位数据**：`GetPaidTierData` — 按 `info.tier_id` 在 `conf.paid_tiers` 中查找。
- **福利金数量**：`GetBonusCount` — `MasterPointModule:GetMasterPointCount(conf.point_id)`。
- **免费礼包**：`HasFreeChargeLeft` — 结合 `free_reward_time` 与 `GetIsDailyRefreshByChargeId`（charge_id 含 `"free"` 字样的项）。
- **购买后刷新**：`SetFreeRewardTime` 写当前服务器时间并重算红点。
- **缓存**：`cache_yield_result`、`cache_master_play_id` 供恭喜获得与随后 `MasterTestCloseMainUI`。

---

5. 数据结构
- **`info.big_reward`**：是否已领取终极大奖（非 0 表示已领）。
- **`info.free_reward_time`**：上次领取免费礼包时间戳（0 表示可领等语义由 `HasFreeChargeLeft` 解析）。
- **`info.tier_id`**：当前付费档位。
- **配置**：`conf.paid_tiers`、`conf.all_paid`、`conf.pay_time`、`conf.point_id`。

---

6. 协议与接口
| 方向 | MessageType | 回调 | 说明 |
|------|-------------|------|------|
| 下行 | `MasterBankClaimBigReward` | `OnClaimBigRewardReturn` | 领取终极大奖，`DispatchEvent(MasterBankClaimBigReward, ..., bonus_index+1)` |

**对外**：`RequestClaimBigReward`、`PlayCachedRewardMessageBox(master_id)`。

### 事件参数
- `MasterBankClaimBigReward` 事件第二参为 **`msg.res.bonus_index + 1`**（Lua 层 +1 后的展示索引）。

---

7. 红点系统
- **主注册 Key（`GetRedDotKey`）**：`MasterBank_FreeRedDot_{master_play_id}` — **购买阶段**且仍有免费礼包可领 → 1。
- **气泡 Key（独立）**：`MasterBank_BubbleRedDot_{master_play_id}` — **Claim 阶段**常亮 1（用于大奖可领提示，**未拼进 GetRedDotKey**）。
- **跨天**：`ANewDay` 触发全量 `CalcRedDotNumber`。

---

8. 完成条件
以下任一为真即视为完成：`master_data:Conf().end_time` 已到、`info.big_reward ~= 0`、或 **已过付费期**（`cur_time >= start_time + pay_time`）且 **`GetBonusCount <= 0`**（无剩余福利金）。

---

9. 开发注意事项
- **派发**：`MasterBankClaimBigReward`、`MasterPlayComplete`（`CheckAndComplete` / `OnMasterPlayInfoRefresh`）。
- **恭喜获得后**：`StartTask` 延迟关闭主 UI，避免与奖励弹窗抢焦点。
- **工具函数扩展**：新增 charge 规则时同步维护 `GetIsDailyRefreshByChargeId` 与 `HasFreeChargeLeft` 分支。
- **福利金耗尽**：`CheckComplete` 的 `no_bonus` 分支依赖 `GetBonusCount`，改 point 类型或同步逻辑时需回归 **活动未结束但已无福利金** 是否误完成。
- **Bubble 红点**：`GetRedDotKey` 未包含 Bubble，入口若只绑主 key 会漏掉 **Claim 阶段提示**，需双绑或自定义聚合。
- **缓存清理**：`PlayCachedRewardMessageBox` 播放结束才清空 `cache_yield_result`，异常路径若未播放需自查是否泄漏。

10. 配表结构（MasterBank.xls）


### Sheet: Bank（主表）

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 玩法id |
| comment | string | - | 自己看的备注 |
| paid_tiers | PaidTier | array | 根据付费金额推送的产出，根据tiers_type决定用哪个属性来区分，引用 PaidTier 子表 |
| pay_time | duration | - | 购买礼包的时间 |
| default_chip | int | - | 宝库默认的金币 |
| bonus | Bonus | array | 开启金库时获得的随机加成，引用 Bonus 子表 |
| ab_test_id | string | - | 填写AB测试的id |
| reward_mail | string | - | 未领取奖励补发邮件 |
| point_id | string | - | 积分id |

### Sheet: Paid（子表：Paid）

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 玩法id |
| comment | string | - | 自己看的备注 |
| charge | string | - | 计费点id |
| is_daily_refresh | int | - | 是否每日刷新 |

### Sheet: PaidTier（子表：PaidTier）

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一ID |
| comment | string | - | 备注名 |
| paid_items | Paid | array | 礼包产出，引用 Paid 子表 |
| ab_test_label | string | - | ab测试标签 |
| condition_1 | string | - | 条件1类型 |
| c1_min | int | - | 条件1小值 / -1无穷小 |
| c1_max | int | - | 条件1大值 / -1无穷大 |
| condition_2 | string | - | 条件2类型 |
| c2_min | int | - | 条件2小值 / -1无穷小 |
| c2_max | int | - | 条件2大值 / -1无穷大 |

### Sheet: Bonus（子表：Bonus）

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 玩法id |
| bonus | float | - | 加成 |
| rate | int | - | 当前加成的权重 |
| first_rate | int | - | 首次加成权重 |
| comment | string | - | 备注名 |
