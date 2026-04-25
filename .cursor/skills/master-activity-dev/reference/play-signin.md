<!--
参考代码文件:
- lua/framework/components/game_module/module_impl/master_play_module/master_play_signin_module.lua
最后参考时间: 2026-04-16
-->
================================================================================
                        签到（MasterSignIn）玩法说明
================================================================================
                           版本: 2026-04-16
================================================================================

1. 适用场景与需求匹配

### 核心玩法模式
按天领取 **免费 / 付费 / VIP 额外** 档奖励，支持补签、付费线解锁、追赶与加倍等扩展字段；`conf.type` 为 `add` 等时与 `login_days` 等统计联动。

### 典型需求场景
每日登录签到、VIP 额外倍率、补签付费、首登领奖、需要区分多档按钮态的签到页。

### 能力标签
每日签到、免费与付费档、VIP 倍率、补签、多列表状态（`free_rewards` / `paid_rewards` / `vip_free_extra`）。

### 与相似玩法的区别
相对 **MasterFestivalSignIn**：本模块为 **常规 SignIn** 数据模型（含 `add`/`replace` 等模式）；节日签到在 **充值补签、VIP 补领差额、按天时间戳索引** 等方面单独扩展，且继承 **`MasterPlaySignInModuleBase`** 的另一子分支（见 `play-festivalsignin.md`）。

---

2. 玩法概述
`MasterPlaySignInModule` 处理 `MasterSignInDoSignIn`、`MasterSignInStatusChange`、`MasterSignInMakeUpReward` 等推送，维护各天领取状态与付费解锁标记，并向 UI 派发领奖与解锁事件；跨天与 VIP 变更时刷新可领状态。

**典型流程**
1. 打开界面拉取/刷新 info → 根据 `free_rewards` 等列表渲染天格子。
2. 点击签到 → `RequestDoSignIn` → `RecieveDoSignIn`。
3. 补签 → `RequestSignInMakeUpReward` → `ReceiveSignInMakeUpReward`。

---

3. 玩法类型定义
**枚举 `MasterSignInRewardType`**：`Free = 1`、`Paid = 2`、`VipExtra = 3`。

---

4. 核心模块说明
| 职责 | 说明 |
|------|------|
| 请求 | `RequestDoSignIn`、`RequestSignInMakeUpReward` |
| 展示 | `ShowRewards`、`HasPaidReward`、`IsFreeClaimed`、`IsPaidClaimed`、`GetAvailableDayNum`、`GetDaysNotSigned`、`IsAllSignInCompleted` |
| 数值 | `GetVipRewardMultiply`、`GetFixedChipNumber`、`GetRewardChipByVipRegion` |
| 事件 | 监听 `VIPInfoChanged`、`ANewDay`；派发首登领奖、补签结果、付费/追赶解锁、信息就绪等 |

---

5. 数据结构（节选）
- **`info`**：`free_rewards`、`paid_rewards`、`vip_free_extra`、`claim_chip`、`paid_extra`（按天索引的字符串 key）、`paid_unlock`、`early_unlock`、`catch_up_unlock`、`double_unlock`、`login_days`（`type=="add"`）等
- 具体字段含义以源码与 **MasterSignIn 配表** 为准，切勿凭名猜测服务端语义

---

6. 协议与接口
- **RegisterPushHandler**：`MasterSignInDoSignIn` → `RecieveDoSignIn`；`MasterSignInStatusChange` → `OnSignInStatusChange`；`MasterSignInMakeUpReward` → `ReceiveSignInMakeUpReward`
- **出站**：`MasterSignInDoSignIn`、`MasterSignInMakeUpReward`

---

7. 红点系统
- **Common**：`GetRedDotKey_Common` → `"MasterSignInRewards_" .. masterPlayId`
- **VIP 补签等**：`GetRedDotKey_VIPFix` → `"MasterSignInVIPFixRewards_" .. masterPlayId`
- UI 层通常合并两类子红点或分入口展示

---

8. 完成条件
模块内 **未定义** `CheckComplete` 覆写；活动「全部签完」若参与 Master 完成判定，需在策划侧确认是否由其它模块或基类处理。

---

9. 开发注意事项
- 与 VIP、跨天强相关：补签与 VIP 档变化必须监听对应事件并刷新列表。
- 与节日签到并存时，勿混用协议与红点 key。
- 展示金币等数值时使用 `GetRewardChipByVipRegion` 等封装，避免重复实现膨胀。
- `paid_extra` 等使用 **字符串天 key** 时，注意与服务器时区、活动日边界一致。

**联调与测试建议**
- `MasterSignInStatusChange` 到达时 UI 应全量刷新，避免仅改单日格子导致状态漂移。
- 首登领奖与引导事件顺序：确认 `MasterSignInClaimFirstDayFreeReward` 仅触发一次。
- 付费解锁与追赶解锁并存时，按钮显隐依赖 `paid_unlock` / `catch_up_unlock` 组合，需列矩阵用例。

**UI 建议**
- 多档奖励并列时，用 `MasterSignInRewardType` 区分样式，避免硬编码天数索引。

10. 配表结构（MasterSignIn.xls）

### Sheet: MasterSignIn

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一ID |
| comment | string | - | 注释 |
| type | string | - | 签到的类型，跟随活动日期走-date、累计签到天数-add、连续签到-series |
| boost_free | string | array | 免费奖励受哪些boost影响？ / 只对免费奖励的金币生效 |
| boost_paid | string | array | 付费奖励受哪些boost影响？ / 只对付费奖励的金币生效 |
| signin_rewards | SignReward | array | 签到奖励，List长度是N天（签到天数），引用 SignReward 子表 |
| cumulative_rewards | ProgressReward | array | 累计签到奖励，int是天数，不配则没有，引用 ProgressReward 子表 |
| paid_type | string | - | 付费奖励的解锁方式，paid-充值，consume-消耗，charge-购买指定charge |
| paid_condition | string | - | 付费奖励的具体解锁条件，type不同，含义不同，paid-充值的最低金额，consume-消耗的最低点券数，charge-需要购买的charge id |
| double_claim_condition | string | - | 再领一次条件： / excode-兑换码解锁 |
| catch_up_type | string | - | 补签的解锁方式，paid-充值，charge-购买指定礼包 |
| catch_up_param1 | int | - | 补签的具体条件 / chtch_up_tpye==paid时，配置充值的金额 |
| catch_up_param2 | string | array | 补签的具体条件 / chtch_up_tpye==charge时，配置礼包的charge id |
| catch_ahead_tpye | string | - | 提前签到的解锁方式，paid-充值，charge-购买指定礼包 / 如果不配则不支持提前签到 |
| catch_ahead_param1 | int | - | 提前签到的具体条件，type不同，含义不同，paid-充值的金额，节日打卡功能该字段配置补签VIP等级 |
| catch_ahead_param2 | string | array | 提前签到的具体条件，type不同，含义不同，conume-消耗的钻石数，charge-需要购买的charge id |
| catch_up_max | int | - | 补签最大次数限制，配置0代表不限制 |
| per_card_number | int | - | 获得1张补签卡，需要充值的金额，-1不给卡 |
| early_condition | int | - | 提前签到的条件，最低充值多少金额后有提前签到功能，不配置的该签到无法提前签到 |
| congratulations_umg | string | - | 恭喜获得的umg，为空表示使用通用的 |
| unlock_umg | string | - | 购买页的UMG，为空代表使用通用的，不需要单独换皮 |
| unlock_tip | string | - | 购买页的文本 |
| reward_recycle_mail | string | - | 奖励补发的邮件，不配则没有奖励补发 |

### Sheet: SignReward

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一ID |
| comment | string | - | 注释 |
| reward_free | yield | array | 免费奖励 |
| vip_extra_rewards_free | VipReward | array | 根据VIP等级的额外免费奖励，List是可能有多个VIP的不同奖励，int表示vip等级，不配则没有，引用 VipReward 子表 |
| reward_paid | yield | array | 付费奖励，不配则没有 |
| vip_chip_reward_multiply | object | array | 免费奖励中全部奖励的翻倍倍数，根据vip不同，倍数不同{vip:倍数} |
| reward_level | int | - | 奖励价值等级，0为最高 / 前端用，确定奖励背景 |

### Sheet: IntYield

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一ID |
| comment | string | - | 注释 |
| number | int | - | 不同地方意思不一样 |
| reward | yield | array | 奖励 |

### Sheet: VipReward

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一ID |
| comment | string | - | 注释 |
| number | int | - | vip等级，大于等于该等级才能领奖 |
| reward | yield | array | 奖励 |

### Sheet: ProgressReward

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一ID |
| comment | string | - | 注释 |
| number | int | - | 累计签到几天才能领奖 |
| reward | yield | array | 奖励 |
