<!--
参考代码文件:
- lua/framework/components/game_module/module_impl/master_play_module/master_play_dh_paint_module.lua
最后参考时间: 2026-04-16
-->
================================================================================
                        壁画（MasterPaint）玩法说明
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

- **核心诉求**：消耗活动积分逐步绘制壁画，分阶段解锁，最终领取大奖。
- **典型活动**：壁画绘制、分阶段涂色/创作类活动。
- **标签**：阶段绘画、积分消耗、终极大奖。
- **选型提示**：需要「多阶段进度 + 单次绘制请求 + 阶段奖/大奖分离」时使用；红点与 `master_play_id` 的拼接方式与多数玩法不同，需特别注意。

================================================================================
2. 玩法概述
================================================================================

玩家消耗配置的 `point_id` 对应积分进行单次绘制；服务端维护当前阶段、各阶段状态与大奖状态。客户端在积分变化时刷新可绘制与可领奖表现，并在领奖后派发刷新与完成事件。

**流程摘要**：检查积分 → `SendPlayOnce` 推进当前阶段绘制 → 阶段满后 `SendGetStageReward` → 全部阶段完成后 `SendRequestBigReward` → `big_reward_status` 到位后玩法可标记完成。

**配表重心**：`all_stages` / `all_paints` 决定 UI 分块与资源路径；`point_id` 与全局积分模块一致。

================================================================================
3. 玩法类型定义
================================================================================

- **枚举**：`MasterPlayType.Paint = "MasterPaint"`。
- **模块类**：`MasterPlayPaintModule`（文件名为 `master_play_dh_paint_module.lua`），继承 `MasterPlayModuleBase`。

================================================================================
4. 核心模块说明
================================================================================

- **关键方法**：`SendPlayOnce`、`SendGetStageReward`、`SendRequestBigReward`、`IsAllStageFinish`。
- **事件监听**：`MasterPointChanged`。
- **事件派发**：`MasterPaintPlayOnceReturn`、`MasterPaintRefreshNextStage`、`MasterPaintStageRewardReturn`、`MasterPlayComplete`、`MasterPaintBigRewardReturn`。

================================================================================
5. 数据结构
================================================================================

- **info**：`stages`、`cur_stage_id`、`big_reward_status` 等。
- **conf**：`all_stages`、`all_paints`、`point_id` 等阶段与消耗配置。

================================================================================
6. 协议与接口
================================================================================

| 请求 | 回调 |
|------|------|
| `MasterPaintPlayOnce` | `OnPlayOnceReceived` |
| `MasterPaintStageReward` | `OnMasterPaintStageReward` |
| `MasterPaintBigReward` | `OnMasterPaintBigReward` |

- 单次绘制与阶段领奖、大奖领取为三条独立链路，UI 需根据 `cur_stage_id` 与 `big_reward_status` 控制按钮显隐，避免重复请求。

================================================================================
7. 红点系统
================================================================================

- `GetRedDotKey` 通过 `GetNormalPaintKey` / `GetPaintRewardKey` 区分。
- **注意**：键名为固定风格——  
  - 普通：`"Master_Paint_RedDot"`  
  - 奖励：`"Master_Paint_Rew_RedDot"`  
  **字符串中不包含 `master_play_id`**，与「mpid 拼接」类玩法不同；新增入口时勿照搬其它玩法的红点拼接习惯。

================================================================================
8. 完成条件
================================================================================

- `PlayInfo.info.big_reward_status == 2`（大奖已处理完成，具体语义以服务端约定为准）。

================================================================================
9. 开发注意事项
================================================================================

- 红点键无 mpid：多活动并存时依赖框架层区分实例的方式，避免误用同一红点键导致串活动。
- 阶段切换与 `MasterPaintRefreshNextStage` 时，UI 应全量刷新阶段进度，避免只改局部导致阶段条与大奖按钮状态不一致。
- 积分不足与 `MasterPointChanged` 联动频繁，注意防连点与按钮置灰。
- `all_paints` 与 `all_stages` 的 ID 对应关系变更时，同步检查壁画预览资源与加载失败兜底图。
- 大奖 `big_reward_status` 与 `MasterPlayComplete` 的先后顺序以服务端为准，客户端勿在回调前本地改状态。
- 阶段资源异步加载失败时，`SendPlayOnce` 回包前应禁止连点，避免积分扣除与表现不同步。
- 若同一账号多设备登录，以服务端阶段为准，本地勿缓存「已绘满」状态跨会话使用。
- 自动化验收可对比 `cur_stage_id` 与壁画节点解锁数是否一致。

10. 配表结构（MasterPaint.xls）


### Sheet: Main（主表）

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | id |
| comment | string | - | 自己看的备注 |
| stages | Stage | array | 关卡，引用 Stage 子表 |
| final_rewards | yield | array | stage全部通过的大奖 |
| point_id | string | - | 使用游戏币id |
| point_mail | string | - | 积分回收邮件，不回收为空 |
| reward_recycle_mail | string | - | 未领取奖励的回收邮件 |
| clear_condition | int | - | 玩法完成要求(需要通过关卡x次），为空则表示没有玩法完成的判断 |
| target_umg | string | - | 目标奖励的umg |
| go_now | object | - | 按钮跳转 |
| tab_title | string | - | 作为玩法tab的多语言 |

### Sheet: Stage（子表：Stage）

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | id |
| comment | string | - | 相当于备注名，自己看的 |
| paint_picture | string | - | 本关的完整图 |
| paint_settings | PaintSetting | array | 本关的未上色图块id，按顺序，引用 PaintSetting 子表 |
| stage_rewards | yield | array | stage通过奖励 |
| stage_umg | string | - | 每关的umg |
| stage_text | string | - | 每关的文案 |
| effect_picture | string | - | 本关的动效贴图 |

### Sheet: PaintSetting（子表：PaintSetting）

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | id |
| comment | string | - | 相当于备注名，自己看的 |
| paint_piece | string | - | 图块未上色的图 |
| input | int | - | 该图块上色需要的游戏币 |
