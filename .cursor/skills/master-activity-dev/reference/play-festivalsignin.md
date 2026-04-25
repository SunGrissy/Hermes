<!--
参考代码文件:
- lua/framework/components/game_module/module_impl/master_play_module/master_play_signin_modules/master_play_festival_signin_module.lua
最后参考时间: 2026-04-16
-->
================================================================================
                        节日签到（MasterFestivalSignIn）玩法说明
================================================================================
                           版本: 2026-04-16
================================================================================

1. 适用场景与需求匹配

### 核心玩法模式
限时节日签到：按活动天索引领取奖励；支持 **充值补签**、**VIP 额外金币补领**；`summary` 在刷新时汇总首日时间戳、分大区金币与其它奖励，供界面一次性展示。

### 典型需求场景
春节/周年庆等短期签到、带付费补签与 VIP 差额补领的运营活动；需要与充值、VIP、膨胀系数联动的签到。

### 能力标签
节日签到、充值补签、VIP 补领、按天时间轴索引、红点编码（今日可签/补签/VIP 位）。

### 与相似玩法的区别
- 继承 **`MasterPlaySignInModuleBase`**，与 **MasterSignIn** 的协议集合与红点策略不同。
- 含 **`catch_up_type` / `vip_reward_reissue`** 等节日专用逻辑；普通 SignIn 以多列表与 `add/replace` 为主（见 `play-signin.md`）。

---

2. 玩法概述
`MasterPlayFestivalSignInModule` 使用 **共享推送** `MasterSignIn` 与独立推送 `MasterSignInClaimVipExtraReward`；监听充值结束、VIP、跨天、膨胀相关事件以重算可领金币与红点编码。

**典型流程**
1. `RequestSignIn` → `OnSignInReturn` 更新 `sign_status` / `catch_up_days`。
2. 需领 VIP 差额 → `RequestClaimVipExtraReward` → `OnClaimVipExtraRewardReturn`。
3. UI 读取 `summary` 展示总览与分区金币。

---

3. 玩法类型定义
**枚举 `MasterSignInCatchUpType`**：`None = ""`、`Charge = "paid"`、`ConsumeDiamond = "consumeDiamond"`。

---

4. 核心模块说明
| 职责 | 说明 |
|------|------|
| 请求 | `RequestSignIn`、`RequestClaimVipExtraReward` |
| 索引 | `GetTodayIndex`、`IsValidDayIndex` |
| 数值 | `GetVipRewardMultiply`、`GetMaxChipCountClaimeAble`、`GetChipCountClaimed`、`GetVipExtraChipCount`、`GetCatchUpChipCount` |
| 事件 | 监听 `RechargeEnd`、`VIPInfoChanged`、`ANewDay`、`BreakGrowthChipInflationValueChanged`、`WeaponBetInflationChanged`；派发 `MasterSignInReturn`、`MasterSignInClaimVipExtraRewardReturn`、`MasterSignInPaidCurrencyChanged` |

---

5. 数据结构
- **`conf`**：`signin_rewards`、`catch_up_type`、`catch_up_param1`、`vip_reward_reissue` 等
- **`info`**：`catch_up_days`、`sign_status`、`paid_currency` 等
- **`summary`**：`first_day_timestamp`、`reward_chip`、`reward_others`、`reward_chip_by_vip_region` —— 供主界面减少重复计算

---

6. 协议与接口
- **RegisterSharedPushHandler**：`MasterSignIn` → `OnSignInReturn`
- **RegisterPushHandler**：`MasterSignInClaimVipExtraReward` → `OnClaimVipExtraRewardReturn`
- **出站**：`MasterSignIn`、`MasterSignInClaimVipExtraReward`

---

7. 红点系统
- `GetRedDotKey` = `GetRedDotKey_Reward`：`"Master_FestivalSignIn_RedDot_" .. master_play_id`
- `CalcRedDotNumber`：**编码** —— `today_index * 100`（可签主态） + `10`（补签） + `1`（VIP 额外）；调试时勿当普通 0/1

---

8. 完成条件
模块内 **未定义** `CheckComplete` 覆写。

---

9. 开发注意事项
- 红点为 **位编码**，改 UI 条件时务必对照 `CalcRedDotNumber` 全文，避免截断或比较错误。
- 膨胀与武器下注变更会触发重算，主界面需订阅 `BreakGrowthChipInflationValueChanged` / `WeaponBetInflationChanged`。
- 与商店充值回调 `RechargeEnd` 耦合，改付费补签流程时验证 `paid_currency` 与推送顺序。
- `summary` 为客户端派生数据，**勿直接篡改** 引用表当作持久状态；以后端 `info` 为准。

**联调与测试建议**
- `catch_up_type` 为 `ConsumeDiamond` 时，钻石余额与补签扣费顺序需与服务器一致。
- VIP 变更后 `GetVipExtraChipCount` 与展示金币应对齐，避免「可领」与按钮灰态矛盾。
- `first_day_timestamp` 用于活动期展示，时区错误会导致「第几天」整页偏移。

**共享推送注意**
- `RegisterSharedPushHandler` 可能在多玩法间共享路由，处理函数内务必校验 `master_play_id`。

10. 配表结构（MasterFestivalSignIn.xls）

### Sheet: MasterFestivalSignIn

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一ID |
| comment | string | - | 注释 |
| signin_rewards | SignReward | array | 签到奖励，List长度是N天（签到天数），引用 SignReward 子表 |
| vip_free_double | object | array | 免费奖励的金币翻倍倍数，根据vip不同，倍数不同{vip:倍数} |
| catch_up_type | string | - | 补签的解锁方式，paid-充值，consumeDiamond-消耗钻石 |
| catch_up_param1 | int | - | 补签的具体条件，type不同，含义不同，paid-充值的金额，consumeDiamond-特权等级 |
| catch_up_param2 | string | array | 补签的具体条件，type不同，含义不同，conume-消耗的钻石数 |
| vip_reward_reissue | int | - | 是否有vip升级补领 |
| congratulations_umg | string | - | 恭喜获得的umg，为空表示使用通用的 |
| reward_recycle_mail | string | - | 奖励补发的邮件#R:SystemMail |
| subtitle_string | string | - | 庆典节日打卡的副标题 / 配置i18n的key / 不配置默认为master_festival_desc |

### Sheet: SignReward

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一ID |
| comment | string | - | 注释 |
| date | string | - | 日期 |
| daily_reward | yield | array | 免费奖励 |
| vip_reward_multiply | object | array | 免费奖励中全部奖励的翻倍倍数，根据vip不同，倍数不同{vip:倍数} |
| daily_reward_image | string | - | 奖励图标内容 |
| back_image | string | - | 背面图片内容 |
| back_voice | string | - | 吉祥话语音 |
| vip_extra_rewards_free | VipReward | array | 根据VIP等级的额外免费奖励，List是可能有多个VIP的不同奖励，int表示vip等级，不配则没有，引用 VipReward 子表 |
| reward_free | yield | array | 免费奖励 |

### Sheet: VipReward

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一ID |
| comment | string | - | 注释 |
| number | int | - | vip等级，大于等于该等级才能领奖 |
| reward | yield | array | 奖励 |

### Sheet: IntYield

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一ID |
| comment | string | - | 注释 |
| number | int | - | 不同地方意思不一样 |
| reward | yield | array | 奖励 |
