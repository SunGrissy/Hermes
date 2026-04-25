<!--
参考代码文件:
- lua/framework/components/game_module/module_impl/master_play_module/master_play_spin_draw_module.lua
最后参考时间: 2026-04-16
-->
================================================================================
                        转盘抽奖（MasterSpinDraw）玩法说明
================================================================================
                           版本: 2026-04-16
================================================================================

1. 适用场景与需求匹配

- **核心模式**：转盘形式的**单次**抽奖，消耗积分转动转盘获得随机奖励。
- **典型需求**：幸运转盘、每日一转、规则简单的活动抽奖。
- **能力标签**：随机奖励、积分消耗、转盘动画展示。
- **与 Draw 区别**：SpinDraw 更简单，单次操作，**无连抽、无完整保底体系**；复杂抽奖请用 MasterDraw。

适合「一次一转、界面以转盘为主」的轻量活动，不适合需要多连抽或复杂保底的需求。

2. 玩法概述

`MasterPlaySpinDrawModule` 继承 `MasterPlayModuleBase`，将积分与单次转盘请求绑定，通过推送更新客户端状态并驱动「再转一次」等 UI 流程。

3. 玩法类型定义

- **模块类**：`MasterPlaySpinDrawModule`
- **基类**：`MasterPlayModuleBase`
- **实现文件**：`master_play_spin_draw_module.lua`

4. 核心模块说明

积分由 **`MasterPointModule`** 统一管理。配置中的 **`draw_point`** 用于标识/关联本次转盘消耗的积分类型或消耗规则（以项目内实际解析为准）。模块在积分变化时刷新可用状态，并发起点转盘请求。

5. 数据结构

- 玩法数据依赖 **`MasterPointModule`** 的积分与玩法维度数据。
- **配置**：`conf.draw_point` 等与积分相关的字段。

无 Draw 玩法中那样复杂的 `draw_status` / 幸运值结构；以单次请求 + 推送结果为主。

6. 协议与接口

**下行推送（RegisterPushHandler）**

- `MessageType.MasterSpinDraw` → `ReceivedMasterSpinDraw`

**上行请求**

- `MessageType.MasterSpinDraw`：`RequestMasterSpinDraw`

**常用对外方法**

- `RequestMasterSpinDraw`
- `OnMasterPointChanged`（积分变化时的内部/对外刷新入口，依项目封装而定）

7. 红点系统

- **规则**：`GetRedDotKey` 等同于 `GetRedDotKey_Hint`。
- **Key**：`"Master_SpinDraw_RedDot_" .. master_play_id .. "Hint"`

8. 完成条件（CheckComplete）

- **未在模块内单独实现**；继承基类行为 → 默认 **`false`**（不构成自动完成）。

若产品需要「转满 N 次即完成」，需在配置或其它模块层补充逻辑，勿默认本玩法自带完成。

9. 开发注意事项

**事件**

- **监听**：`MasterPointChanged`
- **派发**：`MasterSpinDrawReceived`、`MasterSpinDrawAgain`

UI 应在收到推送后播放转盘动画，并根据 `MasterSpinDrawAgain` 决定是否展示「再转」入口。积分不足时需结合 `MasterPointModule` 提示。不要将本玩法与 MasterDraw 的连抽/保底接口混用。

**选型对照（Draw 家族）**

| 维度 | MasterSpinDraw | MasterDraw |
|------|----------------|------------|
| 操作粒度 | 单次转盘 | 单次 / 多抽 / 免费抽 |
| 保底 / 幸运值 | 无完整体系 | 有（依配置） |
| 积分模型 | `MasterPointModule` + `draw_point` | 付费/免费积分类型拆分 |
| 典型 UI | 转盘动画为主 | 宝箱 / 列表 / 连抽按钮 |

**集成检查清单**

- 确认 `conf.draw_point` 与策划表、积分类型枚举一致。
- 推送到达后再驱动转盘停止角度，避免客户端先停后端未到。
- 若入口与 Master 活动框架绑定，红点仅一条 Hint key，勿重复注册。

**测试关注点**

- 积分为 0、网络失败、重复点击请求时的防抖与提示。
- `MasterSpinDrawAgain` 与 UI「再转」显隐是否与服务器剩余次数一致。

10. 配表结构（MasterSpinDraw.xls）

### Sheet: MasterSpinDraw

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 玩法id |
| comment | string | - | 自己看的备注 |
| draw_point | string | - | 抽奖积分id |
| bet_times | Bet | - | 抽奖倍率，引用 Bet 子表 |
| progress_point | string | - | 进度积分id |
| reward | Reward | array | 进度奖池，引用 Reward 子表 |
| strategy | int | - | 策略开启进度 / 进度积分值 |
| strategy_min | int | - | 策略参数下限 |
| strategy_max | int | - | 策略参数上限 |
| red_dot_count | int | - | 红点计数，抽奖积分>=配置值时，显示可抽奖红点 |

### Sheet: Bet

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 玩法id |
| comment | string | - | 自己看的备注 |
| bet_times | int | - | 倍率 |
| cost | int | - | 抽奖消耗 |
| unlock_condition | int | - | 解锁所需进度积分数量 |

### Sheet: Reward

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一ID |
| comment | string | - | 注释 |
| reward | yield | array | 奖励 |
| weight | int | - | 奖池中的权重 |
| weight_min | int | - | 策略权重1 |
| weight_max | int | - | 策略权重2 |
| spin_again_rate | int | - | 再来一次万分比 |
| is_big_reward | int | - | 是否是大奖，1-是，0或为空-不是，配置1的会出现特殊动画 |
