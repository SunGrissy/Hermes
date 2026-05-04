<!--
参考代码文件:
- lua/framework/components/game_module/module_impl/master_play_module/master_play_search_module.lua
最后参考时间: 2026-04-16
-->
================================================================================
                        搜寻（MasterSearch）玩法说明
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

- **核心诉求**：在界面中查找隐藏物品，配合进度奖励推进活动。
- **典型活动**：找茬、隐藏物品搜寻类活动。
- **标签**：搜寻/找茬、进度奖励、每日限次。
- **选型提示**：需要「点击场景找物 + 领取阶段奖励 + 谜题/线索类红点」时优先考虑本玩法。

================================================================================
2. 玩法概述
================================================================================

玩家在配置的搜寻点中逐个「找到」物品，服务端记录已找到 ID 与进度奖励领取情况；客户端在刷新玩法信息时汇总场景与 ID 映射，并监听跨天、弹窗展示等事件以刷新可交互状态与红点。

**流程摘要**：进入活动 → 按 UI 场景定位未找到点位 → 调用 `FindOne` 上报 → 更新 `search_ids` 与谜题红点 → 进度达标后领取 `GetMasterSearchProgressReward` → 全部条件满足后 `MasterPlayComplete`。

**关联**：与 Master 主数据、积分模块无强绑定时可独立交互；进度奖励与「清屏条件」共同决定活动是否可结算。

================================================================================
3. 玩法类型定义
================================================================================

- **枚举**：`MasterPlayType.Search = "MasterSearch"`（定义于 `master_play_module_base.lua`）。
- **模块类**：`MasterPlaySearchModule`，继承 `MasterPlayModuleBase`。

================================================================================
4. 核心模块说明
================================================================================

- **继承**：`MasterPlaySearchModule` → `MasterPlayModuleBase`，与其它玩法共用 `master_play_dict` 生命周期。
- **关键方法**：`IsSearchPlaceFound`、`GetLeftToday`、`FindOne`、`GetProgressReward`、`IsStrictlyMatch`。
- **事件监听**：`ANewDay`、`AfterShowDialog`、`AfterShowPopup`（用于界面/跨天刷新）。
- **事件派发**：`MasterSearchFindOneReturn`、`MasterPlayComplete`、`MasterSearchGetProgressRewardReturn`。
- **UI 协作**：搜寻点与 `ui2ids_dict` 绑定后，点击校验可走 `IsStrictlyMatch`（是否必须点中精确物件由配置与该方法共同决定）。

================================================================================
5. 数据结构
================================================================================

- `OnMasterPlayInfoRefresh` 会构建 `search_place_summary`，包含 `default_start_time`、`default_end_time`、`ui2ids_dict` 等，供 UI 按场景聚合展示。
- 服务端下发的 `progress_reward` 相关索引在客户端处理时存在 **+1 偏移**（与进度条展示/领取对齐时注意不要用错下标）。

================================================================================
6. 协议与接口
================================================================================

| 方向 | 说明 |
|------|------|
| 请求 → 回调 | `MasterSearchFindOne` → `OnFindOneReturn` |
| 请求 → 回调 | `GetMasterSearchProgressReward` → `OnGetProgressRewardReturn` |

================================================================================
7. 红点系统
================================================================================

- `GetRedDotKey` 区分奖励与谜题两类：
  - **奖励**：`"Master_Search_RedDot_" .. mpid`
  - **谜题**：`"Master_Search_Riddle_RedDot_" .. mpid`
- 具体由 `GetRedDotKey_Reward` / `GetRedDotKey_Riddle` 等封装组合使用。

================================================================================
8. 完成条件
================================================================================

`#info.search_ids >= conf.clear_condition` **且** 进度奖励已全部领取：  
`#info.progress_reward == #conf.progress_reward`。

================================================================================
9. 开发注意事项
================================================================================

- 每日限次与「今日剩余次数」展示务必与 `GetLeftToday` 及服务端配置一致。
- 进度奖励索引偏移易踩坑，联调时对照协议字段与 `info.progress_reward` 长度。
- 弹窗/对话展示后依赖 `AfterShowDialog`、`AfterShowPopup` 刷新，避免界面仍显示旧可点状态。
- `FindOne` 与 `GetProgressReward` 失败路径要提示原因（次数不足、已找到、网络错误），避免静默无反馈。
- 与 Master 主界面同时存在时，注意 `MasterPlayComplete` 派发后关闭入口或刷新列表，防止重复领奖。
- 配表 `clear_condition` 与「已找到个数」比较时类型一致（number），避免字符串比较恒假。
- 场景热更或动态下载 UI 时，`ui2ids_dict` 重建前要判空，防止点击崩溃。
- 自动化测试可断言 `search_ids` 长度单调不减，防止回退异常。

10. 配表结构（MasterSearch.xls）


### Sheet: MasterSearch（主表）

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 玩法id |
| comment | string | - | 自己看的备注 |
| search_field_umg | string | - | 资源名 |
| search_field_umg_class | string | - | umg逻辑对应的类名 |
| guide_search_id | string | - | 出现在活动主页的物品 |
| search_place | Search | array | 每天出现的物品，引用 Search 子表 |
| progress_reward | ProgressReward | array | 进度奖，引用 ProgressReward 子表 |
| clear_condition | int | - | 玩法完成要求(需要达成关键行为x次），为空则表示没有玩法完成的判断 |
| reward_recycle_mail | string | - | 未领取奖励的回收邮件 |

### Sheet: Search（子表：Search）

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 物品id |
| comment | string | - | 自己看的备注 |
| start_time | time | - | 开始时间，为空取对应活动时间，必须是一整天 |
| end_time | time | - | 结束时间，为空取对应活动时间 |
| icon | string | - | 物品umg |
| ref_id | string | - | 物品出现所处活动的id |
| search_ui | string | - | 出现的页面umg |
| anchor_x | float | - | 出现在该页面的锚点的X值 / [0,1] |
| anchor_y | float | - | 出现在该页面的锚点的Y值 / [0,1] |
| pos_x | float | - | x坐标 |
| pos_y | float | - | y坐标 |
| search_rewards | yield | array | 奖励 |
| search_riddle | string | - | 物品线索 |

### Sheet: ProgressReward（子表：ProgressReward）

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 玩法id |
| comment | string | - | 自己看的备注 |
| find_number | int | - | 找到几个 |
| rewards | yield | array | 奖励 |
| is_big_reward | int | - | 是否为升级形态的进度点，1：是；空：不是 |
