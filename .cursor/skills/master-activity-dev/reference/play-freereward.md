<!--
参考代码文件:
- lua/framework/components/game_module/module_impl/master_play_module/master_play_free_reward_module.lua
最后参考时间: 2026-04-16
-->
================================================================================
                        MasterFreeReward 玩法开发规范
================================================================================
                           版本: 2026-04-16
================================================================================

简述
----
FreeReward（免费奖励）玩法用于在活动中提供每日/每周/一次性的免费奖励。
玩家满足条件后可直接领取，无需完成任务。

================================================================================
1. 核心模块
================================================================================

MasterPlayFreeRewardModule
位置: lua/framework/components/game_module/module_impl/master_play_module/master_play_free_reward_module.lua

================================================================================
2. 配置说明
================================================================================

play_info.conf 关键字段：
- id                  : 玩法 ID
- free_reward         : 奖励配置数组，格式如 {{["user:chip"] = 10000}}
- reward_refresh      : 刷新类型
                        0 = 不刷新（只能领一次）
                        1 = 每周刷新
                        2 = 每天刷新
- shortcut_enable     : 是否启用快捷领取（大厅入口）

play_info.info 关键字段：
- last_take_reward    : 上次领取时间戳
- extra_coin          : VIP 额外金币数量（服务端算好；`GetVipExtraCoinYieldItemInfo` 读取）

================================================================================
3. 常用 API
================================================================================

说明：`master_play_id` 可为当前活动玩法列表里 **FreeReward 的玩法 id**，也可为与其并列的 **兄弟玩法 id**。模块内通过 `GetFreeRewardPlayID(master_play_id)` 解析出真正的 FreeReward `class_id` 后再访问玩法数据；`GetCanClaimFreeReward`、`CheckComplete`、红点等逻辑均基于解析后的 FreeReward 玩法信息（每个活动仅允许一个 FreeReward 玩法）。

3.1 获取玩法信息
----------------
-- 通过 master_data 获取 FreeReward 玩法信息
local play_info = master_data:GetMasterPlayInfo(MasterPlayType.FreeReward)
local master_play_id = master_data:GetMasterPlayID(MasterPlayType.FreeReward)

-- 通过 Module 获取
local play_info = MasterPlayFreeRewardModule.Instance:GetMasterPlayInfo(master_play_id)

-- 兄弟玩法 id → FreeReward 玩法 id（无 FreeReward 时返回 nil）
local free_reward_play_id = MasterPlayFreeRewardModule.Instance:GetFreeRewardPlayID(master_play_id)

3.2 检查是否可领取
------------------
local can_claim = MasterPlayFreeRewardModule.Instance:GetCanClaimFreeReward(master_play_id)

内部判断逻辑（reward_refresh）：
- 0（不刷新）: last_take_reward == 0 时可领
- 1（每周刷新）: last_take_reward <= 上周末时间戳 时可领
- 2（每天刷新）: last_take_reward <= 今日零点时间戳 时可领

3.3 发起领取请求
----------------
MasterPlayFreeRewardModule.Instance:RequestMasterFreeRewardTake(master_play_id)

3.4 监听领取结果
----------------
self:RegisterEvent(GameEventType.MasterFreeRewardTakeReturn, self.OnReceiveReward)

function XXX:OnReceiveReward(master_id)
    -- master_id 是活动 ID（不是 master_play_id）
    if self.master_data:ID() == master_id then
        self:Refresh()
    end
end

3.5 获取奖励信息
----------------
local reward = play_info.conf.free_reward[1]  -- 第一个奖励
local reward_info = UIHelper.GetYieldItemUIInfo(reward)
-- reward_info.count    : 数量
-- reward_info.icon     : 图标
-- reward_info.name     : 名称

-- 获取金币数量
local chip_count = reward["user:chip"] or reward["User:Chip"] or 0

3.6 红点
--------
local red_dot_key = MasterPlayFreeRewardModule.Instance:GetCommonRedDotKey(master_play_id)
-- 与 GetRedDotKey 相同；红点 key 格式: "free_reward:" .. master_play_id

MasterPlayFreeRewardModule.Instance:InitRedDot(master_play_id)   -- 确保 reddot_key 已在 RedDotManager 中注册
MasterPlayFreeRewardModule.Instance:CalcRedDotNumber(master_play_id)  -- 按当前是否可领刷新红点数值

3.7 VIP 倍率与 YieldItem（展示用）
---------------------------------
local multiple = MasterPlayFreeRewardModule.Instance:GetFreeRewardVipMultiple(master_play_id)
-- 未配置 vip_level_multiple 时返回 1

local coin_yield = MasterPlayFreeRewardModule.Instance:GetFreeRewardCoinYieldItemInfo(master_play_id)
-- free_reward 中第一个 Chip 类型奖励的 YieldItemUIInfo，已按当前 VIP 等级倍率写入数量；无则 nil
-- GetFreeRewardVipMultiple / GetFreeRewardCoinYieldItemInfo / GetVipExtraCoinYieldItemInfo 均为 `GetMasterPlayInfo(master_play_id)` 字典直查；若仅有兄弟玩法 id，请先 `GetFreeRewardPlayID` 再传入

local vip_extra_yield = MasterPlayFreeRewardModule.Instance:GetVipExtraCoinYieldItemInfo(master_play_id)
-- 来自 play_info.info.extra_coin 的金币展示（后端已算好膨胀等，Lua 侧不再乘倍率）

3.8 快捷领取（RewardShortcut）
------------------------------
Constructor 中 `RegisterRewardShortcut("MasterFreeReward", ...)` 注册大厅一键领链路：
- `CollectShortcutReward`：遍历 `shortcut_enable == 1` 的实例，对可领项组装 `ShortcutRewardInfo` 列表
- `RequestMasterFreeRewardTake(master_play_id)`：发起领取（与 UI 手动领同一套推送）
- `IsMasterFreeRewardTakeReturn(msg)`：识别 `MessageType.MasterFreeRewardTake` 回包并取出 `master_play_id`

================================================================================
4. 事件
================================================================================

GameEventType.MasterFreeRewardTakeReturn
  - 参数: master_id（活动 ID）
  - 触发: 领取推送成功（status == 0）后；在此之前已更新 `last_take_reward` 并 `CalcRedDotNumber`

GameEventType.MasterPlayComplete
  - 参数: master_play_id
  - 触发: 领取成功且 `CheckComplete(master_play_id)` 为真时（与 `MasterFreeRewardTakeReturn` 同一次成功回调内）

GameEventType.MasterTestCloseMainUI
  - 参数: master_id（活动 ID，由 `GetMasterIDByMasterPlayID` 解析）
  - 触发: 与 `MasterPlayComplete` 相同条件（测试/关闭主界面用）

GameEventType.ANewDay
  - 触发: 跨天时
  - 用途: 业务 UI 可监听以刷新展示
  - 模块层：`MasterPlayFreeRewardModule:Init` 中 `AttachEvent(ANewDay, OnNewDay)`，`OnNewDay` 对 **所有已注册实例** 调用 `CalcRedDotNumber(master_play_id)`（不依赖新 Master 跨天失效推送）

================================================================================
CheckComplete 行为（领取成功回调内）
================================================================================

- `reward_refresh == 0`（不刷新）：当 **当前不可再领**（已领过）时返回 `true`，表示该玩法可视为「已完成」一次；其它刷新类型下恒为 `false`（若以后要支持「领完最后一次算完成」需再扩展）。
- 与事件：`CheckComplete` 为真时会额外派发 `MasterPlayComplete` 与 `MasterTestCloseMainUI`（见上一节）。

================================================================================
5. 完整示例
================================================================================

_class("MyFreeRewardWidget", UIWidget)
MyFreeRewardWidget = MyFreeRewardWidget

function MyFreeRewardWidget:Constructor(UMG)
    self:AddCallback("ClaimBtn", "OnClicked")
    self:RegisterEvent(GameEventType.MasterFreeRewardTakeReturn, self.OnReceiveReward)
    self:RegisterEvent(GameEventType.ANewDay, self.OnNewDay)
end

function MyFreeRewardWidget:ReceivedOnCreated(master_data)
    self.master_data = master_data
    self.play_info = self.master_data:GetMasterPlayInfo(MasterPlayType.FreeReward)
    self.master_play_id = self.play_info.conf.id
    
    self:Init()
end

function MyFreeRewardWidget:Init()
    -- 获取奖励金币数量
    local reward = self.play_info.conf.free_reward[1]
    local chip_count = reward["user:chip"] or reward["User:Chip"] or 0
    self.UMG:SetRewardChip(chip_count)
    
    self:Refresh()
end

function MyFreeRewardWidget:Refresh()
    local can_claim = MasterPlayFreeRewardModule.Instance:GetCanClaimFreeReward(self.master_play_id)
    self.UMG:SetCanClaim(can_claim)
end

function MyFreeRewardWidget:OnReceiveReward(master_id)
    if self.master_data:ID() == master_id then
        self:Refresh()
    end
end

function MyFreeRewardWidget:OnNewDay()
    self:Refresh()
end

function MyFreeRewardWidget:ClaimBtnOnClicked()
    if MasterPlayFreeRewardModule.Instance:GetCanClaimFreeReward(self.master_play_id) then
        MasterPlayFreeRewardModule.Instance:RequestMasterFreeRewardTake(self.master_play_id)
    end
end

================================================================================
6. 配表结构（MasterFreeReward.xls）
================================================================================

### Sheet: MasterShops

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 玩法id |
| comment | string | - | 自己看的备注 |
| reward_refresh | int | - | 0:不刷新；1:每周刷新；2:每天刷新 |
| free_reward | yield | array | 奖励内容 |
| vip_level_multiple | VipLevelMultiple | array | ALL:不同vip玩家能拿到的奖励；为空则没有该功能，引用 VipLevelMultiple 子表 |
| vip_coin_multiple | int | - | 金币系数，充值1单位货币，给多少金币 |
| minimum_coin | int | - | 金币下限 |
| maximum_coin | int | - | 金币上限 |
| shortcut_enable | int | - | 0:不允许一键领；1:允许 |
| shortcut_order | int | - | master免费奖励内部领取优先级，越小越优先 |
| shortcut_title_image | string | - | 图标，不填用RewardShortcut表的title_image |
| shortcut_title_name | string | - | 名称，不填用RewardShortcut表的title_name |
| is_not_congratulation | int | - | 0或者不填表示要显示恭喜获得 / 1-代表不显示恭喜获得 |

### Sheet: VipLevelMultiple

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一ID |
| freereward_vip_level | int | - | vip等级 |
| comment | string | - | 自己看的备注 |
| vip_multiple | float | - | 每个vip等级乘上的系数 |

================================================================================
                               文档结束
================================================================================
