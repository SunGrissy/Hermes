<!--
参考代码文件:
- lua/framework/components/game_module/module_impl/master_play_module/master_play_boost_milestone_module.lua
最后参考时间: 2026-04-16
-->
================================================================================
                        增益里程碑（MasterBoostMilestone）玩法说明
================================================================================
                           版本: 2026-04-16
================================================================================

1. 适用场景与需求匹配
2. 玩法概述
3. 玩法类型定义
4. 核心模块说明
5. 数据结构
6. 协议与接口
7. 红点系统
8. 完成条件
9. 开发注意事项

================================================================================
1. 适用场景与需求匹配
================================================================================

- **核心诉求**：里程碑奖励金额随 **Boost/装备养成** 等动态变化，支持领取与重新申请（刷新可领金额）。
- **典型活动**：装备收益挑战、动态金币里程碑。
- **标签**：boost 加成、动态金币、里程碑、重新申请。
- **对比**：普通 `MasterMilestone` 多为固定档位；本玩法强调 **数值随外部长线养成变化**，且可 **Reapply**。

================================================================================
2. 玩法概述
================================================================================

配表定义多档奖励；服务端/客户端根据当前 boost、神器等级等计算展示金币（含 `inflated_chip` 等）。玩家可领取当前可领额度，或在规则允许时重新申请以刷新额度。模块监听积分、破成长金币膨胀、神器升级等事件以保持显示一致。

**流程摘要**：档位解锁 → `CanClaimReward` 为真 → 发 `RequestClaimRewards` → 收到 `MasterBoostMilestoneClaimRewardReceive` → 若规则允许则 `RequestReapply` 刷新下一档可领金币。

**数值**：`DealBoostFunc` 与配表 `type` 字段绑定，新增养成线时同步扩展类型字符串。

================================================================================
3. 玩法类型定义
================================================================================

- **枚举**：`MasterPlayType.BoostMilestone = "MasterBoostMilestone"`。
- **模块类**：`MasterPlayBoostMilestoneModule`，继承 `MasterPlayModuleBase`。

================================================================================
4. 核心模块说明
================================================================================

- **静态表**：`DealBoostFunc`，按类型（如 `"artifact"`）映射到 boost 计算函数。
- **关键方法**：`CanClaimReward`、`HasRewardCanClaimed`、`IsClaimed`、`GetTotalClaimedChip`、`GetRewardChipCount`、`GetBoostBet`、`GetCurrentTotalClaimableChip`、`GetReapplyChipAmount`、`CanReapply`、`ShowBoostInfoController`。
- **事件监听**：`MasterPointChanged`、`BreakGrowthChipInflationValueChanged`、`ArtifactLevelUpReceiveEvent`、`GetArtifactReceiveEvent`。
- **事件派发**：`MasterBoostMilestoneClaimRewardReceive`、`MasterBoostMilestoneChipChanged`。

================================================================================
5. 数据结构
================================================================================

- **info.reward_state**：按奖励 ID 记录状态，常含 `inflated_chip`、`boost` 等用于展示与校验的字段。
- **展示**：`ShowBoostInfoController` 用于弹层说明当前 boost 来源，与 `DealBoostFunc` 计算结果应对齐，避免「说明一套、数字一套」。

================================================================================
6. 协议与接口
================================================================================

- 对外领取：`MasterBoostMilestoneClaimReward` → `RecieveClaimRewards`（命名以文件为准）。
- 业务封装：`RequestClaimRewards`、`RequestReapply` 发送协议并驱动刷新。

================================================================================
7. 红点系统
================================================================================

- **可领取**：`GetClaimRedDotKey` → `"MasterBoostMsClaimRedDot_" .. mpid`。
- **可重新申请**：`GetReapplyRedDotKey` → `"MasterBoostMsReapplyRedDot_" .. mpid`。

================================================================================
8. 完成条件
================================================================================

- 模块内 **未定义**统一 `CheckComplete`（或依赖活动侧/配表「领完即完成」）；以产品需求为准。

================================================================================
9. 开发注意事项
================================================================================

- 任何展示金币处需与 `GetRewardChipCount` / `GetCurrentTotalClaimableChip` 同源，避免 UI 与协议不一致。
- `DealBoostFunc` 扩展新类型时补齐映射与配表，否则 boost 为 0 或错误分支。
- 神器升级与膨胀系数变更会高频刷新，注意性能与红点抖动。
- `CanReapply` 与 `GetReapplyChipAmount` 需与服务器 CD/次数限制一致，避免客户端显示可点实际失败。
- 领取后 `MasterBoostMilestoneClaimRewardReceive` 应驱动全列表刷新，勿只改单行 item。
- 低端机关闭复杂 boost 说明弹窗动效时，仍需保证数字与 `GetRewardChipCount` 一致。
- 赛季切换或神器重置时，旧 `reward_state` 清理顺序依赖服务端，客户端勿先清空再拉包。
- 展示总可领金币时做上限保护，防止 uint 溢出或科学计数法展示异常。
- 与 VIP、月卡等全局倍率叠乘时，说明文案写清「已含哪些加成」。
- 领奖失败重试需防抖，避免弱网下重复请求导致重复领奖报错刷屏。
- 红点：领取与重新申请互斥展示时，优先级由产品定，代码侧勿双键常亮冲突。
- 自动化：切换神器等级前后断言 `GetCurrentTotalClaimableChip` 变化方向符合预期。
- 弱网：请求中旋转锁与按钮遮罩需成对出现，防止重复点击。
- 文档：对外说明「可领金额会随养成变化」以减少客诉。

================================================================================
10. 配表结构（MasterBoostMilestone.xls）
================================================================================

### Sheet: BoostMileStone

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 进度奖id |
| comment | string | - | 自己看的备注 |
| reward | Reward | array | 对应的奖励，引用 Reward 子表 |
| inflation_type | int | - | 奖励中金币的膨胀属性 / 不膨胀：0 / 付费膨胀：1 / 免费膨胀：2 |
| set | SetContents | array | 奖励中金币产出是否受某个boost影响，不配则不受影响，引用 SetContents 子表 |
| reapply_on_inflation_change | int | - | 是否可以补发膨胀差值 |
| reapply_on_boost_change | int | - | 是否可以补发boost差值 |
| reward_return_mail | string | - | 进度奖补发邮件 / #R:SystemMail |
| point | string | - | 积分id |
| is_merge_rewards | int | - | 进度奖励领取类型，当同时领取多个进度奖励中相同的奖励时，是否需要合并（不配置默认为0） / 需要：1 / 不需要：0 |

### Sheet: Reward

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 进度奖id |
| comment | string | - | 自己看的备注 |
| points | int | - | 达到本阶段所需积分/需要完成的任务条数 |
| rewards | yield | array | 奖励 |

### Sheet: SetContents

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | id |
| comment | string | - | 自己看的备注 |
| type | string | - | 内容的类型 |
| content | string | array | 共鸣的内容，对应id |
| bonus | object | - | boost值对应的加成系数 |
| boost_info_umg | string | - | 详情UMG |
| go_now | object | - | 用于界面跳转 |
