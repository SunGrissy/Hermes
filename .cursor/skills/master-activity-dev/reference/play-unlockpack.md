<!--
参考代码文件:
- lua/framework/components/game_module/module_impl/master_play_unlock_pack_module.lua
最后参考时间: 2026-04-16
-->
================================================================================
                        解锁礼包（MasterUnlockPack）玩法说明
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

- **核心诉求**：**付费解锁**后进入**抽奖 + 自选**等多段流程的礼包类活动。
- **典型活动**：解锁大礼包、分层付费、抽选+自选组合。
- **标签**：付费解锁、抽奖、自选、流程驱动。
- **对比**：`MasterUnlock` 为服务端推送任务进度；本玩法为 **充值/购买驱动** 的流程机，配表含 `paid_tiers`、计费映射等。

================================================================================
2. 玩法概述
================================================================================

玩家在某一计费档购买后推进 `cur_charge_id` / `cur_paid_id` 等状态；可进行抽奖 `DoDraw`、自选 `SelectOne`。`OnMasterPlayInfoRefresh` 中预构建 `charge_id_map`、`last_charge_id_map` 以快速跳转相邻档位；若 `cur_charge_id` 为空可能 **自动请求** `DoDraw` 推进流程。

**流程摘要**：打开界面拉玩法信息 → 若需自动抽则 `RequestDoDraw` → 付费成功推送更新 → `RequestSelectOne` 确定分支 → 买满库存后 `CheckComplete`。

**目录**：实现位于 `module_impl/master_play_unlock_pack_module.lua`，与 `master_play_module/` 下文件并列，引用路径勿写进子目录。

================================================================================
3. 玩法类型定义
================================================================================

- **枚举**：`MasterPlayType.UnlockPack = "MasterUnlockPack"`。
- **模块类**：`MasterPlayUnlockPackModule`，继承 `MasterPlayModuleBase`。
- **路径注意**：实现文件位于  
  `lua/framework/components/game_module/module_impl/master_play_unlock_pack_module.lua`  
  （与多数 `master_play_module/` 子目录下的文件**同级目录不同**，引用时勿写错路径）。

================================================================================
4. 核心模块说明
================================================================================

- `IsRegisterPointRequired` → **false**。
- **关键方法**：`RequestDoDraw`、`RequestSelectOne`、`GetPaidTierConf`、`GetCurPaidItemConf`、`GetUnlockDrawConf`、`GetCurChoosedOptionConf`、`GetHistoryChoosedOptionConf`。
- **事件派发**：`MasterPlayComplete`、`MasterTestCloseMainUI`、`MasterUnlockPackNextFlow`、`MasterUnlockPackChangeChoose`。

================================================================================
5. 数据结构
================================================================================

- **info**：`cur_charge_id`、`cur_paid_id`、`cur_charge_buy_times`、`paid_history`、`choose_option`、`tier_id` 等。
- **conf**：`paid_tiers`；刷新时构建 `charge_id_map`、`last_charge_id_map`（用于 `last_charge_id_map[cur_charge_id]` 查找链上付费项）。
- **choose_option**：自选结果影响后续可抽池或展示，切换档位时需重新拉取 `GetCurChoosedOptionConf`。

================================================================================
6. 协议与接口
================================================================================

| 场景 | 回调 |
|------|------|
| 推送成功购买 | `MasterUnlockPackSuccessBuyCharge` → `OnPushSuccessBuyCharge` |
| 抽奖 | `MasterUnlockPackDoDraw` → `RecieveDoDraw` |
| 自选 | `MasterUnlockPackSelectOne` → `RecieveSelectOne` |

================================================================================
7. 红点系统
================================================================================

- 模块内 **未定义**通用红点；若需提示可购/可抽，由入口或 Business 层组合。

================================================================================
8. 完成条件
================================================================================

- 通过 `conf.last_charge_id_map[cur_charge_id]` 找到当前链末端 `paid_item`，当 `buy_times >= paid_item.stock`（或等价字段）时视为买满/流程结束（以实现与配表为准）。

================================================================================
9. 开发注意事项
================================================================================

- 自动 `DoDraw` 在 `cur_charge_id` 为空时触发，避免与首次打开弹窗重复请求——注意防抖与服务器幂等。
- `charge_id_map` / `last_charge_id_map` 与配表变更必须同步测试，避免断链导致 `GetCurPaidItemConf` nil。
- 与纯任务 `MasterUnlock` 命名相近，文档与策划表需写全 **`UnlockPack`** 以免混用。
- 购买推送 `OnPushSuccessBuyCharge` 与主动拉取玩法信息顺序不确定，UI 需以最新 `info` 为准重绑。
- `MasterUnlockPackNextFlow` / `MasterUnlockPackChangeChoose` 与弹窗步骤机配合时，保持一步一请求，避免状态机错乱。
- 支付取消与失败须回滚 UI 按钮状态，勿停留在「处理中」不可点。
- `paid_history` 仅作展示时勿用于判定完成，完成以 `buy_times` 与 `stock` 为准。
- 配表 `paid_tiers` 热更后需重新进玩法界面触发 `OnMasterPlayInfoRefresh` 重建映射表。
- 与支付 SDK 对账：`cur_charge_buy_times` 与渠道订单号映射建议在运营后台可查。

================================================================================
10. 配表结构（MasterUnlockPack.xls）
================================================================================

### Sheet: MasterUnlockPack

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一ID |
| comment | string | - | 注释 |
| paid_tiers | PaidTier | array | 根据付费金额推送的产出，根据rec_tier_type决定用哪个属性来区分，引用 PaidTier 子表 |

### Sheet: PaidTier

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一ID |
| comment | string | - | 备注名 |
| paid_items | Paid | array | 礼包产出，引用 Paid 子表 |
| optional_pool | OptionalPool | array | 自选奖励池，引用 OptionalPool 子表 |
| condition_1 | string | - | 条件1类型 / 累充：vip_exp / 30天内：30_days_paid_amount |
| c1_min | int | - | 条件1小值 / -1无穷小 |
| c1_max | int | - | 条件1大值 / -1无穷大 |
| condition_2 | string | - | 条件2类型 |
| c2_min | int | - | 条件2小值 / -1无穷小 |
| c2_max | int | - | 条件2大值 / -1无穷大 |

### Sheet: Paid

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一ID |
| comment | string | - | 注释 |
| charge | string | - | 买的礼包的charge id |
| type | string | - | 类型 |
| stock | int | - | 限购次数 |
| unlock_draw | UnlockDraw | array | 解锁抽奖，引用 UnlockDraw 子表 |

### Sheet: OptionalPool

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一ID |
| comment | string | - | 备注名 |
| output | yield | array | 道具产出 |
| image | string | - | 立绘使用资源 |

### Sheet: UnlockDraw

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一ID |
| comment | string | - | 备注名 |
| number | int | - | 抽取的具体数值 |
| weight | int | - | 抽取的权重 |
| charge | string | - | 抽取后使用的charge |
