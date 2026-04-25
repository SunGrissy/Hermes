<!--
参考代码文件:
- lua/framework/components/game_module/module_impl/master_play_module/master_play_chest_upgrade_module.lua
最后参考时间: 2026-04-16
-->
================================================================================
                        MasterChestUpgrade（宝箱升级）玩法说明
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
单次抽奖对应 **pool 条目 + bet**，开箱结果驱动 **宝箱升级链**（`chest_reward_dict` 的 `update_time`）；支持 **积分兑换**（`convert`）与 **局终结算**（`RequestGameEnd`）弹出恭喜获得。

**典型需求场景**  
连续开箱升级、倍率/运算操作链、积分与玩法专用进度 point 转换。

**能力标签**  
宝箱升级、积分转换、缓存奖励、假序列演出（`ChestUpgradeReturn`）、游戏结束清局。

**与相似玩法的区别**  
- **MasterChest**：周任务钥匙 + 多组 7 次抽奖；本玩法为 **单线 pool + chest 升级链条 + last_draw_id 局状态**，协议为 `RequestMasterChestUpgrade` / `RequestMasterChestPointConvert` / `RequestGameEnd`。

================================================================================
2. 玩法概述
================================================================================

玩家消耗玩法积分抽奖，服务端返回 `draw_id`、`bet_id`，客户端更新 `last_draw_id`、缓存过滤后的恭喜获得数据；可主动结束一局并清空 `last_draw_id` 再弹窗。监听 `MasterPointChanged` 刷新红点（抽奖点与 99 上限取 min）。

================================================================================
3. 玩法类型定义
================================================================================

- `MasterPlayType.ChestUpgrade = "MasterChestUpgrade"`
- 模块：`MasterPlayChestUpgradeModule` → `master_play_chest_upgrade_module.lua`
- 单例：`MasterPlayChestUpgradeModule.Instance`（Constructor 中赋值）

================================================================================
4. 核心模块说明
================================================================================

- **Init**：`AttachEvent(MasterPointChanged)`；注册 `RequestMasterChestUpgrade`、`RequestMasterChestPointConvert`、`RequestGameEnd`
- **cached_rewards[play_id]**：抽奖后过滤 `mp_cu_prog` 类进度 point 的恭喜获得数据；结束时 `ShowRewardsCongradulation`
- **工具**：`GetLevelUpQueue`（含随机插入 upgrade）、`GetNextChestResultbyOpera`、`GetInitChest`、`GetBigChest`、`ClearCachedRewards`

================================================================================
5. 数据结构
================================================================================

- **info**：`last_draw_id`（`"draw_id:bet_id"`，空串表示无进行中的局）、`draw_times`
- **conf**：`draw_point`、`pool`（`operation`、`reward` 等）、`chest_reward_dict`、`convert`
- **Dispose**：清空 `cached_rewards`

================================================================================
6. 协议与接口
================================================================================

| 推送 | 处理函数 |
|------|----------|
| RequestMasterChestUpgrade | OnMasterChestUpgradeDraw |
| RequestMasterChestPointConvert | OnMasterChestUpgradePointConverted |
| RequestGameEnd | OnChestUpgradeGameEnd |

**请求**：`RequestChestUpgradeDraw`、`RequestConvertPoints`、`RequestChestUpgradeGameEnd`

**派发**：`PointChanged`、`ChestUpgradeReturn`（假升级序列）、`PointConvertReturn`、`ChestUpgradeGameEnd`

================================================================================
7. 红点系统
================================================================================

- **GetRedDotKey**：`"Master_ChestUpgrade_RedDot_"..play_id`
- **CalcRedDotNumber**：可抽时按 `draw_point` 当前数量（**cap 99**）刷新枚举红点

================================================================================
8. 完成条件
================================================================================

模块 **未实现** `CheckComplete`。  
**IsFinished(play_id)**：`string.isNullOrEmpty(play_info.info.last_draw_id)` 为 true 时表示当前无进行中的抽奖局（与“可继续开箱”语义相反，用于“已结束/可重新开始”类判断时需对照调用处）。

================================================================================
9. 开发注意事项
================================================================================

- 积分转换弹窗使用 `UIYieldRewardMessageBox`，`action = "monitor_master_chestupgrade"`。
- `OnMasterChestUpgradeDraw` 内对 `mp_cu_prog` 前缀的 point 奖励过滤，避免进入恭喜获得。
- `GetLevelUpQueue` 使用 `math.random` 插入 `levelup` 步，表现层需与服务器结果一致时再对协议。
- 运算映射 `OPERA_MAP` 支持 `plus` / `mul`；未知 operation 打 Log。

================================================================================
10. 配表结构（MasterChestUpgrade.xls）
================================================================================

### Sheet: Main

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 活动id |
| comment | string | - | 备注 |
| draw_point | string | - | 抽奖用积分id |
| draw_cost | Cost | array | 抽奖消耗，引用 Cost 子表 |
| pool | Pool | array | 抽卡组合，引用 Pool 子表 |
| convert | Convert | array | 积分转换配置，引用 Convert 子表 |
| convert_unlock | int | - | 玩几次小游戏解锁转换 |
| chest_reward | Chest | array | 宝箱id（前端用），引用 Chest 子表 |
| point_mail | string | - | 游戏币转金币邮件 #R:SystemMail |

### Sheet: Cost

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一ID |
| comment | string | - | 注释 |
| input | int | - | 抽奖币消耗数量 |
| draw_type | string | - | same=每次都一样，奖励按照抽取结果乘 |
| progress_output | yield | array | 产生的进度奖积分数量 |
| reward_mul | int | - | 产出奖励倍数 |

### Sheet: Pool

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 组合ID |
| comment | string | - | 备注 |
| weight | int | - | 随机权重，万分比 |
| reward | string | - | 宝箱内容 |
| num | int | - | 宝箱数量 |
| operation | Operation | array | 宝箱数量计算路径，引用 Operation 子表 |

### Sheet: Operation

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 组合ID |
| comment | string | - | 备注 |
| cal | string | - | 操作内容 |

### Sheet: Chest

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 组合ID |
| comment | string | - | 备注 |
| name | string | - | 宝箱名称 |
| reward | yield | array | 宝箱内容 |
| image | string | - | 宝箱图片 |
| update_time | int | - | 达到此等级，需要几次升级 |

### Sheet: Convert

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 配置ID |
| comment | string | - | 备注 |
| input | int | - | 输入内容 / 默认扣除抽奖币，即Main.draw_pointh中配置的内容 |
| output | yield | array | 输出内容 |

================================================================================
                               文档结束
================================================================================

