<!--
参考代码文件:
- lua/framework/components/game_module/module_impl/master_play_module/master_play_sbpv1_module.lua
最后参考时间: 2026-04-16
-->
================================================================================
                        MasterSBPv1（赛季通行证）玩法说明
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

**核心玩法模式**  
完整 **赛季通行证**：日/周/赛季任务、`bar` 进度、`milestonerewards` 等级奖励、**兑换 exchanges**、付费档位与 **继承点**（`SBPV1Inherit`）等。

**典型需求场景**  
战令、赛季 BP、任务+等级+商店兑换一体化活动。

**能力标签**  
赛季制、多任务组红点、里程碑、兑换公式、formula_tips、配表里程碑覆盖（`GetMasterSeasonBpTaskInfo` 拉回）。

**与相似玩法的区别**  
- **MasterBaseBP**：偏 **经验→里程碑**，协议为 `ClaimBaseBPMilestoneReward` 等；SBPv1 为 **赛季任务树 + 兑换 + 多子红点聚合**，枚举 `MasterPlaySBPv1Type` / `MasterPlaySBPv1TaskType`。

================================================================================
2. 玩法概述
================================================================================

模块注册 7 类赛季 BP 推送；Constructor 监听 `ANewDay`、`MasterPointChanged`、`PlayerInflationListChanged`、`ItemListReceiveEvent`。新一天请求刷新任务信息。等级与点数由 `conf.point_id`、`bp_setting.level_up_point` 与 `GetPointAndLevel` 计算。

================================================================================
3. 玩法类型定义
================================================================================

- `MasterPlayType.SeasonBp = "MasterSBPv1"`
- 模块：`MasterPlaySBPv1Module` → `master_play_sbpv1_module.lua`
- 枚举：`MasterPlaySBPv1Type`（Reward/Task/Exchange/Display/Show 等）、`MasterPlaySBPv1TaskType`（daily/weekly/seasonly_tasks）

================================================================================
4. 核心模块说明
================================================================================

- **Init**：注册 `ClaimMasterSeasonBpTaskReward`、`ClaimMasterSeasonBpMilestoneReward`、`PushMasterSeasonBpTaskInfo`、`DoMasterSeasonBpExchange`、`MasterSeasonBpChangeFormulaTips`、`GetMasterSeasonBpTaskInfo`、`PushMasterSeasonBpReturnPoint`
- **RegisterPointByType**：`PointType.SBPV1Inherit`
- **主要请求**：`RequestOnClaimMasterSeasonBpTaskReward`、`RequestOnClaimMasterSeasonBpMilestoneReward`、`RequestOnDoMasterSeasonBpExchange`、`RequestGetMasterSeasonBpTaskInfo` 等

================================================================================
5. 数据结构
================================================================================

- **info（常见）**：`bar`、`task`、`refresh_time`、`point`、`formula_times`、`formula_tips`、`gain_record`（如 `"level:f"` / `"level:p"`）、`inherit_level_point`、`unlock_state` 等
- **conf**：`milestonerewards`（可被服务端覆盖）、`daily_tasks` / `weekly_tasks` / `seasonly_tasks`、`exchanges`、`bp_setting`
- **GetMasterSeasonBpTaskInfo**：`bp_reward==0` 同步 bar/task/point；`bp_reward==1` 同步 `milestonerewards`

================================================================================
6. 协议与接口
================================================================================

| MessageType | 处理函数 |
|-------------|----------|
| ClaimMasterSeasonBpTaskReward | OnClaimMasterSeasonBpTaskReward |
| ClaimMasterSeasonBpMilestoneReward | OnClaimMasterSeasonBpMilestoneReward |
| PushMasterSeasonBpTaskInfo | OnPushMasterSeasonBpTaskInfo |
| DoMasterSeasonBpExchange | OnDoMasterSeasonBpExchange |
| MasterSeasonBpChangeFormulaTips | OnMasterSeasonBpChangeFormulaTips |
| GetMasterSeasonBpTaskInfo | OnGetMasterSeasonBpTaskInfo |
| PushMasterSeasonBpReturnPoint | OnPushMasterSeasonBpReturnPoint |

**派发事件（节选）**：`ClaimMasterSeasonBpTaskRewardEvent`、`ClaimMasterSeasonBpMilestoneRewardEvent`、`PushMasterSeasonBpTaskInfoEvent`、`DoMasterSeasonBpExchangeEvent`、`MasterSeasonBpRefreshTaskEvent`

================================================================================
7. 红点系统
================================================================================

- **主 key**：`"Master_Play_sbpv1_"..master_play_id` — `RefreshRedDotKey` 聚合 **reward | task | exchange** 子 key 是否有数
- **子 key**：`Master_Play_sbpv1_reward_`、`Master_Play_sbpv1_display_`、`Master_Play_sbpv1_exchange_`；任务为 **按日/周/季 sub_groups**：`Master_Play_sbpv1_task_`..id..groupId，多段 `"|"` 拼接
- **CalcRedDotNumber**：重置 `have_init_red` 后 `InitRedDot` + `CalcRewardRedDotNumber` + `CalcTaskRedDotNumber` + `RefreshExchangeRedDot`

================================================================================
8. 完成条件
================================================================================

模块内 **未定义** `CheckComplete`；赛季结束与领奖逻辑由活动与服务器状态驱动。

================================================================================
9. 开发注意事项
================================================================================

- 领取里程碑时若奖励含 `sbp_v1_inherit`，会累加 `inherit_level_point`。
- 兑换成功会本地 `AddItemCount` 扣消耗道具并发 `DoMasterSeasonBpExchangeEvent`。
- `CheckCanExchange` 依赖 `formula_tips`、`unlock_state`、等级与背包数量。
- `MasterPlaySBPv1Type` 用于 UI 页签语义（Show/Display 等），与红点类型注释一致即可。

================================================================================
10. 配表结构（MasterSBPv1.xls）
================================================================================

### Sheet: MasterSBPv1

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 每个id对应一个bp排期 |
| comment | string | - | 自己看的备注 |
| daily_tasks | MainGroup | - | 每日任务的主分组id，引用 MainGroup 子表 |
| weekly_tasks | MainGroup | - | 每周任务的主分组id，引用 MainGroup 子表 |
| seasonly_tasks | MainGroup | - | 赛季任务的主分组id，引用 MainGroup 子表 |
| point_id | string | - | 使用的等级积分id |
| exchanges | Formula | array | 兑换商城的配方列表，引用 Formula 子表 |
| bp_setting | BPSetting | - | 引用BP内容，引用 BPSetting 子表 |
| milestonerewards | MilestoneReward | array | 等级奖励，引用 MilestoneReward 子表 |
| artifact | string | - | 总览页展示神器大奖id |
| cannon | string | - | 大奖炮台id |
| wing | string | - | 大奖翅膀id |
| unlock_artifact | string | - | 购买页展示神器图片 |
| unlock_cannon | string | - | 购买页展示炮台图片 |
| unlock_wing | string | - | 购买页展示炮翅图片 |
| image_basic | string | - | 购买页进阶版图片 |
| image_upgrade | string | - | 购买页豪华版图片 |
| season_serial_title | string | - | "Sn"图片字 |
| start_popup_title | string | - | 开场动画Sn图片字 |
| expire_mail | string | - | 提醒即将结束的邮件 |
| start_umg | string | - | 新赛季曝光界面UMG |
| inherit_point_id | string | - | 当期bp使用的赛季继承点数的point id。为空表示没有继承点数 |
| inherit_bp_id | string | - | 上一期baseid（用于读取继承等级点数存储情况),可以为空 |

### Sheet: BPSetting

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | id |
| comment | string | - | 自己看的备注 |
| task_bonus | string | array | 豪华版任务加成的可加的任务类型 |
| task_bonus_num | float | - | 加成的数值n，计算为：该任务积分x(1+n) |
| exchange_point_type | int | - | 兑换使用的兑换币 |
| charge_basic | string | - | 基础版BP的Charge id |
| charge_upgrade | string | - | 基础升豪华BP的 |
| charge_deluxe | string | - | 豪华版BP的Charge id |
| reward_mail | string | - | 未领取奖励补发的邮件 |
| point_mail | string | - | 多余积分回收的邮件 |
| level_up_point | int | - | 升级所需积分 |
| charge_level_up | string | - | 购买100积分的Charge id |
| reward_show_umg | string | - | 恭喜获得的UMG |
| end_umg | string | - | 临期提醒UMG配置 |

### Sheet: Formula

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一ID |
| comment | string | - | 注释 |
| input | int | - | 需要的兑换币数 |
| output | yield | array | 兑换的产出内容 |
| limit | int | - | 兑换次数，-1表示无限次数 |
| is_reminder | int | - | 1默认开启兑换提示，0不开 |
| ui_background | string | - | 资源底板，区分低级/高级 |
| limit_level | int | - | 可开放兑换的等级限制 |

### Sheet: MilestoneReward

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 积分奖励固定唯一id |
| comment | string | - | 备注 |
| free_rewards | yield | array | 免费奖励，放大，免费膨胀 |
| paid_rewards | yield | array | 付费奖励，放大，付费膨胀 |
| grand_level | int | - | 是否是大奖等级，1-是，0或不填-不是 |
| eolve_level | int | - | 是非为突破等级，需要购买豪华版本bp解锁 |

### Sheet: MainGroup

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | - |
| comment | string | - | 备注 |
| display_name | string | - | i18n key |
| sub_groups | SubGroup | array | 引用SubGroup / 本主分组包含哪些副分组，引用 SubGroup 子表 |

### Sheet: SubGroup

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | - |
| comment | string | - | 相当于备注名，自己看的 |
| display_name | string | - | i18n key |
| unlock_duration | duration | - | 本副分组在BP开始后多久解锁，为空表示BP开始后即解锁 |
| tasks | AllTask | array | 引用子任务AllTask，该副分组包含哪些任务，引用 AllTask 子表 |
| progress_rewards_requirement | int | - | 完成该副分组下多少个任务可以领进度奖励 |
| progress_rewards | yield | array | 进度奖励 |
| progress_tip | string | - | i18n key |

### Sheet: AllTask

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | - |
| comment | string | - | 相当于备注名，自己看的 |
| description | string | - | 任务描述 |
| task_action | string | - | 具体的任务条件类型，参考dash_action？ |
| task_filters | object | array | 过滤事件 |
| task_value | object | - | 具体的任务条件数值，参考dash_value？ |
| rewards | yield | array | 完成本任务可领的奖励 |
| go_now | object | - | 跳转配置，如果不为空，任务没完成时显示“前往”按钮，点击跳转到配置的界面 |
| if_task_hint | int | - | 是否有任务详情按钮 |
| hint_desc | string | - | 任务详情内的文字 |

================================================================================
                               文档结束
================================================================================

