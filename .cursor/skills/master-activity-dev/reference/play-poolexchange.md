<!--
参考代码文件:
- lua/framework/components/game_module/module_impl/master_play_module/master_play_pool_exchange_module.lua
最后参考时间: 2026-04-16
-->
================================================================================
                        池兑换（MasterPoolExchange）玩法说明
================================================================================
                           版本: 2026-04-16
================================================================================

1. 适用场景与需求匹配

### 核心玩法模式
随机配方池兑换：玩家在多个槽位/池子中按当前随机出的配方消耗积分兑换；支持手动刷新池子内容，刷新可能消耗积分或受次数限制；可通过 Tips 协议同步「哪些配方值得关注」。

### 典型需求场景
活动内「刷新商店」、随机兑换池、多池并行展示、需提示「配方变化/新配方」类玩法；需要与积分余额强联动的主界面入口。

### 能力标签
积分消耗、随机配方、刷新机制、多槽位、配方提醒（formula_tips）、池字典驱动展示。

### 与相似玩法的区别
与 **MasterExchange（固定兑换）** 相比：池兑换的配方来自随机池且可刷新；MasterExchange 多为固定配方列表/分组，强调批量与抵扣等复杂兑换能力。与 **Forge** 相比：池兑换面向「池+槽位+刷新」，非单次 `input_id` 固定配方。

---

2. 玩法概述
客户端由 `MasterPlayPoolExchangeModule`（继承 `MasterPlayModuleBase`）驱动：维护池字典、刷新次数、本地配方索引缓存；兑换/刷新/提醒通过对应协议与后端同步，并派发 UI 与积分变更事件。

**典型交互流（概念）**
1. 打开界面 → `RefreshFormulasData` 根据 `pool_dict` 生成展示列表。
2. 玩家点刷新 → `RequestRefreshPool` → 下行更新各 `pool_id` 与 `refresh_times` → `MasterPoolExchangeRefreshPool`。
3. 玩家兑换 → `RequestExchangeItem(pool_id, formula_index)` → 更新单池 `record` → `MasterPoolExchangeDoExchangeBack`。
4. 需要红点/角标 → `RequestFormulaTips` → `RecieveFormulaTips` 更新 `formula_tips` 并重算红点。

---

3. 玩法类型定义
- **类名**：`MasterPoolExchange`（逻辑模块：`MasterPlayPoolExchangeModule`）
- **常量**：`MaxSlotCount = 15`（红点与槽位遍历上限；源码注释：预先创建的红点槽位数量）
- **刷新费用**：`RefreshCostFunc.Accumulate` —— `params[1] + params[2] * refresh_time` 增长，直至不超过 `params[3]` 封顶

---

4. 核心模块说明
| 职责 | 说明 |
|------|------|
| 协议收发 | `RegisterPushHandler`：`MasterPoolExchangeExchangeItem`→`RecieveExchangeItem`；`MasterPoolExchangeFormulaTips`→`RecieveFormulaTips`；`MasterPoolExchangeRefreshPool`→`RecieveRefreshPool` |
| 对外请求 | `RequestExchangeItem`、`RequestFormulaTips`、`RequestRefreshPool`（出站 MessageType 与推送同名） |
| 数据整理 | `RefreshFormulasData`、`GetPoolInfo`、`GetFormulaInfoBySlot`、`GetShowFormulas`、`GetCanExchange`、`GetRefreshCost`、`GetCanRefresh` |
| 生命周期 | `OnMasterPlayInfoRefresh` 内刷新公式与 Tips 修复；`Dispose` 清空本地映射表 |
| 事件 | 监听 `MasterPointChanged`；派发 `PointChanged`、`MasterPoolExchangeDoExchangeBack`、`MasterPoolExchangeRecieveFormulaTips`、`MasterPoolExchangeRefreshPool`、`MasterPoolExchangePointNumChange` |

---

5. 数据结构
- **服务端同步**：`play_info.info.pool_dict[pool_id]`、`info.formula_tips[pool_id][index]`、`info.refresh_times`
- **本地缓存**：`slot_2_formula_index`、`pool_id_2_pool_info`、`formula_id_2_pool_id`、`formula_id_2_formula_info`（展示、可兑判断、红点）
- **说明**：`pool_dict` 在兑换推送里按 `msg.pool_id` 写回单条；刷新推送里遍历 `msg.res` 多池合并

---

6. 协议与接口
- **下行（推送）**
  - 兑换成功：写 `pool_dict`、派发积分 `PointChanged`、`RefreshFormulasData`、`MasterPoolExchangeDoExchangeBack`
  - Tips 成功：写 `formula_tips`、`CalcRedDotNumber`、`MasterPoolExchangeRecieveFormulaTips`
  - 刷新成功：合并多池、`refresh_times`、`PointChanged`、`RefreshFormulasData`、`ResetFormulaTips`、`MasterPoolExchangeRefreshPool`
- **上行**：`RequestExchangeItem` / `RequestFormulaTips` / `RequestRefreshPool` —— `CreateMsg` + `Push`

---

7. 红点系统
- `GetRedDotKey`：将 `1..MaxSlotCount` 的 `GetRedDotKeyBySlot` 结果拼接为管道串，供上层聚合
- `GetRedDotKeyBySlot`：`"MasterPoolExchange_Common_" .. master_play_id .. "_" .. slot_id`
- `InitRedDot`：逐槽位注册 **Common** 类型；`CalcRedDotNumber` 结合公式可兑与 Tips

---

8. 完成条件
未覆写 `CheckComplete`，沿用 `MasterPlayModuleBase` 默认（活动「完成」若需自定义，应在模块或活动层扩展）。

---

9. 开发注意事项
- 刷新与兑换都会改积分与池数据，UI 需订阅 `PointChanged` 与池相关事件，避免只刷单一字段。
- `formula_tips` 与 `RefreshFormulasData` 强相关，改展示逻辑时同步核对 `TryFixFormulaTips` / `ResetFormulaTips`。
- 红点按槽位拆分，**MaxSlotCount 与后端池数量** 需一致，否则会出现空槽位或漏绑。
- 积分类型取自 `play_info.conf.exchange_point` 对应 `Point` 配表，改表需回归测试 `PointChanged` 参数。

**联调与测试建议**
- 断网重连后执行 `OnMasterPlayInfoRefresh`，确认 `pool_dict` 与本地缓存表一致、无脏槽位。
- 刷新到封顶费用后，`GetRefreshCost` 与 `GetCanRefresh` 应与 `RefreshCostFunc` 数学关系一致。
- 多池并存时，单次刷新下行遍历 `msg.res` 的每个 `pool_id`，UI 列表需按 `pool_id` 排序稳定（避免 pairs 顺序抖动）。

**与 Master 框架关系**
- 玩法注册仍走 `MasterModule` / `master_play` 标准生命周期；本模块不单独处理活动开闭服，依赖基类刷新 info。

10. 配表结构（MasterPoolExchange.xls）

### Sheet: Main

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 玩法id |
| comment | string | - | 自己看的备注 |
| exchanges | Pool | array | 可兑换的奖库 / 价值从高到低，引用 Pool 子表 |
| exchange_point | string | - | 用于兑换的积分id / #R:Point |
| refresh_init | object | - | 刷新起步消耗计算公式 / Accumulate:[起始,步长,上限] |
| point_mail | string | - | 积分回收邮件 / #R:SystemMail |
| confirm_umg | string | - | 二次确认弹窗 |

### Sheet: Pool

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 奖池的唯一ID |
| comment | string | - | 自己看的备注 |
| formula | Formula | array | 可兑换的物品，list顺序，引用 Formula 子表 |
| order | int | - | 奖池优先级 / 数字越小越靠前 |
| num | int | - | 本奖池中的抽取数量 |
| repeat_type | int | - | 不放回抽取类型： / 0=不放回抽取（默认） / 1=有放回抽取（暂未实现） |
| init_type | string | - | 每名玩家的初始化类型 / same=所有人一致(默认,按fomula顺序取） / random=接取时每人随机生成 |
| random_strategy | string | - | 随机策略 / diff=尽量排除上次的产出（默认） / real=真随机 |

### Sheet: Formula

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 配方id |
| comment | string | - | 备注 |
| input | int | - | 兑换需要的积分数量 |
| discounts | int | - | 兑换原价显示 |
| output | yield | array | 兑换的产出内容 |
| limit | int | - | 兑换次数，-1表示无限次数 |
| is_reminder | int | - | 1默认开启兑换提示，0不开 |
| weight | int | - | 随机权重 |
| display_type | object | - | 资源等级，越小越高级 / umg有配置确定前端资源 |
| bg_img | string | - | 预览大板子上的角色底图 |
