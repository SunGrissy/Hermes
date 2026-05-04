<!--
参考代码文件:
- lua/framework/components/game_module/module_impl/master_play_module/master_ranking_module.lua
最后参考时间: 2026-04-16
-->
================================================================================
                        MasterRanking 排行榜开发规范
================================================================================
                           版本: 2026-04-16
================================================================================

简述
----
MasterRankingModule 用于处理活动排行榜的配置获取、数据请求和排名展示。
支持三种排行榜类型：活跃榜、每周榜、每日榜。

================================================================================
1. 核心模块
================================================================================

MasterRankingModule
位置: lua/framework/components/game_module/module_impl/master_play_module/master_ranking_module.lua

================================================================================
2. 排行榜类型
================================================================================

MasterRankingType 枚举：
- MasterRankingType.Lively    = "ranking"        -- 活跃榜（活动期间）
- MasterRankingType.Weekly    = "weekly_ranking" -- 每周榜
- MasterRankingType.Daily     = "daily_ranking"  -- 每日榜

================================================================================
3. 常用 API
================================================================================

3.1 获取排行榜配置
------------------
local rank_conf = MasterRankingModule.Instance:GetRankConf(rank_id)

rank_conf 包含（节选，完整见第 9 节配表）：
- rank_show_top      : 显示前多少名
- rank_point_id      : 积分 ID
- ranking            : 活跃榜奖励配置
- weekly_ranking     : 每周榜奖励配置
- daily_ranking      : 每日榜奖励配置
- push_score_change  : 积分变化是否由后端 Push（0/1，见配表）
- toast              : 排名/积分变化时使用的 Toast UMG 名称（非空时走运行时 Toast，见第 4 节）

3.2 获取排行榜类型
------------------
local rank_type = MasterRankingModule.Instance:GetRankingType(rank_id)
-- 返回 MasterRankingType.Lively / Weekly / Daily

3.3 获取排行榜数据（会自动请求）
--------------------------------
local rank_data = MasterRankingModule.Instance:GetRankInfo(rank_id, master_id, force, rank_type)

参数：
- rank_id    : 排行榜 ID
- master_id  : 活动 ID（ac_base_id）
- force      : 是否强制刷新（true/false）
- rank_type  : 排行榜类型（可选，默认 "ranking"）

返回值（rank_data）：
- my_rank_info       : 我的排名信息
- rank_list_info     : 排行榜列表（按 rank 索引）

返回 nil 时表示正在请求，需监听事件。

3.4 直接请求排行榜数据
----------------------
MasterRankingModule.Instance:RequestRankInfo(rank_id, master_id, start_index, end_index, rank_type, is_yesterday)

参数：
- start_index   : 起始索引（1-based，默认 1）
- end_index     : 结束索引（默认 rank_show_top）
- rank_type     : 排行榜类型（可选）
- is_yesterday  : 为 true 时按「服务器昨天」日期请求历史榜，结果写入 history_rank_info；为 false/nil 时请求当前榜，写入 rank_info

3.5 获取排名奖励
----------------
local reward = MasterRankingModule.Instance:GetRankRewardAuto(rank_id, rank_index)

参数：
- rank_id    : 排行榜 ID
- rank_index : 排名（nil 则返回整个奖励配置）

3.6 请求排行榜配置
------------------
MasterRankingModule.Instance:RequestRankConf(rank_id)

若本地尚无该 rank_id 的配置则发起协议请求；配置到达后派发 MasterRankingConfReceived。

3.7 标记需要刷新
----------------
MasterRankingModule.Instance:SetNeedRefresh(rank_id)

将 need_refresh 置为 true，下次 GetRankInfo(..., force=false) 会视为需重新请求。

3.8 获取历史榜缓存
------------------
local rank_data = MasterRankingModule.Instance:GetHistoryRankInfo(rank_id, day)

- day : 与 RequestRankInfo(..., is_yesterday=true) 使用的日期字符串一致（通常为 UIHelper.GetDateString(服务器时间 - 86400) 等形式对应的「昨天」）
- 返回 nil 表示该日缓存尚未通过请求写入；需先 RequestRankInfo(rank_id, master_id, nil, nil, rank_type, true) 并监听 MasterRankingInfoRefreshed

================================================================================
4. 事件
================================================================================

GameEventType.MasterRankingInfoRefreshed
  - 参数: rank_id, day（当前榜 day 为空字符串 ""；历史榜为具体日期字符串）
  - 触发: 排行榜数据请求成功后

GameEventType.MasterRankingConfReceived
  - 参数: rank_id
  - 触发: GetMasterRankConf 配置到达并写入 rank_conf 后

GameEventType.MasterRankingLvlChanged
  - 参数: master_id, rank_id, old_rank_pos, new_rank_pos
  - 触发: 后端推送 RankRankingChanged 且处理成功时

GameEventType.MasterRankingScoreChanged
  - 参数: master_id, rank_id, old_score, new_score
  - 触发: 后端推送 RankRankingScoreChanged 且处理成功时

4.1 服务端 Push 与 Toast
------------------------
模块注册并处理 Push：
- RankRankingChanged ：排名变化 → 派发 MasterRankingLvlChanged，并 TryShowToast
- RankRankingScoreChanged ：积分变化 → 派发 MasterRankingScoreChanged，并 TryShowToast

运行时 Toast 链路：上述 Push 处理成功且 rank_conf.toast 非空时，TryShowToast 使用本地 rank_info 中的 my_rank_info 补全缺省名次/分数，调用 DialogRankToast.ShowRankUp(conf.toast, ...)。

================================================================================
5. 数据结构
================================================================================

5.1 rank_data.my_rank_info
--------------------------
{
    rank        : 排名（-1 表示未上榜）
    rank_score  : 积分
    user_id     : 用户 ID
    user_name   : 用户名
    avatar      : 头像
    vip_level   : VIP 等级
}

5.2 rank_data.rank_list_info[rank]
----------------------------------
{
    rank        : 排名
    rank_score  : 积分
    user_id     : 用户 ID
    user_name   : 用户名
    avatar      : 头像
    vip_level   : VIP 等级
    extra_info  : 额外信息（如鱼的ID、炮倍等）
}

================================================================================
6. 获取 rank_id 的方式
================================================================================

从 master_data 获取：
local rank_ids = master_data:GetRankIds()
local rank_id = rank_ids and rank_ids[1] or ""

从子活动获取：
local sub_master_data = master_data:SubMasterData(theme_tag)
local rank_ids = sub_master_data:GetRankIds()
local rank_id = rank_ids[1]

================================================================================
7. 完整示例
================================================================================

_class("MyRankingWidget", UIWidget)
MyRankingWidget = MyRankingWidget

function MyRankingWidget:Constructor(UMG)
    self:RegisterEvent(GameEventType.MasterRankingInfoRefreshed, self.OnRankInfoRefreshed)
end

function MyRankingWidget:ReceivedOnCreated(master_data)
    self.master_data = master_data
    self:InitRankData()
    self:RequestRankInfo()
end

function MyRankingWidget:InitRankData()
    local rank_ids = self.master_data:GetRankIds()
    if rank_ids and #rank_ids > 0 then
        self.rank_id = rank_ids[1]
        self.master_id = self.master_data:ID()
        self.rank_type = MasterRankingModule.Instance:GetRankingType(self.rank_id)
    end
end

function MyRankingWidget:RequestRankInfo()
    if string.isNullOrEmpty(self.rank_id) then return end
    MasterRankingModule.Instance:GetRankInfo(self.rank_id, self.master_id, true, self.rank_type)
end

function MyRankingWidget:OnRankInfoRefreshed(rank_id, day)
    if rank_id ~= self.rank_id then return end
    -- 若只关心当前榜，可忽略非空 day（历史榜）
    if not string.isNullOrEmpty(day) then return end
    self:RefreshView()
end

function MyRankingWidget:RefreshView()
    local rank_data = MasterRankingModule.Instance:GetRankInfo(self.rank_id, self.master_id)
    if not rank_data then return end

    -- 显示我的排名
    local my_rank = rank_data.my_rank_info.rank or -1
    self.UMG:SetMyRank(my_rank)

    -- 显示排行榜列表
    for rank, rank_info in pairs(rank_data.rank_list_info) do
        self.UMG:AddRankItem(rank, rank_info.user_name, rank_info.avatar, rank_info.rank_score)
    end
end

================================================================================
8. 注意事项
================================================================================

1. GetRankInfo 返回 nil 时，需要等待 MasterRankingInfoRefreshed 事件
2. rank_list_info 是按 rank 索引的 table，不是连续数组
3. 跨天/跨周时会自动清空数据，需要重新请求
4. 历史（指定日）榜：使用 RequestRankInfo(..., is_yesterday=true) 请求，结果缓存在 history_rank_info，通过 GetHistoryRankInfo(rank_id, day) 读取；MasterRankingInfoRefreshed 的第二个参数 day 非空时表示该次刷新为历史榜

================================================================================
9. 配表结构（MasterRanking.xls）
================================================================================

### Sheet: Bank

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 玩法id |
| comment | string | - | 自己看的备注 |
| rank_point_id | string | - | 排行榜积分id |
| rank_type | int | - | 排行榜类型： / 0=数据累加型 / 1=最高值覆盖型 |
| order_type | int | - | 分数排序规则 / 0=默认排序。(按照上榜时间二次排序) / 1=不做二次排序 / 2= 根据额外信息里的捕获时间进行二次排序。主分值/10000再参与排序(一种自定义方式) |
| log_score_type | int | - | 日志记录分支是否放大 /  / 不填或填0 = 不放大 / 填1 = 日志记录和金币一样进行数值放大 |
| ranking | Ranking | array | 活动结束后结算，根据功能时间的排名及奖励，引用 Ranking 子表 |
| daily_ranking | Ranking | array | 每日结算一次&刷新排行榜&发奖，为空则没有，未启用，引用 Ranking 子表 |
| weekly_ranking | Ranking | array | 每周结算一次&刷新排行榜&发奖，为空则没有，具体周几刷新需要支持配置，未启用，引用 Ranking 子表 |
| weekly_ranking_refresh | int | - | 周结算的排行榜，具体周几刷新 / 1-周一; / 2-周二； / … / 7-周日 |
| ranking_mail | string | - | 排名奖励邮件 |
| daily_ranking_mail | string | - | 每日奖励邮件，为空则没有 / #R:SystemMail |
| weekly_ranking_mail | string | - | 每周奖励邮件，为空则没有 |
| classify_server_type | string | - | 分服类型: / modulo-用分服数量对玩家服务器取模计算 / nearby-根据开服时间相邻服务器成组 / treasure-按宝藏悬赏分服 |
| classify_server_name | string | array | 服务器名称 |
| classify_server_num | int | - | 分服数量 / classify_server_type=modulo时，这里是排行榜总数 / classify_server_type=nearby时，这里是多少个服在一个榜中 / classify_server_type=treasure时，这里不配参数 |
| rank_show_top | int | - | 显示前n名 |
| is_show_title | int | - | 是否显示称号信息 / 0=不显示不下发 / 1=显示、下发数据 |
| main_ui | string | - | mainui页面 |
| main_ui_class | string | - | mainui类 |
| look_pre_diff_score | int | - | 是否显示距离下一档奖励积分 / 0=不显示 / 1=显示 |
| push_score_change | int | - | 积分变化时， / 是否向前端推送 / 0=不推送 / 1=推送 |
| toast | string | - | 积分变化的toast / 配置umg名称 |
| robot_hold_pool | Robothold | array | 占位机器人池，引用 Robothold 子表 |
| hold_num | int | - | 占位机器人总数量 |
| robot_com_pool | Robotcompete | array | 卡位机器人池，引用 Robotcompete 子表 |

### Sheet: Ranking

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 玩法id |
| rank | int | - | 排名（上一个数到该数之间的排名，左开右闭） |
| reward | yield | array | 奖励 |

### Sheet: Robothold

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | robot行为id |
| comment | string | - | 备注 |
| weight | int | - | 占位机器人权重 |
| score | int | - | 机器人最终得分 |
| start_time | object | - | 占位机器人启动时间及权重 |
| avatar | string | array | 从以下头像头随机挑选1个作为头像 |

### Sheet: Robotcompete

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | robot行为id |
| comment | string | - | 备注 |
| num | int | - | 每个榜内机器人数量 |
| min_score | int | - | 机器人最终得分下限 |
| max_score | int | - | 机器人最终得分上限 |
| avatar | string | array | 从以下头像头随机挑选1个作为头像 |
| title | object | - | 从以下头像头随机挑选1个作为头像 |
| score_inflate | float | - | 分数校正系数 |

================================================================================
                               文档结束
================================================================================
