<!--
参考代码文件:
- lua/framework/components/game_module/module_impl/master_play_module/master_play_collection_draw_module.lua
最后参考时间: 2026-04-16
-->
================================================================================
                        收集抽奖（MasterCollectionDraw）玩法说明
================================================================================
                           版本: 2026-04-16
================================================================================

1. 适用场景与需求匹配

- **核心模式**：在抽奖基础上**收集文字或拼图碎片**，集齐后触发**里程碑奖励**，支持**重置**循环参与。
- **典型需求**：集字活动、拼图收集、带里程碑的长期抽奖活动。
- **能力标签**：随机奖励、收集机制、里程碑、重置、跨天刷新（模块层对「新日数据失效」有专门处理）。
- **与 Draw 区别**：除抽奖外还有**收集进度 + 里程碑**；抽奖过程会同步产出碎片/字块。

若活动仅要纯抽奖无收集，用 MasterDraw 更简单；需要「集齐换大奖」时用本玩法。

2. 玩法概述

`MasterPlayCollectionDrawModule` 协调抽奖、里程碑领取、重置、更换大奖等流程，并缓存字块/奖励列表用于展示与校验。跨天时 `IsDataInvalidOnNewDay` 返回 `true`，需按产品规则重新拉取或刷新数据。

3. 玩法类型定义

- **模块类**：`MasterPlayCollectionDrawModule`
- **基类**：`MasterPlayModuleBase`
- **实现文件**：`master_play_collection_draw_module.lua`

4. 核心模块说明

模块在抽奖与里程碑之间同步状态：计算可领里程碑数量、可抽位置、膨胀加成后的奖励数量，并在奖励展示完成后继续链路。多处 `cached_*` 用于避免重复计算与展示闪烁。

5. 数据结构

**玩法 info（关键字段）**

- `all_times`、`draw_times`、`draw_status`
- `draw_pos`
- `word_list`：字块/收集列表
- `milestone_record`：里程碑领取记录
- `reward_index`、`inflation_list`：奖励索引与膨胀相关

**模块缓存**

- `cached_word_list`、`cached_yield_list`
- `cached_no_draw_item`、`cached_draw_info`

6. 协议与接口

**下行推送（RegisterPushHandler）**

- `MasterCollectionDrawDraw`
- `MasterCollectionDrawClaimeMileStoneReward`
- `MasterCollectionDrawReset`
- `MasterCollectionDrawChangeBigReward`
- `MasterCollectionDrawAll`

**上行请求**

- `Draw`、`DrawAll`、`Milestone`、`Reset`、`ChangeBigReward`

**常用对外方法**

- `PatchDrawInfo`、`CanReset`
- `CalcRewardChipCountWithInflation`
- `TryPlayWordYieldResult`、`TryShowYieldResult`
- `CheckHaveNoDrawReward`、`GetClaimeAbleMileStoneRewardCount`
- `GetCanPositions`、`GetDrawResult`

7. 红点系统

- **Draw**：`GetRedDotKey_Draw` → `"Master_CD_RedDot_" .. master_play_id`
- **Reward（里程碑/可领）**：`GetRedDotKey_Reward` → `"Master_CD_Reward_RedDot_" .. master_play_id`

8. 完成条件（CheckComplete）

- **未实现**（模块内不构成通用完成判定）。
- **`IsDataInvalidOnNewDay`**：返回 **`true`**，跨天后需视为数据失效并重新同步。

9. 开发注意事项

**事件**

- **监听**：`MasterPointChanged`、`YieldRewardShowComplete`
- **派发**：`MasterCollectionDrawReturn`、`MasterCollectionDrawMileStoneRewardClaimed`、`MasterCollectionDrawReset`、`MasterCollectionDrawChangeBigReward`、`MasterCollectionDrawAppendWordReward`

实现 UI 时注意：里程碑弹窗与抽奖动画的顺序；重置与更换大奖后清空缓存并 `PatchDrawInfo`。不要在跨天仍使用旧的 `cached_*` 数据。

10. 配表结构（MasterCollectionDraw.xls）

### Sheet: CollectionDraw

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 玩法id |
| comment | string | - | 自己看的备注 |
| milestone_reward | MilestoneReward | array | 进度奖，引用 MilestoneReward 子表 |
| big_reward_show | int | - | 默认展示的大奖，配置index,从MilestoneReawd.reward找 |
| word_show | WordShow | array | 字的展示，引用 WordShow 子表 |
| free_point | string | - | 免费抽奖币的id,为空为不存在免费抽奖币 |
| paid_point | string | - | 付费抽奖币的id,为空为不存在付费抽奖币 |
| free_draw_num | int | - | 免费抽奖的次数，不配则没有免费抽奖次数 |
| rewards_type | string | - | take_out：取出式 / random：每次独立随机 / 如果是取出式抽奖，则当大奖全部抽完时，若还剩有奖励未全部取出，则将剩余部分奖励直接发放 |
| input_type | string | - | same：每次都一样 / increase：随次数递增 |
| inputs | int | array | 单次抽奖的真实抽奖币消耗,same就填一个数，increase就枚举每一次消耗 |
| reward | Reward | array | 奖池奖励，引用 Reward 子表 |
| is_pre_big_rewards | int | - | 是否提前保底（当多个奖池都同时差2抽触发保底时，下一抽则提前保底，触发表中list排序为先的奖池的保底。 / 1=是，0或为空=不提前保底 |
| inflation_type | int | - | 奖池中金币的膨胀属性 / 不膨胀：0 / 付费膨胀：1 / 免费膨胀：2 |
| boost_available | int | - | 奖池中金币产出是否受charge_chip_bonus影响，1为是，不配则不受影响 |
| reward_return_mail | string | - | 未领取进度奖补发邮件 |
| recycle_mail | string | - | 抽奖币回收邮件 |

### Sheet: Reward

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一ID |
| comment | string | - | 注释 |
| reward | yield | array | 奖励 |
| word | string | - | 字的类型 |
| big_rewards_max_times | int | - | 大奖最多多少抽抽到（真保底） |
| weight | int | - | 奖池中的权重 |
| is_big_reward | int | - | 是否是大奖，1-是，0或为空-不是，配置1的会出现特殊动画 |
| show_type | string | - | 显示的类型，根据抽奖不同，填写不同显示 |
| probability_show | string | - | 奖励概率（显示用） |
| min_times | int | - | 至少多少次才能抽到，-1不限制 |
| ranking_point | int | - | 抽取到后，排行榜对应分数 |
| amount | int | - | 奖励库存数量，-1表示可以重复抽取 |
| is_free | int | - | 免费抽奖能否抽到 / 1：可以，0：不能 |
| vip_limit | int | - | VIP最低等级要求，-1不限制 |
| daily_server_cap | int | - | 每日全服限量，-1不限制 |
| total_user_cap | int | - | 一次活动每人获得数量上限，-1不限制 |
| show_position | string | - | 界面显示的位置 |
| reward_icon | string | - | 对应的部件icon |
| reward_icon_name | string | - | 对应的部件icon名称i18n |

### Sheet: MilestoneReward

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一的id |
| comment | string | - | 备注 |
| word | string | array | 字的类型 |
| is_optional | int | - | 是否是可选奖励 |
| reward | yield | array | 奖励内容 |

### Sheet: WordShow

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 字 |
| comment | string | - | 自己看的备注 |
| word | string | - | 字的类型 |
| word_image | string | - | 亮字资源 |
