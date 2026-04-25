<!--
参考代码文件:
- lua/framework/components/game_module/module_impl/master_play_module/master_play_transform_module.lua
最后参考时间: 2026-04-16
-->
================================================================================
                        转化（MasterTransform）玩法说明
================================================================================
                           版本: 2026-04-16
================================================================================

1. 适用场景与需求匹配

### 核心玩法模式
将一类资源转化为另一类（碎片、炮灵、神器等），按配方执行；支持每日次数、输出上限、二次确认 UMG 配置；客户端按 `MasterPlayTransformType` 分支格式化展示与校验。

### 典型需求场景
物品回收转化、材料升级、碎片合成前置步骤；需要强依赖背包/神器实时数据的界面。

### 能力标签
物品转化、多类型分支、材料消耗、每日限制、`HaveShowUMGToday` 红点策略。

### 与相似玩法的区别
比 **Forge** 更强调 **类型维度**（枚举）与 **多数据源校验**；比 **Exchange** 更偏「单向转化」而非积分商城列表。比 **PoolExchange** 无随机池。

---

2. 玩法概述
`MasterPlayTransformModule` 监听登录红点、道具变更、神器获得与升级等事件，在数据变化时重算可否转化与红点；转化请求走 `MasterTransformTrans`，成功后走通用 `MasterExchangeReceived` 通知。

**为何事件多**：转化条件可能同时依赖碎片数量、神器等级、系统解锁——故需订阅多类 `GameEventType`。

---

3. 玩法类型定义
**枚举 `MasterPlayTransformType`**（节选，以代码为准）：`Unknown`、`Chip`、`Cannon`、`Spirit`、`SpiritFragment`、`ArtifactFragment`、`CannonFragment`、`Humanoid`。

---

4. 核心模块说明
| 职责 | 说明 |
|------|------|
| 积分 | `IsRegisterPointRequired` → `false` |
| 推送 | `RegisterPushHandler`：`MasterTransformTrans` → `OnMasterTransformTrans` |
| 业务 | `GetCanTransformByInfo`、`CheckCanTransform`、`GetCanDisplay`、`FormateTransformByType`、`GetMaxTransformNum`、`GetUnlockDesc`、`GetConfirmDialogName` |
| 事件 | 监听 `MasterPlayTransformLoginRedEvent`、`ItemDataChangeReceiveEvent`、`GetArtifactReceiveEvent`、`ArtifactLevelUpReceiveEvent`；派发 `MasterExchangeReceived` |

---

5. 数据结构
- **`masterPlayInfo.info.total_point`**：与转化次数或进度相关（以模块内使用为准）
- **`info[formula_id]`**：如 `trans_num` —— 当日或累计转化次数
- **`conf`**：`transform` 列表、`output_max_limit`、`confirm_umg` 等

---

6. 协议与接口
- **上行**：`MasterTransformTrans`，参数 `formula_id`、`num`
- **下行**：成功后更新本地数据并 `DispatchEvent(MasterExchangeReceived, ...)`（注意与 Exchange 系监听区分 `master_play_id`）

---

7. 红点系统
- `GetRedDotKey`：`"Master_Play_Transform_" .. master_play_id`
- `CalcRedDotNumber`：若 **当日未展示过** 引导 UMG 且 `GetHaveCanTransform` 为真则 1，否则 0（偏「首次提示」）

---

8. 完成条件
未覆写 `CheckComplete`，沿用基类默认。

---

9. 开发注意事项
- 新增 `MasterPlayTransformType` 时，必须补齐 `FormateTransformByType` / `GetCanDisplay` 分支，避免默认可转导致刷资源。
- `GetConfirmDialogName` 与 `confirm_umg` 需在 `ui_register` 或动态加载路径可解析。
- Yield 展示遵守 `YieldItemUIInfo`：`SetRawCount` / `GetRawCount`，禁止 `info.count =`。
- `MasterExchangeReceived` 为共享事件名，UI 回调务必过滤玩法 ID。

**联调与测试建议**
- 切换账号或清空背包后，转化按钮态应与 `GetCanTransformByInfo` 一致。
- `output_max_limit` 边界：最后一次转化数量为 1 与满额批量需各测一轮。
- `HaveShowUMGToday` 依赖本地日界，跨时区需与产品确认是否与服务端一致。

**相关系统**
- 神器/炮灵/背包模块任意一方延迟到达时，应触发已注册的 `*ReceiveEvent`，避免首屏全灰。

10. 配表结构（MasterTransform.xls）

### Sheet: MasterTransform

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 玩法id |
| comment | string | - | 自己看的备注 |
| transform | Formula | array | 可转换的物品，list顺序，引用 Formula 子表 |
| point_id | string | - | 转换的积分id |
| output_max_limit | int | - | 一次活动转换获得的output总数限制，不配则不限制 |
| confirm_umg | string | - | 兑换确认框资源 |

### Sheet: Formula

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一的id |
| comment | string | - | 备注 |
| type | string | - | 转换的物品类型，Artifact代表神器，Wing代表炮翅，Cannon代表炮台，Spirit代表英雄 |
| input | yield | array | 转换的回收内容 |
| output | yield | array | 转换的产出内容 |
| limit_reg | int | - | 限制参数，0代表已拥有，1-N代表等级，-1则不限制 |
| limit | int | - | 兑换次数，-1表示无限次数 |

### Sheet: Draft

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| 当配置了output_max_limit时，Formula里的output产出必须为单种产出，进行计数，用于限制每次活动转换获得的output总数限制 |  | - | - |
