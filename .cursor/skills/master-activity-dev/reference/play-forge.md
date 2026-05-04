<!--
参考代码文件:
- lua/framework/components/game_module/module_impl/master_play_module/master_play_forge_module.lua
最后参考时间: 2026-04-16
-->
================================================================================
                        锻造（MasterForge）玩法说明
================================================================================
                           版本: 2026-04-16
================================================================================

1. 适用场景与需求匹配

### 核心玩法模式
消耗指定材料（或积分类输入）按配方 **锻造/兑换** 产出，支持一次提交数量 `num`；客户端以单次请求-单次推送为主，逻辑路径短。

### 典型需求场景
材料合成、简易兑换、单次多数量制作；不需要随机池、分组 Tab、批量确认弹窗链的活动。

### 能力标签
材料消耗、确定产出、数量参数、`ex_count` 次数统计。

### 与相似玩法的区别
相对 **MasterExchange**：无分组列表、批量兑换 UI、抵扣积分链路等重型能力。相对 **PoolExchange**：配方固定，无随机池与刷新。相对 **Transform**：Forge 不强调多类型枚举与神器/碎片分支校验。

---

2. 玩法概述
`MasterPlayForgeModule` 注册 `MasterForgeExchange` 推送，成功时更新 `play_data.info[formula_id].ex_count` 并派发 `MasterForgeExchange` 事件携带 `master_play_id` 与 `res`，供 UI 弹恭喜获得或刷新列表。

**交互流（概念）**
1. UI 选择配方与数量 → `ReforgeExchangeItem(master_play_id, input_id, num)`。
2. 下行成功 → 更新次数 → 监听方刷新界面与红点（Remind）。

---

3. 玩法类型定义
- **类名**：`MasterForge`
- **模块**：`MasterPlayForgeModule`

---

4. 核心模块说明
| 职责 | 说明 |
|------|------|
| 积分 | `IsRegisterPointRequired` → `false` |
| 兑换 | `ReforgeExchangeItem` —— 出站 `MasterForgeExchange`，参数 `input_id`、`num` |
| 推送 | `RegisterPushHandler`：`MasterForgeExchange` → `OnReforgeExchangeItem` |
| 其它 | 若有 `OnMasterPlayInfoRefresh` 实现，用于初始化展示（以代码为准） |

---

5. 数据结构
- **`play_data.info[formula_id].ex_count`**：各配方已兑换/锻造次数（限购、进度条或「已打造」标签）
- **配表**：配方 ID、消耗与产出由 Master 配表定义（文件名以项目为准）

---

6. 协议与接口
- **下行**：`MasterForgeExchange` —— `status == 0` 时写 `ex_count` 并 `DispatchEvent(GameEventType.MasterForgeExchange, master_play_id, res)`
- **上行**：`CreateMsg(MessageType.MasterForgeExchange)`，填充 `input_id`、`num`

---

7. 红点系统
- `GetRedDotKey`：`"forge_item_" .. master_play_id`
- `InitRedDot`：**Remind** 类型，配合 `LoadValue(reddot_key, ...)`
- `CalcRedDotNumber`：与 `LoadValue` 同步，表示「有新配方/未读提醒」类产品语义（以策划配置为准）

---

8. 完成条件
未覆写 `CheckComplete`，沿用基类默认。

---

9. 开发注意事项
- 红点为 **提醒型**，与任务类「可领」红点不同，产品需约定何时写入/清除 `LoadValue`。
- UI 监听 `MasterForgeExchange` 时核对 `res` 内 Yield 结构，对接 `UIHelper.GetYieldItemUIInfo` 时不要直接写 `YieldItemUIInfo.count`。
- 不涉及随机池，**勿混用** PoolExchange 的 `pool_id` / `formula_index`。
- 若同一活动存在多个 Forge 玩法，key 仅依赖 `master_play_id`，一般不会冲突。

**联调与测试建议**
- `status ~= 0` 时需有统一错误提示，避免静默失败。
- 大额 `num` 连续点击应走 UI 防连点，防止重复 `Push`。
- 热更或重登后 `ex_count` 与服务器对齐，若出现偏差优先查推送是否丢失。

**扩展点**
- 若未来需与抵扣积分或批量兑换对齐，应评估是否改用 `MasterExchange` 而非继续堆叠 Forge。

10. 配表结构（MasterForge.xls）

### Sheet: MasterForge

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一id |
| comment | string | - | 备注 |
| formula | formula | array | 配方列表，引用 formula 子表 |
| confirm_umg | string | - | 二次确认框umg |

### Sheet: formula

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一id |
| comment | string | - | 自己看的备注 |
| output | yield | array | 道具产出 |
| input | input | array | 可用的道具投入，引用 input 子表 |
| max_stock | stock | array | 最大兑换次数，引用 stock 子表 |

### Sheet: input

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一id |
| comment | string | - | 备注 |
| require | yield | array | 道具投入 |
| input_limit | object | - | 需求条件，区间左闭右闭，-1表示无穷大，为空表示无限制 |
| free | int | - | 不消耗次数，为1表示不消耗，为空表示消耗1次兑换次数 |

### Sheet: stock

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一id |
| comment | string | - | 备注 |
| number | int | - | 兑换次数 |
| stock_limit | object | - | 兑换次数启用需求，区间左闭右闭，-1表示无穷大，为空表示无限制 |

### Sheet: Draft

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| freeze_lock_1 | freeze_fury_1 | - | freeze_summon_1 |
| 锁定换冰冻 | 冰冻换冰冻 | - | 召唤换冰冻 |
| 激光4 | 激光3 | - | 激光2 |
