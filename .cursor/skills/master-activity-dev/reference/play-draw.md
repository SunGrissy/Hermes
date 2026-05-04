<!--
参考代码文件:
- lua/framework/components/game_module/module_impl/master_play_module/master_play_draw_module.lua
最后参考时间: 2026-04-16
-->
================================================================================
                        抽奖（MasterDraw）玩法说明
================================================================================
                           版本: 2026-04-16
================================================================================

1. 适用场景与需求匹配

- **核心模式**：消耗积分或免费次数进行抽奖，获取随机奖励。
- **典型需求**：周年庆抽奖、活动抽奖、限时宝箱抽奖等通用抽奖活动。
- **能力标签**：随机奖励、积分消耗、免费次数、保底机制、连抽、幸运值。
- **与 SpinDraw 区别**：Draw 支持连抽、免费次数、保底等完整抽奖体系；SpinDraw 为单次转盘，逻辑更简单。
- **与 LiftingDraw 区别**：LiftingDraw 为多层级递进、每层独立奖池；Draw 为单奖池模型。

若活动需要「多抽一次」「免费抽」「幸运值/保底」等，优先选用本玩法而非 SpinDraw。

2. 玩法概述

MasterDraw 由 `MasterPlayDrawModule`（继承 `MasterPlayModuleBase`）实现，负责抽奖次数、奖池状态、存储（宝箱/道具）及与服务端的抽奖请求（单次、多抽、免费抽）。

3. 玩法类型定义

- **模块类**：`MasterPlayDrawModule`
- **基类**：`MasterPlayModuleBase`
- **实现文件**：`master_play_draw_module.lua`

4. 核心模块说明

模块封装抽奖流程：根据配置解析付费/免费积分类型、计算可抽次数、维护抽奖结果与存储数据，并向 UI 派发结果动画、拼图结算、玩法完成等事件。监听积分变化、跨天、以及「继续展示奖励」等事件以同步状态。

5. 数据结构

**玩法 info（关键字段）**

- `draw_times`：已抽次数。
- `base_id`：基础标识相关数据（与配置/奖池关联）。
- `draw_status`：各奖励位/奖励项的抽取计数或状态（per-reward counts）。
- `luck_value` / `inherit_luck_value`：幸运值及继承幸运值（用于保底等）。
- `free_times`：剩余免费次数。

**配置 conf（与完成条件相关）**

- `clear_condition`：清空/完成条件阈值（与 `draw_times` 比较）。
- `rewards_type`：奖励类型；若为 `"take_out"` 等与「最大可领奖励数」相关的模式，会影响完成判定。

6. 协议与接口

**下行推送（RegisterPushHandler）**

- `MessageType.MasterDraw` → `OnMasterDraw`

**上行请求（Outgoing / CreateMsg）**

- `MessageType.MasterDraw`：`RequestDraw`、`RequestMultiDraw`、`RequestFreeDraw`

**常用对外方法**

- `RequestDraw` / `RequestMultiDraw` / `RequestFreeDraw`
- `GetFreePointType`、`GetPaidPointType`
- `GetHasDrawnNum`、`GetMaxValidDrawTimes`、`GetDrawFreePointCountForOneDraw`
- `GetChestStorage`、`GetItemStorage`、`ParseChest`

7. 红点系统

- **入口**：`GetRedDotKey` 组合使用 `GetNormalRedDotKey`、`GetFreeRedDotKey`、`GetRemindRedDotKey`。
- **Normal**：`"Master_Draw_RedDot_" .. master_play_id`
- **Free**：`"Master_Draw_RedDot_" .. master_play_id .. "_Free"`
- **Remind**：`"Master_Draw_RedDot_" .. master_play_id .. "_Remind"`

8. 完成条件（CheckComplete）

- 若配置中存在 `conf.clear_condition`：当 `draw_times >= clear_condition` 时视为完成。
- 否则若 `rewards_type == "take_out"`：当 `draw_times >= GetMaxRewardNum` 时完成。
- 其他情况：返回 `false`。

9. 开发注意事项

**事件**

- **监听**：`MasterPointChanged`、`MasterDrawContinueShowReward`、`ANewDay`
- **派发**：`MasterDrawShowResultAnim`、`FinishPlayPicturePuzzleYield`、`MasterPlayComplete`、`MasterDrawStorageChanged`

实现 UI 或子玩法时，需在展示链路上订阅派发事件，并注意跨天与积分变化对可抽次数的影响。新增协议字段时同步更新 `draw_status`、存储解析与红点刷新逻辑。

10. 配表结构（MasterDraw.xls）

### Sheet: Draw

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 玩法id |
| comment | string | - | 自己看的备注 |
| free_point | string | - | 免费抽奖币的id,为空为不存在免费抽奖币 |
| paid_point | string | - | 付费抽奖币的id,为空为不存在付费抽奖币 |
| free_draw_num | int | - | 免费抽奖的次数，不配则没有免费抽奖次数 |
| cost | Cost | array | 抽奖消耗，引用 Cost 子表 |
| input_type | string | - | same：每次都一样 / increase：随次数递增 |
| inputs | int | array | same就填一个数，increase就枚举每一次消耗 |
| rewards_type | string | - | take_out：取出式 / random：每次独立随机 |
| pool | Pool | array | 奖池，引用 Pool 子表 |
| is_pre_big_rewards | int | - | 是否提前保底（当多个奖池都同时差2抽触发保底时，下一抽则提前保底，触发表中list排序为先的奖池的保底。 / 1=是，0或为空=不提前保底 |
| is_draw_bonus | int | - | 是否有以下抽奖相关的boost: / 1.道具返还draw_token_return / 2.抽奖金币增益draw_capsule_chip_bonus |
| inflation_type | int | - | 奖池中金币的膨胀属性 / 不膨胀：0 / 付费膨胀：1 / 免费膨胀：2 |
| boost_available | int | - | 奖池中金币产出是否受charge_chip_bonus影响，1为是，不配则不受影响 |
| is_double | int | - | 奖池中金币产出是否受charge_double_chip双倍金币影响，1为是，不配则不受影响 |
| recycle_mail | string | - | 抽奖币回收邮件 |
| related_recycle | string | array | 填写要同时回收的抽卡id |
| tab_title | string | - | 作为玩法tab的多语言 |
| congratulations_umg | string | - | 恭喜获得的umg，为空表示使用通用的 |
| big_reward_congratulations_umg | string | - | 大奖的恭喜获得，为空表示使用通用的 |
| congratulations_ranking_key | string | - | 恭喜获得排行榜积分提示 |
| clear_condition | int | - | 玩法完成要求(需要达成关键行为x次），为空则表示没有玩法完成的判断 |
| available_point_num | int | - | 玩家可领取抽奖币数量>=n后，活动中心入口弹出弹条 |
| remind_point_num | int | - | 玩家可用抽奖币达到配置数量后，入口出现红点 |
| rule | string | - | 规则描述 |
| umg | string | - | 主页umg |
| related_draw_id | string | - | 关联抽奖（用于计算掉落上限） / Chest进背包后有逻辑冲突，使用前需要跟服务器同步 |
| limited_item_ids | string | array | 活动掉落上限道具 / Chest进背包后有逻辑冲突，使用前需要跟服务器同步 |
| limited_item_amount | int | - | 道具掉落上限 / Chest进背包后有逻辑冲突，使用前需要跟服务器同步 |
| feature_item_id | string | array | feature神器id / Chest进背包后有逻辑冲突，使用前需要跟服务器同步 |
| feature_item_amount | int | - | feature神器碎片上限 / Chest进背包后有逻辑冲突，使用前需要跟服务器同步 |
| num_limit | int | - | 抽取次数上限 |
| reward_limit | object | - | 产出的数量限制，已产出数量不在范围内则不可抽该奖池 |

### Sheet: Cost

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一ID |
| comment | string | - | 注释 |
| comment | string | - | 折扣 |
| is_merge | int | - | 同类奖励是否合并 |
| input_type | string | - | same：每次都一样 / increase：随次数递增 |
| pull_times | int | - | 抽奖次数 |
| inputs | int | array | 单次抽奖的真实抽奖币消耗,same就填一个数，increase就枚举每一次消耗 |
| discount | int | - | 抽奖折扣次数，用免费抽 |
| addition | float | - | 加成状态下积分产出（百分比） |

### Sheet: Pool

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一ID |
| comment | string | - | 注释 |
| big_rewards_max_times | int | - | 大奖最多多少抽抽到（真保底） / 各奖池的保底进度独立，抽到该奖池对应的大奖时重置保底进度 |
| max_luck_value | int | - | 保底值（假保底纯显示） |
| luck_value_type | string | - | 继承保底值的类型，配置代表有继承，不同奖池需要配不同的值，配相同的值表示两个奖池的继承进度一致，不配则代表不继承 |
| reward | Reward | array | 奖池奖励，当奖池中只有一个奖励时，该奖励的在奖池中的权重为1，引用 Reward 子表 |
| weight | int | - | 抽奖权重 |
| weight_add | int | - | 到了min_times后，每抽1抽，奖池增加的权重，不配则不增加 |
| is_free | int | - | 免费抽奖能否抽到 / 1：可以，0：不能 |
| min_times | int | - | 至少多少次才能抽到，-1不限制 |
| vip_limit | int | - | VIP最低等级要求，-1不限制 |
| reward_preview | Preview | array | 用于显示特殊抽奖的卡池预览例如： / 1.限时卡册 / 2.葫芦娃抽奖，引用 Preview 子表 |
| point_preview | int | - | 用于显示特殊抽奖的积分产出例如： / 1.限时卡册 / 2.葫芦娃抽奖 |

### Sheet: Reward

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一ID |
| comment | string | - | 注释 |
| reward | yield | array | 奖励 |
| weight | int | - | 奖池中的权重 |
| is_big_reward | int | - | 是否是大奖，1-是，0或为空-不是，配置1的会出现特殊动画 |
| show_type | string | - | 显示的类型，根据抽奖不同，填写不同显示 |
| probability_show | string | - | 奖励概率（显示用） |
| ranking_point | int | - | 抽取到后，排行榜对应分数 |
| amount | int | - | 奖励库存数量，-1表示可以重复抽取 |
| is_free | int | - | 免费抽奖能否抽到 / 1：可以，0：不能 |
| min_times | int | - | 至少多少次才能抽到，-1不限制 |
| max_times | int | - | 最多多少次才能抽到，填0不限制 |
| vip_limit | int | - | VIP最低等级要求，-1不限制 |
| daily_server_cap | int | - | 每日全服限量，-1不限制 |
| total_user_cap | int | - | 一次活动每人获得数量上限，-1不限制 |
| show_position | string | - | 界面显示的位置 |
| reward_icon | string | - | 对应的部件icon |
| reward_icon_name | string | - | 对应的部件icon名称i18n |

### Sheet: Preview

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一的ID |
| comment | string | - | 备注名 |
| group | string | - | 奖励组 |
| reward | yield | array | 奖励 |
| probability_show | string | - | 奖励概率（显示用） |
| limited_item_type | int | - | 0=不限制掉落 / 1=limited_item / 2=feature_item |
