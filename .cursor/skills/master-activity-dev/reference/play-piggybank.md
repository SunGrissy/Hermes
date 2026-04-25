<!--
参考代码文件:
- lua/framework/components/game_module/module_impl/master_play_module/master_play_piggy_bank_module.lua
最后参考时间: 2026-04-16
-->
================================================================================
                        存钱罐（MasterPiggy / PiggyBank）玩法说明
================================================================================
                           版本: 2026-04-16
================================================================================

1. 适用场景与需求匹配

### 核心玩法模式
玩家购买 **多个付费档（paids）**，局内捕鱼累积 **罐内金币** `piggy_cur_chip`；协议推送进度，破罐/领奖走商店与恭喜获得链路；支持 **购买后复弹主界面**（`toggle_yield_show` + 阻塞 UI 清空）。

### 典型需求场景
存钱罐礼包、多档购买、累积可视化；与 **点券返还** 等商店逻辑存在时序耦合（模块内对 `user:conch` 做了补偿扣回）。

### 能力标签
付费多档、`PiggyBank` 专用协议、无 Master 积分注册、完成条件 **三档全购**。

### 与相似玩法的区别
相对 **MasterBank**：存钱罐无 **分期大奖/福利金档位** 状态机；协议注册方式特殊（见下文 **仅 [2]**）。

---

2. 玩法概述
`MasterPlayPiggyModule`：`PiggyBankRewardProgress` 更新 `piggy_cur_chip`；`PiggyBankLatestData` 将当前金币派发给 UI。`IsRegisterPointRequired` 为 **false**。购买回调里 **延迟一帧** 修正点券返还导致的双倍海螺显示问题。

### 关键时序（摘要）
1. 打开界面或需要刷新 → `RequestLatestData` → `PiggyBankReceiveLatestData(cur_chip)` 驱动条/数字。
2. 局内累积 → 推送 `OnRewardProgressUpdate` → `PiggyBankRewardProgressUpdate`。
3. 购买触发恭喜获得 → `ToggleYieldShow` 记下弹窗 → 关闭后与 `UIBlockEmpty` 配对再 `ShowMasterMainDialogAgain`。

### 与 MasterBank 的差异
存钱罐 **无** `MasterBankState` 阶段划分与福利金 point 线；核心字段为 **`paids` 购买态 + `piggy_cur_chip`**。

---

3. 玩法类型定义
- **类名（概念）**：`MasterPiggy` / `PiggyBank`（`MasterPlayType.PiggyBank`）
- **模块**：`MasterPlayPiggyModule`
- **基类**：`MasterPlayModuleBase`

---

4. 核心模块说明
- **最新数据**：`RequestLatestData` → `OnPiggyBankLatestData` → `PiggyBankReceiveLatestData`（参数为 `msg.cur_chip`）。
- **进度推送**：`OnRewardProgressUpdate` → `PiggyBankRewardProgressUpdate`。
- **多档购买**：`GetCurPaid` 找首个 `has_buy == 0` 的 `paid_id`。
- **解锁一起**：`IsUnlockTogether` 读 `conf.unlock_together`。
- **复弹**：`ToggleYieldShow` 记录弹窗 id；`YieldRewardMessageBoxClose` / `UIBlockEmpty` 配对后 `ShowMasterMainDialogAgain`。

---

5. 数据结构
- **`info.paids`**：每档 `paid_id`、`has_buy` 等。
- **`info.piggy_cur_chip`**：当前罐内金币（推送更新）。
- **运行时**：`toggle_yield_show`、`next_show_need_refresh_effect`（复弹前刷新动效标记）。

---

6. 协议与接口
| 方向 | MessageType | 回调 | 说明 |
|------|-------------|------|------|
| 推送/下行 | `PiggyBankRewardProgress` | `OnRewardProgressUpdate` | **仅注册 `[2]` 段**（非 `[1]_[2]` 拼接） |
| 下行 | `PiggyBankLatestData` | `OnPiggyBankLatestData` | 标准 `[1]_[2]` 注册 |

**注意**：新增或排查协议注册时务必核对 `MessageType.PiggyBankRewardProgress[2]` 的特殊写法。

### 回调签名
`OnPiggyBankLatestData` 注册为 **静态函数引用** `MasterPlayPiggyModule.OnPiggyBankLatestData`，排查 `self` 绑定时勿与普通实例方法混淆。

---

7. 红点系统
模块内 **未实现** `GetRedDotKey` / `CalcRedDotNumber`（无通用 Master 红点键逻辑，入口红点由活动/HUD 侧配置）。

---

8. 完成条件
当 **`#info.paids == 3`** 且 **三个档位的 `has_buy` 均非 0** 时返回 **true**；`PlayerInfo` 异常时有一分支返回 **true**（需结合调用场景理解，避免误关 UI）。

---

9. 开发注意事项
- **监听**：`PiggyBankBuyReturn`、`YieldRewardMessageBoxClose`、`UIBlockEmpty`。
- **派发**：`PiggyBankReceiveLatestData`、`PiggyBankRewardProgressUpdate`。
- **商店返还**：`OnPiggyBankBuyReturn` 内 `StartTask` 延迟扣海螺 — 修改奖励结构前需回归。
- **主界面再开**：`ShowDialog(..., {reason = "master_piggy_repop"})`。
- **`OnPiggyBankLatestData` 参数**：事件只带 **当前罐内金币** `cur_chip`，不带 `master_play_id`，监听方需自行绑定上下文。
- **完成分支**：`PlayerInfo` 缺失时 `CheckComplete` 返回 true 的路径易引发误关 UI，改动前务必做 **nil 回归**。
- **动效**：`next_show_need_refresh_effect` 与复弹联动，改 UI 动效触发条件时同步搜该字段引用。

10. 配表结构（MasterPiggy.xls）


### Sheet: MasterPiggy（主表）

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一ID |
| comment | string | - | 注释 |
| chip_number_formula | string | - | 每炮存金币数量（公式） |
| paid_tiers | PaidTier | array | 根据付费金额推送的产出，根据rec_tier_type决定用哪个属性来区分，引用 PaidTier 子表 |
| go_now | object | - | 主页的按钮跳转 |
| ab_test_id | string | - | 填写AB测试的id |
| paid_items | Paid | array | 付费内容，引用 Paid 子表 |
| rec_tier_type | string | - | vip_exp：累计付费金额 / 30_days_paid_amount:近30天累计付费 |
| unlock_together | int | - | 是否为同时解锁，0为顺序解锁，1为同时解锁 |

### Sheet: Paid（子表：Paid）

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一ID |
| comment | string | - | 注释 |
| charge | string | - | 计费点id |
| bank_base | int | - | 存钱罐金币基础产出 |
| bank_capacity | int | - | 存钱罐金币产出总上限 |
| extra_rewards | yield | array | 额外奖励（配置则有相关UI显示，不配置不显示） |
| bank_icon | string | - | 存钱罐图标-大图样式 |

### Sheet: PaidTier（子表：PaidTier）

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一ID |
| comment | string | - | 备注名 |
| paid_items | Paid | array | 礼包产出，引用 Paid 子表 |
| ab_test_label | string | - | ab测试标签 |
| condition_1 | string | - | 条件1类型 / 累充：vip_exp / 30天内：30_days_paid_amount |
| c1_min | int | - | 条件1小值 / -1无穷小 |
| c1_max | int | - | 条件1大值 / -1无穷大 |
| condition_2 | string | - | 条件2类型 |
| c2_min | int | - | 条件2小值 / -1无穷小 |
| c2_max | int | - | 条件2大值 / -1无穷大 |
| min | int | - | 这个类型tier的最小值-左闭-元，-1表示不限 |
| max | int | - | 这个类型tier的最大值-右闭-元 / ，-1表示不限 |
