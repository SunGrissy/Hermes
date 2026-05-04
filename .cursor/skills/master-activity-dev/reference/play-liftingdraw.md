<!--
参考代码文件:
- lua/framework/components/game_module/module_impl/master_play_module/master_play_lifting_draw_module.lua
最后参考时间: 2026-04-16
-->
================================================================================
                        升降抽奖（MasterLiftingDraw）玩法说明
================================================================================
                           版本: 2026-04-16
================================================================================

1. 适用场景与需求匹配

- **核心模式**：**多层级**抽奖，每层有独立奖池；消耗**券**进行抽奖，并可兑换累计/阶梯奖励。
- **典型需求**：阶梯式抽奖、层层递进的活动奖励、分层保底或安全次数设计。
- **能力标签**：随机奖励、多层级、兑换、券消耗。
- **与 Draw 区别**：本玩法有明确的**层级**概念，每层独立奖池与安全次数；MasterDraw 为单奖池抽奖。

适合「升层/降层、每层奖池不同」的活动；单奖池通用抽奖请用 MasterDraw。

2. 玩法概述

`MasterPlayLiftingDrawModule` 处理分层抽奖请求、兑换奖励推送，并向 UI 派发抽奖结果与兑换结果事件。各层是否可抽、已消耗券量、安全次数等通过模块内查询接口获取。

3. 玩法类型定义

- **模块类**：`MasterPlayLiftingDrawModule`
- **基类**：`MasterPlayModuleBase`
- **实现文件**：`master_play_lifting_draw_module.lua`

4. 核心模块说明

模块负责：发起分层抽奖、领取/兑换分层奖励、校验某层是否允许再抽、查询券消耗与安全次数、兑换项剩余次数等。服务端返回的 `info` 会驱动客户端展示与限制逻辑。

5. 数据结构

- **`info`**：由协议响应 `msg.res.info` 赋值；含各层进度、可选状态等（以协议为准）。
- **`info.limit_select[select_id]`**：兑换/选择类限制的索引表，用于限制某些奖励或兑换次数。

6. 协议与接口

**下行推送（RegisterPushHandler）**

- `LiftingDrawDoDraw` → `OnReceiveDoLiftingDraw`
- `LiftingDrawClaimReward` → `OnReceiveRedeemTrainReward`

**上行请求**

- `LiftingDrawDoDraw`
- `LiftingDrawClaimReward`

**常用对外方法**

- `RequestDoLiftingDraw`、`RequestClaimLiftingDrawReward`
- `IsValidForDrawForOneLevel`
- `GetConsumedCouponInLevel`、`GetSafeDrawTimesInLevel`
- `GetLiftingDrawReward`、`IsValidForChange`、`GetRewardLeftTimes`

7. 红点系统

- 红点相关方法在代码中**被注释掉**，当前**无生效的红点注册**。

若产品需要红点，需在确认协议与数据后再恢复或重写红点 key，避免与注释逻辑冲突。

8. 完成条件（CheckComplete）

- **未实现**；继承基类 → 默认不自动完成。

9. 开发注意事项

**事件**

- **派发**：`DoLiftingDraw`、`LiftingDrawReward`（用于 UI 刷新抽奖与兑换结果）

分层 UI 需按「层 id」区分奖池与按钮状态；兑换前务必检查 `limit_select` 与 `GetRewardLeftTimes`。改动协议时同步更新 `OnReceiveDoLiftingDraw` / `OnReceiveRedeemTrainReward` 内对 `info` 的解析。

**与其它抽奖玩法差异**

| 维度 | LiftingDraw | MasterDraw | MasterCollectionDraw |
|------|-------------|------------|----------------------|
| 层级奖池 | 多层级独立 | 单奖池 | 单抽奖 + 收集线 |
| 消耗物 | 券 | 积分 / 免费次数 | 积分（依配置） |
| 红点 | 当前注释未启用 | Normal/Free/Remind | Draw / Reward 双 key |

**接口使用提示**

- `IsValidForDrawForOneLevel`：刷新「本层抽奖」按钮前调用，避免券不足仍可调请求。
- `GetSafeDrawTimesInLevel`：用于展示安全次数或保底进度（文案需与策划一致）。
- `GetLiftingDrawReward` / `GetRewardLeftTimes`：兑换入口与剩余次数展示成对使用。

**测试关注点**

- 切换层级时 `info` 是否完整刷新；`limit_select` 边界（0 次、已满）展示。
- 注释掉的红点若重新启用，需全量回归 Master 入口与活动页。

10. 配表结构（MasterLiftingDraw.xls）

### Sheet: MasterLiftingDraw

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一id |
| comment | string | - | 备注名 |
| paid_point | string | - | 付费抽奖币的id,为空为不存在付费抽奖币 |
| floor | Floor | array | 层数配置，引用 Floor 子表 |
| reward | Reward | array | 奖励配置，引用 Reward 子表 |
| inflation_type | int | - | 奖励中金币的膨胀属性 / 不膨胀：0 / 付费膨胀：1 / 免费膨胀：2 |
| boost_available | int | - | 奖励中金币产出是否受charge_chip_bonus影响，1为是，不配则不受影响 |
| is_double | int | - | 奖励中金币产出是否受charge_double_chip双倍金币影响，1为是，不配则不受影响 |
| reward_recycle_mail | string | - | 奖励补发的邮件，不配则没有奖励补发 |
| pop_image | string | - | 抽奖主界面的气泡资源名称 |

### Sheet: Floor

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一id |
| comment | string | - | 备注名 |
| floor | int | - | 层数 |
| number | int | - | 当层保护抽花费抽奖币数量 |
| draw_times | int | - | 当层保护抽多少次必升层(显示用) |
| real_draw_times | int | array | 本层第几抽保底抽抽到升层，在区间内随机一个数（左闭右闭） |
| pool | Pool | array | 非保护抽概率，引用 Pool 子表 |
| protect_pool | Pool | array | 保护抽概率，引用 Pool 子表 |

### Sheet: Pool

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一id |
| comment | string | - | 备注名 |
| result | int | - | 抽奖结果 |
| weight | int | - | 抽奖权重 |

### Sheet: Reward

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一id |
| comment | string | - | 备注名 |
| floor | int | - | 层数 |
| gold_reward | yield | array | 金币奖励 |
| select_reward | SelectReward | array | 可选择奖励，引用 SelectReward 子表 |

### Sheet: SelectReward

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一id |
| comment | string | - | 备注名 |
| reward | yield | array | 奖励 |
| times | int | - | 可选择次数 |
