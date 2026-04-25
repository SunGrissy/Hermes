<!--
参考代码文件:
- lua/framework/components/game_module/module_impl/master_play_module/master_play_draw_three_module.lua
最后参考时间: 2026-04-16
-->
================================================================================
                        三图抽奖（MasterThreeImageDraw）玩法说明
================================================================================
                           版本: 2026-04-16
================================================================================

1. 适用场景与需求匹配

- **核心模式**：三张图（图案）排列组合的**趣味抽奖**，带**存储积分**（可累计或消耗，依配置与协议）。
- **典型需求**：老虎机风格活动、三图匹配类轻量趣味抽奖。
- **能力标签**：随机奖励、图案匹配、存储积分。

与 MasterDraw 的单奖池逻辑不同：本玩法侧重**三格结果组合**与**独立存储分**，模块内还有排列/概率辅助逻辑。

2. 玩法概述

`MasterPlayThreeImageDrawModule`（类名注意：**ThreeImage**，文件名为 `master_play_draw_three_module.lua`）处理单次抽奖请求、结果恭喜、存储分变化恭喜及 BI 上报。部分数据按 `master_play_id` 存在模块级 `permutation` 表中，而非仅依赖 `master_play_dict` 内统一结构。

3. 玩法类型定义

- **模块类**：`MasterPlayThreeImageDrawModule`
- **基类**：`MasterPlayModuleBase`
- **实现文件**：`master_play_draw_three_module.lua`（与「Draw」系列文件命名并列，勿与 `master_play_draw_module.lua` 混淆）

4. 核心模块说明

模块维护三图抽奖的排列/概率辅助数据、存储分数量、最低概率奖励 id（用于展示或规则），并在 `MasterPointChanged` 时同步积分侧状态。抽奖结果与存储分变化均可能触发 UI 恭喜流程。

5. 数据结构

- **`info`**：来自 `msg.res.info`；含抽奖与展示所需字段。
- **`store_point_count`**：存储积分数量（用于 UI 与逻辑判断）。
- **模块级数据**：`permutation` 按 **`master_play_id`** 索引；该表**不在** `master_play_dict` 内部，读取时勿按统一字典路径假设。

6. 协议与接口

**下行推送（RegisterPushHandler）**

- `MessageType.MasterThreeDraw` → `OnMasterDrawThree`

**上行请求**

- `MessageType.MasterThreeDraw`：`RequestDraw`

**常用对外方法**

- `RequestDraw`
- 与 `permutation` 相关的辅助方法（排列/组合计算，见模块内实现）
- `GetRewardInfoById`
- `ShowDrawResultCongradulation`、`ShowPointCongradulation`
- `GetDrawCount`、`GetStoragePointCount`、`GetLowestProbabilityId`
- `ReportBI`

7. 红点系统

- **Key**：`GetRedDotKey` / `GetNormalRedDotKey` → `"Master_Draw_Three_RedDot_" .. master_play_id`
- **`CalcRedDotNumber`**：函数体为空，**无实际刷新/计算逻辑**；若需红点数量，需在本模块或上层补全。

8. 完成条件（CheckComplete）

- **未实现**；继承基类 → 默认不自动完成。

9. 开发注意事项

**事件**

- **监听**：`MasterPointChanged`
- **派发**：`PointChanged`、`MasterDrawThreeStoragePointChanged`、`MasterDrawThreeResult`

UI 需区分「抽奖结果动画」与「存储积分变化」两套恭喜逻辑。使用 `permutation` 时务必用 **`master_play_id`** 取表，且勿与 `master_play_dict` 混用。补红点时优先实现 `CalcRedDotNumber` 或在红点模块侧挂钩，避免仅注册 key 从不更新。

**数据存放注意**

- `permutation`：**模块级**表，键为 `master_play_id`；不要在玩法 info 里假设存在同名字段。
- `store_point_count`：与「存储积分」相关 UI（进度条、兑换入口）绑定前核对协议是否含溢出/上限。

**BI 与展示**

- `ReportBI`：抽奖、结果类型等埋点若与三格图案 id 相关，需与 `GetRewardInfoById` 使用同一套 id 定义。
- `GetLowestProbabilityId`：常用于稀有展示或规则说明，勿与「当前抽中 id」混用。

**与其它 Draw 玩法差异**

| 维度 | ThreeImageDraw | MasterDraw |
|------|----------------|------------|
| 结果形态 | 三格组合 / 图案 | 常规随机奖励 |
| 存储分 | `store_point_count` + 模块 permutation | 宝箱/道具存储等 |
| 红点 | key 有，`CalcRedDotNumber` 空 | 三套 key + 逻辑 |

**测试关注点**

- 切换不同 `master_play_id` 活动时 `permutation` 是否串线。
- `MasterDrawThreeStoragePointChanged` 与 `MasterDrawThreeResult` 触发顺序及对恭喜弹窗的影响。

10. 配表结构（MasterThreeImageDraw.xls）

### Sheet: MasterThreeImageDraw

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 玩法id |
| comment | string | - | 自己看的备注 |
| free_point | string | - | 免费抽奖币的id,为空为不存在免费抽奖币 |
| paid_point | string | - | 付费抽奖币的id,为空为不存在付费抽奖币 |
| reward | Reward | array | 奖池奖励内容，引用 Reward 子表 |
| unit_reward | yield | array | 提取积分的单位奖励 |
| image_number | int | - | 一份奖励展示上需要的图片数量 |
| image | string | array | 奖池图案显示配置 |
| min_points | int | - | 至少存了多少分才能抽到取出积分的奖励，-1不限制 |
| max_points | int | - | 至多存了多少分一定能抽到取出积分的奖励，-1不限制 |
| pop_image | string | - | 抽奖主界面的气泡资源名称 |

### Sheet: Reward

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一ID |
| comment | string | - | 注释 |
| reward | yield | array | 奖励 |
| point_number | int | - | 抽到后存取的积分数 |
| weight | int | - | 奖池中的权重 |
| extract_point | int | - | 此奖励代表提取积分玩法，抽到此奖励把存的积分全提取出来 |
| image | string | array | 奖励图案配置 |
| min_times | int | - | 最少多少次才能抽到，-1不限制 |
| max_times | int | - | 最多多少次一定能抽到，-1不限制 |
| recount | int | - | 抽到该奖励是否重新计数，0为不计数 |
