<!--
参考代码文件:
- lua/framework/components/game_module/module_impl/master_play_module/master_play_saga.lua
最后参考时间: 2026-04-16
-->
================================================================================
                        Saga冒险（MasterSaga）玩法说明
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

- **核心诉求**：多关卡任务 + 捕鱼积分推进，渔场内实时追踪任务与阶段，支持局内 Toast 提示。
- **典型活动**：逐妖令、多关卡冒险、限定房间玩法。
- **标签**：多关卡、捕鱼任务、渔场内、实时 Toast。
- **选型提示**：需要「房间匹配校验 + 阶段积分 + 任务进度 + 鱼目标刷新」时选用；与 FishDrop 存在数据联动。

================================================================================
2. 玩法概述
================================================================================

每个阶段有积分目标与解锁条件，关卡内任务以 `task_id` 维度记录进度。玩家在合适房间捕鱼累积积分，完成阶段并领取阶段奖励后推进下一关；模块在进出渔场、结算、积分变化时刷新阶段与任务，并向鱼目标模块派发刷新。使用 `DialogMasterSagaToastController` 做局内提示。

**流程摘要**：进房校验 `IsSuitableRoom` → 捕鱼累积 `PointChanged` → 任务与阶段刷新 → 领取 `MasterBlastSagaStageReward` / `MasterBlastSagaProgressReward` → 必要时 `MasterBlastSagaTaskRefresh`。

**协作**：与 FishDrop 共享 `master_play_dict` 片段时，避免在未刷新完成前读取过期鱼目标列表。

================================================================================
3. 玩法类型定义
================================================================================

- **枚举**：`MasterPlayType.MasterSaga = "MasterSaga"`。
- **模块类**：`MasterPlaySagaModule`（文件 **`master_play_saga.lua`**，无 `_module` 后缀），继承 `MasterPlayModuleBase`。

================================================================================
4. 核心模块说明
================================================================================

- **关键方法**：`IsStageComplete`、`GetCurrentStagePoint`、`IsStageUnlock`、`IsSuitableRoom`、`TestTaskComplete`、`TestStageStateChange`、`IsNextStageUnlock`。
- **事件监听**：`MasterOver`、`EnterFishField`、`LeaveFishField`、`PointChanged`、`MasterPointChanged`。
- **事件派发**：`MasterBlastSagaRefreshStage`、`MasterBlastSagaRefreshProgress`、`MasterBlastSagaRefreshTask`、`MasterSagaFishTargetRefresh`、`MasterPlayComplete`。

**跨模块**：`OnMasterPlayInfoRefresh` 中会向 `MasterPlayFishDropModule.master_play_dict` 写入数据，并派发 `MasterSagaFishTargetRefresh` 供渔场内鱼目标刷新。

================================================================================
5. 数据结构
================================================================================

- **conf**：`stages` + `stage_setting`（含 `point_id`、`clear_condition`、`unlock_condition` 等），以及 `total_tasks`。
- **info**：`stage[stage_id]` → `{ s, dc }`；`task[task_id]` → `{ p }`；`gain_record`；运行时 `curr_room_id`、`curr_stage_index` 等。
- **任务进度**：`p` 一般为任务当前进度值，与 `TestTaskComplete` 内阈值比较；具体任务类型（捕获条数、积分等）由配表驱动。

================================================================================
6. 协议与接口
================================================================================

| 请求 | 回调 |
|------|------|
| `MasterBlastSagaStageReward` | `OnGetStageReward` |
| `MasterBlastSagaProgressReward` | `OnGetProgressReward` |
| `MasterBlastSagaTaskRefresh` | `OnTaskRefresh` |

================================================================================
7. 红点系统
================================================================================

- **奖励**：`GetRedDotKey_Reward` → `"master_blast_saga_reward_" .. mpid`。
- **新阶段/新内容**：`GetRedDotKey_New` → `"master_blast_saga_new_" .. mpid`。
- **分阶段新红点**：`GetNewStageReddotKey`，结合 Remind 类型与参数区分关卡。

================================================================================
8. 完成条件
================================================================================

- 所有阶段积分达到 `clear_condition` 且阶段奖励已领（`s == 1`），**且** 无未领取的进度奖励（与 `info` / `conf` 中进度奖励列表一致）。

================================================================================
9. 开发注意事项
================================================================================

- 房间是否适用必须用 `IsSuitableRoom` 与配置一致，避免错误房间累计。
- 修改 `OnMasterPlayInfoRefresh` 时谨慎：影响 FishDrop 字典与鱼目标，需联合测试局内表现。
- Toast 与 `DialogMasterSagaToastController` 频率需控制，避免进房反复弹。
- 阶段奖励与进度奖励两条协议回调都要刷新列表，避免只更新其一导致红点残留。
- `MasterOver` 与 `LeaveFishField` 时清理当前房间上下文，防止下一局错误继承 `curr_room_id`。
- 断线重连回房后立刻拉一次任务进度，避免 `task` 与表现脱节。
- `MasterBlastSagaTaskRefresh` 与积分刷新顺序以服务端说明为准，客户端避免本地预减任务进度。
- 关卡预览 UI 应读取 `conf.stages` 排序后的列表，勿依赖哈希遍历顺序。
- 性能：阶段任务列表刷新时 diff 更新子项，避免整表 Destroy 重建造成卡顿。

================================================================================
10. 配表结构（MasterSaga.xls）
================================================================================

### Sheet: Main

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | id |
| comment | string | - | 自己看的备注 |
| stages | Stage | array | 关卡，引用 Stage 子表 |
| progress_reward | ProgressReward | array | 进度奖，引用 ProgressReward 子表 |
| reward_recycle_mail | string | - | 未领取奖励的补发邮件 |
| bigreward_gonow | object | - | 大奖预览的跳转 |
| finish_reward | string | - | 大奖展示图的umg |
| big_reward_desc | string | - | 大奖描述语的图 |
| big_reward_button | string | - | 大奖跳转的按钮图 |
| guidance_pop | string | - | 引导图片资源配置 |

### Sheet: Stage

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | id |
| comment | string | - | 相当于备注名，自己看的 |
| comment | string | - | featureboss是 |
| comment | string | - | 档位 |
| feature_fish | int | array | featureboss的fishid #Fish |
| room_id | string | - | 房间id |
| stage_setting | StageSetting | - | 关卡id，引用 StageSetting 子表 |
| total_tasks | AllTask | array | 一次活动不用刷新的总任务，引用 AllTask 子表 |
| stage_cover_image | string | - | 关卡入口图的资源名 |
| go_now | object | - | 前往渔场的跳转 |
| stage_task_des | string | - | 捕获任意boss掉落积分任务描述 |
| unlock_stage_des | string | - | 关卡未解锁时的i18n描述 |

### Sheet: StageSetting

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | id |
| comment | string | - | 相当于备注名，自己看的 |
| point_id | string | - | 积分id / #R:Point |
| fish_drop | string | - | 掉落 / #R:FishDrop |
| clear_condition | int | - | 本关最多可拿积分数（本关完成条件） |
| unlock_condition | int | - | 解锁本关需要的积分数，为空为第一关不需要解锁 |
| stage_rewards | yield | array | stage通过奖励 |

### Sheet: AllTask

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 任务id |
| comment | string | - | 相当于备注名，自己看的 |
| comment | string | - | 相当于备注名，自己看的 |
| comment | string | - | 相当于备注名，自己看的 |
| description | string | - | 任务描述 |
| task_action | string | - | 具体的任务条件类型 |
| task_filters | object | array | 过滤事件 |
| task_value | object | - | 如何累加值 |
| output | int | - | 完成本任务（最多）可得积分 |

### Sheet: ProgressReward

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 玩法id |
| comment | string | - | 自己看的备注 |
| input | int | - | 累计多少积分拿到 |
| rewards | yield | array | 奖励 |
