<!--
参考代码文件:
- lua/framework/components/game_module/module_impl/master_play_module/master_play_cycle_task_module.lua
最后参考时间: 2026-04-16
-->
================================================================================
                        MasterCycleTask 玩法开发规范（客户端）
================================================================================
版本: 2026-01-15
适用范围: Master 系统下 class_type = "MasterCycleTask" 的玩法（周期任务/日周例行）

目录
----
1. 概述与玩法拆分
2. 活动结构（MasterAct）推荐配置
3. 配表结构（MasterCycleTask.xls）
4. 运行时数据结构（master_play_info.info）
5. 协议与事件（MessageType / GameEventType）
6. 模块接入与业务流程（不依赖具体页面）
7. 玩法红点规范（任务/进度）
8. 跨天/刷新与补发（refresh_type、return_point、task_reward_mail）
9. 开发步骤清单（最短路径，不含页面约束）
附录A. 参考UI实现（仅供参考，可按项目替换）
附录B. 可选：与其他玩法/上层聚合联动（仅供参考）
10. 常见坑与注意事项

================================================================================
1. 概述与玩法拆分
--------------------------------------------------------------------------------
MasterCycleTask 是“按周期刷新的一组任务 + 进度里程碑奖励”的玩法实现，典型用于日常/周常。
核心特性：
- 按 refresh_type 周期刷新任务进度与里程碑进度（客户端按周期展示与判定）。
- 任务奖励：完成单个任务后可领取（客户端当前按“任务组 task_group[1]”来展示/领奖）。
- 进度奖励：累积 point 达到 ProgressReward.points 后可领取阶段奖励。
- 可选付费解锁（paid_task_charge）：未购买时，客户端会屏蔽领取与红点，并展示购买入口。
- 可与其他系统联动：阶段奖励可产出 Point/道具等资源，供其他玩法或系统消耗（联动方式不属于本玩法必选流程）。

核心文件（客户端）：
- 配表：`D:\FishUE4L3\FishUE4\Tables\server_data\Master\MasterCycleTask.xls`
- 模块：`lua/framework/components/game_module/module_impl/master_play_module/master_play_cycle_task_module.lua`
- UI：`lua/product/components/ui_item/master/cycle_task/` 目录下各脚本

================================================================================
2. 活动结构（MasterAct）推荐配置
--------------------------------------------------------------------------------
本章仅描述“让 MasterCycleTask 玩法跑起来”的最小活动配置，不约束你的 UI 组织方式。

2.1 最小接入（单 MasterAct）
- 在 MasterAct.xls 中创建一个活动（type=Act），并在该活动的 master_plays 中配置 MasterCycleTask 玩法：
  - class_type = MasterCycleTask
  - class_id = MasterCycleTask.xls/Main.id（配表行 id）
  - 最终 master_play_id 由框架拼接：`{act_id}:{class_id}`

2.2 Dialog 名称规则（用于打开活动主界面）
Dialog 名称由 `MasterData:FormatMainDialogName()` 自动拼：
- Act：`DialogAct{theme_tag}Controller`
说明：theme_tag 属于活动维度（MasterAct.xls），用于决定“主界面 Controller/UI 入口名字”；与玩法本体无关。

2.3 UI 配置的边界
MasterCycleTask 文档只规定“玩法数据、领奖、红点与刷新”如何工作；主界面 UMG/class 选型属于项目 UI 方案。
若项目存在“上层聚合入口/多子活动聚合/跨玩法联动”等结构，请参考 **附录B**（可选）。

================================================================================
3. 配表结构（MasterCycleTask.xls）
--------------------------------------------------------------------------------
配表字段结构可用工具导出查看：
`python lua/docs/table_tool/xls_schema_preview.py D:\FishUE4L3\FishUE4\Tables\server_data\Master\MasterCycleTask.xls --all-sheets`
（本仓库也可参考 `lua/docs/schema_MasterCycleTask.txt`）

3.1 Main（主表，1 行 = 1 个 CycleTask 玩法配置）
- id[string]：配表行 id（将作为 class_id，最终拼成 master_play_id = "{act_id}:{class_id}"）
- mission_type[string]：任务类型（用于 UI 展示/埋点/入口气泡 `SetTaskInfo(desc, mission_type)`）
- tab_name[string]：Tab 页签名称（i18n key，UI 使用 `UIHelper.FormatI18NTextWithLatentArguments`）
- task_group[array<TaskGroup>]：按周期刷新的任务组
  - 客户端当前只读取 `task_group[1]` 进行列表展示、领奖、红点统计
- progress_reward[array<ProgressReward>]：里程碑阶段奖励
- progress_point[string]：进度奖积分（Point id，用于 UI 左上角展示图标）
- paid_task_charge[string]：付费解锁 charge_id（不配=免费；未购买时任务不可领取/不出红点）
- refresh_type[duration]：刷新间隔（秒）
- task_reward_mail[string]：刷新时奖励补发邮件（#R:SystemMail）
- return_point[array<string>]：活动刷新时补发涉及的积分（Point id）
- return_type[array<string>]：与 return_point 一一对应，补发方式
  - add / coin / mail / discard（见字段备注）

3.2 TaskGroup（任务组）
- id[string]：任务组 id（客户端领奖时使用 `group_id = task_group[1].id`）
- tasks[array<AllTask>]：任务列表

3.3 AllTask（任务配置）
- id[string]：任务 id（服务端/客户端共同的 key）
- description[string]：任务描述（由 UIHelper.FormatTaskDesc/Process 格式化）
- task_action[string]：任务条件类型（服务端累加逻辑依据）
- task_filters[array<object>]：过滤参数（客户端用于“图鉴目标弹窗”的 fish_id 推导等）
- task_value[object]：累加值规则（服务端用，客户端一般仅展示）
- rewards[array<yield>]：任务奖励
- is_task_hint[int]：1=显示图鉴详情（UI 会显示 Tip 按钮）
- go_now[object]：跳转配置（不为空则显示“前往”按钮）
  - go_now.go_now / go_now.params：供 `GoNow.GoNowFun` 使用

3.4 ProgressReward（里程碑阶段）
- id[string]：阶段唯一 id（领取状态会写入 progress[day_str][id]）
- points[int]：达成所需积分
- rewards[array<yield>]：阶段奖励（可包含 Point/道具等资源；联动由项目自行定义）

================================================================================
4. 运行时数据结构（master_play_info.info）
--------------------------------------------------------------------------------
4.1 task（按周期存档的任务进度/领奖状态）
`play_info.info.task` 是一个 dict，key 为 day_str（字符串或数字时间戳），value 为任务进度表：
- task[day_str][task_id].p：当前进度（process）
- task[day_str][task_id].s：是否已领取（>=1 表示已领）

模块以“是否落在当前周期”来挑选有效 day_str（见 `IsMatchDay`）。

4.2 progress（按周期存档的里程碑进度/领奖状态/付费状态）
`play_info.info.progress` 是一个 dict，key 为 day_str，value 为：
- progress[day_str].point：当前累计积分
- progress[day_str].paid_flag：是否已付费解锁（1=已购）
- progress[day_str][progress_reward_id]：是否已领取该阶段（存在即已领）

================================================================================
5. 协议与事件（MessageType / GameEventType）
--------------------------------------------------------------------------------
5.1 协议（`lua/framework/core/network/call/message/message_type.lua`）
- MessageType.MasterCycleTaskClaimTaskReward
  - 请求：params.group_id
  - 回包：res.task（任务领奖状态增量）、res.point、day_str
- MessageType.MasterCycleTaskClaimProgressReward
  - 回包：res（进度信息增量）、day_str
- MessageType.PushMasterCycleTaskInfo
  - 推送：day_str + res（任务进度增量/全量，模块会合并）
- MessageType.MasterCycleTaskClaimAllTaskReward
  - 回包：res.day_strs（需要清理的历史周期，用于一键领取历史奖励）

注意：客户端发送时统一使用 `CreateMsg(msg_type, master_play_id)`，框架会自动填 act_id，并把 master_play_id 转换为 class_id。

5.2 事件（`lua/framework/core/game_logic/game_event/game_event_type.lua`）
- GameEventType.MasterCycleTaskInfoRefresh(master_play_id, task_res)
- GameEventType.MasterCycleTaskClaimTaskReward(master_play_id, claimed_task_dict)
- GameEventType.MasterCycleTaskClaimProgressReward(master_play_id)
- GameEventType.MasterCycleTaskBuySuccess(master_play_id)

================================================================================
6. 模块接入与业务流程（不依赖具体页面）
--------------------------------------------------------------------------------
6.1 注册与入口
模块已在 `game_module_register.lua` 注册：
`logic:AddModule(MasterPlayCycleTaskModule, ...)`

6.2 关键 API（供 UI 调用）
- RequestClaimTaskRewards(master_play_id, group_id)
- RequestClaimProgressRewards(master_play_id)
- RequestClaimAllTaskRewards(master_play_id)

- GetTodayTaskInfos(master_play_id) / GetTodayProgressInfos(master_play_id)
- GetTaskInfos(master_play_id, target_day_str)：获取指定日期的任务列表
- GetProgressInfos(master_play_id, target_day_str)：获取指定日期的进度列表
- GetIsTaskCompleteInToday(master_play_id, task_conf)
- GetIsTaskClaimedInToday(master_play_id, task_conf)
- GetTodayProgressReached(master_play_id, progress_conf)
- GetTodayProgressisClaimed(master_play_id, progress_conf)
- GetNeedBuy(master_play_id)：是否需要付费解锁（paid_task_charge 配了且未购）
- HaveBeforeReward(master_play_id)：是否存在历史周期未处理数据（用于“一键领取历史奖励”）

- GetRedDotKey_Reward(master_play_id)：获取奖励红点 key

6.3 与付费购买的联动
模块监听 `GameEventType.ShopBuyReturn`：
- 若购买的 charge_id 命中某个 play_info.conf.paid_task_charge，则写入 progress[day_str].paid_flag = 1 并派发 `MasterCycleTaskBuySuccess`。

6.4 端到端业务流程（不依赖具体页面）
- 活动数据到达：
  - MasterModule 收到 GetMasterActInfo 后，会对该活动内每个 master_play 调用 `RefreshMasterPlayInfo(master_play_id, info, conf)`。
  - CycleTask 模块拿到 info/conf 后即可提供“今日任务/进度”读取能力与红点计算能力。
- 任务进度更新：
  - 服务端推送 `PushMasterCycleTaskInfo`（按 day_str + res），模块合并到 `play_info.info.task[day_str]` 并派发 `MasterCycleTaskInfoRefresh`。
- 领取任务奖励：
  - 调用 `RequestClaimTaskRewards(master_play_id, group_id)` -> 回包更新 `task[day_str][task_id]` 的领取态，同时更新 `progress[day_str].point`，派发 `MasterCycleTaskClaimTaskReward`。
- 领取里程碑奖励：
  - 调用 `RequestClaimProgressRewards(master_play_id)` -> 回包更新 `progress[day_str]`（含阶段领取标记），派发 `MasterCycleTaskClaimProgressReward`。
- 历史周期清理/补领：
  - 若检测到存在历史 day_str（`HaveBeforeReward == true`），调用 `RequestClaimAllTaskRewards`，模块会清理对应的 task/progress 历史条目。
- 付费解锁：
  - 购买成功时模块监听 `ShopBuyReturn`，写入 `paid_flag=1` 并派发 `MasterCycleTaskBuySuccess`。

================================================================================
附录A. 参考UI实现（仅供参考，可按项目替换）
--------------------------------------------------------------------------------
本附录仅用于说明仓库里现成实现“长什么样/怎么接模块”，不作为玩法开发流程的必选项。
如果你的活动 UI 结构不同，只需保证：
- 能正确请求/接收 MasterActInfo 与 PushMasterCycleTaskInfo
- 能调用模块的 3 个领奖 API
- 能监听并处理 4 个事件
- 红点 key 绑定正确

A.1 任务主界面（`MasterCycleTaskMain`）
- self.play_infos = master_data:GetMasterPlayInfo(MasterPlayType.CycleTask)
  - 允许一个子活动挂多个 CycleTask 玩法实例，用 Tab 展示（tab_name 来自各自 conf）
- 里程碑：`MasterCycleTaskMilestone` + `MasterCycleTaskMilestoneNode`
- 行项目：`MasterCycleTaskRow`
- 倒计时：显示到下次刷新（注意见第 10 章“时间对齐”）

A.2 Tab（`MasterCycleTaskTab`）
- 红点 key：直接绑定 `MasterPlayCycleTaskModule.Instance:GetRedDotKey(master_play_id)`（内部拼了任务红点与进度红点）
- Tab 可展示自定义统计信息（例如基于奖励产出的某种 Point 数量等，取决于你的 UI 设计）

A.3 Row（`MasterCycleTaskRow`）
- 展示任务描述、进度、奖励
- 状态：完成/已领/需要付费/可跳转/是否显示 tip
- GoNow：使用 `GoNow.EnoughConditon` + `GoNow.GoNowFun(go_now, params, {reason=MasterPlayType.CycleTask})`
- Tip：打开鱼图鉴目标弹窗（依赖 task_filters 里 fish_type/fish_types/fish_id）

A.4 入口气泡（`MasterCycleTaskEntryBubble`）
- 监听 `MasterCycleTaskInfoRefresh`，当发现“可领取且未领取且不需要付费”时显示气泡
- 通过回调实现“前往/展示”逻辑（由入口脚本注入）

A.5 说明：上层聚合/入口拆红点
如项目存在“上层聚合入口、多子活动聚合、入口红点拆分”等实现，这些属于项目级 UI 组织方式，不属于 MasterCycleTask 玩法本体规范。
请参考 **附录B**（可选）或直接以你们项目现有实现为准。

================================================================================
7. 红点规范（玩法红点 + 入口三段红点）
--------------------------------------------------------------------------------
7.1 玩法红点 key（模块定义）
- 进度奖励红点：`MasterCycleTask_ProgressReward_{master_play_id}`
- 任务奖励红点：`MasterCycleTask_TaskReward_{master_play_id}`
- 玩法总红点：`progress_key|task_key`

7.2 计算规则（模块 CalcRedDotNumber）
当 `GetNeedBuy(master_play_id) == false` 时：
- progress：遍历 conf.progress_reward，满足“达成且未领”则 +1
- task：遍历 conf.task_group[1].tasks，满足“完成且未领”则 +1

================================================================================
8. 跨天/刷新与补发（refresh_type、return_point、task_reward_mail）
--------------------------------------------------------------------------------
8.1 refresh_type 的意义
- UI 倒计时用于提示“距离下次刷新”
- 模块使用 refresh_type 判断某个 day_str 是否属于“当前周期”（`IsMatchDay`）

8.2 补发相关字段（依赖服务端实现）
- task_reward_mail：刷新时补发邮件（SystemMail id）
- return_point + return_type：刷新时对指定积分进行 add/coin/mail/discard 处理

客户端侧的配合点：
- `TryClaimBeforeReward` 逻辑在 UI 层（`master_cycle_task_main.lua`）实现，而非 Module 层。Module 仅提供 `HaveBeforeReward` 判断和 `RequestClaimAllTaskRewards` 调用能力；UI 在检测到存在历史周期数据时调用 `RequestClaimAllTaskRewards` 进行清理/补领。

================================================================================
9. 开发步骤清单（最短路径，不含页面约束）
--------------------------------------------------------------------------------
1) 配置 MasterCycleTask.xls：
   - Main：refresh_type（秒）、tab_name、progress_reward、progress_point、paid_task_charge（可选）
   - TaskGroup/AllTask：任务列表、go_now（可选）、is_task_hint（可选）
2) 配置子活动 MasterAct（CycleTaskDaily）：
   - master_plays 里添加 1~N 个 MasterCycleTask
3) 配置活动主界面（按项目 UI 方案）：
   - 在 MasterAct.xls 中配置 main_umg / main_umg_class（可复用现成 UI，也可自研）
4) 校验协议/推送与数据闭环（不依赖页面）：
   - 任务进度推送 PushMasterCycleTaskInfo
   - 领奖回包字段能正确更新 task/progress
   - 红点 key 对应的数量能随推送/领奖变化（领取后红点应下降）
   - 事件派发（InfoRefresh/ClaimTask/ClaimProgress/BuySuccess）能被上层订阅到

注：如复用仓库现成 UI，再做“界面显示与交互一致性”校验（见附录A）。

================================================================================
10. 常见坑与注意事项
--------------------------------------------------------------------------------
10.1 task_group 多组
客户端当前大量逻辑写死 `task_group[1]`（列表、领奖、红点），若要支持多组任务，需要扩展 UI 与模块。

10.2 时间对齐（非常关键）
`MasterCycleTaskMain:CountDown()` 使用：
`left_time = (act_end_time - now) % refresh_type`
这意味着倒计时以 end_time 为锚点回推周期边界。
为了避免 UI 倒计时与真实刷新点不一致，建议：
- 让活动的 end_time 与 refresh_type 周期边界对齐（或按项目约定对齐到整点/0点）。

10.3 付费解锁时的红点与领取
未购买时模块会整体屏蔽红点与领取判断；如产品需求是“可看但不可领/仍提示红点”，需要改模块与 UI 状态机。

10.4 go_now 配置为空的判断
Row 用 `next(self.task_info.go_now) ~= nil` 判断是否可跳转；确保 go_now 是 table 或为空 table，避免 nil/类型不符。

10.5 入口红点聚合/拆分（项目级）
玩法只提供自身红点 key；活动入口如何聚合/拆分红点属于项目 UI 策略，不在本玩法规范内。

================================================================================
附录B. 可选：与其他玩法/上层聚合联动（仅供参考）
--------------------------------------------------------------------------------
本附录用于记录“MasterCycleTask 之外”的常见项目组合方式，避免影响主干阅读：
- 有些项目会将 CycleTask 与其他玩法放在同一入口/集群中统一展示（例如 ActGroup + 多子活动等）。
- 也可能将 CycleTask 产出的某种 Point/道具资源，用于其他玩法消耗（例如商店/转化等）。

这些联动的关键原则：
- **MasterCycleTask 玩法本体只负责**：任务进度推送合并、任务/进度领奖、周期判断、红点计算、历史周期清理。
- **联动系统负责**：消耗何种资源、资源如何展示、入口如何组织、红点如何拆分与展示。


11. 配表结构（MasterCycleTask.xls）

### Sheet: Main

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 任务组 |
| comment | string | - | 自己看的备注 |
| mission_type | string | - | 任务类型 |
| tab_name | string | - | tab页签名称 |
| task_group | TaskGroup | array | 按周期周期刷新的任务组，引用 TaskGroup 子表 |
| progress_reward | ProgressReward | array | 按周期刷新的进度奖，引用 ProgressReward 子表 |
| progress_point | string | - | 进度奖积分 |
| paid_task_charge | string | - | 用于解锁付费任务的charge / 不配为免费 / 未购买时，任务不能领取 |
| refresh_type | duration | - | 刷新间隔 |
| task_reward_mail | string | - | 奖励补发邮件 / 刷新时触发 / #R:SystemMail |
| return_point | string | array | 活动刷新时补发涉及的积分 |
| return_type | string | array | 刷新时补发积分的处理，按照return_point的次序 / add=加到玩家身上 / coin=转金币通过邮件发放 / mail=直接通过邮件发放point / discard=丢弃 |

### Sheet: TaskGroup

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 玩法id |
| comment | string | - | 自己看的备注 |
| tasks | AllTask | array | 任务，引用 AllTask 子表 |

### Sheet: AllTask

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 任务id |
| comment | string | - | 相当于备注名，自己看的 |
| description | string | - | 任务描述 |
| task_action | string | - | 具体的任务条件类型 |
| task_filters | object | array | 过滤事件 |
| task_value | object | - | 如何累加值 |
| rewards | yield | array | 完成本任务可领的奖励 |
| is_task_hint | int | - | 1-显示图鉴详情 / 为空=不显示 |
| go_now | object | - | 跳转配置，如果不为空，任务没完成时显示“前往”按钮，点击跳转到配置的界面 |

### Sheet: ProgressReward

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一id |
| comment | string | - | 自己看的备注 |
| points | int | - | 达到本阶段所需积分 |
| rewards | yield | array | 奖励 |

================================================================================
文档结束
================================================================================

