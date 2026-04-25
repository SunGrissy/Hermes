<!--
参考代码文件:
- lua/framework/components/game_module/module_impl/master_module.lua
- lua/game_mode/master_data.lua
- lua/framework/components/game_module/module_impl/master_play_module/master_play_module_base.lua
- lua/framework/components/game_module/module_impl/master_play_module/master_point_module.lua
最后参考时间: 2026-02-24
-->
================================================================================
                        Master 活动系统使用规则详细说明
================================================================================
                           版本: 2026-02-24
================================================================================

目录
----
1. 系统概述
2. 核心概念与数据结构
3. 活动类型(MasterType)
4. 玩法类型(MasterPlayType)
5. 解锁条件(MasterUnLockRequirementType)
6. 核心模块说明
7. UI组件层次结构
8. 事件系统
9. 红点系统
10. 积分系统(MasterPoint)
11. 强弹系统(PopUp)
12. 活动生命周期
13. 开发新活动的步骤
14. 开发新玩法的步骤
15. 常见问题与注意事项
16. 代码规范

================================================================================
1. 系统概述
================================================================================

Master系统是一个统一的活动管理框架，用于管理游戏中的各类限时活动。该系统具有
以下特点：

- 支持独立活动(Act)和活动集群(ActGroup)两种活动类型
- 每个活动可以包含多种玩法(MasterPlay)
- 支持活动解锁条件配置
- 统一的强弹、红点、积分管理
- 支持活动依赖关系和排他解锁

主要涉及的核心文件:
- lua/framework/components/game_module/module_impl/master_module.lua
- lua/game_mode/master_data.lua
- lua/framework/components/game_module/module_impl/master_play_module/master_play_module_base.lua
- lua/framework/components/game_module/module_impl/master_play_module/master_point_module.lua

================================================================================
2. 核心概念与数据结构
================================================================================

2.1 活动(Master)
----------------
一个活动代表一个限时事件，包含：
- id: 活动唯一标识
- conf_info: 活动配置数据（从服务器获取）
- type: 活动类型（Act 或 ActGroup）
- start_time/end_time: 活动时间范围
- master_plays: 活动包含的玩法列表
- unlock_requirements: 解锁条件
- popup_rule: 强弹规则

2.2 玩法(MasterPlay)
--------------------
玩法是活动的功能单元，一个活动可以包含多个玩法。每个玩法有：
- id: 玩法实例ID (格式: "{活动id}:{玩法配置id}")
- class_type: 玩法类型（如MasterDraw, MasterExchange等）
- class_id: 玩法配置ID
- info: 玩法数据（从服务器获取）
- conf: 玩法配置

2.3 ID命名规则
--------------
- 活动ID: 如 "act_mission_7days", "act_hlw_draw"
- 玩法实例ID: 格式为 "{活动id}:{玩法配置id}"
  例如: "act_hlw_draw:mp_draw_hlw"
- 玩法配置ID(class_id): 配表中的原始ID

重要：玩法实例ID会在MasterData构造时自动拼接活动ID前缀，确保全局唯一。

================================================================================
3. 活动类型(MasterType)
================================================================================

定义于: lua/game_mode/master_data.lua

local MasterType = {
    Act = "act",           -- 独立活动
    ActGroup = "act_group" -- 活动集群
}

3.1 独立活动(Act)
-----------------
- 单独的活动实体
- 可以包含多个玩法
- 可以设置独立入口(independent_entry)
- 可以属于某个活动集群

3.2 活动集群(ActGroup)
----------------------
- 多个子活动的容器
- 提供统一的入口和界面
- 子活动间可以有依赖关系
- 支持虚拟集群(is_virtual)，虚拟集群不显示集群入口，子活动各自独立显示

关键方法：
- MasterData:SubMasterDict()       -- 获取子活动字典
- MasterData:SubMasterData(tag)    -- 根据theme_tag获取子活动
- MasterData:ParentMasterData()    -- 获取父活动(集群)

================================================================================
4. 玩法类型(MasterPlayType)
================================================================================

定义于: lua/framework/components/game_module/module_impl/master_play_module/master_play_module_base.lua

目前支持的玩法类型：

MasterPlayType = {
    None = "",
    Draw = "MasterDraw",                    -- 抽奖
    Exchange = "MasterExchange",            -- 兑换
    Task = "MasterTask",                    -- 任务
    Search = "MasterSearch",                -- 搜寻
    PiggyBank = "MasterPiggy",              -- 存钱罐
    Shops = "MasterShops",                  -- 商店
    FishDrop = "MasterFishDrop",            -- 鱼掉落
    Mission = "MasterMission",              -- 任务
    Transform = "MasterTransform",          -- 转化
    Paint = "MasterPaint",                  -- 绘画
    MineTreasure = "MasterMineTreasure",    -- 挖宝
    SeasonBp = "MasterSBPv1",               -- 赛季通行证
    FreeReward = "MasterFreeReward",        -- 免费奖励
    Bank = "MasterBank",                    -- 银行
    MasterSaga = "MasterSaga",              -- Saga
    Coin = "MasterCoin",                    -- 金币活动
    CoinV2 = "MasterCoinNewBie",            -- 新手金币
    Milestone = "MasterMilestone",          -- 里程碑
    Catch = "MasterCatch",                  -- 捕获
    BaseBP = "MasterBaseBP",                -- 基础通行证
    CollectionDraw = "MasterCollectionDraw",-- 收集抽奖
    Forge = "MasterForge",                  -- 锻造
    SignIn = "MasterSignIn",                -- 签到
    FestivalSignIn = "MasterFestivalSignIn",-- 节日签到
    Chest = "MasterChest",                  -- 宝箱
    AlbumCard = "MasterAlbumCard",          -- 集卡
    Quiz = "MasterQuiz",                    -- 答题
    SpinDraw = "MasterSpinDraw",            -- 转盘抽奖
    ChargeReward = "MasterChargeReward",    -- 充值奖励
    LiftingDraw = "MasterLiftingDraw",      -- 升降抽奖
    BossChallenge = "MasterBossChallenge",  -- Boss挑战
    SeasonRank = "MasterSeasonRank",        -- 赛季排行
    AdvPopup = "MasterAdvPopup",            -- 广告弹窗
    WeeklyChest = "MasterWeeklyChest",      -- 周宝箱
    CardLevel = "MasterCardLevel",          -- 卡牌等级
    RankPoint = "MasterRankPoint",          -- 排行积分
    CyclePack = "MasterCyclePack",          -- 周期礼包
    BossRush = "MasterBossRush",            -- Boss冲刺
    CycleTask = "MasterCycleTask",          -- 周期任务
    PoolExchange = "MasterPoolExchange",    -- 池兑换
    CombineDraw = "MasterCombineDraw",      -- 组合抽奖
    ChestUpgrade = "MasterChestUpgrade",    -- 宝箱升级
    Unlock = "MasterUnlock",                -- 解锁玩法
    UnlockPack = "MasterUnlockPack",        -- 解锁礼包
    ThreeImageDraw = "MasterThreeImageDraw",  -- 三图抽奖
}

玩法模块命名规则：
- 模块类名: MasterPlay{玩法类型去掉Master前缀}Module
- 例如: MasterPlayDrawModule, MasterPlayExchangeModule
- 通过 MasterData.FormatMasterPlayModuleName(class_type) 获取模块名

================================================================================
5. 解锁条件(MasterUnLockRequirementType)
================================================================================

定义于: lua/game_mode/master_data.lua

MasterUnLockRequirementType = {
    MaxBet = "max_bet",               -- 炮倍要求
    PlayerLevel = "player_level",      -- 玩家等级
    VipLevel = "vip_level",            -- VIP等级
    VipExp = "vip_exp",                -- VIP经验(充值金额)
    WeaponSoulLevel = "weapon_soul",   -- 炮魂等级
    UnlockPoint = "master_inherit_point" -- 可继承积分
}

解锁条件配置格式（在活动配置中）:
unlock_requirements = {
    max_bet = {100},      -- 炮倍达到100
    player_level = {10},  -- 等级达到10级
    vip_level = {3},      -- VIP达到3级
}

依赖关系类型(MasterDependOnType):
- Complete = 0     -- 完成依赖：依赖活动完成后解锁
- End = 1          -- 结束依赖：依赖活动结束后解锁
- CompleteOrEnd = 2 -- 完成或结束后解锁

排他解锁状态(ExclusiveUnlockState):
- Locked = 0           -- 未解锁
- ClientUnlocked = 1   -- 客户端已判定解锁
- ServerUnlocked = 2   -- 服务器已判定解锁
- CompleteOrEnd = 99   -- 已完成/结束

================================================================================
6. 核心模块说明
================================================================================

6.1 MasterModule
----------------
文件: lua/framework/components/game_module/module_impl/master_module.lua

职责：
- 管理所有活动数据(master_data_dict)
- 处理活动的生命周期（开始、解锁、完成、结束）
- 请求和处理活动详细信息
- 管理玩法ID到活动ID的映射(master_play_id_2_master_id)
- 处理跨天逻辑
- 管理活动私有存档数据

单例访问: MasterModule.Instance

关键接口：
-- 获取活动数据
MasterModule:GetMasterData(master_id)                    -- 根据ID获取活动数据
MasterModule:GetMasterDataByMasterPlayID(master_play_id) -- 根据玩法ID获取活动数据
MasterModule:GetMasterIDByMasterPlayID(master_play_id)   -- 根据玩法ID获取活动ID

-- 查找活动
MasterModule:FindMasterDataByGoNowTag(gonow_tag, master_play_type)
MasterModule:FindMasterContainPlayType(master_play_type, only_visiable, include_independent)  -- only_visiable 为代码中历史拼写
MasterModule:FilterVisibleMasters(include_independent)

-- 请求活动信息
MasterModule:RequestMasterActInfo(master_data, force_request)
MasterModule:RequestMasterActInfoByID(master_id, force_request)

-- 私有数据
MasterModule:GetMasterPrivateData(master_id, data_name, default_data_val)
MasterModule:SetMasterPrivateData(master_id, data_name, data_val)

-- 弹窗相关
MasterModule:StandardRewardMessageBoxName(master_play_id)
MasterModule:StandardRuleMessageBoxName(master_play_id)

-- 其他
MasterModule:GetOuterMostMasterIDByMasterPlayID(master_play_id) -- 获取最外层活动ID
MasterModule:IsInited()                                          -- 是否已完成初始化
MasterModule:GetVisibleMasterDataByEntryID(target_entry_id)     -- 根据entry_id获取可见活动
MasterModule:CanDailyEndReminderPopup(master_id)                -- 是否需要结束提醒强弹
MasterModule:AddDailyEndReminderTimes(master_id)                -- 增加当日结束提醒次数

6.2 MasterData
--------------
文件: lua/game_mode/master_data.lua

职责：
- 封装单个活动的数据和状态
- 提供活动状态判断方法
- 管理活动内的玩法
- 处理解锁和完成状态

关键接口：
-- 基本信息
MasterData:ID()                    -- 获取活动ID
MasterData:Conf()                  -- 获取活动配置
MasterData:Type()                  -- 获取活动类型

-- 状态判断
MasterData:IsOpen()                -- 是否在活动时间内
MasterData:IsEnd()                 -- 是否已结束
MasterData:IsUnlocked()            -- 是否已解锁
MasterData:IsActive()              -- 是否活跃(开放且解锁)
MasterData:IsVisible(independence_affected)  -- 是否可见
MasterData:IsComplete()            -- 是否已完成
MasterData:IsHaveActInfo()         -- 是否已获取详细信息

-- 玩法相关
MasterData:GetMasterPlayID(master_play_type)      -- 获取指定类型玩法ID
MasterData:GetMasterPlayInfo(master_play_type)    -- 获取指定类型玩法信息
MasterData:GetMasterPlayInfoByID(master_play_id)  -- 根据ID获取玩法信息
MasterData:GetMasterPlayType(master_play_id)      -- 获取玩法类型
MasterData:GetAllMasterPlayTypes()                -- 获取所有玩法类型

-- 集群相关
MasterData:ParentMasterData()      -- 获取父活动
MasterData:SubMasterDict()         -- 获取子活动字典
MasterData:SubMasterData(theme_tag) -- 根据tag获取子活动

-- 红点
MasterData:GetRedDotKey(scoped_types, ignore_state)

-- UI相关
MasterData:FormatMainDialogName()  -- 获取主Dialog名称
MasterData:StandardRewardMessageBoxName()
MasterData:StandardRuleMessageBoxName()

6.3 MasterPlayModuleBase
------------------------
文件: lua/framework/components/game_module/module_impl/master_play_module/master_play_module_base.lua

职责：
- 所有玩法模块的基类
- 管理玩法数据(master_play_dict)
- 提供红点、完成检查等通用接口

关键接口（子类需要重写）：
MasterPlayModuleBase:InitRedDot(master_play_id)     -- 初始化红点
MasterPlayModuleBase:GetRedDotKey(master_play_id)   -- 获取红点Key
MasterPlayModuleBase:CalcRedDotNumber(master_play_id) -- 计算红点数量
MasterPlayModuleBase:CheckComplete(master_play_id)  -- 检查是否完成
MasterPlayModuleBase:IsDataInvalidOnNewDay(id)      -- 跨天数据是否失效
MasterPlayModuleBase:IsRegisterPointRequired()      -- 是否需要注册积分

数据刷新接口（框架调用）：
MasterPlayModuleBase:RefreshMasterPlayInfo(master_play_id, info, conf)
MasterPlayModuleBase:OnMasterPlayInfoRefresh(master_play_id, play_info) -- 可重写

获取玩法数据：
MasterPlayModuleBase:GetMasterPlayInfo(master_play_id)
MasterPlayModuleBase:ContainMasterPlayConf(master_play_id)

消息创建：
MasterPlayModuleBase:CreateMsg(msg_type, master_play_id)
-- 自动填充 act_id 和 master_play_id

================================================================================
7. UI组件层次结构
================================================================================

7.1 DialogMasterControllerBase
------------------------------
文件: lua/product/components/ui_dialog/dialog_master/base/dialog_master_controller_base.lua

职责：
- 活动主界面的加载容器
- 处理活动信息请求和等待
- 加载活动主Widget
- 处理活动结束时的页面关闭

默认资源: "UMG_MasterMainUMGLoader"

OnShow参数定义：
uiParams[1]: master_id (活动ID)
uiParams[2]: master_play_id (可选，默认显示的玩法)
uiParams[3]: bi_args (BI日志参数)
uiParams[4]: close_info (页面关闭后的跳转信息)

打开活动页面的方式：
ShowDialog(
    master_data:FormatMainDialogName(),  -- Dialog名称
    master_data:ID(),                     -- 活动ID
    master_play_id,                       -- 可选：指定玩法
    {reason = "xxx", param = "xxx"}       -- BI参数
)

主Widget参数定义（传递给main_umg_class）：
参数1: dialog (DialogMasterControllerBase实例)
参数2: master_data (活动数据)
参数3: default_show_master_play_type (默认显示的玩法类型)
参数4: bi_args (BI参数)

7.2 MasterPlayHudBase
---------------------
文件: lua/product/components/ui_item/master/common/master_play_switcher/master_play_hud_base.lua

职责：
- 支持Tab切换的活动主界面基类
- 管理多个玩法页面的切换

使用要求：
1. UMG必须有 MasterPlayContent 和 MasterPlayTabContent 容器
2. UMG必须提供 TabWidgetResName 变量
3. UMG必须提供 GetMasterPlayWidgetResName 方法

子类需要重写的方法：
GetMasterPlayWidgetClassName(master_play_type) -- 玩法页面脚本类名
GetMasterPlayTabClassName(master_play_type)    -- Tab脚本类名
GetAllMasterPlayTypes()                         -- 可选，返回要显示的玩法列表

切换Tab：
MasterPlayHudBase:SwitchTab(master_play_type)

7.2.1 MasterPlayTabBase
-----------------------
文件: lua/product/components/ui_item/master/common/master_play_switcher/master_play_tab_base.lua

使用要求：
- UMG必须有 SelectBtn 控件
- UMG必须提供 SetIsSelected 和 SetTabInfo 方法
- 普通红点：UMG需要 RedDot 控件(NewCommonRedDot类型)
- 否则重写 MasterPlayTabBase:InitRedDot

7.3 MasterEntryBase
-------------------
文件: lua/product/components/ui_item/master/master_entry_base.lua

职责：
- 活动入口的基类
- 处理点击进入活动
- 显示倒计时
- 管理红点

ReceivedOnCreated参数：
load_from: 加载来源信息
master_data: 活动数据

子类可重写的方法：
RegisterEvents()      -- 注册事件
BindRedDot()          -- 绑定红点控件
SetRedDotKey()        -- 设置红点Key
InitSpecial()         -- 自定义初始化
GetEnterBtnClickInfo() -- 点击配置

7.4 MasterPopUpAssisterBase
---------------------------
文件: lua/game_mode/master_popup_assister/base_class/master_popup_assister_base.lua

职责：
- 活动强弹的辅助类基类
- 处理活动的自动弹出逻辑

子类需要重写：
ExecPopUp(popup_scence, popup_conf)  -- 执行强弹逻辑
OnUIOpened(ui_queue_item)            -- UI打开回调
OnUIClosed(ui_queue_item)            -- UI关闭回调

================================================================================
8. 事件系统
================================================================================

Master系统使用的主要事件：

-- 活动状态事件
GameEventType.MasterSystemInited     -- Master系统初始化完成
GameEventType.MasterStart            -- 活动开始
GameEventType.MasterUnLocked         -- 活动解锁
GameEventType.MasterComplete         -- 活动完成
GameEventType.MasterOver             -- 活动结束 (master_id, is_because_complete)
GameEventType.MasterActInfoGot       -- 获取到活动详细信息
GameEventType.MasterActConfGot       -- 获取活动配置

-- 玩法事件
GameEventType.MasterPlayInfoRefresh  -- 玩法信息刷新
GameEventType.MasterPlayComplete     -- 玩法完成

-- 积分事件
GameEventType.MasterPointChanged     -- 活动积分变化

-- UI事件
GameEventType.MasterMainUIOpen       -- 活动主UI打开

-- 数据事件
GameEventType.MasterActReceivedStart -- 开始接收活动数据
GameEventType.MasterActReceivedEnd   -- 活动数据接收完成

事件监听示例：
self:RegisterEvent(GameEventType.MasterActInfoGot, self.OnMasterActInfoGot)

function Class:OnMasterActInfoGot(master_id)
    if(self.master_data:ID() == master_id) then
        -- 处理活动信息获取
    end
end

================================================================================
9. 红点系统
================================================================================

9.1 红点Key命名规范
-------------------
玩法模块定义自己的红点Key格式，例如：
- Master_Draw_RedDot_{master_play_id}
- Master_Draw_RedDot_{master_play_id}_Free
- Master_Exchange_RedDot_{master_play_id}

9.2 红点初始化
--------------
在MasterPlayModuleBase子类中重写：

function Module:InitRedDot(master_play_id)
    local redDotKey = self:GetRedDotKey(master_play_id)
    RedDotManager.Instance.red_dot_info[redDotKey] = 
        RedDotManager.Instance:GetCommonTypeDict(redDotKey)
    self:CalcRedDotNumber(master_play_id)
end

function Module:GetRedDotKey(master_play_id)
    return "Master_XXX_RedDot_" .. master_play_id
end

function Module:CalcRedDotNumber(master_play_id)
    local redDotKey = self:GetRedDotKey(master_play_id)
    local value = ... -- 计算红点值
    RedDotManager.Instance:RefreshRedDotInfoByEnum(redDotKey, value)
end

9.3 活动红点合并
----------------
MasterData:GetRedDotKey() 会合并活动下所有玩法的红点Key
格式: "|{玩法1红点Key}|{玩法2红点Key}|..."

9.4 简化红点
------------
框架会为每个活动创建简化版红点Key，用于活动大厅等入口：
RedDotManager.Instance:CreateSimplifiedMasterRedDot(master_id, red_dot_key)

================================================================================
10. 积分系统(MasterPoint)
================================================================================

文件: lua/framework/components/game_module/module_impl/master_play_module/master_point_module.lua

10.1 积分注册
-------------
活动开始时自动注册积分：
MasterPointModule:RegisterMasterPoint(master_id, ignore_fail)

10.2 积分同步
-------------
-- 根据积分ID同步
MasterPointModule:SyncMasterPointCount(master_points)

-- 根据积分类型同步
MasterPointModule:SyncMasterPointCountByType(master_points)

10.3 获取积分
-------------
-- 根据积分ID获取
MasterPointModule:GetMasterPointCount(point_id)

-- 根据积分类型获取
MasterPointModule:GetMasterPointCountByType(point_type)

-- 增加积分
MasterPointModule:AddMasterPointCount(point_id, count)       -- 增加积分(按point_id)
MasterPointModule:AddMasterPointCountByType(point_type, count) -- 增加积分(按point_type)

10.4 积分变化事件
-----------------
监听 GameEventType.MasterPointChanged(point_id, count) 获取积分变化通知

10.5 可继承积分
---------------
配置 is_inherit = 1 的积分会在多个活动间保留
这类积分可以用作解锁条件(MasterUnLockRequirementType.UnlockPoint)

================================================================================
11. 强弹系统(PopUp)
================================================================================

11.1 强弹规则配置
-----------------
活动配置中指定 popup_rule，系统会自动创建对应的 PopUpAssister：
- 类名格式: {popup_rule}PopUpAssister
- 如: "MasterCoin" -> MasterCoinPopUpAssister

11.2 强弹场景(UIPopUpScence)
----------------------------
- Login: 登录后
- NewDayBeginInLobby: 跨天(大厅)
- NewDayBeginInRoom: 跨天(渔场)
- 等等...

11.3 实现强弹
-------------
继承 MasterPopUpAssisterBase，重写 ExecPopUp 方法：

function XxxPopUpAssister:ExecPopUp(popup_scence, popup_conf)
    if(popup_scence == UIPopUpScence.Login) then
        -- 检查条件
        if(self:ShouldPopUp()) then
            PopupManager.Alert("UIXxxMessageBox", PopupPriority.High, ...)
        end
    end
end

11.4 强弹配置
-------------
通过 UIPopUpConfigureModule 获取强弹配置：
popup_conf = UIPopUpConfigureModule.Instance:GetPopUpConfig(scence, master_data:GetPopUpConfID(), true)

================================================================================
12. 活动生命周期
================================================================================

12.1 活动数据接收
-----------------
1. 服务器推送 MessageType.GetMasterInfo
2. MasterModule:OnGetMasterInfo 处理数据
3. 创建 MasterData 实例
4. 初始化解锁状态、完成状态
5. 注册积分
6. 派发 GameEventType.MasterActReceivedEnd

12.2 活动开始
-------------
1. 达到 start_time
2. 调用 MasterModule:DealMasterPreStart
3. 检查解锁条件
4. 如果解锁，调用 DealMasterUnLocked
5. 注册积分
6. 设置结束定时器
7. 派发 GameEventType.MasterStart

12.3 活动解锁
-------------
1. 满足解锁条件时调用 CheckUnlock
2. 非 end_together 活动需要向服务器确认
3. 解锁成功后派发 GameEventType.MasterUnLocked
4. 如果配置了 request_data = 1，自动请求活动信息

12.4 获取活动详情
-----------------
1. 调用 MasterModule:RequestMasterActInfo
2. 服务器返回 MessageType.GetMasterActInfo
3. MasterModule:OnGetMasterActInfo 处理
4. 设置 MasterData 的 act_info
5. 刷新各玩法模块数据
6. 派发 GameEventType.MasterActInfoGot
7. 执行强弹逻辑

12.5 活动完成
-------------
1. 玩法完成时派发 GameEventType.MasterPlayComplete
2. MasterModule:OnMasterPlayComplete 检查活动完成
3. MasterData:CheckComplete 判断所有 complete_condition 是否满足
4. 完成后派发 GameEventType.MasterComplete
5. 如果 hidden_if_complete = 1，活动直接结束

12.6 活动结束
-------------
1. 达到 end_time 或完成后结束
2. 调用 MasterModule:DealMasterEnd
3. MasterData:Destroy 清理资源
4. 派发 GameEventType.MasterOver
5. 检查依赖此活动的其他活动解锁

================================================================================
13. 开发新活动的步骤
================================================================================

13.1 配置活动
-------------
在服务器配置活动数据，包括：
- id: 活动唯一ID
- start_time/end_time: 活动时间
- theme_tag: 主题标签
- main_umg: 主界面UMG名称
- main_umg_class: 主界面脚本类名
- popup_rule: 强弹规则
- master_plays: 玩法列表配置
- unlock_requirements: 解锁条件
- entry_icon: 入口图标
- entry_order: 入口排序

13.2 创建主界面
---------------
1. 创建UMG资源
2. 创建Lua脚本类，继承 UIWidget 或 MasterPlayHudBase

class("DialogActXxxController", UIWidget)

function DialogActXxxController:ReceivedOnCreated(dialog, master_data, default_show_play_type, bi_args)
    self.parent = dialog
    self.master_data = master_data
    self.bi_args = bi_args
    
    -- 获取玩法数据
    self.play_info = master_data:GetMasterPlayInfo(MasterPlayType.Xxx)
    self.play_id = master_data:GetMasterPlayID(MasterPlayType.Xxx)
    
    self:Init()
end

13.3 创建入口(可选)
-------------------
如果需要自定义入口，继承 MasterEntryBase：

_class("MasterEntryXxx", MasterEntryBase)

function MasterEntryXxx:InitSpecial()
    -- 自定义初始化
end

function MasterEntryXxx:RegisterEvents()
    self:RegisterEvent(GameEventType.MasterActInfoGot, self.OnMasterActInfoGot)
end

13.4 创建强弹助手(可选)
-----------------------
如果需要自定义强弹，创建 PopUpAssister：

_class("XxxPopUpAssister", MasterPopUpAssisterBase)

function XxxPopUpAssister:ExecPopUp(popup_scence, popup_conf)
    -- 实现强弹逻辑
end

================================================================================
14. 开发新玩法的步骤
================================================================================

14.1 定义玩法类型
-----------------
在 MasterPlayType 枚举中添加新类型：
MasterPlayType.NewPlay = "MasterNewPlay"

14.2 创建玩法模块
-----------------
文件: lua/framework/components/game_module/module_impl/master_play_module/master_play_new_play_module.lua

_class("MasterPlayNewPlayModule", MasterPlayModuleBase)
MasterPlayNewPlayModule = MasterPlayNewPlayModule

function MasterPlayNewPlayModule:Constructor()
    MasterPlayNewPlayModule.Instance = self
end

function MasterPlayNewPlayModule:Init()
    self.super.Init(self)
    -- 注册协议处理
    self.caller:RegisterPushHandler(
        MessageType.NewPlayAction[1].."_"..MessageType.NewPlayAction[2],
        self.OnNewPlayAction, self)
end

-- 重写红点相关方法
function MasterPlayNewPlayModule:InitRedDot(master_play_id)
    local redDotKey = self:GetRedDotKey(master_play_id)
    RedDotManager.Instance.red_dot_info[redDotKey] = 
        RedDotManager.Instance:GetCommonTypeDict(redDotKey)
    self:CalcRedDotNumber(master_play_id)
end

function MasterPlayNewPlayModule:GetRedDotKey(master_play_id)
    return "Master_NewPlay_RedDot_" .. master_play_id
end

function MasterPlayNewPlayModule:CalcRedDotNumber(master_play_id)
    local redDotKey = self:GetRedDotKey(master_play_id)
    local playInfo = self.master_play_dict[master_play_id]
    local value = 0
    if playInfo then
        -- 计算红点值
        value = ...
    end
    RedDotManager.Instance:RefreshRedDotInfoByEnum(redDotKey, value)
end

-- 重写完成检查
function MasterPlayNewPlayModule:CheckComplete(master_play_id)
    local playInfo = self.master_play_dict[master_play_id]
    if playInfo then
        return playInfo.info.is_complete == 1
    end
    return false
end

-- 可选：重写数据刷新回调
function MasterPlayNewPlayModule:OnMasterPlayInfoRefresh(master_play_id, master_play_info)
    -- 额外的数据处理逻辑
end

-- 业务方法
function MasterPlayNewPlayModule:DoSomeAction(master_play_id, params)
    local msg = self:CreateMsg(MessageType.NewPlayAction, master_play_id)
    msg.params.xxx = params
    self:Push(msg)
end

function MasterPlayNewPlayModule:OnNewPlayAction(msg)
    if msg.status == 0 then
        local playId = msg.master_play_id
        local playInfo = self.master_play_dict[playId]
        if playInfo then
            -- 更新数据
            playInfo.info.xxx = msg.res.xxx
            -- 刷新红点
            self:CalcRedDotNumber(playId)
            -- 派发事件
            DispatchEvent(GameEventType.NewPlayActionComplete, playId)
            -- 检查完成
            if self:CheckComplete(playId) then
                DispatchEvent(GameEventType.MasterPlayComplete, playId)
            end
        end
    end
end

14.3 注册模块
-------------
在模块注册文件中添加：
GameModule.ModuleType.MasterPlayNewPlayModule = MasterPlayNewPlayModule

14.4 创建玩法UI
---------------
_class("MasterNewPlayMain", UIWidget)

function MasterNewPlayMain:Constructor(UMG)
    self:AddCallback("ActionBtn", "OnClicked")
    self:RegisterEvent(GameEventType.NewPlayActionComplete, self.OnActionComplete)
end

function MasterNewPlayMain:ReceivedOnCreated(parent, master_play_id, bi_args)
    self.parent = parent
    self.master_play_id = master_play_id
    self.master_data = MasterModule.Instance:GetMasterDataByMasterPlayID(master_play_id)
    self.play_info = MasterPlayNewPlayModule.Instance:GetMasterPlayInfo(master_play_id)
    
    self:Init()
end

================================================================================
15. 常见问题与注意事项
================================================================================

15.1 玩法ID的使用
-----------------
- 服务器返回的是 class_id（配表ID）
- 客户端内部使用的是 master_play_id（格式: "{活动id}:{class_id}"）
- MasterData 在构造时会自动转换
- 发送协议时使用 CreateMsg 会自动处理转换

15.2 数据请求时机
-----------------
- request_data = 1 的活动会在登录时自动请求
- 其他活动在打开页面时请求（通过 DialogMasterControllerBase）
- 可以通过 MasterData:IsHaveActInfo() 判断是否已有数据

15.3 跨天处理
-------------
- 部分玩法需要跨天刷新数据
- 重写 IsDataInvalidOnNewDay 返回 true
- 框架会在跨天时自动请求 MessageType.GetMasterActInfoOnNewDayBegin

15.4 独立计时活动
-----------------
- end_together = 0 的活动有独立计时
- 解锁时服务器返回真正的 start_time
- 结束时间 = start_time + duration

15.5 存档数据
-------------
- 使用 MasterModule:GetMasterPrivateData/SetMasterPrivateData
- 存档Key格式: MasterPrivateData_{master_id}
- 存档会在活动结束后被清理

15.6 活动完成判定
-----------------
- complete_condition 配置需要完成的玩法列表
- 只有列表中的玩法全部完成，活动才算完成
- hidden_if_complete = 1 时完成后活动会结束

15.7 Dispose 方法
-----------------
重要：MasterPlayModuleBase 子类如果重写 Dispose，必须调用父类方法或清理 master_play_dict！
否则会导致数据残留，框架在启动时会检查并报错。

15.8 消息发送
-------------
使用 CreateMsg 创建消息：
local msg = self:CreateMsg(MessageType.Xxx, master_play_id)
-- 框架会自动填充 act_id 和 master_play_id（转换为class_id）
msg.params.xxx = xxx
self:Push(msg)

================================================================================
16. 代码规范
================================================================================

16.1 命名规范
-------------
- 活动ID: 小写下划线，如 act_xxx, act_group_xxx
- 玩法类型: 大驼峰，如 MasterDraw, MasterExchange
- 模块类: MasterPlay{类型}Module
- 主界面类: Master{功能名}Main 或 Dialog{类型}{主题}Controller
- 入口类: MasterEntry{功能名} 或 Master{功能名}Entry
- PopUpAssister: Master{规则}PopUpAssister

16.2 文件组织
-------------
lua/framework/components/game_module/module_impl/master_play_module/
    - master_play_xxx_module.lua    -- 玩法模块

lua/product/components/ui_item/master/{功能名}/
    - master_{功能名}_main.lua      -- 主界面
    - master_{功能名}_entry.lua     -- 入口
    - master_{功能名}_xxx.lua       -- 其他组件

lua/game_mode/master_popup_assister/
    - master_{规则}_popup_assister.lua -- 强弹助手

16.3 事件派发规范
-----------------
- 玩法完成时派发 GameEventType.MasterPlayComplete
- 数据变化时派发玩法特定事件，如 GameEventType.MasterXxxDataChanged
- 不要直接派发 MasterComplete/MasterOver，由框架处理

16.4 红点规范
-------------
- 红点Key必须全局唯一
- 包含 master_play_id 以区分不同实例
- 提供分类红点（奖励/新增/可兑换等）

16.5 错误处理
-------------
- 使用 Log.error 记录错误
- 关键路径使用 ProtectionCall 保护
- 提供有意义的错误信息，包含活动/玩法ID

16.6 规则弹窗
-------------
Master 活动的规则弹窗统一写法：

function XxxMain:RuleBtnOnClicked()
    if self.master_data then
        local conf_info = self.master_data:Conf()
        PopupManager.Alert(
            self.master_data:StandardRuleMessageBoxName(),
            PopupPriority.Normal,
            UIHelper.FormatI18NTextWithLatentArguments(conf_info.rule, {})
        )
    end
end

说明：
- master_data:Conf() 获取活动配置
- master_data:StandardRuleMessageBoxName() 获取规则弹窗资源名
- conf_info.rule 是配表中的规则文案（支持 i18n）
- UIHelper.FormatI18NTextWithLatentArguments 处理国际化文本参数替换

================================================================================
17. 配表结构补充（MasterAct / MasterActGroup）
================================================================================

17.1 本节说明
-------------
- 本章仅补充 MasterAct / MasterActGroup 两张表的关键字段含义。
- 如需查看任何 Master 配表的完整字段结构，请使用 table-schema-preview skill。
- Master 配表目录：../../Tables/server_data/Master/

17.2 MasterAct（MasterAct.xls）
------------------------------
- Main 表核心字段
  - id：活动唯一ID；comment：备注。
  - start_time/end_time：计划时间；00:00 视为次日 00:00；end_together=0 时真正结束=解锁时间+duration。
  - gonow_tag：[string]；MasterGoNow 跳转标签，空则无跳转；同标签可共享入口跳转。
  - preview_cd：预告冷却；countdown：临期倒计时展示时长（-1 不展示）。
  - end_together：1 同步开始/结束；0 独立计时；duration：独立计时时长。
  - end_reminder_duration/end_reminder_times：临期强弹提醒窗口与次数。
  - unlock_requirements：解锁条件（与关系），键使用 MasterUnLockRequirementType。
  - master_plays：[MasterPlay]；玩法列表。complete_condition：[string]，引用 master_plays 中的玩法ID，全部完成则活动完成；为空表示无“完成”概念。
  - hidden_if_complete：完成后是否隐藏（1 是）。
  - depend_on：前置依赖；类型值对应 MasterDependOnType（Complete=0 / End=1 / CompleteOrEnd=2）。
  - entry_*：入口资源/脚本/位置（entry_place 枚举 ClassicLeft/ClassicRight/LobbyLeft/LobbyRight/ActivityAfk 等）、排序(entry_order)；independent_entry 表示子活动是否需要独立入口；visible_if_locked 控制未解锁时是否可见。
  - rule/rule_special：规则文案及是否用特殊规则弹窗；congratulations_special：是否用特殊领奖弹窗。
  - main_umg/main_umg_class：主界面资源与脚本。
  - parm_1/parm_2/parm_3：玩法自定义扩展参数；theme_tag：子活动主题标签；unlock_name：解锁提示 i18n。
  - request_data：1 登录即请求活动详情；0 仅在打开 UI 时请求。
  - popup_rule/popup_params：强弹规则与参数。
  - act_type/type_order：同类型并发活动的优先级选择。
  - special_master：活动间特殊关联或复用数据。
  - 客户端/渠道过滤：client_version 白名单，[string] main_channel/sub_channel；client_channel_version_excluded 为按渠道的禁用版本列表。
  - 分群与复用（SVR_ONLY）：player_group/not_in_group（白/黑名单），create_label/return_order（群组复用顺序），is_refresh_timely（是否需要“即时刷新”），is_forever_recycle（是否可循环复用）。
  - 注册时间窗（SVR_ONLY）：register_after/register_before。
  - is_entireday（SVR_ONLY）：end_together=0 时是否按整日对齐计时。
  - ga_act_type（SVR_ONLY）：服务器日志用活动类型（#R:ActType）。
- MasterPlay 表
  - id：玩法配置ID；comment：备注。
  - class_type：玩法类型（MasterPlayType 枚举值，如 MasterDraw/MasterExchange 等）。
  - class_id：玩法内部基准ID；master_plays 中会组合成 master_play_id = "{活动id}:{class_id}"。
  - 其余列为空位，预留给各玩法专属表（如 MasterDraw.xls、MasterExchange.xls 等）按 class_id 读取。
- Story 表（可选，引导/剧情）
  - start_animation/end_animation：[string] 动画资源。
  - start_text/end_text：[string] 文本 key。

17.3 MasterActGroup（MasterActGroup.xls）
----------------------------------------
- Main 表核心字段
  - id/comment/start_time/end_time/gonow_tag/countdown/end_together/duration/end_reminder_*：含义与 MasterAct 相同。
  - unlock_requirements：解锁条件（与关系）。
  - is_virtual：1 虚拟集群（不展示集群入口，子活动独立显示）；0 普通集群。
  - master_acts：[string] 子活动ID列表（引用 MasterAct）。
  - entry_*：入口资源/脚本/位置/排序；visible_if_locked 控制未解锁时是否可见。
  - rule/congratulations_special/rule_special：规则及特殊弹窗开关。
  - main_umg/main_umg_class：集群主界面。
  - parm_1/parm_2/parm_3：扩展参数；theme_tag：集群主题标签；unlock_name：解锁提示 i18n。
  - popup_rule/popup_params：强弹规则与参数。
  - ga_act_type（SVR_ONLY）：日志用活动类型。
  - register_after/register_before（SVR_ONLY）：注册时间窗口。
  - 客户端过滤：client_version 白名单；client_channel_version_excluded 为按渠道禁用版本。
  - story_guide_umg：旧字段，标记为 TO DEL。
================================================================================
18. 规范化使用
================================================================================

18.1 正确的模块调用方式
-----------------------
-- 推荐：直接调用
MasterPlayXXXXModule.Instance:XXXX()

-- 不推荐（仅框架内部或玩法不明确时使用）：
local moduleName = MasterData.FormatMasterPlayModuleName(masterPlayClassInfo.class_type)
local currentModule = GameGlobal.GetModuleByName(moduleName)

18.2 事件处理必须带master_play_id
---------------------------------
function XXXX:DealMasterEvent(master_play_id, ...)
    -- 方式1：持有master_data时
    if self.master_data and self.master_data:ID() ==
       MasterModule.Instance:GetMasterIDByMasterPlayID(master_play_id) then
        -- 处理逻辑
    end

    -- 方式2：确定玩法类型时
    if self.master_data and
       self.master_data:GetMasterPlayID(MasterPlayType.XXXX) == master_play_id then
        -- 处理逻辑
    end

    -- 方式3：持有master_play_id时
    if self.master_play_id == master_play_id then
        -- 处理逻辑
    end
end

18.3 正确获取玩法数据
---------------------
-- 推荐：
-- 持有master_play_id时
MasterPlayModuleBase:GetMasterPlayInfo(master_play_id)

-- 持有master_data时
MasterData:GetMasterPlayInfo(play_type)

-- 不推荐：解构master_data

================================================================================
19. 相关文件及目录索引
================================================================================

核心文件：
- lua/framework/components/game_module/module_impl/master_module.lua
- lua/framework/components/game_module/module_impl/master_play_module/master_play_module_base.lua
- lua/framework/components/game_module/module_impl/master_play_module/master_point_module.lua
- lua/game_mode/master_data.lua
- lua/product/components/ui_dialog/dialog_master/base/dialog_master_controller_base.lua

玩法模块目录：
- lua/framework/components/game_module/module_impl/master_play_module

UI页面目录：
- lua/product/components/ui_item/master

入口相关：
- lua/product/components/ui_item/master/master_entry_base.lua
- lua/product/components/ui_item/master/master_entry_loader.lua
- Content/BasicResource/Entry/UMG_Common_Entry

Tab切换模板：
- lua/product/components/ui_item/master/common/master_play_switcher/master_play_hud_base.lua
- lua/product/components/ui_item/master/common/master_play_switcher/master_play_tab_base.lua

强弹辅助目录：
- lua/game_mode/master_popup_assister
- lua/game_mode/master_popup_assister/base_class/master_popup_assister_base.lua
- lua/product/components/ui_popup/master/ui_master_notice_message_box.lua

================================================================================
20. 警告与禁止事项
================================================================================

1. 禁止直接使用成员变量，必须使用 MasterModule 和 MasterData 提供的接口
2. 禁止在代码中写死任何id
3. 禁止为某期活动写特殊化逻辑
4. 必须注意不同玩法实例间的逻辑隔离（框架允许同一玩法的不同实例同时存在）
5. 尽量使用框架提供的接口完成逻辑，避免重复代码
6. 避免代码膨胀

================================================================================
21. 重大历史调整
================================================================================

【2024/08/29】masterplayid改为拼接实现：masterplayid = mastercatid:masterplayclassid
             实现masterplay在多个masteract之间的复用

【2024/08/22】实现相同type活动的互斥接取，以及活动的重复接取

【2024/05/27】同组活动解锁依赖扩展：活动的完成和结束都可以触发依赖活动的解锁

【2024/05/24】优化mastercatid与masterplayid映射关系，masterplayid不允许活动间复用

【2024/04/18】实现master在新UI系统下的强弹逻辑，增加popup_rule字段

================================================================================
                               文档结束
================================================================================
