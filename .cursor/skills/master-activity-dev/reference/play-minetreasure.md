<!--
参考代码文件:
- lua/framework/components/game_module/module_impl/master_play_module/master_play_mine_treasure_module.lua
最后参考时间: 2026-04-16
-->
================================================================================
                        挖宝（MasterMineTreasure）玩法说明
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

- **核心诉求**：地图翻格子挖宝，按阶段推进，最终领取终局奖励；可配合下注倍数等策略玩法。
- **典型活动**：翻格寻宝、挖矿翻牌、阶段 Boss 格。
- **标签**：翻格挖宝、阶段推进、大奖、免费奖励（可能委托 FreeReward 子模块）。
- **选型提示**：需要「格子开启消耗积分 + 阶段奖 + 终奖 + 下注」的完整闭环时使用。

================================================================================
2. 玩法概述
================================================================================

玩家在当期阶段内翻开地块，消耗积分或满足条件解锁宝藏；阶段完成后领取阶段奖励并可能进入下一阶段。模块监听积分变化，广播翻格、下注、阶段切换与游戏结束事件；完成判定兼顾活动结束与终奖状态。

**流程摘要**：选倍率 `SetBet` → 对可解锁格 `OpenTile` → 满足阶段条件 `GetStageReward` → 终局 `GetFinalReward`；中途可穿插免费奖励红点。

**UI**：格子与 `GenerateTreasureIdTiles` 一一对应；阶段切换监听 `MineTreasureNextStage`。

================================================================================
3. 玩法类型定义
================================================================================

- **枚举**：`MasterPlayType.MineTreasure = "MasterMineTreasure"`。
- **模块类**：`MasterPlayMineTreasureModule`，继承 `MasterPlayModuleBase`。

================================================================================
4. 核心模块说明
================================================================================

- **关键方法**：`GetActiveStage`、`IsAllStageComplete`、`IsCompleteStage`、`IsUnlockTile`、`IsUnlockTreasure`、`GetOpenTileRequirePoint`、`GenerateTreasureIdTiles`、`SetBet`、`OpenTile`、`GetStageReward`、`GetFinalReward`。
- **事件监听**：`MasterPointChanged`。
- **事件派发**：`MineTreasureRefreshBet`、`MineTreasureOpenTile`、`MasterPlayComplete`、`MineTreasureNextStage`、`MineTreasureGameOver`。
- **协作**：`GetFreeRewardRedDotKey` 与 `MasterPlayFreeRewardModule` 共用一套免费奖励红点逻辑，改键名时需两边确认。

================================================================================
5. 数据结构
================================================================================

- **conf**：`stages`，内含 `stage_setting`（每阶段格子、消耗、宝藏等配置）。
- **info**：以服务端下发为准，包含当前阶段、已翻开格子、终奖状态等（字段名以实现为准）。

================================================================================
6. 协议与接口
================================================================================

| 请求 | 回调 |
|------|------|
| `OpenMineTreature` | `OnOpenTile` |
| `GetMinTreatureStageReward` | `OnGetStageReward` |
| `GetMinTreatureFinalReward` | `OnGetFinalReward` |
| （额外）`SetMineTreatureBet` | 配合下注刷新 |

*注：协议名拼写以项目内注册名为准（历史命名可能存在 Treature 拼写）。*

================================================================================
7. 红点系统
================================================================================

- `GetCommonRedDotKey`：格子可开——`"mine_treasure_tile_" .. mpid`。
- `GetRedDotKey_Reward`：阶段奖励——`"mine_treasure_tile_reward_" .. mpid`。
- **免费奖励**：`GetFreeRewardRedDotKey` 委托 `MasterPlayFreeRewardModule`，避免重复实现。

================================================================================
8. 完成条件
================================================================================

- 活动已结束（`end_time <= now`），**或**
- `IsAllStageComplete` 为真 **且** `info.final_reward_status > 0`（终奖已领取/已处理，具体语义联调确认）。

================================================================================
9. 开发注意事项
================================================================================

- 阶段与格子生成 `GenerateTreasureIdTiles` 需与 UI 网格索引严格一致，避免错位翻开。
- 下注 `SetBet` 与 `MineTreasureRefreshBet` 成对考虑，避免显示倍数与协议不一致。
- 与 FreeReward 红点并存时，勿重复注册冲突键。
- 活动结束但仍未领终奖时，完成条件分支与弹窗提示需与策划一致（是否允许补领）。
- 协议历史命名含 `Treature` 拼写，全文搜索与日志过滤时注意别名。
- 终奖与阶段奖领奖动画若串行，注意锁住 `OpenTile` 防止动画期间重复开格。
- 多语言下格子坐标与 RTL 布局需单独验收，避免索引镜像错误。

10. 配表结构（MasterMineTreasure.xls）


### Sheet: Main（主表）

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | id |
| comment | string | - | 自己看的备注 |
| tile_w | int | - | 每个格子的宽度 |
| tile_h | int | - | 每个格子的高度 |
| is_loop | int | - | 0=固定数量关卡 / 1=无限循环关卡 |
| stages | Stage | array | 关卡，引用 Stage 子表 |
| final_rewards | yield | array | stage全部通过的大奖 |
| point_id | string | - | 使用游戏币id |
| reward_point | yield | array | 每消耗1个游戏币，获得的奖励 |
| available_bet | Bet | - | 可用倍率，引用 Bet 子表 |
| point_value | yield | array | 赛季玩法游戏币价值，用于计算预存奖励（回收价值不用了，走Point表的回收） |
| deposit_interval | int | - | 预存奖励触发间隔,仅计算空格 |
| point_mail | string | - | 积分回收邮件，不回收为空 |
| reward_recycle_mail | string | - | 未领取奖励的回收邮件 |
| clear_condition | int | - | 玩法完成要求(需要通过关卡x次），为空则表示没有玩法完成的判断 |
| finish_umg | string | - | 大奖的umg |
| fish_drop | string | - | 掉落 / #R:FishDrop |
| go_now | object | - | 按钮跳转 |
| drop_show | string | - | 掉落限制的显示,day表示每天，all表示总数 |
| tab_title | string | - | 作为玩法tab的多语言 |

### Sheet: Stage（子表：Stage）

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | id |
| comment | string | - | 相当于备注名，自己看的 |
| map_grids_rows | int | - | 棋盘行数 |
| map_grids_columns | int | - | 棋盘列数 |
| treasure_locations | TreasureLocation | array | 关卡中的宝石分布，引用 TreasureLocation 子表 |
| input_type | string | - | same：每次都一样 / increase：随次数递增 |
| inputs | int | array | 敲一次格子需要消耗的游戏币个数 / same就填一个数，increase就枚举每一次消耗 |
| expect_cost_times | int | - | 预期翻格子次数 |
| draw_rewards | DrawReward | array | 敲一次格子的可能获得的奖励奖池.取出式抽奖，引用 DrawReward 子表 |
| stage_rewards | yield | array | stage通过奖励 |
| show_big_stage | string | - | 每关的瑞兽大图 |
| show_small_stage | string | - | 每关进度上的关卡小图 |
| show_title | string | - | 每关的瑞兽标题字 |
| show_blessing | string | - | 每关的瑞兽祝福图片字 |

### Sheet: TreasureLocation（子表：TreasureLocation）

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 任务id |
| comment | string | - | 备注,正式数据每一关的宝石设置配置一致，宝石收集栏一致，宝石位置treasure_location有所变化 |
| treasure_settings | TreasureSetting | array | 宝石设置，引用 TreasureSetting 子表 |
| treasure_location | int | array | 宝石位置:宝石左上角锚点所在位置,[行,列]。点击可查看示意图。四芒星的锚点为中上 / 在随机宝石的玩法里，这个位置用于保底预设 |
| slot_widget | string | - | 每关宝石收集栏的umg |
| slot_name | string | array | 每关宝石收集栏对应的宝石位置 |

### Sheet: TreasureSetting（子表：TreasureSetting）

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 宝石id； / 横-horizontal / 竖-vertical / 方-rectangle / 不规则-irregular |
| comment | string | - | 相当于备注名，自己看的 |
| treasure_grids | int | array | 宝石形态,左上角为宝石锚点,坐标(0,0) |
| treasure_rotation | int | - | 宝石摆放顺时针旋转角度，90是往下转，180的位置跟不旋转相同展示出来会镜像 |
| treasure_icon | string | - | 宝石图 |
| treasure_slot | string | - | 正常的宝石轮廓图 |
| treasure_bright | string | - | 亮的宝石轮廓图 |
| treasure_name | string | - | 宝物名称i18N |

### Sheet: DrawReward（子表：DrawReward）

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一的ID |
| comment | string | - | 备注名 |
| reward | yield | array | 奖励 |
| weight | int | - | 抽奖权重 |
| amount | int | - | 奖励库存数量 |
| min_times | int | - | 至少多少次才能抽到，-1不限制 |
| user_limit_during_activity | int | - | 一次活动期间每人获得数量上限 |

### Sheet: Bet（子表：Bet）

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | id |
| comment | string | - | 自己看的备注 |
| bet_times | int | - | 消耗/奖励倍率 |
| point_condition | int | - | 当前积分数量要求 |
| unlock_weapon | int | - | 解锁锻造炮倍 |
| deposit_rate | float | - | 预存奖励折损率 |
| deposit_min_reawrd | int | - | 预存奖励最低可触发 |
| deposit_max_reawrd | int | - | 预存奖励最高可获得 |
| deposit_formule | string | - | 预存奖励触发概率公式 |

### Sheet: Draft（子表：Draft）

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| （无字段列） | - | - | - |
