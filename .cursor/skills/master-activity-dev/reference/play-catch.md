<!--
参考代码文件:
- lua/framework/components/game_module/module_impl/master_play_module/master_play_catch_module.lua
最后参考时间: 2026-04-16
-->
================================================================================
                        捕获（MasterCatch）玩法说明
================================================================================
                           版本: 2026-04-16
================================================================================

1. 适用场景与需求匹配

### 核心玩法模式
**多付费包（paid）并行**：每包有 **积分 point、购买次数 buy、里程碑 reward_state**；可付费解锁奖池，达成里程碑领取奖励；支持 **积分推送** 与 **商店购买** 本地补齐 `buy`。

### 典型需求场景
捕获类收集活动、多 Tab 展示、满进度/推荐购买引导；部分活动耦合 **战魂退炮** 等特殊弹窗（`CloseWeaponEvent`）。

### 能力标签
收集、付费解锁、里程碑、多 Tab 红点（Common/Filled/Recommend）、私有数据 `CatchData`。

### 与相似玩法的区别
相对纯任务玩法的 **按日任务结构**，Catch 以 **stones × all_paid** 的里程碑矩阵为主，完成条件为 **全里程碑均已登记 reward_state**。

---

2. 玩法概述
`MasterPlayCatchModule` 注册领取与 `PushMasterCatchInfo`；购买走 `ShopBuyReturn` 增量更新对应 `paidId` 的 `buy`。私有数据 `CatchData` 记录弹窗时间、进度快照、战魂专用每日次数等。`IsRegisterPointRequired` 返回 `false`，但在 `point_type == "point"` 时仍会 `CheckPointRegistered`。

### 关键时序（摘要）
1. `OnMasterPlayInfoRefresh`：为 `sort_list` 中各包初始化 `CatchData` 进度槽，并视配置注册 Master 积分点。
2. 积分推送：`OnMasterPlayCatchInfoRefresh` 只更新 **point**，然后尝试满额弹窗 → `MasterCacthRefreshPoint`。
3. 商店购买成功：本地 `buy+1` → `MasterCacthRefreshBuy`，**不等**下行全量刷新（注意与纯服务端计数活动差异）。

### Tab 与 sort_list
`sort_list` 的 **数组下标** 即 Tab 序号（1–3），红点 `GetRedDotKey_TabCommon` 使用该序号；新增 Tab 配置时需同步 `InitRedDot` 循环上限（当前写死 3）。

---

3. 玩法类型定义
- **类名（概念）**：`MasterCatch`
- **模块**：`MasterPlayCatchModule`
- **基类**：`MasterPlayModuleBase`
- **枚举**：`MasterCacthRewardState`、`UnavailableReason`（协议名为历史拼写 `MasterCacth*`）

---

4. 核心模块说明
- **领奖**：`RequestClaimRewards` → `RecieveClaimRewards`，按 `msg.res.change` 写入 `reward_state`，成功后可能 `CheckComplete` 并 `MasterPlayComplete`。
- **推送**：`OnMasterPlayCatchInfoRefresh` 更新各 `stones[].point`，尝试 `TryExecFilledPopUp`（满里程碑且未购买时的引导弹窗）。
- **战魂特例**：`OnCloseWeapon` → `TryExecCloseWeaponPopUp`（非通用，注释已说明）。
- **弹窗关闭**：`OnDialogClose` 把当前各包 `point` 写回 `CatchData`，用于跨会话对比是否「满额可推」。

---

5. 数据结构
- **`info.stones[paidId]`**：`point`、`buy`、`reward_state`（里程碑领取映射）。
- **`info.sort_list`**：Tab/包顺序。
- **`conf.all_paid[id].milestone`**：里程碑列表（含 `point`、`charge_times` 等）。
- **私有 `CatchData`**：`popUpTime`、各 `paidId` 进度缓存、`closeWeaponPopUpTime` / `closeWeaponPopUpTimes`（战魂弹窗限次）。

---

6. 协议与接口
| 方向 | MessageType | 回调 | 说明 |
|------|-------------|------|------|
| 下行 | `MasterCacthClaimReward` | `RecieveClaimRewards` | 领取里程碑奖励 |
| 推送 | `PushMasterCatchInfo` | `OnMasterPlayCatchInfoRefresh` | 积分等增量刷新 |

### 参数约定
- `MasterCacthClaimReward`：`params.paid_id` 指定领取哪一包里程碑。

---

7. 红点系统
- **`GetRedDotKey`**：当前实现为 **`GetRedDotKey_Common`** 的管道串（Tab 1–3 的 `GetRedDotKey_TabCommon` 用 `|` 拼接）。
- **Tab**：`MasterCatch_Common_{mpid}_{tabId}`；另 **`Filled`** / **`Recommend`** 后缀供满额/宣传引导（`InitRedDot` 三类均注册）。
- **`CalcRedDotNumber`**：已购买线算可领里程碑差；未购买线在满进度或宣传/里程碑标签下点亮 Filled/Recommend。

---

8. 完成条件
对每个 `info.stones` 中的包，遍历 `conf.all_paid[id].milestone`：**所有** `item.id` 在 `packge.reward_state` 中均有值（`nil` 表示未完成）。

---

9. 开发注意事项
- **监听**：`CloseWeaponEvent`、`ShopBuyReturn`、`MasterCacthDialogClose`（关闭时把进度写回 `CatchData`）。
- **派发**：`MasterCacthReceiveClaimReward`、`MasterPlayComplete`、`MasterCacthRefreshPoint`、`MasterCacthRefreshBuy`。
- **主界面复用**：动态列表重建时注意池化 Widget 归还规则（见项目 UI 规范）；本模块含较多 **业务特例**，扩展前确认是否应抽通用层。
- **协议拼写**：历史原因协议为 `MasterCacth*`，全文搜索时勿误改为 `MasterCatch`。
- **里程碑遍历**：`CheckComplete` 使用 `pairs` 遍历 milestone，若需「按顺序」展示请仅在 UI 层排序，完成条件仍以 **集合全领取** 为准。
- **`is_end_return`**：红点计算分支引用该字段，改配表时需回归 **活动结束后是否仍显示可领红点**。

---

10. 配表结构（MasterCatch.xls）

### Sheet: MasterCatch

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 活动id |
| comment | string | - | 注释 |
| display_name | string | - | 该任务的名字，用于补发邮件的读取。 |
| entry_icon | string | - | 前端用字段，用于配置入口图标 |
| ab_test_id | string | - | 填写AB测试的id |
| paid_tiers | PaidTier | array | 根据付费金额推送的产出，引用 PaidTier 子表 |
| point_type | string | - | 进度分数类型 / count：boss只数 / coin：打boss的金币数 / point：积分 |
| point_param | string | - | 根据point type不同，填写内容表示不同意思 / point：积分的id |
| is_end_return | int | - | 是否活动结束后返还点券。 / 1-是 / 0或空为-否 / 前端用该字段（为1）判断已购买且进度奖集满后不显示红点。 / 后端用该字段判断进度奖集满后是否可领取奖励，1为不可以领取。 |
| is_end_conch | int | - | 是否活动结束后直接将点券返还至玩家账户 |
| min_chip | yield | array | 单只boss要达到该金币数才计数，为空不限制 |
| min_bet | int | - | 最低可参与的炮ID / 为空不限制 |
| target_type | string | - | fish：某一个id的鱼，fishtype：鱼类型，比如黄金鱼/Boss |
| target_param | int | array | 根据target不同填写不同的参数，fish：填写Fish的base id / fishtype：下面的id填写FishType的value值 |
| target_tips1 | string | - | 当目标boss头像只有1个的时候，不显示boss栏，显示配置的提示语 |
| target_tips2 | string | - | 当目标target_type不是fish的时候，不显示boss栏，显示配置的提示语 |
| target_name | string | array | 和fish_id一一对应，显示boss的名称 |
| room_go_now | object | - | 前往捕获跳转参数 |
| reward_mail | string | - | 奖励补发邮件 |
| publicity_label | string | - | 宣传标签的配置，为空则是没有该标签 |
| milestone_label | string | - | 进度奖集满时的配置，为空则是没有该标签 |

### Sheet: PaidTier

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

### Sheet: Paid

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一ID |
| comment | string | - | 注释 |
| charge | string | - | 买的礼包的charge id |
| cycle_buy_limit | int | - | 周期内限购次数 |
| milestone | Milestone | array | 进度奖励，引用 Milestone 子表 |
| subtitle_word | string | - | 副标题宣传语的文案 |
| subtitle_num | int | - | 副标题中需要读的数，由后端下发，不填则表示没有 |
| subtitle_word_2 | string | - | 第二个副标题宣传语的文案 |
| rewards_icon | string | - | 大奖图标 |
| title_banner | string | - | 标题图 |
| preview_btn | string | - | 预览按钮 |
| go_now | object | - | 预览跳转参数 |
| get_way | string | array | 获取途径，填写GetWaySetting的id |
| reward_type | string | - | 奖励样式类型,图片：image,3d：3d |
| reward_blueprint | string | array | 蓝图类 |
| tab_type | string | - | tab样式类型,点券价格：prize,i18n：word |
| tab_word | string | - | i18n |
| resonance_btn | string | - | 炮翅共鸣按钮是否显示,显示：1,不显示：为空/0 |
| system_mail | string | - | 点券返还告知邮件 |
| title_num | string | - | 显示的返点券数量 |

### Sheet: Milestone

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一ID |
| comment | string | - | 注释 |
| point | int | - | 累计进度需要的分数 |
| rewards | yield | array | 进度奖励 |
| charge_times | int | - | 达到进度后可领取奖励。需要购买的礼包次数；所有进度奖励可领取的大前提是购买过1次，为空则默认为购买即可领取。 |
| panel_size | int | - | 进度奖在界面的大小 / 0-大；1-非大 |
| inflation_type | int | - | 如果进度奖励有金币的话需要判断 / 0，不膨胀 / 1，Fish.inflation / 2，Fish.free_inflation |
| boost_available | int | - | 如果进度奖励有金币的话需要判断 / 0，无充值boost / 1，有充值boost |
| tag | string | - | 奖励上方角标读点击显示道具描述配置，为空则不显示背景和多语言 |

### Sheet: Draft

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| catch_328_conch_2 | catch_328_conch_4 | - | catch_328_conch_6 |
| catch_328_conch_2,catch_328_conch_4,catch_328_conch_6,catch_328_conch_10, |  | - | - |
