<!--
参考代码文件:
- lua/framework/components/game_module/module_impl/master_play_module/master_play_base_bp_module.lua
最后参考时间: 2026-04-16
-->
================================================================================
                        MasterBaseBP（基础通行证）玩法说明
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
**经验（exp）→ 当前等级 → 里程碑多档奖励**；支持 **免费 / 付费 / Deluxe** 三轨，`unlock_state` 控制解锁。经验来源可为金币、**MasterPoint** 或签到（`MasterPlayBaseBPExpType`）。

**典型需求场景**  
简化战令、短周期通行证、仅里程碑无复杂任务树的活动。

**能力标签**  
经验等级、里程碑、额外宝箱 `extra_reward`、付费解锁、商店购买回调播解锁 UI。

**与相似玩法的区别**  
- **MasterSBPv1**：完整赛季任务 + 兑换 + 多子红点；BaseBP **无** 赛季任务树与 exchange 体系，协议为 `ClaimBaseBPMilestoneReward` / `BaseBPExpCountChanged`。

================================================================================
2. 玩法概述
================================================================================

`OnMasterPlayInfoRefresh` 时 `CalcCurrentLevel`；`exp_type == Point` 时动态编译 `exp_type_formula` 为每炮经验函数。监听积分、商城购买、恭喜获得关闭以处理解锁展示。

================================================================================
3. 玩法类型定义
================================================================================

- `MasterPlayType.BaseBP = "MasterBaseBP"`
- 模块：`MasterPlayBaseBPModule` → `master_play_base_bp_module.lua`
- 枚举：`MasterPlayBaseBPExpType`、`MasterPlayBaseBPRewardType`
- 静态工具：`GetCurrentExpPoint`、`CalcCurrentLevel`、`GetRewardState`、`MergeRewardTo`、`HaveRewardToClaim`、`HaveExtraRewardToClaim`、`GetUnlockRewards`

================================================================================
4. 核心模块说明
================================================================================

- **Init**：注册 `ClaimBaseBPMilestoneReward`、`ClaimBaseBPExtraReward`、`BaseBPExpCountChanged`
- **事件**：`MasterPointChanged`、`ShopBuyReturn`、`YieldRewardShowComplete`
- **请求**：`RequestBaseBPReward(master_play_id, level)` — `reward_level` 0 表示一键领

================================================================================
5. 数据结构
================================================================================

- **master_play_info.curr_level**：由 `CalcCurrentLevel` 写入
- **info**：`exp_point`（非 Point 类型时）、`gain_record`（键前缀 `GAIN_RECORD_PREFIX_BY_TYPE` + `":"` + level）、`chest_times`（额外奖励进度）、`unlock_state`
- **conf**：`milestone_rewards`（每档 `score`、三轨奖励数组）、`extra_reward`、`exp_type`、`exp_type_param`、`charge_*` 等

================================================================================
6. 协议与接口
================================================================================

| 推送 | 处理函数 |
|------|----------|
| ClaimBaseBPMilestoneReward | ReceivedBaseBPReward |
| ClaimBaseBPExtraReward | ReceivedBaseBPExtraReward |
| BaseBPExpCountChanged | ReceivedBaseBPExpChanged |

**派发**：`BaseBPReceivedReward`、`BaseBPReceivedExtraReward`、`BaseBPExpPointChanged`、`BaseBPUnlockStateChange`（以源码为准）

================================================================================
7. 红点系统
================================================================================

- **GetRedDotKey** = **GetRedDotKey_Reward**：`"MasterBaseBp_"..master_play_id`
- **CalcRedDotNumber**：`HaveRewardToClaim` **或** `HaveExtraRewardToClaim` 任一为真则 1

================================================================================
8. 完成条件
================================================================================

模块内 **未实现** `CheckComplete`；是否视为“活动结束”由 Master 活动与配表决定。业务上常用红点代替完成判定。

================================================================================
9. 开发注意事项
================================================================================

- `GetRewardState`：付费/Deluxe 轨会检查 `unlock_state` 是否足够，否则 `Locked`。
- `HaveExtraRewardToClaim`：满级后消耗溢出经验按 `extra_reward.score` 与 `chest_times` 计算。
- `YieldRewardShowComplete`：`action == "shop_buy_free"` 时按 `charge_basic` / `charge_deluxe` / `charge_upgrade` 播 `unlock_umg`。
- 合并奖励用 `MergeRewardTo`，避免重复道具多条展示。

================================================================================
10. 配表结构（MasterBaseBP.xls）
================================================================================

### Sheet: MasterSBPv1

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 每个id对应一个bp排期 |
| comment | string | - | 自己看的备注 |
| exp_type | string | - | 升级方式： / point-计算积分升级，需在下一列配point_id / coin-监控炮台开火消耗的金币数量，或每次开炮时根据公式获得经验 / sign-签到 |
| exp_type_param | string | - | 升级方式拓展参数 / exp_type=point时填用于升级的积分id / exp_type=coin 时填开始积攒经验的炮倍id，为空则不限制 / exp_type=sign 签到-累计/指定日期 |
| exp_type_formula | string | - | 升级经验计算公式 / exp_type=coin时，将根据此字段公式计算获得的经验； / 若此字段为空则直接按照金币计算经验 |
| is_weekly_reset | int | - | 0或为空-不重置 / 1-每周重置 |
| weekly | int | - | 每周几重置,1~7 |
| milestone_rewards | MilestoneReward | array | 等级奖励，引用 MilestoneReward 子表 |
| charge_basic | string | - | 基础版BP的Charge id / 奖励内容对应paid_rewards |
| charge_deluxe | string | - | 豪华版BP的Charge id / 奖励内容对应paid_rewards_deluxe / 为空代表没有豪华版 |
| charge_upgrade | string | - | 基础升豪华BP的charge_id / (如果为空则代表不支持基础升豪华) |
| rule | string | - | 规则 |
| reward_mail | string | - | 未领取奖励补发的邮件 |
| return_point | string | array | 大周期结束需要回收的抽奖币id；（如果有小周期（重置），则小周期结束不回收，直接补发） |
| point_mail | string | - | 多余积分回收的邮件;超出等级上限部分回收；付费回收 |
| unlock_umg | string | - | 解锁提示UMG |
| unlock_umg_class | string | - | 解锁提示UMG逻辑类 |
| reward_umg | string | - | 恭喜获得UMG |
| reward_umg_class | string | - | 恭喜获得UMG逻辑类 |
| charge_list_umg | string | - | 购买页UMG |
| charge_list_umg_class | string | - | 购买页UMG逻辑类 |
| extra_reward | ExtraRewardSetting | - | 溢出经验后的额外奖励，不配则没有，引用 ExtraRewardSetting 子表 |

### Sheet: MilestoneReward

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 积分奖励固定唯一id |
| score | int | - | 累计获得积分/累计消耗金币 / 这里数值没有膨胀10000倍操作，金币计数时需要注意配置乘10000的数值 |
| free_rewards | yield | array | 免费奖励，放大，免费膨胀 |
| paid_rewards | yield | array | 基础版付费奖励，放大，付费膨胀 |
| paid_rewards_deluxe | yield | array | 豪华版付费奖励，放大，付费膨胀,可以为空 |
| grand_level | int | - | 是否是大奖等级，1-是，0或不填-不是 |

### Sheet: ExtraRewardSetting

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | iD |
| comment | string | - | 自己看的备注 |
| score | int | - | 每溢出多少经验可领取一次奖励 |
| reward | yield | array | 奖励 |
| inflation_type | int | - | 奖池中金币的膨胀属性 / 不膨胀：0 / 付费膨胀：1 / 免费膨胀：2 |
| boost_available | int | - | 奖池中金币产出是否受charge_chip_bonus影响，1为是，不配则不受影响 |

### Sheet: Draft

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| 名称 | 点券 | - | 钻石 |
| yield | [{User:Conch: | - | [{User:Diamond: |
| Draft | 1 | - | 2 |
| 经验 | 100 | - | 100 |
| 奖励1 | 金币 | - | 锁定 |
| 数量1 | 100000 | - | 2 |
| 奖励2 | 静态头像 | - | 钻石 |
| 数量2 | 1 | - | 10 |
| 奖励3 | 动态头像 | - | - |
| 数量3 | 1 | - | - |
| 公式 | [{User:Chip: | - | [{item:3101: |
| 数量 | 100000 | - | 2 |
| 奖励2 | [{avatar:normal_110: | - | [{User:Diamond: |
| 公式汇总 | User:Chip:100000 | array > dict | [{item:3101:2}] |

================================================================================
                               文档结束
================================================================================

