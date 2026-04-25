<!--
参考代码文件:
- lua/framework/components/game_module/module_impl/master_play_module/master_play_mission_module.lua
最后参考时间: 2026-04-16
-->
================================================================================
                      MasterMission 玩法开发规范详细说明
================================================================================
                           版本: 2026-04-16
================================================================================

目录
----
1. 玩法概述
2. 核心数据结构
3. 逻辑模块 (MasterPlayMissionModule)
4. UI基类层次结构
5. 事件系统
6. 红点系统
7. 开发新MasterMission活动的完整步骤
8. 代码模板与示例
9. 常见问题与注意事项

================================================================================
1. 玩法概述
================================================================================

MasterMission 是 Master 活动系统中的"任务"玩法类型，用于实现任务收集类活动。

玩法标识：MasterPlayType.Mission = "MasterMission"

典型应用场景：
- 新手引导任务（NewBieMission）
- 房间引导任务（RoomGuideMission）
- 回归玩家任务（SeasonReturnMission）
- 神灵冲刺任务（DeityRushMission）
- 圣物同步任务（RelicSyncMission）

核心特点：
1. 支持任务分组（TaskGroup）
2. 每组包含多个任务（Task）
3. 任务可重复领取（claim_times）
4. 支持进度奖励（ProgressReward）
5. 支持组奖励（GroupReward）+ 双倍奖励
6. 支持最终大奖（FinalReward）+ 补领机制
7. 支持多种解锁方式（时间/顺序/积分）
8. 支持任务堆叠显示（type字段）
9. 支持难度等级限制（difficulty字段）

玩法变种（MasterMissionType）：
- MasterMissionType.None     -- 默认
- MasterMissionType.Mission  -- XX宝册
- MasterMissionType.Festival -- 福利活动

================================================================================
2. 核心数据结构
================================================================================

2.1 配置数据结构 (play_info.conf)
----------------------------------

play_info.conf = {
    id = "xxx",                    -- 玩法配置ID
    point_id = "xxx",              -- 积分ID（用于进度奖励）
    unlock_point_id = "xxx",       -- 解锁积分ID（用于难度解锁）
    
    -- 任务组解锁方式
    group_delta_time = 0,          -- 0:非按时间解锁（linear_unlock=1时前组完成才开后组）
                                   -- 1:每天解锁1组
                                   -- 2:顺序+时间解锁（param配置开启天数，完成前组可提前解锁）
                                   -- 3:按天数配置解锁（param配置每组开启天数）
                                   -- 4:顺序解锁（前一组组奖励领完才解锁下一组）
                                   -- 5:顺序解锁+组内积分解锁（组级同4；组内每个任务需积分>=difficulty且前置任务已领才解锁）
                                   -- 6:任务完成控制解锁（2n组对n天：第k天奇数组2k-1解锁，领完组奖励后偶数组2k解锁；需偶数个组且奇数组必须配group_rewards）
                                   -- 7:时间控制解锁+每天独立一组（第1天只有第1组可见，第2天只有第2组，过期锁定）
                                   -- 8:与7相同+未领取补发逻辑（服务端差异，前端逻辑同7）
    group_delta_param = {},        -- 解锁参数（天数配置等）
    linear_unlock = 0,             -- 0:非线性解锁 1:线性解锁（前组完成才能开启后组）
    
    -- 新解锁组是否显示"新"红点
    need_new_group_rd = 0,         -- 0:不需要 1:需要
    
    -- 任务组配置
    total_tasks = {
        [1] = {
            id = "group_1",             -- 任务组ID
            display_name = "i18n_key",  -- 显示名（i18n）
            my_group_index = 1,         -- 组索引（框架自动添加）
            
            tasks = {
                [1] = {
                    id = "task_1",          -- 任务ID
                    title = "i18n_key",     -- 任务标题（i18n）
                    display_name = "i18n",  -- 任务描述（i18n）
                    description = "i18n",   -- 详细说明（点击Tips按钮显示）
                    max_process = 100,      -- 完成所需进度
                    claim_times = 1,        -- 可领取次数
                    type = "kill_fish",     -- 任务类型（用于任务堆叠，可为空）
                    difficulty = 0,         -- 难度等级（0为无难度限制）
                    is_task_hint = 0,       -- 是否显示目标鱼提示
                    
                    rewards = {...},        -- 奖励配置
                    go_now = {...},         -- 前往按钮配置
                    task_filters = {...},   -- 任务过滤条件（目标鱼等）
                    
                    -- 框架自动添加
                    my_group_index = 1,     -- 所属组索引
                    my_group_conf = ref,    -- 所属组配置引用
                    my_task_index = 1,      -- 任务在组内的索引
                },
                ...
            },
            
            -- 组奖励配置
            group_rewards = {
                points = 3,             -- 需要完成多少个任务
                rewards = {...},        -- 奖励配置
                bigreward_show = {...}, -- 大奖预览配置
            },
            
            -- 双倍奖励配置（可选）
            extra_rewards = {...},
            extra_reward_condition = 0, -- 充值条件（0=无双倍奖励）
        },
        ...
    },
    
    -- 进度奖励配置
    progress_reward = {
        [1] = {
            id = "prog_1",
            points = 100,           -- 所需积分
            rewards = {...},        -- 奖励配置
        },
        ...
    },
    
    -- 最终大奖配置
    final_reward = {
        [1] = {
            id = "final_1",
            condition = {           -- 领取条件
                {vip_level = {0, -1}},  -- VIP等级范围
            },
            rewards = {...},
        },
        ...
    },
    final_reward_add = 0,           -- 0:不支持补领 1:支持补领
    final_reward_alltask = 0,       -- 0:默认（全部组任务领完才能领取）
                                    -- 1:每个任务至少领取1次才能领取（用于跨组模式）
}


2.2 运行时数据结构 (play_info.info)
------------------------------------

play_info.info = {
    task = {
        ["task_id"] = {
            p = 50,     -- 当前进度 (process)
            ct = 0,     -- 已领取次数 (claim_times)
        },
        ...
    },
    
    progress_record = {
        ["prog_id"] = 1,    -- 已领取的进度奖
        ...
    },
    
    group_record = {
        ["group_id"] = 1,   -- 已领取的组奖励
        ...
    },
    
    extra_group_record = {
        ["group_id"] = 1,   -- 已领取的双倍奖励
        ...
    },
    
    extra_g_p = 0,          -- 双倍奖励的充值进度
    
    final_reward = 0,       -- 已领取的最终大奖档次（0=未领取）
    
    ranking_data = {        -- 排行数据（可选）
        ["group_id"] = {
            rank = 1,
            total = 100,
            score = 500,
        },
        ...
    },
}


2.3 额外计算数据
----------------

框架在 OnMasterPlayInfoRefresh 中会自动添加：

play_info.reward_chip_by_vip_region = {
    [1] = {
        min_vip_lvl = 0,
        max_vip_lvl = 5,
        total_chip_count = 10000,
    },
    ...
}


================================================================================
3. 逻辑模块 (MasterPlayMissionModule)
================================================================================

文件位置: lua/framework/components/game_module/module_impl/master_play_module/
          master_play_mission_module.lua

继承关系: MasterPlayMissionModule <- MasterPlayModuleBase <- GameModule

3.1 获取模块实例
----------------

MasterPlayMissionModule.Instance


3.2 获取数据的API
-----------------

-- 获取玩法信息
MasterPlayMissionModule.Instance:GetMasterPlayInfo(master_play_id)
    返回: play_info = {conf = {...}, info = {...}}

-- 获取任务状态
MasterPlayMissionModule.Instance:GetTaskState(master_play_id, task_conf)
    返回: MasterMissionRowState.Claim/Doing/Lock/Done

-- 获取任务组状态
MasterPlayMissionModule.Instance:GetTaskGroupState(master_play_id, group_index)
    返回: MasterMissionGroupTabState.Unlock/Lock/Done

-- 获取任务组奖励状态
MasterPlayMissionModule.Instance:GetTaskGroupRewardState(master_play_id, group_index)
    返回: MMTaskGroupRewardState 枚举

-- 获取最终大奖领取状态
MMFinalRewardClaimState = {
    Claim = 0,      -- 第一次领
    Supplement = 1, -- 补领
    No = 2,         -- 不能领
}
MasterPlayMissionModule.Instance:GetFinalRewardClaimState(master_play_id)
    返回: MMFinalRewardClaimState.Claim/Supplement/No

-- 获取指定状态的任务数量
MasterPlayMissionModule.Instance:GetTaskNumOfTargetState(master_play_id, group_index, task_state)

-- 检查是否有可领取的奖励
MasterPlayMissionModule.Instance:CanClaimReward(master_play_id)

-- 检查进度是否达到
MasterPlayMissionModule.Instance:IsProgReached(master_play_id, points)

-- 检查进度奖是否已领取
MasterPlayMissionModule.Instance:IsProgClaimed(master_play_id, prog_reward_id)

-- 检查任务组是否已解锁
MasterPlayMissionModule.Instance:IsUnlockTaskGroup(master_data, play_info, group_index)

-- 检查组内任务是否全部领完
MasterPlayMissionModule.Instance:IsGroupTaskAllClaimed(play_info, group_index)

-- 检查组内任务是否全部完成（不管是否领取）
MasterPlayMissionModule.Instance:IsGroupComplete(play_info, group_index)

-- 检查组奖励是否已领取
MasterPlayMissionModule.Instance:IsTaskGroupRewardClaimed(master_play_id, task_group_id)

-- 检查组奖励是否可领取（未领取 + 满足完成条件）
MasterPlayMissionModule.Instance:CanClaimGroupReward(master_play_id, group_index)
    返回: true/false

-- 检查所有任务是否都至少领取1次（用于 final_reward_alltask = 1）
MasterPlayMissionModule.Instance:IsAllTaskClaimedAtLeastOnce(master_play_id)
    返回: true/false

-- 检查是否有组任务可领取
MasterPlayMissionModule.Instance:HasTaskReward(master_play_id, group_index, is_include_group_reward)

-- 获取最终大奖的金币数量
MasterPlayMissionModule.Instance:GetTargetFinalRewardChipCount(master_play_id)

-- 获取补领金币数量
MasterPlayMissionModule.Instance:GetFinalRewardSupplementChipCount(master_play_id)

-- 获取排行数据
MasterPlayMissionModule.Instance:GetMissionRank(master_play_id, group_id)
    返回: { rank, total, score }，不存在时返回 nil

-- 组奖励相关
MasterPlayMissionModule.Instance:IsGroupRewardClaimed(master_play_id, task_group_idx)   -- 组奖励是否已领取
MasterPlayMissionModule.Instance:IsDoubleGroupReward(master_play_id, task_group_idx)    -- 是否双倍组奖励

-- 任务状态查询
MasterPlayMissionModule.Instance:IsAllTaskComplete(master_play_id)                      -- 所有任务是否完成
MasterPlayMissionModule.Instance:IsTaskComplete(master_play_id, task)                  -- 单任务是否完成
MasterPlayMissionModule.Instance:IsTaskClaimed(master_play_id, task)                   -- 单任务奖励是否已领
MasterPlayMissionModule.Instance:GetComplateGroupTaskNums(master_play_id, task_group_id) -- 组内已完成任务数

-- 难度相关查询（group_delta_time == 5 时使用）
MasterPlayMissionModule.Instance:IsUnLockTaskInGroup(master_id, play_id, group_index, task_id)
    -- 类型5下判断组内单个任务是否解锁（积分>=difficulty 且前置任务已领）
MasterPlayMissionModule.Instance:IsGroupCompleteWithDifficulty(play_info, group_index)
    -- 含难度条件的组完成判断（进度达标+积分>=difficulty+有奖励）
MasterPlayMissionModule.Instance:IsGroupTaskAnyNotClaimedWithDifficulty(play_info, group_index)
    -- 含难度条件的组内是否有可领取奖励

-- 数据查询
MasterPlayMissionModule.Instance:GetGroupId(master_play_id, task_id)                   -- 根据任务ID获取组ID
MasterPlayMissionModule.Instance:GetTaskIndexInGroup(master_play_id, task_id)          -- 任务在组内的索引
MasterPlayMissionModule.Instance:GetIsGroupWatched(master_play_id, group_id)           -- 组是否已查看
MasterPlayMissionModule.Instance:GetFirstDidnotClaimedTaskGroupIndex(master_play_id)   -- 首个未领取组索引
MasterPlayMissionModule.Instance:GetAllCanClaimRewardTaskConf(master_play_id)          -- 所有可领奖任务配置
MasterPlayMissionModule.Instance:IsTaskClaimedById(master_play_id, task_id)            -- 按task_id查询是否已领取
MasterPlayMissionModule.Instance:GetTaskRewardPointNum(master_play_id, group_index)    -- 组内可领取的积分奖励总数
MasterPlayMissionModule.Instance:GetTaskRewardPointTaskIdList(master_play_id)          -- 所有可领积分奖励的任务id列表
MasterPlayMissionModule.Instance:FinalRewardAddTags(msg, multi_rewards)                -- 为大奖恭喜获得添加VIP横幅标签


3.3 请求API
-----------

-- 领取单个任务奖励
MasterPlayMissionModule.Instance:RequestClaimSingleTaskReward(master_play_id, task_id)

-- 一键领取任务奖励
MasterPlayMissionModule.Instance:RequestClaimAllTasksReward(master_play_id, group_index, is_all_group)
    group_index: 组索引（从1开始）
    is_all_group: 是否领取所有组

-- 领取进度奖励
MasterPlayMissionModule.Instance:RequestClaimProgReward(master_play_id, progress_id, is_all)

-- 领取任务组奖励
MasterPlayMissionModule.Instance:ClaimTaskGroupReward(master_play_id, group_id)

-- 领取最终大奖
MasterPlayMissionModule.Instance:RequestClaimFinalReward(master_play_id)

-- 打开UI通知
MasterPlayMissionModule.Instance:OpenUI(action_id)


3.4 管理API
-----------

-- 设置/获取当前MasterMission种类
MasterPlayMissionModule.Instance:SetMissionType(MasterMissionType.Mission)
MasterPlayMissionModule.Instance:GetMissionType()

-- 标记组已查看（消除"新"红点）
MasterPlayMissionModule.Instance:MarkGroupWatched(master_play_id, group_id)


================================================================================
4. UI基类层次结构
================================================================================

重要原则（优先复用基类）：
- MasterMission 相关 UI 开发时，若需求形态能覆盖在现有基类能力范围内，必须优先继承并复用本节基类（Row/RowBox/Tab/TabBox...）。
- 不要重复实现基类已提供的通用逻辑（如：拉取 play_info/group_conf、任务状态判断、事件刷新、排序/堆叠、通用按钮逻辑等）。
- 若在各自玩法目录或项目公共目录中已存在“公有基类/公用组件”，也遵循同样原则：**优先使用**。
- 只有在你（需求方/负责人）明确说明“不使用基类”或基类能力无法满足且改造成本不合理时，才允许另写一套。

4.1 任务行 (MasterMissionRowBase)
---------------------------------

文件: lua/product/components/ui_item/master/master_mission_base/master_mission_row_base.lua
绑定UMG: UMG需要继承自 [UMG_MasterMission_RowBase]

职责：单条任务的显示和交互

状态枚举：
MasterMissionRowState = {
    Claim = "Claim",  -- 可领取
    Doing = "Doing",  -- 进行中
    Lock  = "Lock",   -- 未解锁
    Done  = "Done",   -- 已完成
}

优先级（排序用）：
MasterMissionRowStateToPriority = {
    Claim = 4,  -- 最高
    Doing = 3,
    Lock  = 2,
    Done  = 1,  -- 最低
}

关键成员变量：
- self.master_play_id   -- 玩法ID
- self.group_index      -- 组索引
- self.task_index       -- 任务索引
- self.play_info        -- 玩法信息
- self.master_data      -- 活动数据
- self.group_conf       -- 组配置
- self.task_conf        -- 任务配置
- self.task_info        -- 任务运行时信息
- self.task_state       -- 当前任务状态
- self.yield_data_list  -- 奖励列表 [{yield_item_info, yield_item_widget}]

可重写方法：
- CustomRefresh()       -- 自定义刷新逻辑（在基础刷新后调用）

配置方法：
- SetNeedClaimAll(bool)         -- 设置是否使用一键领取
- SetNeedClaimAllGroup(bool)    -- 一键领取时是否领取所有组
- SetDescriptionUMG(name)       -- 设置描述Tips的UMG名称
- SetFishTargetUMG(name)        -- 设置目标鱼UMG名称
- SetGonowCloseInfo(info)       -- 设置GoNow按钮的关闭信息

UMG需要实现的方法：
- RefreshDisplayTextAndProgText(display_text, prog_text)
- RefreshProgressBar(percent)
- SetStateToClaim() / SetStateToDoing() / SetStateToDone() / SetStateToLock()
- ClearYieldBox() / AddYield(umg)
- SetTitleText(text)
- RefreshCanClaimTimesText(text, is_show)
- RefreshClaimedTimesText(text, is_show)
- SetDifficulty(difficulty)
- AfterRefresh(sort_index)


4.2 任务行容器 (MasterMissionRowBoxBase)
----------------------------------------

文件: lua/product/components/ui_item/master/master_mission_base/master_mission_row_box_base.lua
绑定UMG: UMG需要继承自 [UMG_MasterMission_RowBoxBase]

职责：管理一组任务行的创建、刷新、排序

关键成员变量：
- self.master_play_id   -- 玩法ID
- self.group_index      -- 当前显示的组索引
- self.row_data_list    -- 任务行数据列表 [{task_index, task_conf, widget}]
- self.sort_function    -- 排序函数

必须重写：
- GetRowLuaClassName()  -- 返回Row的Lua类名
- GetRowUMGClassName()  -- 返回Row的UMG类名

可重写：
- CustomAfterSort()     -- 排序后的自定义处理

配置方法：
- SetSortFunction(func) -- 设置排序函数

预定义排序函数：
- MasterMissionSortRowFunction_ConfIndex      -- 按配置顺序
- MasterMissionSortRowFunction_ClaimDoingDone -- 按状态优先级

UMG需要实现：
- OnRefresh()
- ClearRowBox()
- AddRow(row_umg)


4.3 任务组Tab (MasterMissionGroupTabBase)
-----------------------------------------

文件: lua/product/components/ui_item/master/master_mission_base/master_mission_group_tab_base.lua
绑定UMG: UMG需要继承自 [UMG_MasterMission_GroupTabBase]

职责：任务组Tab的显示和交互

状态枚举：
MasterMissionGroupTabState = {
    Unlock = 3, -- 已解锁
    Lock   = 2, -- 未解锁
    Done   = 1, -- 已完成
}

关键成员变量：
- self.master_play_id   -- 玩法ID
- self.group_index      -- 组索引
- self.tab_state        -- Tab状态
- self.group_conf       -- 组配置
- self.red_dot_widget   -- 红点组件

UMG需要实现：
- SetStateToUnlock() / SetStateToLock() / SetStateToDone()
- SetIsSelected(is_selected)
- SetDisplayText(text)
- UpdateTaskStateNum(doing_count, claim_count, done_count)


4.4 任务组Tab容器 (MasterMissionGroupTabBoxBase)
------------------------------------------------

文件: lua/product/components/ui_item/master/master_mission_base/master_mission_group_tab_box_base.lua
绑定UMG: UMG需要继承自 [UMG_MasterMission_GroupTabBoxBase]

职责：管理任务组Tab的创建、选中切换

关键成员变量：
- self.master_play_id       -- 玩法ID
- self.row_box_widget       -- 关联的RowBox组件
- self.cur_group_index      -- 当前选中的组索引
- self.tab_data_list        -- Tab数据列表
- self.pri_index_function   -- 优先选中策略函数
- self.is_enable_view_unlock -- 是否允许查看未解锁的组

必须重写：
- GetTabLuaClassName()  -- 返回Tab的Lua类名（默认"MasterMissionGroupTabBase"）
- GetTabUMGClassName()  -- 返回Tab的UMG类名

配置方法：
- SetPriorityGroupIndexFunction(func)   -- 设置优先选中策略
- EnableViewLockGroup(bool)             -- 是否允许查看未解锁组

预定义优先策略（成员方法）：
- __MasterMissionPriorityGroupIndexFunction_Stay()
    保持当前选中
    
- __MasterMissionPriorityGroupIndexFunction_CanClaimOrLastest()
    优先可领取的组，否则最新已解锁但未完成的组

UMG需要实现：
- ClearTabBox()
- AddTab(tab_umg)


4.5 进度奖相关基类
------------------

MasterMissionProgBase      -- 进度奖容器基类（待完善）
MasterMissionProgItemBase  -- 进度奖项基类（待完善）

文件：
- lua/product/components/ui_item/master/master_mission_base/master_mission_prog_base.lua
- lua/product/components/ui_item/master/master_mission_base/master_mission_prog_item_base.lua


4.6 目标鱼组件
--------------

MasterMissionCommonFishTarget

文件: lua/product/components/ui_item/master/master_mission_base/master_mission_common_fish_target.lua

用途：显示任务目标鱼的弹窗


================================================================================
5. 事件系统
================================================================================

5.0 模块自身监听的事件
-----------------------

MasterPlayMissionModule 在 Init 中监听以下事件：

- GameEventType.MasterMissionOpenUI → OpenUI（打开UI通知）
- GameEventType.VIPInfoChanged → OnVIPInfoChanged（VIP升级时刷新补领红点）
- GameEventType.ANewDay → OnNewDay（跨天刷新任务组红点）
- GameEventType.MasterPointChanged → OnPointChanged（积分变化时刷新相关红点）
- GameEventType.BreakGrowthChipInflationValueChanged → OnChipInflationChanged（炮段膨胀变化时刷新VIP分段金币数）
- GameEventType.WeaponBetInflationChanged → OnChipInflationChanged（武器投注膨胀变化时刷新VIP分段金币数）


5.1 MasterMission专属事件
-------------------------

-- 任务信息更新（进度/状态变化）
GameEventType.MasterMissionTaskInfoUpdate
    参数: master_play_id
    触发时机: 任务进度推送/领取奖励后

-- 任务信息更新完成（用于排序后的后处理）
GameEventType.MasterMissionTaskInfoUpdateComplete
    参数: master_play_id
    触发时机: 任务信息更新后

-- 任务奖励领取完成
GameEventType.MasterMissionClaimedTaskReward
    参数: master_play_id, res
    触发时机: 领取任务奖励协议返回后

-- 任务领取返回（专注于领取动作）
GameEventType.MasterMissionTaskClaimReturn
    参数: master_play_id
    触发时机: 任务领取成功后

-- 任务进度推送（服务器主动推送）
GameEventType.MasterMissionTaskPush
    参数: master_play_id, res
    触发时机: 服务器推送任务进度时

-- 进度奖信息更新
GameEventType.MasterMissionProgressInfoUpdate
    参数: master_play_id
    触发时机: 领取进度奖后

-- 进度奖动画返回（用于插入自定义动画）
GameEventType.MasterMissionProgressAnimReturn
    参数: master_play_id
    返回: 是否有动画要播放

-- 组奖励刷新
GameEventType.MasterMissionRefreshGroupReward
    参数: master_play_id, group_id
    触发时机: 领取组奖励后

-- 组额外进度刷新
GameEventType.MasterMissionGroupExtraProgRefresh
    参数: master_play_id
    触发时机: 双倍奖励进度更新时

-- 最终大奖刷新
GameEventType.MasterMissionRefreshFinalReward
    参数: master_play_id
    触发时机: 领取最终大奖后

-- 点击Tab
GameEventType.MasterMissionClickTab
    参数: (由具体实现决定)

-- Tab点击选中按钮（基类内部使用）
GameEventType.MasterMissionGroupTabClickSelectBtn
    参数: master_play_id, group_index
    触发时机: 用户点击Tab选中按钮时

-- 切换组
GameEventType.MasterMissionChangeGroup
    参数: master_play_id, group_index
    触发时机: 当前显示的组切换时

-- 打开UI
GameEventType.MasterMissionOpenUI
    参数: action_id


5.2 监听事件示例
----------------

function YourClass:Constructor(UMG)
    -- 注册事件
    self:RegisterEvent(GameEventType.MasterMissionTaskClaimReturn, self.OnTaskClaimReturn)
    self:RegisterEvent(GameEventType.MasterMissionRefreshGroupReward, self.OnRefreshGroupReward)
    self:RegisterEvent(GameEventType.MasterMissionChangeGroup, self.OnChangeGroup)
end

function YourClass:OnTaskClaimReturn(master_play_id)
    if(self.master_play_id == master_play_id) then
        self:Refresh()
    end
end

function YourClass:OnRefreshGroupReward(master_play_id, group_id)
    if(self.master_play_id == master_play_id) then
        self:Refresh()
    end
end

function YourClass:OnChangeGroup(master_play_id, group_index)
    if(self.master_play_id == master_play_id) then
        self.cur_group_index = group_index
        self:RefreshGroup()
    end
end


================================================================================
6. 红点系统
================================================================================

6.1 红点Key获取方法
-------------------

-- 所有红点（任务+进度+组+大奖+补领）
MasterPlayMissionModule.Instance:GetRedDotKey(master_play_id)

-- 所有奖励红点（不含"新"红点）
MasterPlayMissionModule.Instance:GetRedDotKey_Reward(master_play_id)

-- 所有"新"红点
MasterPlayMissionModule.Instance:GetRedDotKey_New(master_play_id)

-- 任务红点
MasterPlayMissionModule.Instance:GetRedDotKey_Task(master_play_id)
    Key格式: "Master_Mission_Task_RedDot_{master_play_id}"

-- 进度奖红点
MasterPlayMissionModule.Instance:GetRedDotKey_Prog(master_play_id)
    Key格式: "Master_Mission_Prog_RedDot_{master_play_id}"

-- 单个任务组红点
MasterPlayMissionModule.Instance:GetRedDotKey_TaskGroup(master_play_id, group_id)
    Key格式: "Master_Mission_TaskGroup_{master_play_id}_{group_id}"

-- 所有任务组红点
MasterPlayMissionModule.Instance:GetRedDotKey_AllTaskGroup(master_play_id)
    Key格式: "Master_Mission_AllTaskGroup_{master_play_id}"

-- 单个任务组"新"红点
MasterPlayMissionModule.Instance:GetRedDotKey_TaskGroup_New(master_play_id, group_id)
    Key格式: "Master_Mission_TaskGroup_New_{master_play_id}_{group_id}"

-- 所有任务组"新"红点
MasterPlayMissionModule.Instance:GetRedDotKey_AllTaskGroup_New(master_play_id)
    Key格式: "Master_Mission_AllTaskGroup_New_{master_play_id}"

-- 最终大奖红点
MasterPlayMissionModule.Instance:GetRedDotKey_FinalReward(master_play_id)
    Key格式: "Master_Mission_FinalReward_{master_play_id}"

-- 最终大奖补领红点
MasterPlayMissionModule.Instance:GetRedDotKey_FinalRewardSupplement(master_play_id)
    Key格式: "Master_Mission_FinalRewardSupplement_{master_play_id}"

-- 难度解锁任务红点
MasterPlayMissionModule.Instance:GetRedDotKey_DifficultyMission(master_play_id, group_id)
    Key格式: "Master_Mission_ProgUnLockMission_{master_play_id}_{group_id}"

-- 所有难度解锁任务红点
MasterPlayMissionModule.Instance:GetRedDotKey_AllDifficultyMission(master_play_id)
    Key格式: "Master_Mission_AllProgUnLockMission_{master_play_id}"


6.2 红点使用示例
----------------

-- 在Tab上绑定红点
function YourTab:Constructor(UMG)
    self.red_dot_widget = self:BindUIWidget("NewCommonRedDot", self.UMG.RedDot)
end

function YourTab:Refresh_Impl()
    if(self.red_dot_widget) then
        self.red_dot_widget:SetKey(
            MasterPlayMissionModule.Instance:GetRedDotKey_TaskGroup(
                self.master_play_id,
                self.group_conf.id
            )
        )
    end
end

-- 在入口上绑定红点
function YourEntry:SetRedDot()
    local red_dot_key = MasterPlayMissionModule.Instance:GetRedDotKey(self.master_play_id)
    self.red_dot_widget:SetKey(red_dot_key)
end


================================================================================
7. 开发新MasterMission活动的完整步骤
================================================================================

7.x 基类复用要求（必须遵守）
--------------------------

- 优先在 `lua/product/components/ui_item/master/master_mission_base/` 查找可直接复用的基类（如 `MasterMissionRowBase` / `MasterMissionRowBoxBase` / `MasterMissionGroupTabBase` / `MasterMissionGroupTabBoxBase`）。
- 若在对应玩法目录或项目公共目录中已存在同类“公有基类/公用组件”，也必须先评估复用；除非你明确告知“不使用基类”。
- 只有当需求与基类设计目标明显冲突，或复用/扩展会导致基类变形（污染通用性）时，才考虑另写实现。

7.1 创建文件结构
----------------

lua/product/components/ui_item/master/{活动名}/
    ├── {活动名}_main.lua           -- 主界面Lua
    └── 其他组件...

UE蓝图目录：
Content/UI/Master/{活动名}/
    ├── UMG_{活动名}_Main.uasset    -- 主界面UMG
    ├── UMG_{活动名}_Row.uasset     -- 任务行UMG
    ├── UMG_{活动名}_Tab.uasset     -- 组TabUMG（可选）
    └── ...


7.2 创建主界面类
----------------

_class("YourMissionMain", UIWidget)
YourMissionMain = YourMissionMain

function YourMissionMain:Constructor(UMG)
    -- 注册按钮回调
    self:AddCallback("CloseBtn", "OnClicked")
    self:AddCallback("GroupRewardBtn", "OnClicked")
    self:AddCallback("FinalRewardBtn", "OnClicked")
    
    -- 注册事件
    self:RegisterEvent(GameEventType.MasterMissionTaskClaimReturn, self.OnTaskClaimReturn)
    self:RegisterEvent(GameEventType.MasterMissionRefreshGroupReward, self.OnRefreshGroupReward)
    self:RegisterEvent(GameEventType.MasterMissionRefreshFinalReward, self.OnRefreshFinalReward)
    self:RegisterEvent(GameEventType.MasterMissionChangeGroup, self.OnChangeGroup)
end

function YourMissionMain:ReceivedOnCreated(dialog, master_data, default_show_master_play_type, bi_args)
    self.parent_dialog = dialog
    self.master_data = master_data
    self.bi_args = bi_args
    
    -- 获取玩法信息
    self.play_info = self.master_data:GetMasterPlayInfo(MasterPlayType.Mission)
    self.master_play_id = self.master_data:GetMasterPlayID(MasterPlayType.Mission)
    
    self:Init()
    self:Refresh()
end

function YourMissionMain:Init()
    -- 创建Row容器
    self.row_box = self:BindUIWidget("YourMissionRowBox", self.UMG.RowBox)
    
    -- 创建Tab容器（如果有多组）
    self.tab_box = self:BindUIWidget(
        "YourMissionTabBox",
        self.UMG.TabBox,
        self.master_play_id,
        self.row_box
    )
    self.cur_group_index = self.tab_box.cur_group_index
end

function YourMissionMain:Refresh()
    -- 刷新组奖励、最终大奖等...
end


7.3 创建子项类
--------------

-- 任务行
_class("YourMissionRow", MasterMissionRowBase)
YourMissionRow = YourMissionRow

function YourMissionRow:Constructor()
    -- 配置一键领取（如需要）
    self:SetNeedClaimAll(true)
end

function YourMissionRow:CustomRefresh()
    -- 自定义刷新逻辑
    -- 例如：隐藏已完成任务的奖励名称
    if (self.task_state == MasterMissionRowState.Done) then
        for _, yield_data in ipairs(self.yield_data_list) do
            yield_data.yield_item_widget:HideName()
        end
    end
end


-- 任务行容器
_class("YourMissionRowBox", MasterMissionRowBoxBase)
YourMissionRowBox = YourMissionRowBox

function YourMissionRowBox:Constructor(UMG)
    -- 设置排序方式
    self:SetSortFunction(MasterMissionSortRowFunction_ClaimDoingDone)
end

function YourMissionRowBox:GetRowLuaClassName()
    return "YourMissionRow"
end

function YourMissionRowBox:GetRowUMGClassName()
    return "UMG_YourMission_Row"
    -- 或从UMG获取: return self.UMG.RowUMGClassName
end

function YourMissionRowBox:CustomAfterSort()
    -- 排序后自动滚动到第一个可领取或进行中的任务
    for _, row_data in ipairs(self.row_data_list) do
        if (row_data.widget.task_state == MasterMissionRowState.Claim or
            row_data.widget.task_state == MasterMissionRowState.Doing
        ) then
            self.UMG:ScrollToTargetRowWidget(row_data.widget.UMG)
            break
        end
    end
end


-- 任务组Tab（如需要）
_class("YourMissionTab", MasterMissionGroupTabBase)
YourMissionTab = YourMissionTab

function YourMissionTab:Refresh_Impl(...)
    YourMissionTab.super.Refresh_Impl(self, ...)
    -- 自定义刷新逻辑
end


-- 任务组Tab容器
_class("YourMissionTabBox", MasterMissionGroupTabBoxBase)
YourMissionTabBox = YourMissionTabBox

function YourMissionTabBox:Constructor(UMG)
    -- 设置优先选中策略
    self:SetPriorityGroupIndexFunction(
        MasterMissionGroupTabBoxBase.__MasterMissionPriorityGroupIndexFunction_CanClaimOrLastest
    )
    -- 允许查看未解锁的组
    self:EnableViewLockGroup(true)
end

function YourMissionTabBox:GetTabLuaClassName()
    return "YourMissionTab"
end

function YourMissionTabBox:GetTabUMGClassName()
    return "UMG_YourMission_Tab"
end


7.4 单组任务的简化写法
----------------------

如果活动只有一组任务，可以省略Tab相关类，直接初始化RowBox：

function YourMissionMain:Init()
    self.row_box = self:BindUIWidget("YourMissionRowBox", self.UMG.RowBox)
    -- 直接刷新第一组
    self.row_box:Refresh(self.master_play_id, 1)
end


================================================================================
8. 代码模板与示例
================================================================================

8.1 完整的单组任务活动示例
--------------------------

以下为简化的单组模式示意代码，非 deity_rush 的真实实现（deity_rush 实际为 UIWidget 嵌套 MasterMissionRowBox_CreateFromClass）。

-- 示意：单组任务时，可使用一个继承 MasterMissionRowBoxBase 的组件，固定显示第 1 组

_class("SimpleMissionMain", MasterMissionRowBoxBase)
SimpleMissionMain = SimpleMissionMain

function SimpleMissionMain:ReceivedOnCreated(dialog, master_data, default_show_master_play_type, biArgs)
    local master_play_id = master_data:GetMasterPlayID(MasterPlayType.Mission)
    -- 调用父类初始化，固定显示第1组
    SimpleMissionMain.super.ReceivedOnCreated(self, master_play_id, 1)
end

function SimpleMissionMain:GetRowUMGClassName()
    return self.UMG:GetRowUMGClassName()
end


8.2 完整的多组任务活动示例
--------------------------

参考: lua/product/components/ui_item/master/room_guide_mis/room_guide_mis_main.lua

完整的类层次：
- RoomGuideMisMain      (主界面)
- RoomGuideMisRowBox    (继承 MasterMissionRowBoxBase)
- RoomGuideMisRow       (继承 MasterMissionRowBase)
- RoomGuideMisGroupTabBox (继承 MasterMissionGroupTabBoxBase)

关键点：
1. 主界面负责整体布局和组奖励/最终大奖的显示
2. RowBox 和 TabBox 作为子组件在 Init 中创建
3. 通过事件监听来响应数据变化
4. TabBox 持有 RowBox 的引用，切换组时自动刷新 RowBox


8.3 领取组奖励的实现
--------------------

function YourMissionMain:GroupRewardBtnOnClicked()
    local group_conf = self.play_info.conf.total_tasks[self.cur_group_index]
    if(not group_conf) then
        Log.error("Invalid group_index:", self.cur_group_index)
        return
    end
    
    -- 检查是否可以领取
    if(MasterPlayMissionModule.Instance:IsGroupTaskAllClaimed(self.play_info, self.cur_group_index) and
       not MasterPlayMissionModule.Instance:IsTaskGroupRewardClaimed(self.master_play_id, group_conf.id)
    ) then
        MasterPlayMissionModule.Instance:ClaimTaskGroupReward(
            self.master_play_id,
            group_conf.id
        )
    else
        -- 显示未完成提示
        UIHelper.ShowTip(UIHelper.FormatI18NTextWithLatentArguments("complete_all_tasks_first", {}))
    end
end


8.4 领取最终大奖的实现
----------------------

function YourMissionMain:FinalRewardBtnOnClicked()
    local state = MasterPlayMissionModule.Instance:GetFinalRewardClaimState(self.master_play_id)
    if(state == MMFinalRewardClaimState.Claim or 
       state == MMFinalRewardClaimState.Supplement
    ) then
        MasterPlayMissionModule.Instance:RequestClaimFinalReward(self.master_play_id)
    end
end

-- 自动领取最终大奖（在活动打开时）
function YourMissionMain:TryClaimFinalReward()
    if(MasterPlayMissionModule.Instance:GetFinalRewardClaimState(self.master_play_id) == MMFinalRewardClaimState.Claim) then
        MasterPlayMissionModule.Instance:RequestClaimFinalReward(self.master_play_id)
    end
end


================================================================================
9. 常见问题与注意事项
================================================================================

9.1 任务堆叠机制
----------------

当多个任务的 task.type 字段相同时，系统会自动进行任务堆叠：
- 只显示一个任务行
- 自动选择优先级最高的任务显示（可领取 > 进行中 > 未解锁 > 已完成）
- RowBox 会自动处理堆叠逻辑

如果需要自定义堆叠行为，可以重写 Row 的 ChangeTaskIndexByTaskType 方法。


9.2 任务解锁规则
----------------

group_delta_time 的各种模式：
- 0: 非按时间解锁，使用 linear_unlock 控制
- 1: 每天解锁1组（常用于跨组显示模式，配合 final_reward_alltask 使用）
- 2: 顺序+时间解锁（完成前组可提前解锁，否则按时间）
- 3: 按天数配置解锁（使用 group_delta_param 配置）
- 4: 顺序解锁（领取完前组才能开启后组）
- 5: 顺序解锁 + 组内任务也顺序解锁
- 6: 开放时间总共 n 天、2n 组任务，第 k 天仅有第 2k-1 组解锁，完成该组后第 2k 组解锁
- 7/8: 单组模式，页面按组切换，宝箱对应 group_rewards


9.3 跨组模式与单组模式的宝箱奖励
--------------------------------

根据 group_delta_time 的配置，宝箱奖励对应不同的字段：

【跨组模式】(group_delta_time = 1 或其他非 7/8)
- 宝箱对应 final_reward 配置
- 使用 GetFinalRewardClaimState 判断领取状态
- 若 final_reward_alltask = 1，需要所有任务至少领取1次
- 调用 RequestClaimFinalReward 领取

示例：
```lua
function YourClass:RefreshChest_FinalReward(play_info)
    local master_play_id = play_info.conf.id
    
    -- 统计任务领取进度（用于显示）
    local total_count = 0
    local claimed_count = 0
    local task_info_dict = play_info.info.task or {}
    for _, group_conf in ipairs(play_info.conf.total_tasks or {}) do
        for _, task_conf in ipairs(group_conf.tasks or {}) do
            total_count = total_count + 1
            local task_info = task_info_dict[task_conf.id]
            if task_info and (task_info.ct or 0) >= 1 then
                claimed_count = claimed_count + 1
            end
        end
    end
    
    -- 使用 module 函数判断领取状态
    local claim_state = MasterPlayMissionModule.Instance:GetFinalRewardClaimState(master_play_id)
    local can_claim = (claim_state == MMFinalRewardClaimState.Claim or claim_state == MMFinalRewardClaimState.Supplement)
    local is_claimed = (claim_state == MMFinalRewardClaimState.No and claimed_count >= total_count)
    
    self.UMG:SetChestState(claimed_count, total_count, can_claim, is_claimed)
end
```

【单组模式】(group_delta_time = 7 或 8)
- 宝箱对应 group_rewards 配置
- 使用 CanClaimGroupReward 判断是否可领取
- 使用 IsTaskGroupRewardClaimed 判断是否已领取
- 调用 ClaimTaskGroupReward 领取

示例：
```lua
function YourClass:RefreshChest_GroupReward(play_info)
    local master_play_id = play_info.conf.id
    local group_index = self:GetCurrentUnlockedGroupIndex(play_info)
    local group_conf = play_info.conf.total_tasks[group_index]
    
    if not group_conf then
        self.UMG:SetChestState(0, 0, false, false)
        return
    end
    
    -- 使用 module 函数统计完成任务数
    local complete_count = MasterPlayMissionModule.Instance:GetTaskNumOfTargetState(
        master_play_id, group_index, MasterMissionRowState.Claim
    ) + MasterPlayMissionModule.Instance:GetTaskNumOfTargetState(
        master_play_id, group_index, MasterMissionRowState.Done
    )
    
    local group_rewards = group_conf.group_rewards
    local require_count = group_rewards and group_rewards.points or #(group_conf.tasks or {})
    local is_claimed = MasterPlayMissionModule.Instance:IsTaskGroupRewardClaimed(master_play_id, group_conf.id) ~= nil
    local can_claim = MasterPlayMissionModule.Instance:CanClaimGroupReward(master_play_id, group_index)
    
    self.UMG:SetChestState(complete_count, require_count, can_claim, is_claimed)
end
```


9.4 一键领取的使用
------------------

在 Row 的 Constructor 中设置：
self:SetNeedClaimAll(true)           -- 一键领取当前组
self:SetNeedClaimAllGroup(true)      -- 一键领取所有组

注意：一键领取调用的是 RequestClaimAllTasksReward，只会领取已完成的任务。


9.5 VIP相关的最终大奖
---------------------

如果最终大奖配置了 VIP 条件，需要监听 VIP 变化事件：

self:RegisterEvent(GameEventType.VIPInfoChanged, self.OnVIPInfoChanged)

function YourClass:OnVIPInfoChanged(is_vip_level_up)
    if(is_vip_level_up) then
        self:RefreshFinalReward()
    end
end


9.6 积分相关的刷新
------------------

如果任务奖励包含积分，模块会自动处理积分同步。
但如果有额外的积分显示UI，需要监听：

self:RegisterEvent(GameEventType.MasterPointChanged, self.OnPointChanged)


9.7 错误处理
------------

所有获取数据的方法都应该进行空值检查：

local play_info = MasterPlayMissionModule.Instance:GetMasterPlayInfo(master_play_id)
if(not play_info) then
    Log.error("Cant find play_info, master_play_id:", master_play_id)
    return
end


9.8 UMG蓝图要求
---------------

Row UMG 需要继承 UMG_MasterMission_RowBase 并实现：
- ClaimBtn: Button
- GoNowBtn: Button
- TipsBtn: Button
- RefreshDisplayTextAndProgText(FText, FText)
- RefreshProgressBar(float)
- SetStateToClaim/ToDoing/ToDone/ToLock()
- ClearYieldBox() / AddYield(UWidget)
- SetTitleText(FText)
- RefreshCanClaimTimesText(FText, bool)
- RefreshClaimedTimesText(FText, bool)
- SetDifficulty(int)
- AfterRefresh(int)

RowBox UMG 需要继承 UMG_MasterMission_RowBoxBase 并实现：
- OnRefresh()
- ClearRowBox()
- AddRow(UWidget)

Tab UMG 需要继承 UMG_MasterMission_GroupTabBase 并实现：
- SelectBtn: Button
- RedDot: UWidget (红点容器)
- SetStateToUnlock/ToLock/ToDone()
- SetIsSelected(bool)
- SetDisplayText(FText)
- UpdateTaskStateNum(int, int, int)

TabBox UMG 需要继承 UMG_MasterMission_GroupTabBoxBase 并实现：
- ClearTabBox()
- AddTab(UWidget)


10. 配表结构（MasterMission.xls）

### Sheet: Main

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 玩法id |
| comment | string | - | 自己看的备注 |
| display_name | string | - | 该任务的名字，用于补发邮件的读取。 |
| is_not_congratulation | int | - | 0或者不填表示要显示恭喜获得 / 1-代表不显示恭喜获得 / 2-程序处理是否显示恭喜获得 |
| congratulations_umg | string | - | 领取Task奖励时， / 指定特殊的恭喜获得 |
| deal_pre_rmb_count | int | - | 充值相关任务，是否统计玩家未接到活动时的当天充值金额 / 1-代表统计玩家当天的充值金额 / 不配则不统计 |
| popup_bet | int | - | 用于配置玩法内强弹出现的炮倍条件，前端用字段，炮倍为游戏内看到的数值 |
| return_point | string | - | 用于不同活动中做积分回收的关联查询 |
| total_tasks | TaskGroup | array | 一次活动不用刷新的总任务组，引用 TaskGroup 子表 |
| group_delta_time | int | - | 0-非按时间解锁 / 1-按天解锁，每天解锁1组 / 2-顺序+时间解锁，param配置开启天数 / 3-时间控制解锁，param配置开启天数 / 4-任务+组任务顺序解锁 / 5-master_point数量+顺序控制解锁 / 6-任务完成控制解锁 / 7-时间控制解锁，且每天独立一组任务 / 8-时间控制解锁，且每天独立一组任务，且有未领取补发逻辑 |
| group_delta_param | int | array | 各任务组解锁时间 |
| unlock_point_id | string | - | group_delta_time==5时 / 任务解锁判断依据的积分id |
| point_id | string | - | 积分id |
| reward_mail | string | - | 未领取奖励补发邮件 / #R:SystemMail |
| mail_expire_by_act_end | int | - | 补发邮件结束时间是否与对应act结束时间相关 / 0-无关 / 1-相关 |
| point_mail | string | - | 积分回收邮件 |
| progress_reward | ProgressReward | array | 进度奖，引用 ProgressReward 子表 |
| extra_reward_type | string | - | 额外领取一次组奖励需要的付费类型 / （不配置默认没有额外领取） / 累消-conch / 累充-currency |
| go_now | object | - | 跳游戏内界面 Go Now（界面跳转）规则 |
| linear_unlock | int | - | 组任务是否存在线性解锁逻辑（完成上一组内全部任务才可以解锁领取下一组奖励） |
| final_reward | FinalReward | array | 全部任务组奖励领取后可领取大奖，引用 FinalReward 子表 |
| final_reward_alltask | int | - | 1=全部任务组中每个任务奖励领取领取次数>=1后可领取大奖 / 0=final_reward老逻辑 |
| final_reward_add | int | - | 活动期间是否根据玩家vip等级提升补发final_reward的奖励 / 0=不补发，领取大奖算活动完成 / 1=补发 |
| need_new_group_rd | int | - | 任务组解锁是否显示【新】 / 1=显示解锁新红点 / 0=不显示新红点 |
| coin_point | string | array | 活动需要转金币的point_id / 没有point_value的point将丢弃 / 没有在此处配置的point将随邮件发放 |
| item_recycle | string | array | 活动需要转金币的item_id / 没有在此处配置的item将随邮件发放 |

### Sheet: TaskGroup

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | - |
| comment | string | - | 备注 |
| display_name | string | - | i18n key |
| tasks | AllTask | array | 本任务组包含哪些子任务，列表顺序代表默认显示顺序，引用 AllTask 子表 |
| group_rewards | ProgressReward | - | 任务组完成奖励，引用 ProgressReward 子表 |
| extra_reward_condition | int | - | 额外领取一次组奖励需要的数值需求 / （不配置默认没有额外领取） |
| extra_rewards | yield | array | 额外领取一次奖励的内容 |
| task_inflation_type | int | - | 金币的膨胀属性 / 不膨胀：0 / 免费膨胀：1 / 付费膨胀：2 |
| is_ranking | int | - | 是否具有按完成进度计算的排行榜功能 / 1：是 / 0：否 |

### Sheet: ProgressReward

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 玩法id |
| comment | string | - | 自己看的备注 |
| is_group | int | - | 0-非组任务奖励 / 1-组任务额外奖励 |
| points | int | - | 达到本阶段所需积分/需要完成的任务条数 |
| rewards | yield | array | 奖励 |
| panel_size | int | - | 进度奖在界面的大小 / 0-大；1-非大；2-大且展示动画 |
| bigreward_show | BigReward | - | 大奖切换展示相关配置，引用 BigReward 子表 |
| inflation_type | int | - | 金币的膨胀属性 / 不膨胀：0 / 免费膨胀：1 / 付费膨胀：2 |

### Sheet: AllTask

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 任务id |
| comment | string | - | 相当于备注名，自己看的 |
| type | string | - | 需要堆叠的任务组类型 |
| title | string | - | 任务标题i18n key |
| difficulty | int | - | 任务难度 / group_delta_time==5时 / 为任务解锁所需数量 |
| display_name | string | - | i18n key / 占位符规则： / {0}=task_value / {1….}=task_filter顺序从左至右 / *注意：含有多个id的marco会占用多个占位符 |
| is_unlock | int | - | 1-该任务需要解锁后才开始计数 |
| description | string | - | 如果不为空，给任务展示个详情按钮，在浮窗里显示本说明 |
| task_action | string | - | 具体的任务条件类型 |
| task_filters | object | array | 过滤事件 |
| task_value | object | - | 如何累加值 |
| rewards | yield | array | 完成本任务可领的奖励 |
| claim_times | int | - | 本条子任务可重复领取的总次数 |
| go_now | object | - | 跳转配置，如果不为空，任务没完成时显示“前往”按钮，点击跳转到配置的界面 |
| is_task_hint | int | - | 1-显示图鉴详情 |
| is_acc | int | - | 该任务是否与成就关联 / 1=是 |

### Sheet: BigReward

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 大奖显示id |
| comment | string | - | 备注 |
| bp | string | - | 大奖对应的蓝图资源 |
| show_umg | string | - | 大奖umg |
| show_umg_class | string | - | 大奖umg逻辑 |
| audio | string | - | 大奖入场音效 |
| go_now | object | - | 大奖的跳转 |
| preview_icon | string | - | 大奖的预览按钮 |
| rewards_icon | string | - | 切换图标 |
| rewards_name | string | - | 大奖标题 |
| rewards_desc | string | - | 大奖描述 |
| rewards_iconshow | string | - | 大奖图标 |

### Sheet: FinalReward

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 最终大奖id |
| comment | string | - | 备注 |
| condition | object | array | 过滤条件 |
| rewards | yield | array | 奖励 / final_reward_add=0时填总奖励 / final_reward_add=1时填每一档奖励增量 |
| package_id | string | - | 领取大奖后弹出的礼包id |

### Sheet: Draft.001

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 任务id |
| comment | string | - | 相当于备注名，自己看的 |
| type | string | - | 需要堆叠的任务组类型 |
| display_name | string | - | i18n key |
| is_unlock | int | - | 1-该任务需要解锁后才开始计数 |
| description | string | - | 如果不为空，给任务展示个详情按钮，在浮窗里显示本说明 |
| task_action | string | - | 具体的任务条件类型 |
| task_filters | object | array | 过滤事件 |
| task_value | object | - | 如何累加值 |
| rewards | yield | array | 完成本任务可领的奖励 |
| claim_times | int | - | 本条子任务可重复领取的总次数 |
| go_now | object | - | 跳转配置，如果不为空，任务没完成时显示“前往”按钮，点击跳转到配置的界面 |
| 任务名前缀 | 数值 | - | 奖励 |
| mission_dhxy_ | by_times: | - | [{master_point:ms_mission_dhxy: |
| _ |  | - | }] |

### Sheet: Draft.002

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 任务id |
| comment | string | - | 相当于备注名，自己看的 |
| type | string | - | 需要堆叠的任务组类型 |
| display_name | string | - | i18n key |
| is_unlock | int | - | 1-该任务需要解锁后才开始计数 |
| description | string | - | 如果不为空，给任务展示个详情按钮，在浮窗里显示本说明 |
| task_action | string | - | 具体的任务条件类型 |
| task_filters | object | array | 过滤事件 |
| task_value | object | - | 如何累加值 |
| rewards | yield | array | 完成本任务可领的奖励 |
| claim_times | int | - | 本条子任务可重复领取的总次数 |
| go_now | object | - | 跳转配置，如果不为空，任务没完成时显示“前往”按钮，点击跳转到配置的界面 |
| is_task_hint | int | - | 1-显示图鉴详情 |

### Sheet: Draft.003筛选分析-完成赏金令任务xxx次 (计数)

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| task_action | cost_conch | - | master_point_decrease |
| task_filters |  | - | {point_type:mp_draw_ld} |
| task_value | by_times: | - | by_times: |
| mission_spring2025l_ | conch | - | lifting |
| 需要堆叠的任务组类型 | mission_spring2025l_conch | - | mission_spring2025l_lifting |
| i18n key | mission_spring2025l_mission_spring2025l_conch | - | mission_spring2025l_mission_spring2025l_lifting |
| is_hint |  | - | - |
| gonow | go_now:DialogShopController | - | go_now:Master,params:[spring2025_page,act_ld_ql_250124] |

================================================================================
                               文档结束
================================================================================
