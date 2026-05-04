<!--
参考代码文件:
- lua/framework/components/game_module/module_impl/master_play_module/master_play_milestone_module.lua
最后参考时间: 2026-04-16
-->
================================================================================
                        MasterMilestone（里程碑）玩法说明
================================================================================
                           版本: 2026-04-16
================================================================================

目录
----
1. 玩法概述
2. 玩法类型定义
3. 核心模块说明
4. 配表结构
5. 协议与接口
6. 红点系统
7. 完成条件
8. VIP金币倍率机制
9. 开发注意事项
10. UI页面基类与组件
11. 进度条布局系统(ProgressListSpirit)
12. 进度刷新Helper系统
13. 开发示例与最佳实践

================================================================================
1. 玩法概述
================================================================================

MasterMilestone（里程碑）是Master活动系统中的一种玩法类型，核心玩法逻辑是：
- 玩家通过参与活动积累积分
- 积分达到指定阈值后，可领取对应的里程碑奖励
- 支持多档奖励，每档有不同的积分要求
- 支持VIP等级金币倍率加成
- 支持可选奖励（玩家可在多个奖励中选择一个）

典型使用场景：
- 周年庆活动进度奖励
- 充值累计奖励
- 活动积分兑换进度

================================================================================
2. 玩法类型定义
================================================================================

定义于: lua/framework/components/game_module/module_impl/master_play_module/master_play_module_base.lua

MasterPlayType.Milestone = "MasterMilestone"  -- 里程碑玩法

模块类名: MasterPlayMilestoneModule
模块文件: lua/framework/components/game_module/module_impl/master_play_module/master_play_milestone_module.lua

================================================================================
3. 核心模块说明
================================================================================

3.1 模块继承关系
----------------
MasterPlayMilestoneModule 继承自 MasterPlayModuleBase

3.2 模块初始化
--------------
- 注册协议处理器：MasterMilestoneClaimReward, MasterMilestoneChangeReward
- 监听事件：MasterPointChanged, VIPInfoChanged, BreakGrowthChipInflationValueChanged, WeaponBetInflationChanged（后两者均绑定 OnChipInflationChanged，与破片膨胀、武器下注膨胀共用同一回调）

3.3 数据存储
------------
- master_play_dict: 存储所有里程碑玩法实例数据
- 每个实例包含:
  - info: 服务器返回的玩法信息
    - reward_state: {reward_id: coin_mul_id} 已领取奖励状态
    - choose_data: {reward_id: select_idx} 可选奖励的选择记录
  - conf: 配表配置
    - point: 积分ID
    - reward: 奖励列表配置
    - clear_condition: 完成条件
    - is_complete_: 是否需要领完才算完成

================================================================================
4. 配表结构
================================================================================

配表文件: D:\FishUE4L3\FishUE4\Tables\server_data\Master\MasterMilestone.xls

4.1 MileStone 表（主表）
------------------------
| 字段名              | 类型       | 说明                                           |
|---------------------|------------|------------------------------------------------|
| id                  | string     | 进度奖id                                       |
| comment             | string     | 自己看的备注                                   |
| return_point        | string     | 用于不同活动中做积分回收的关联查询             |
| reward              | [Reward]   | 对应的奖励（引用Reward表）                     |
| inflation_type      | int        | 奖励中金币的膨胀属性                           |
|                     |            | 0=不膨胀, 1=付费膨胀, 2=免费膨胀               |
| boost_available     | int        | 金币产出是否受charge_chip_bonus影响，1=是      |
| reward_return_mail  | string     | 进度奖补发邮件，引用#R:SystemMail              |
| point               | string     | 积分id（关联Point表）                          |
| clear_condition     | int        | 玩法完成要求(获得积分数量），空=无完成判断     |
| get_way             | [string]   | 获取途径，填写GetWaySetting的id                |
| go_now              | object     | 界面跳转配置                                   |
| is_complete_        | int        | 1=领取全部奖励后活动完成，空=无完成判断        |
| coin_point          | [string]   | 活动需要转金币的point_id                       |
| add_point           | [string]   | 活动结束后奖励补发中需要加到玩家身上的point_id |
| charge              | [Charge]   | w2p礼包（引用Charge表）                        |
| is_merge_rewards    | int        | 同时领取多个奖励时是否合并，1=需要，0=不需要   |

4.2 Reward 表（奖励配置）
-------------------------
| 字段名           | 类型              | 说明                                    |
|------------------|-------------------|-----------------------------------------|
| id               | string            | 进度奖id（奖励节点唯一标识）            |
| comment          | string            | 自己看的备注                            |
| points           | int               | 达到本阶段所需积分/需要完成的任务条数   |
| rewards          | [yield]           | 奖励内容，支持break_through_inflate     |
| choose_rewards   | [yield]           | 可选奖励，配全部可切换的奖励内容        |
| panel_size       | int               | 进度奖在界面的大小，1=大，0=非大        |
| stage            | int               | 当前任务层数（后端做任务条件计算用）    |
| background_show  | string            | 进度奖单个奖励的背景板资源              |
| special_show     | string            | 进度奖单个奖励的特效资源                |
| coin_mul         | [vip_lev]         | VIP膨胀规则（引用vip_lev表）            |

4.3 Charge 表（礼包配置）
-------------------------
| 字段名   | 类型   | 说明                     |
|----------|--------|--------------------------|
| id       | string | 礼包配置id               |
| comment  | string | 备注                     |
| points   | int    | 需要达到多少分可以解锁   |
| charge   | string | 礼包id                   |

4.4 vip_lev 表（VIP倍率配置）
-----------------------------
| 字段名 | 类型   | 说明                       |
|--------|--------|----------------------------|
| id     | string | 配置id                     |
| level  | int    | VIP等级下限                |
| mul    | int    | 领取倍率（总值，非增量）   |

================================================================================
5. 协议与接口
================================================================================

5.1 消息类型定义
----------------
定义于: lua/framework/core/network/call/message/message_type.lua

MessageType.MasterMilestoneClaimReward = {'game', 'claim_master_milestone_reward'}
MessageType.MasterMilestoneChangeReward = {'game', 'master_milestone_choose_big_reward'}

5.2 领取奖励
------------
方法: MasterPlayMilestoneModule:RequestClaimRewards(master_play_id, reward_id)

参数:
- master_play_id: 玩法实例ID
- reward_id: 奖励ID（空则为一键领取）

请求参数:
- is_reapply: 0=普通领取
- reward_type: 0=单个领取, 1=一键领取
- reward_id: 奖励ID（单个领取时需要）

5.3 补领VIP金币
---------------
方法: MasterPlayMilestoneModule:RequestClaimVipRewards(master_play_id)

说明: VIP升级后，可补领已领取奖励的金币差额

请求参数:
- is_reapply: 1
- reward_type: 1

5.4 更换可选奖励
----------------
方法: MasterPlayMilestoneModule:RequestChangeRewards(master_play_id, choose_data)

参数:
- master_play_id: 玩法实例ID
- choose_data: {reward_id: select_idx} 选择映射，idx从0开始

5.5 查询方法
------------
| 方法                                        | 说明                               |
|---------------------------------------------|------------------------------------|
| CanClaimReward(id, reward_id)               | 某奖励是否可领取                   |
| HasRewardCanClaimed(id)                     | 是否有任何奖励可领取               |
| GetHowManyRewardsCanClaimed(id)             | 可领取奖励的数量                   |
| GetFirstAndPreviousShowRewardData(id)       | 获取当前进度最靠前未领取的奖励     |
| GetNextBigRewardUnClaimed(id)               | 获取下一个未领取的大奖             |
| GetNextReward(id, cur_point)                | 获取当前积分左右两边的奖励         |
| GetLastRewardPoints(id)                     | 获取最后一个奖励所需的积分         |
| IsClaimed(id, reward_id)                    | 某奖励是否已领取                   |
| IsReachEnd(id)                              | 是否已领完所有奖励                 |
| GetTotalRewardChip(play_info)               | 当前VIP等级下最多可领金币数        |
| GetRemainRewardChip(play_info)              | 可补领的金币数                     |
| GetRewardYieldItemInfo(play_info, conf)     | 获取某位置的奖励信息               |
| GetRewardChooseIdx(play_info, conf)         | 获取可更换奖励的当前选择           |
| InitRedDot(master_play_id)                  | 初始化可领取/可补领两条红点条目    |
| GetRedDotKey(master_play_id)                | 合并红点 Key（两条用「|」连接）    |
| GetRedDotKey_Reward(master_play_id)         | 与 GetRedDotKey 同义（奖励侧入口） |
| GetClaimRedDotKey(master_play_id)           | 可领取红点 Key                     |
| GetRemainRewardRedDotKey(master_play_id)    | 可补领金币红点 Key                 |

================================================================================
6. 红点系统
================================================================================

6.1 红点Key定义
---------------
- 可领取红点: "MasterMsClaimRedDot_{master_play_id}"
- 可补领金币红点: "MasterMsRemainRewardRedDot_{master_play_id}"
- 合并红点: 上述两个用"|"连接

6.2 红点计算
------------
function MasterPlayMilestoneModule:CalcRedDotNumber(master_play_id)
    -- 可领取红点: HasRewardCanClaimed() 返回true时为1
    -- 可补领红点: GetRemainRewardChip() > 0 时为1
end

6.3 红点刷新时机
----------------
- 积分变化时 (GameEventType.MasterPointChanged)
- VIP 升级时 (GameEventType.VIPInfoChanged → OnVIPInfoChanged(is_level_up)，仅 is_level_up 为真时对全部里程碑实例执行 CalcRedDotNumber)
- 领取奖励后

================================================================================
7. 完成条件
================================================================================

7.1 判断逻辑
------------
function MasterPlayMilestoneModule:CheckComplete(master_play_id)
    -- 优先级1: clear_condition != 0
    --   检查积分是否达到所有奖励节点的points要求
    
    -- 优先级2: is_complete_ == 1
    --   检查所有奖励是否都已领取
    
    -- 都不满足则返回false（无完成判断）
end

7.2 完成后处理
--------------
完成后派发事件:
- GameEventType.MasterPlayComplete
- GameEventType.MasterTestCloseMainUI

================================================================================
8. VIP金币倍率机制
================================================================================

8.1 机制说明
------------
- 每个奖励节点可配置 coin_mul（VIP倍率规则）
- 金币奖励根据玩家VIP等级，按不同倍率发放
- VIP升级后，可补领已领取奖励的金币差额

8.2 倍率计算
------------
配置格式: [{id, level, mul}, ...]
- level: VIP等级下限
- mul: 倍率（总值，非增量）

计算逻辑:
1. 遍历coin_mul，找到level <= 玩家VIP等级的最大mul
2. 金币数量 = 原始金币 * mul

8.3 补领机制
------------
补领金额 = 当前VIP倍率金币 - 领取时VIP倍率金币

服务器通过 reward_state[reward_id] 记录领取时的 coin_mul_id，
客户端对比当前VIP应领倍率与已领倍率，计算差额。

8.4 VIP分区统计
---------------
reward_chip_by_vip_region 由 RefreshRewardChipByVipRegion 计算，触发路径：
- OnMasterPlayInfoRefresh：单实例刷新时调用
- OnChipInflationChanged：BreakGrowthChipInflationValueChanged / WeaponBetInflationChanged 触发时，遍历 master_play_dict 中全部里程碑玩法并逐个调用 RefreshRewardChipByVipRegion

计算含义：
- 按VIP等级区间统计可领总金币数
- 用于UI展示不同VIP等级的奖励差异

================================================================================
9. 开发注意事项
================================================================================

9.1 玩法ID使用
--------------
- 服务器返回的是 class_id（配表ID）
- 客户端内部使用 master_play_id（格式: "{活动id}:{class_id}"）
- 使用 CreateMsg 发送协议会自动处理转换

9.2 积分获取
------------
通过 MasterPointModule.Instance:GetMasterPointCount(point_id) 获取积分
point_id 配置在 MileStone 表的 point 字段

9.3 可选奖励
------------
- choose_rewards 配置可选奖励列表
- 玩家选择通过 RequestChangeRewards 发送
- 选择结果存储在 info.choose_data[reward_id]
- 索引从1开始（协议传输时转为0开始）

9.4 相关事件
------------
| 事件                                  | 说明                 |
|---------------------------------------|----------------------|
| GameEventType.MasterMilestoneClaimRewardReceive | 领取奖励成功   |
| GameEventType.MasterMilestoneChangeReward       | 更换奖励成功   |
| GameEventType.MasterPointChanged                | 积分变化       |
| GameEventType.VIPInfoChanged                    | VIP等级变化    |
| GameEventType.MasterPlayComplete                | 玩法完成       |

9.5 奖励膨胀
------------
- inflation_type: 控制金币膨胀类型
- boost_available: 是否受charge_chip_bonus影响
- rewards配置支持 break_through_inflate:1 标记

9.6 大奖标记
------------
- panel_size = 1 表示大奖，在UI上会有特殊展示
- GetNextBigRewardUnClaimed 可获取下一个未领取的大奖

================================================================================
10. UI页面基类与组件
================================================================================

文件: lua/product/components/ui_item/master/milestone/common/master_play_common_milestone_widget.lua

10.1 主页面基类 MasterMilestoneMainBase
---------------------------------------
所有Milestone主页面的基类，提供通用的进度奖励展示逻辑。

继承关系: MasterMilestoneMainBase -> UIWidget

核心职责：
- 加载并管理所有奖励节点(nodes)
- 创建进度条布局精灵(progress_spirit)
- 监听积分变化并刷新进度
- 领取奖励后刷新滚动位置

生命周期：
- Constructor: 注册 MasterPointChanged, MasterMilestoneClaimRewardReceive 事件
- ReceivedOnCreated(parent, master_data): 初始化玩法数据、加载节点、刷新进度
- ReceivedOnRemoved: 销毁 progress_spirit 和 refresh_helper

子类需要重写的虚函数：
| 方法                              | 说明                           | 是否必须 |
|-----------------------------------|--------------------------------|----------|
| CreateProgressListSpirit()        | 创建进度条布局精灵             | 是       |
| CreateNodeWidget(node_info, base_point, index, max_index)| 创建单个奖励节点控件（基类虚函数签名如此，MasterMilestoneMain 实际实现仅使用 node_info、base_point 两参数） | 是       |
| CreateRefreshHelper()             | 创建进度刷新Helper             | 否       |
| InitSpecial()                     | 自定义初始化                   | 否       |
| IsEnableClaimAll()                | 是否允许一键领取               | 否       |
| RefreshScrollBoxOffset()          | 领取后刷新滚动位置             | 否       |

10.2 默认主页面 MasterMilestoneMain
-----------------------------------
继承自 MasterMilestoneMainBase，提供开箱即用的默认实现。

UMG必要控件：
- NodeContent: 节点容器

UMG可选控件：
- ClaimAllBtn: 一键领取按钮
- PointIcon: 积分图标
- ProgressBar: 进度条

UMG必要配置变量：
- NodeWidgetResName: 节点UMG资源名

UMG可选配置变量：
- ProgressListSpiritStyle: 排版方式（见第11章）
- EnableClaimAll: 是否允许一键领取
- RefreshScrollBoxOffset: 刷新滚动位置的函数

子类可重写：
- GetNodeClassName(): 返回节点绑定的脚本类名，默认 "MasterMilestoneNode"

10.3 扩展主页面变体
-------------------
| 类名                                        | 说明                               |
|---------------------------------------------|------------------------------------|
| MasterMilestoneMain_Lockable                | 支持锁定进度刷新（用于动画控制）   |
| MasterMilestoneMain_LastPin                 | 最后一个节点钉在右侧               |
| MasterMilestoneMain_LastPin_WithoutBG       | 同上，节点隐藏背景                 |

MasterMilestoneMain_LastPin 额外控件要求：
- LastNodeContent: 最后一个节点的容器
- LastNodeWidgetResName: 最后一个节点的UMG资源名

10.4 奖励节点基类 MasterMilestoneNodeBase
-----------------------------------------
所有奖励节点的基类，处理单个奖励节点的展示和交互。

继承关系: MasterMilestoneNodeBase -> UIWidget

核心职责：
- 显示奖励内容
- 根据积分判断状态（未达成/可领取/已领取）
- 处理VIP金币倍率
- 响应领取/更换奖励事件

生命周期：
- Constructor: 注册 VIPInfoChanged, MasterPointChanged, 
               MasterMilestoneClaimRewardReceive, MasterMilestoneChangeReward 事件
- ReceivedOnCreated(parent, play_info, node_info, base_point, enable_claim_all)
- ReceivedOnRemoved: 销毁 node_refresh_helper

关键方法：
- GetState(): 返回 (is_reached, claimed) 判断节点状态
- HandleVipRewardUIInfo(reward_ui_info): 处理VIP金币倍率

子类需要重写的虚函数：
| 方法                        | 说明                     | 是否必须 |
|-----------------------------|--------------------------|----------|
| SetNodeInfo()               | 设置节点信息             | 是       |
| RefreshState(reached, claim)| 刷新节点状态显示         | 是       |
| CreateNodeRefreshHelper()   | 创建节点刷新Helper       | 否       |
| RefreshProgress(point_count)| 刷新节点内进度条         | 否       |

10.5 默认奖励节点 MasterMilestoneNode
-------------------------------------
继承自 MasterMilestoneNodeBase，提供开箱即用的默认实现。

UMG必要控件：
- ClaimBtn: 领取按钮
- YieldItem: 奖励道具显示控件

UMG必要接口（UMG蓝图函数）：
- SetPoint(points): 设置所需点数
- SetState(is_reached, claimed): 设置状态

UMG可选接口：
- SetProgress(percent): 设置自带进度条进度（0~1）

子类可重写：
- HandleYieldInfo(reward_ui_info): 处理奖励信息
- HandleYieldItemWidget(widget): 处理奖励控件

10.6 扩展节点变体
-----------------
| 类名                                  | 说明                           |
|---------------------------------------|--------------------------------|
| MasterMilestoneNode_Lockable          | 支持锁定状态刷新               |
| MasterMilestoneNodeWithoutBG          | 隐藏YieldItem背景              |
| MasterMilestoneNodeAlwaysFragment     | item类型强制显示为碎片         |
| MasterMilestoneNode_MultiReward       | 支持多个奖励的节点             |

MasterMilestoneNode_MultiReward 控件要求：
- YieldBox: 装载多个YieldItem的容器

================================================================================
11. 进度条布局系统(ProgressListSpirit)
================================================================================

文件: lua/product/components/ui_assists/progress_list_spirit.lua

11.1 概述
---------
ProgressListSpirit 是一个进度条节点布局管理器，负责：
- 将节点添加到容器中
- 根据积分计算进度条百分比
- 管理节点间距和进度条padding

11.2 布局样式枚举
-----------------
ProgressListSpiritStyle = {
    None       = "",           -- 无特殊布局，使用Common
    Common     = "common",     -- 通用样式
    SeparateBar= "SeparateBar",-- 每个节点内部有独立进度条
    LastPin    = "LastPin",    -- 最后一个节点钉在右侧
    Carnival   = "Carnival",   -- 节日活动专用布局
}

11.3 创建方法
-------------
使用工厂函数创建：
local spirit = CreateProgressListSpirit(style, node_content, progress_bar, ...)

参数说明：
- style: ProgressListSpiritStyle 枚举值
- node_content: 节点容器控件
- progress_bar: 进度条控件（部分样式不需要）
- ...: 额外参数（如 LastPin 需要 last_node_content）

11.4 各样式说明
---------------

【ProgressListSpirit_Common】
- 节点无间隙排列
- 单一ProgressBar填充
- 进度分段：首个节点占1段，其他节点各占2段
- 自动调整进度条右侧padding

【ProgressListSpirit_SeparateBar】
- 进度条位于每个节点内部
- 没有统一进度条
- 节点排列随意

【ProgressListSpirit_LastPin】
- 最后一个节点钉在右侧（单独容器）
- 进度条位于节点内部
- 适合突出显示终极奖励

【ProgressListSpirit_Carnival】
- Carnival 样式：节日活动专用布局

【ProgressListSpirit_ScaledProgress / V2】
- 支持自定义节点长度
- 可不等距分布节点
- V2版本：节点计算宽度 = 当前宽度/2 + 前一个宽度/2

11.5 核心接口
-------------
| 方法                               | 说明                          |
|------------------------------------|-------------------------------|
| AddNode(node_umg, weight, idx, max)| 添加节点到容器                |
| SetBarPercentByProgress(progress)  | 根据积分设置进度条百分比      |
| ClearNode()                        | 清空所有节点                  |
| Destroy()                          | 销毁精灵                      |

================================================================================
12. 进度刷新Helper系统
================================================================================

文件: lua/product/components/ui_item/master/milestone/common/master_play_common_milestone_widget.lua

12.1 主页面刷新Helper
---------------------
控制主页面进度条的刷新逻辑。

【MilestoneRefreshHelperCommon】
- 通用刷新，直接刷新，没有动画
- RefreshProgress(point_count): 立即刷新进度条和积分显示

【MilestoneRefreshHelper_Lockable】
- 支持锁定/解锁机制
- 锁定时暂存积分变化，解锁时一次性刷新
- 用于配合动画演出

锁定事件：
- GameEventType.RefreshProgressLock: 锁定刷新
- GameEventType.RefreshProgressUnLock: 解锁刷新

12.2 节点刷新Helper
-------------------
控制单个节点的进度刷新逻辑。

【MilestoneNodeRefreshHelperCommon】
- 通用刷新
- 计算节点内进度百分比：(当前积分-起始积分)/(目标积分-起始积分)
- 调用 UMG:SetProgress(percent)

【MilestoneNodeRefreshHelper_Lockable】
- 支持锁定机制
- IsLock(): 返回当前是否锁定
- 锁定时不刷新状态，解锁时刷新

================================================================================
13. 开发示例与最佳实践
================================================================================

13.1 最简单的Milestone页面（使用通用基类）
------------------------------------------
1. 创建UMG资源，包含：
   - NodeContent（节点容器）
   - ProgressBar（进度条，可选）
   - NodeWidgetResName 变量设置节点UMG名

2. 创建节点UMG资源，包含：
   - ClaimBtn（领取按钮）
   - YieldItem（奖励显示）
   - SetPoint/SetState 蓝图函数

3. Lua绑定：
   -- 直接使用通用类，无需写代码
   主页面绑定: "MasterMilestoneMain"
   节点绑定: "MasterMilestoneNode"

13.2 自定义Milestone页面（继承扩展）
------------------------------------
_class("MyMilestoneMain", MasterMilestoneMain)
MyMilestoneMain = MyMilestoneMain

function MyMilestoneMain:Constructor(UMG)
    -- 注册额外事件或回调
    self:AddCallback("VipPreviewBtn", "OnClicked")
end

function MyMilestoneMain:ReceivedOnCreated(dialog, master_data)
    self.master_data = master_data
    self.super.ReceivedOnCreated(self, dialog, master_data)
    -- 额外初始化
    self:RefreshTotalRewardChip()
end

function MyMilestoneMain:GetNodeClassName()
    return "MyMilestoneNode"  -- 使用自定义节点类
end

function MyMilestoneMain:InitSpecial()
    -- 自定义初始化逻辑
    local point_info = GameGlobal.ResDataManager().point[self.master_play_info.conf.point]
    if point_info then
        UIHelper.LoadAndSetImageAutoSize(self.UMG.PointIcon, point_info.point_icon)
    end
end

13.3 自定义节点（继承扩展）
--------------------------
_class("MyMilestoneNode", MasterMilestoneNode)
MyMilestoneNode = MyMilestoneNode

function MyMilestoneNode:HandleYieldItemWidget(yield_item_widget)
    yield_item_widget:HideBG()  -- 隐藏背景
end

function MyMilestoneNode:SetNodeInfo()
    -- 自定义奖励显示逻辑
    local reward_ui_info = MasterPlayMilestoneModule.Instance:GetRewardYieldItemInfo(
        self.master_play_info, self.node_info)
    self:HandleVipRewardUIInfo(reward_ui_info)
    
    -- 绑定奖励控件
    self.yield_item_widget = self:BindUIWidget("UIYieldItemWidget", 
        self.UMG.YieldItem, reward_ui_info)
    self:HandleYieldItemWidget(self.yield_item_widget)
    
    -- 设置积分要求
    self.UMG:SetPoint(self.node_info.points)
end

13.4 不使用通用基类（完全自定义）
--------------------------------
_class("HLWMSMain", UIWidget)
HLWMSMain = HLWMSMain

function HLWMSMain:Constructor(UMG)
    self:RegisterEvent(GameEventType.MasterMilestoneClaimRewardReceive, self.OnClaimRewardReceive)
end

function HLWMSMain:ReceivedOnCreated(master_data, close_delegate)
    self.master_data = master_data
    self.play_info = master_data:GetMasterPlayInfo(MasterPlayType.Milestone)
    self.master_play_id = master_data:GetMasterPlayID(MasterPlayType.Milestone)
    
    self:Init()
    self:RefreshOnShow()
end

function HLWMSMain:Init()
    self.UMG.ItemBox:ClearChildren()
    for index, rew_data in ipairs(self.play_info.conf.reward) do
        local item_widget = self:CreateUIWidget("HLWMSItem", self.UMG.ItemUMGName,
            index, rew_data, self.master_play_id)
        self.UMG.ItemBox:AddChild(item_widget.UMG)
    end
end

function HLWMSMain:RefreshOnShow()
    local point_count = MasterPointModule.Instance:GetMasterPointCount(self.play_info.conf.point)
    self.UMG.PointText:SetText(point_count)
    -- 遍历刷新节点...
end

13.5 关键经验总结
-----------------
1. 【优先使用通用基类】
   - 简单场景直接用 MasterMilestoneMain + MasterMilestoneNode
   - 通过UMG变量配置即可，减少代码量

2. 【事件监听必不可少】
   - MasterPointChanged: 积分变化刷新进度
   - MasterMilestoneClaimRewardReceive: 领取后刷新状态
   - VIPInfoChanged: VIP升级刷新金币显示

3. 【节点状态判断】
   - is_reached = 积分 >= 节点所需积分
   - claimed = reward_state[node_id] != nil
   - 三态：未达成 / 可领取 / 已领取

4. 【VIP金币处理】
   - 使用 HandleVipRewardUIInfo 处理倍率
   - 显示时用 reward_ui_info.count（已乘倍率）

5. 【滚动定位】
   - 领取后自动滚动到：第一个可领取 > 第一个进行中 > 最后已完成
   - 通过 RefreshScrollBoxOffset 实现

6. 【锁定刷新机制】
   - 动画演出时锁定刷新，演出完毕解锁
   - 使用 Lockable 系列类
   - 派发 RefreshProgressLock/UnLock 事件

================================================================================
14. 配表结构（MasterMilestone.xls）
================================================================================

### Sheet: MileStone

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 进度奖id |
| comment | string | - | 自己看的备注 |
| return_point | string | - | 用于不同活动中做积分回收的关联查询 |
| reward | Reward | array | 对应的奖励，引用 Reward 子表 |
| inflation_type | int | - | 奖励中金币的膨胀属性 / 不膨胀：0 / 付费膨胀：1 / 免费膨胀：2 |
| boost_available | int | - | 奖励中金币产出是否受charge_chip_bonus影响，1为是，不配则不受影响 |
| reward_return_mail | string | - | 进度奖补发邮件 / #R:SystemMail |
| point | string | - | 积分id |
| clear_condition | int | - | 玩法完成要求(获得积分数量），为空则表示没有玩法完成的判断 |
| get_way | string | array | 获取途径，填写GetWaySetting的id |
| go_now | object | - | 界面跳转 |
| is_complete_ | int | - | 1=领取全部奖励后活动完成，为空则表示没有玩法完成的判断 |
| coin_point | string | array | 活动需要转金币的point_id / 没有point_value的point将丢弃 / 没有在此处配置的point将随邮件发放 |
| add_point | string | array | 活动结束后的奖励补发中，需要加到玩家身上的point_id |
| charge | Charge | array | w2p礼包，引用 Charge 子表 |
| is_merge_rewards | int | - | 进度奖励领取类型，当同时领取多个进度奖励中相同的奖励时，是否需要合并（不配置默认为0） / 需要：1 / 不需要：0 |

### Sheet: Reward

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 进度奖id |
| comment | string | - | 自己看的备注 |
| points | int | - | 达到本阶段所需积分/需要完成的任务条数 |
| rewards | yield | array | 奖励 |
| trigger_package | string | - | 领奖后触发的packageid |
| choose_rewards | yield | array | 可选奖励，在此处配全部可切换的奖励内容 |
| panel_size | int | - | 进度奖在界面的大小 / 1-大；0-非大 |
| stage | int | - | 当前任务层数 / （后端做任务条件计算用） |
| background_show | string | - | 进度奖单个奖励的背景板 |
| special_show | string | - | 进度奖单个奖励的特效 |
| coin_mul | vip_lev | array | vip膨胀规则，引用 vip_lev 子表 |

### Sheet: Charge

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | id |
| comment | string | - | 备注 |
| points | int | - | 需要达到多少分可以解锁礼包 |
| charge | string | - | 礼包id |

### Sheet: vip_lev

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | id |
| level | int | - | VIP等级下限 |
| mul | int | - | 领取倍率（总值，非增量） |

================================================================================
                               文档结束
================================================================================
