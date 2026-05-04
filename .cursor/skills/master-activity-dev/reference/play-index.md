<!--
Master 玩法一级索引（L1 缓存）
AI 接到需求时第一步读此文件，快速筛选候选玩法，再读对应 play-xxx.md 获取详情。
最后更新: 2026-04-16
-->

# Master 玩法索引

## 速查表

| 枚举名 | class_type | 中文名 | 核心模式 | 能力标签 | 模块文件 |
|--------|-----------|--------|---------|---------|---------|
| Draw | MasterDraw | 抽奖 | 消耗积分/免费次数抽奖获取随机奖励 | 随机奖励, 积分消耗, 免费次数, 保底, 连抽 | master_play_draw_module |
| SpinDraw | MasterSpinDraw | 转盘抽奖 | 转盘形式的单次抽奖 | 随机奖励, 积分消耗, 转盘动画 | master_play_spin_draw_module |
| LiftingDraw | MasterLiftingDraw | 升降抽奖 | 多层级抽奖，每层不同奖池，可兑换累计奖励 | 随机奖励, 多层级, 兑换, 券消耗 | master_play_lifting_draw_module |
| CollectionDraw | MasterCollectionDraw | 收集抽奖 | 抽奖+收集文字/拼图，集齐触发里程碑 | 随机奖励, 收集, 里程碑, 重置, 跨天刷新 | master_play_collection_draw_module |
| CombineDraw | MasterCombineDraw | 组合抽奖 | 消耗门票进行组合式抽奖 | 随机奖励, 门票消耗, 掉落计数 | master_play_combine_draw_module |
| ThreeImageDraw | MasterThreeImageDraw | 三图抽奖 | 三张图排列组合匹配的抽奖 | 随机奖励, 图案匹配, 存储积分 | master_play_draw_three_module |
| Exchange | MasterExchange | 兑换 | 消耗积分兑换指定奖励，支持分组/批量/确认 | 积分消耗, 确定奖励, 分组, 批量, 抵扣 | master_play_exchange_module |
| PoolExchange | MasterPoolExchange | 池兑换 | 随机配方池兑换，可手动刷新 | 积分消耗, 随机配方, 刷新机制, 多槽位 | master_play_pool_exchange_module |
| Shops | MasterShops | 商店 | 对接 BusinessModule 商店页展示付费商品 | 付费购买, 商店页, 定时刷新, 免费商品 | master_play_shops_module |
| Forge | MasterForge | 锻造 | 消耗材料锻造/兑换物品 | 材料消耗, 确定产出, 数量参数 | master_play_forge_module |
| Transform | MasterTransform | 转化 | 将一种物品转化为另一种(神器/炮灵/武器等) | 物品转化, 多类型, 材料消耗, 每日限制 | master_play_transform_module |
| Task | MasterTask | 任务 | 每日/每周/每月任务，完成获取积分 | 周期任务, 积分奖励, 付费任务解锁 | master_play_task_module |
| Mission | MasterMission | 任务册 | 分组任务系统，多种解锁方式，进度+组+最终大奖 | 分组任务, 时间/顺序解锁, 进度奖励, 大奖 | master_play_mission_module |
| CycleTask | MasterCycleTask | 周期任务 | 按天循环的任务+分档进度奖励 | 每日循环, 任务+进度, 付费解锁 | master_play_cycle_task_module |
| SignIn | MasterSignIn | 签到 | 每日签到领取奖励，支持付费/VIP/补签 | 每日签到, 免费/付费, VIP倍率, 补签 | master_play_signin_module |
| FestivalSignIn | MasterFestivalSignIn | 节日签到 | 限时节日签到，充值补签，VIP补领 | 节日签到, 充值补签, VIP补领, 按天计算 | master_play_festival_signin_module |
| Milestone | MasterMilestone | 里程碑 | 积分达标领取分档奖励 | 积分里程碑, 分档奖励, VIP倍率, 可选奖励 | master_play_milestone_module |
| BoostMilestone | MasterBoostMilestone | 增益里程碑 | 基于 boost 加成的里程碑，奖励随装备动态变化 | boost加成, 动态金币, 里程碑, 重新申请 | master_play_boost_milestone_module |
| FreeReward | MasterFreeReward | 免费奖励 | 简单的免费领取奖励，可定时刷新 | 免费领取, 定时刷新, VIP倍率 | master_play_free_reward_module |
| Chest | MasterChest | 宝箱 | 每日任务获取钥匙→开宝箱抽奖，按周循环 | 每日任务, 钥匙收集, 宝箱抽奖, 周循环 | master_play_chest_module |
| WeeklyChest | MasterWeeklyChest | 周宝箱 | 按周任务+宝箱+海螺消耗系统 | 每周任务, 宝箱, 海螺消耗, 补签 | master_play_weekly_chest_module |
| ChestUpgrade | MasterChestUpgrade | 宝箱升级 | 开宝箱+升级链条，带积分转换 | 宝箱升级, 积分转换, 连续开箱 | master_play_chest_upgrade_module |
| SeasonBp | MasterSBPv1 | 赛季通行证 | 赛季制通行证，任务→等级→奖励+兑换 | 赛季通行证, 等级奖励, 任务, 兑换, 付费 | master_play_sbpv1_module |
| BaseBP | MasterBaseBP | 基础通行证 | 经验→等级→里程碑奖励，支持付费额外 | 通行证, 经验等级, 里程碑, 付费额外 | master_play_base_bp_module |
| SeasonRank | MasterSeasonRank | 赛季排行 | 赛季排行榜+结算奖励+历史记录 | 排行榜, 赛季结算, 历史赛季 | master_play_season_rank_module |
| RankPoint | MasterRankPoint | 排行积分 | 纯数据模块，为积分排行提供框架支撑 | 积分排行, 数据支撑 | master_play_rank_point_module |
| CardLevel | MasterCardLevel | 卡牌等级 | 多卡牌各自升级，积分驱动等级提升 | 卡牌升级, 积分驱动, 多卡牌并行 | master_play_card_level_module |
| BossChallenge | MasterBossChallenge | Boss挑战 | 分组任务挑战 Boss，全局进度+VIP加成 | Boss挑战, 分组任务, 全局进度, VIP金币 | master_play_boss_challenge_module |
| BossRush | MasterBossRush | Boss冲刺 | 多轮 Boss 匹配对战，逐轮推进 | Boss对战, 多轮匹配, 排名, 淘汰制 | master_play_boss_rush_module |
| Catch | MasterCatch | 捕获 | 积分+付费解锁的多包收集系统 | 收集, 付费解锁, 里程碑, 多包 | master_play_catch_module |
| Coin | MasterCoin | 金币活动 | 每日金币任务+翻倍奖励，按天循环 | 每日金币, 任务, 翻倍, 按天循环 | master_play_coin_module |
| CoinV2 | MasterCoinNewBie | 新手金币 | 面向新手的简化金币任务活动 | 新手, 金币任务, 有完成概念 | master_play_coin_newbie_module |
| PiggyBank | MasterPiggy | 存钱罐 | 付费购买存钱罐，捕鱼累积金币后破罐 | 存钱罐, 付费购买, 累积金币 | master_play_piggy_bank_module |
| Bank | MasterBank | 银行 | 定时累积奖励+大奖领取，含免费/付费档 | 累积奖励, 定时, 大奖, 免费/付费 | master_play_bank_module |
| ChargeReward | MasterChargeReward | 充值奖励 | 充值金额达标领取分档奖励 | 充值奖励, 分档领取, 进度追踪 | master_play_charge_reward_module |
| Search | MasterSearch | 搜寻 | 在界面上找隐藏物品+进度奖励 | 搜寻/找茬, 进度奖励, 每日限次 | master_play_search_module |
| FishDrop | MasterFishDrop | 鱼掉落 | 捕鱼时额外掉落特定道具(被动) | 捕鱼掉落, 被动收集, 无红点 | master_play_fish_drop_module |
| Paint | MasterPaint | 壁画 | 消耗积分绘画，分阶段完成，最终大奖 | 阶段绘画, 积分消耗, 大奖 | master_play_dh_paint_module |
| MineTreasure | MasterMineTreasure | 挖宝 | 地图翻格子挖宝，分阶段推进 | 翻格挖宝, 阶段推进, 大奖 | master_play_mine_treasure_module |
| MasterSaga | MasterSaga | Saga冒险 | 多关卡任务+捕鱼积分，渔场内实时追踪 | 多关卡, 捕鱼任务, 渔场内, 实时Toast | master_play_saga |
| AlbumCard | MasterAlbumCard | 集卡 | 收集卡牌填充相册，万能卡兑换 | 集卡, 相册, 万能卡, 循环 | master_play_album_card_module |
| Quiz | MasterQuiz | 答题 | 答题玩法 | 答题, 知识问答 | master_play_quiz_module |
| AdvPopup | MasterAdvPopup | 广告弹窗 | 广告触发后标记完成(极简) | 广告, 完成标记, 无红点, 无协议 | master_play_adv_popup_module |
| CyclePack | MasterCyclePack | 周期礼包 | 周期触发限时礼包+里程碑进度奖励 | 限时礼包, 周期触发, 里程碑, 付费 | master_play_cycle_pack_module |
| Unlock | MasterUnlock | 解锁 | 渐进式解锁任务，服务端推送进度 | 渐进解锁, 服务端推送, 任务完成 | master_play_unlock_module |
| UnlockPack | MasterUnlockPack | 解锁礼包 | 付费解锁+抽奖+自选的礼包流程 | 付费解锁, 抽奖, 自选, 流程驱动 | master_play_unlock_pack_module |

## 按需求场景反向索引

### 需要「随机奖励/抽奖」
- **Draw** — 标准抽奖，保底+免费+连抽，最通用
- **SpinDraw** — 转盘 UI 形态，单次抽奖
- **LiftingDraw** — 多层级递进，每层不同奖池
- **CollectionDraw** — 抽奖+收集集齐触发额外奖励
- **CombineDraw** — 门票消耗的组合式抽奖
- **ThreeImageDraw** — 三图匹配的趣味抽奖

### 需要「积分/材料兑换」
- **Exchange** — 标准兑换，分组+批量，最通用
- **PoolExchange** — 随机配方池，可刷新
- **Forge** — 材料→物品，支持数量
- **Transform** — 物品间转化(神器/炮灵/武器)

### 需要「每日/周期任务」
- **Task** — 日/周/月任务，积分奖励
- **Mission** — 分组任务册，多解锁方式+大奖，最复杂
- **CycleTask** — 按天循环任务+进度
- **BossChallenge** — 分组任务，Boss 主题
- **Coin** / **CoinV2** — 金币专项每日任务

### 需要「签到/登录奖励」
- **SignIn** — 标准签到，VIP+付费+补签
- **FestivalSignIn** — 节日限时签到，充值补签+VIP补领

### 需要「里程碑/进度奖励」
- **Milestone** — 积分里程碑，VIP 倍率，最通用
- **BoostMilestone** — 动态金币里程碑(随装备 boost 变化)
- **BaseBP** — 经验→等级→里程碑形式

### 需要「通行证/赛季」
- **SeasonBp** — 完整赛季通行证(任务+等级+兑换)
- **BaseBP** — 简化通行证(经验→等级→奖励)

### 需要「排行榜/竞技」
- **SeasonRank** — 赛季排行+结算奖励
- **RankPoint** — 积分排行数据支撑
- **BossRush** — 多轮 Boss 对战排名

### 需要「付费/充值相关」
- **ChargeReward** — 充值达标领奖
- **Shops** — 商店付费商品
- **CyclePack** — 周期限时礼包+里程碑
- **PiggyBank** — 存钱罐付费购买
- **Bank** — 累积奖励+付费档
- **Catch** — 积分+付费多包解锁
- **UnlockPack** — 付费解锁+抽奖流程

### 需要「宝箱/开箱」
- **Chest** — 任务→钥匙→开箱，按周循环
- **WeeklyChest** — 按周任务+宝箱
- **ChestUpgrade** — 开箱+升级链条

### 需要「收集/图鉴」
- **AlbumCard** — 集卡填相册+万能卡
- **CollectionDraw** — 抽奖收集拼图/文字
- **Catch** — 多包收集

### 需要「免费/简单领取」
- **FreeReward** — 免费领取，可定时刷新
- **AdvPopup** — 广告触发完成

### 需要「渔场内/捕鱼联动」
- **FishDrop** — 捕鱼掉落道具(被动)
- **MasterSaga** — 渔场内多关卡任务+实时追踪

### 需要「小游戏/互动玩法」
- **Search** — 找隐藏物品
- **Paint** — 绘画/壁画
- **MineTreasure** — 翻格挖宝
- **Quiz** — 答题
- **MasterSaga** — 多关卡冒险

### 需要「卡牌/升级」
- **CardLevel** — 多卡牌升级
- **AlbumCard** — 集卡相册

### 需要「解锁/渐进」
- **Unlock** — 服务端推送的渐进解锁
- **UnlockPack** — 付费驱动的解锁流程

## 相似玩法对比速查

| 对比组 | 区别 |
|-------|------|
| Draw vs SpinDraw | Draw 支持连抽/免费/保底完整体系；SpinDraw 是单次转盘，更简单 |
| Draw vs LiftingDraw | LiftingDraw 多层级递进，每层独立奖池和兑换；Draw 是单奖池 |
| Draw vs CollectionDraw | CollectionDraw 额外有收集+里程碑机制，抽奖同时收集碎片 |
| Draw vs CombineDraw | CombineDraw 用门票而非积分，有掉落计数器 |
| Draw vs ThreeImageDraw | ThreeImageDraw 三图排列匹配，有存储积分，更偏趣味 |
| Exchange vs PoolExchange | PoolExchange 配方随机+可刷新；Exchange 配方固定 |
| Exchange vs Forge | Forge 更简单(单配方+数量)，无分组/批量/抵扣 |
| Exchange vs Transform | Transform 限特定物品类型间转化，有每日显示限制 |
| Task vs Mission | Mission 更复杂：分组+多种解锁+组奖励+大奖；Task 是简单日/周/月 |
| Task vs CycleTask | CycleTask 按天循环+进度奖励，有付费解锁；Task 有日/周/月分类 |
| SignIn vs FestivalSignIn | FestivalSignIn 有充值补签+VIP补领+按天索引；SignIn 用 add/replace 模式 |
| Milestone vs BoostMilestone | BoostMilestone 金额随 boost/装备动态变化，可重新申请；Milestone 固定 |
| Milestone vs BaseBP | BaseBP 有经验→等级的换算层；Milestone 直接按积分分档 |
| SeasonBp vs BaseBP | SeasonBp 完整赛季(任务+等级+兑换+继承)；BaseBP 简化版(经验→等级→奖励) |
| Chest vs WeeklyChest | WeeklyChest 有海螺消耗和补签；Chest 用钥匙+按周7天 |
| Chest vs ChestUpgrade | ChestUpgrade 有升级链条和积分转换，更偏小游戏 |
| Coin vs CoinV2 | CoinV2 面向新手，有完成概念，数据结构更简单 |
| BossChallenge vs BossRush | BossChallenge 是分组任务+VIP 加成；BossRush 是多轮匹配对战+排名 |
| Unlock vs UnlockPack | Unlock 是纯任务解锁(服务端推送)；UnlockPack 是付费+抽奖+自选的购买流程 |
| FreeReward vs AdvPopup | FreeReward 有定时刷新+VIP 倍率；AdvPopup 极简只标记完成 |

## 模块继承关系

```
MasterPlayModuleBase
├── MasterPlayDrawModule
├── MasterPlaySpinDrawModule
├── MasterPlayLiftingDrawModule
├── MasterPlayCollectionDrawModule
├── MasterPlayCombineDrawModule
├── MasterPlayThreeImageDrawModule
├── MasterPlayExchangeModule
├── MasterPlayPoolExchangeModule
├── MasterPlayShopsModule
├── MasterPlayForgeModule
├── MasterPlayTransformModule
├── MasterPlayTaskModule
├── MasterPlayMissionModule
├── MasterPlayCycleTaskModule
├── MasterPlaySignInModule
├── MasterPlaySignInModuleBase
│   └── MasterPlayFestivalSignInModule
├── MasterPlayMilestoneModule
├── MasterPlayBoostMilestoneModule
├── MasterPlayFreeRewardModule
├── MasterPlayChestModule
├── MasterPlayWeeklyChestModule
├── MasterPlayChestUpgradeModule
├── MasterPlaySBPv1Module
├── MasterPlayBaseBPModule
├── MasterPlaySeasonRankModule
├── MasterPlayRankPointModule
├── MasterPlayCardLevelModule
├── MasterPlayBossChallengeModule
├── MasterPlayBossRushModule
├── MasterPlayCatchModule
├── MasterPlayCoinModule
├── MasterPlayCoinNewBieModule
├── MasterPlayPiggyModule
├── MasterPlayBankModule
├── MasterPlayChargeRewardModule
├── MasterPlaySearchModule
├── MasterPlayFishDropModule
├── MasterPlayPaintModule
├── MasterPlayMineTreasureModule
├── MasterPlaySagaModule
├── MasterPlayAlbumCardModule
├── MasterPlayQuizModule
├── MasterPlayAdvPopupModule
├── MasterPlayCyclePackModule
├── MasterPlayUnlockModule
├── MasterPlayUnlockPackModule
├── MasterPlayMatchModule (辅助，不在枚举中)
└── MasterPlayRankingModule (辅助，不在枚举中)
```

## 无独立模块的特殊说明

- **FestivalSignIn** 继承 `MasterPlaySignInModuleBase`（非直接继承 `MasterPlayModuleBase`），位于 `master_play_signin_modules/` 子目录
- **UnlockPack** 模块文件在 `module_impl/` 目录下（非 `master_play_module/` 子目录）
- **MasterSaga** 模块文件名为 `master_play_saga.lua`（无 `_module` 后缀）
- **RankPoint** 极简模块，仅有 Constructor + Init，无任何业务逻辑
- **AdvPopup** 极简模块，无协议/无红点，仅标记完成
