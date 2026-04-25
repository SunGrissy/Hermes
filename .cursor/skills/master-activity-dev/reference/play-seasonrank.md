<!--
参考代码文件:
- lua/framework/components/game_module/module_impl/master_play_module/master_play_season_rank_module.lua
最后参考时间: 2026-04-16
-->
================================================================================
                        MasterSeasonRank（赛季排行）玩法说明
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
基于 **单一排行积分 point** 划分 **段位 rank**，展示进度与升段；支持 **赛季结算信息** 推送、**结算奖励领取**、历史赛季数据与 **tag/series** 维度切换（源码含多期扩展注释）。

**典型需求场景**  
赛季积分榜、段位晋升动效、结算领奖、往期赛季查询。

**能力标签**  
排行榜、赛季结算、私有数据记“上次查看段位”、升段 Toast。

**与相似玩法的区别**  
- **MasterRankPoint**：仅注册积分，无 UI/协议；SeasonRank **全量客户端逻辑 + 结算协议 + 红点**。  
- 积分来源通常由活动其它玩法或 `MasterPlayRankPoint` 写入 point。

================================================================================
2. 玩法概述
================================================================================

`GetCurRank` / `GetCurRankProgress` 由 `conf.rank` 分数区间与当前 `MasterPointModule` 积分计算。`ResetCurRank` 在积分变化时检测升段并派发 `MasterSeasonRankRankUp` 与可选 `toast`。结算数据存 `settlement_data[settlement_mpid]`，含 `info` 与 `conf`。

================================================================================
3. 玩法类型定义
================================================================================

- `MasterPlayType.SeasonRank = "MasterSeasonRank"`
- 模块：`MasterPlaySeasonRankModule` → `master_play_season_rank_module.lua`
- 枚举：`MasterPlayRankRankState`（Unlocked/Current/Locked）

================================================================================
4. 核心模块说明
================================================================================

- **Constructor**：`cur_rank`、`settlement_data` 表
- **Init**：注册 `MasterSeasonRankPushSettlementInfo`、`MasterSeasonRankClaimSettlementReward`、`MasterSeasonRankSettlement`；监听 `MasterPointChanged`
- **关键方法**：`GetCurRank`、`GetCurRankProgress`、`GetSettlementInfo*` 系列、`GetCurMasterPlayId(s)`、`GetSettlementSeasonNames`、`GetPreviousSettlementedInServer`（见源码后半部分）

================================================================================
5. 数据结构
================================================================================

- **self.settlement_data[settlement_mpid]**：`{ info, conf }`（来自 `ReceiveSettlementInfo`）
- **self.cur_rank[mpid]**：缓存段位，用于升段对比
- **play_info.conf**：`point`、`rank`（分数与展示）、`settlement`、`season_previous`、`toast`、`name` 等
- **play_info.info**：`base_id`、`act_id` 等（结算协议使用）
- **MasterPrivateData**：`SeasonSettlementData`、`LastWatchRank`

================================================================================
6. 协议与接口
================================================================================

| 推送 | 处理函数 |
|------|----------|
| MasterSeasonRankPushSettlementInfo | OnRecieveSettlementInfos → RequestSettlementInfo |
| MasterSeasonRankSettlement | ReceiveSettlementInfo |
| MasterSeasonRankClaimSettlementReward | ReceiveSettlementReward |

**请求**：`RequestSettlementInfo()`、`RequestClaimSettlementReward(settlement_series)`（内部可能多次 Push）

**派发**：`MasterSeasonRankGetSettlementInfo`、`MasterSeasonRankGetSettlement`、`MasterSeasonRankClaimeSettlementReward`、`MasterSeasonRankRankUp`

================================================================================
7. 红点系统
================================================================================

- **GetRedDotKey** = **GetRedDotKey_Common**：`"MasterPlaySeasonRank_Common_"..master_play_id`
- **CalcRedDotNumber**：`GetCurRank(master_play_id) > GetLastWatchRank(master_play_id)` 时为 1（“新段位/未查看”类提示）
- **MarkLastWatchRank** 会刷新红点

================================================================================
8. 完成条件
================================================================================

模块内 **未定义** `CheckComplete`；赛季与结算由服务器与活动周期控制。

================================================================================
9. 开发注意事项
================================================================================

- `RequestClaimSettlementReward` 注释说明多期/多 `master_play_id` 的边界，改结算流程需通读该方法与 `GetSettlementPlayIdByActId`。
- 升段 Toast 依赖 `conf.toast` 与当前段位 `rank_icon`/`rank_name`。
- `Dispose` 清空 `cur_rank` 与 `settlement_data`，避免模块热切换脏数据。

10. 配表结构（MasterSeasonRank.xls）

### Sheet: Main

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一id |
| comment | string | - | 备注 |
| name | string | - | 赛季名称多语言 |
| point | string | - | 积分id |
| rank | Rank | array | 段位，引用 Rank 子表 |
| artifact_bg | string | - | 高段位的神器合影资源 |
| gonow | Gonow | array | 积分获取直跳，引用 Gonow 子表 |
| connect | object | array | 与段位有联系的外部系统id |
| reward_preview | Preview | array | 奖励预览弹窗内的信息，价值从低到高，引用 Preview 子表 |
| permanent_reward | int | - | 最终的补发奖励是否永久保留 / 1=是       0=否 |
| season_previous | string | - | 上一期赛季MasterSeasonRank的id |
| reset_umg | string | - | 结算umg / 打开这期时，弹出的umg / 理论上是上一期的风格 |
| toast | string | - | 升段使用的toast / 配置umg名称 |
| settlement | string | - | 结算类型，同类型的活动统一结算 |
| reward_mail | string | - | 结算奖励邮件 |

### Sheet: Rank

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一id |
| comment | string | - | 备注 |
| score | int | - | 积分要求 |
| show_artifact | int | - | 大奖是否有神器 / 0=否 / 1=是 |
| rank_icon | string | - | 段位图标 |
| rank_icon_gray | string | - | 段位图标_灰色 |
| flag_bg | string | - | 段位旗帜底板图片 |
| rank_name | string | - | 段位名称多语言 |
| reward | yield | array | 奖励内容 |
| reward_info | string | - | 前端奖励展示信息 |
| reward_stage | int | - | 奖励升大段位标识 |
| chest_shownum | int | - | 展示用宝箱数量 |

### Sheet: Gonow

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一id |
| comment | string | - | 备注 |
| desc | string | - | 获取途径文本描述 |
| gonow | object | - | 跳转 |

### Sheet: Preview

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一id |
| comment | string | - | 备注 |
| chest_src | string | - | 宝箱图片资源 |
| chest_bg | string | - | 宝箱背景 |
| chest_name | string | - | 宝箱名称i18n |
| chest_name_src | string | - | 宝箱名称图片字资源 |
| probability | yield | array | 概率公式用奖品和概率 |

================================================================================
                               文档结束
================================================================================
