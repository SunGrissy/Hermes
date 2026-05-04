<!--
参考代码文件:
- lua/framework/components/game_module/module_impl/master_play_module/master_play_album_card_module.lua
最后参考时间: 2026-04-16
-->
================================================================================
                        集卡（MasterAlbumCard）玩法说明
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

- **核心诉求**：收集卡牌填充相册，支持万能卡兑换、相册阶段奖励与循环进度。
- **典型活动**：集卡、图鉴、赛季卡牌收集。
- **标签**：集卡、相册、万能卡、循环、进度奖励。
- **选型提示**：需要「多相册多卡牌 + 兑换 + 书本大奖 + 新卡事件」时使用；完成判定常与活动结束绑定。

================================================================================
2. 玩法概述
================================================================================

玩家在卡包或途径中获得卡牌，更新各 `album_id` 的获得列表与奖励状态；万能卡在条件满足时可兑换缺失卡。模块监听积分与新卡事件，派发兑换、进度领奖、相册领奖及积分刷新。

**流程摘要**：获得新卡 → `AddCard` / 推送更新 `albums_status` → 可领进度奖 `MasterAlbumCardProgressReward` → 集齐相册领书本 `MasterAlbumCardBookReward` → 缺卡时用 `MasterAlbumCardWildExchange`。

**循环**：`cycle` 字段驱动多轮集齐奖励，与策划表「赛季轮次」一致。

================================================================================
3. 玩法类型定义
================================================================================

- **枚举**：`MasterPlayType.AlbumCard = "MasterAlbumCard"`。
- **模块类**：`MasterPlayAlbumCardModule`，继承 `MasterPlayModuleBase`。

================================================================================
4. 核心模块说明
================================================================================

- **关键方法**：`ExchangeWildCard`、`GetWildCardCount`、`IsOwnCard`、`HaveProgressReward`、`GetCardIdsWithAlbumId`、`HasAlbumReward`、`CheckAlbumCollectPlan`、`AddCard`、`IsCollectedAll`、`IsWildCardShopUnlock`、`TryPopupWildCardShop`。
- **事件监听**：`MasterPointChanged`、`MasterAlbumNewCard`。
- **事件派发**：`MasterUseWildCard`、`MasterCardReceivedProgressReward`、`MasterReceiveCardBookReward`、`MasterAlbumNewCard`、`PointChanged`。

================================================================================
5. 数据结构
================================================================================

- **展示**：`showing_book_reward` 等 UI 辅助字段。
- **info**：`albums_status[album_id]` → `obtain_cards`、`rewards_status`、`cycle`、`progress_rewards`、`unlock_shop` 等。
- **conf**：`all_albums`、`all_cards`、`wildcard_id`。

================================================================================
6. 协议与接口
================================================================================

| 请求 | 回调 |
|------|------|
| `MasterAlbumCardWildExchange` | `OnExchangeWildCard` |
| `MasterAlbumCardProgressReward` | `OnGetProgressReward` |
| `MasterAlbumCardBookReward` | `OnGetCardBookReward` |

================================================================================
7. 红点系统
================================================================================

- **万能卡/兑换相关**：`GetWildCardRedDotKey` → `"master_album_wildcard_" .. mpid`。
- **进度奖励**：`GetRedDotKey_Reward` → `"master_album_card_reward_" .. mpid`。
- 相册集齐与书本可领可能分属不同红点策略，若新增「书本可领」独立键需在模块内扩展并与 UI 注册一致。

================================================================================
8. 完成条件
================================================================================

- 仅在 **活动已结束**（`end_time <= now`）时视为玩法层面「可完成/已完成」语义（`CheckComplete` 返回 true）；进行中的集卡活动通常不提前 Complete。

================================================================================
9. 开发注意事项
================================================================================

- 与「进行中即可完成」类玩法不同，策划文案与入口隐藏逻辑勿假设中途 Complete。
- 新卡 `MasterAlbumNewCard` 与弹窗队列交互频繁，接入 UIQueue 时遵守项目弹窗顺序规则。
- `AddCard` 与 `IsOwnCard` 需防重复与并发推送导致列表闪烁。
- `unlock_shop` 与 `TryPopupWildCardShop` 触发条件变更时，注意避免进主界面连环弹窗。
- `cycle` 与多轮进度奖励展示需对齐服务端轮次，避免客户端显示下一轮而服务端仍为上一轮。
- 卡牌立绘异步加载完成须 `ResetShow` 类全量刷新（与项目 Yield/UI 规范一致），避免只换图不换框。
- 万能卡兑换前二次确认目标卡牌，防止误兑稀有卡。
- 相册奖励批量领取时注意弹窗队列，避免与恭喜获得叠层。
- 图鉴分享/截图功能若读取 `obtain_cards`，注意脱敏玩家 ID。
- 合服或回档后卡牌状态以服务端为准，禁止客户端强行 merge 本地缓存。

================================================================================
10. 配表结构（MasterAlbumCard.xls）
================================================================================

### Sheet: MasterAlbumCard

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 活动id |
| comment | string | - | 备注 |
| album_id | Album | array | 包含卡册，引用 Album 子表 |
| draw_id | string | - | 抽奖卡池[MasterDraw] |
| recycle_draw_id | string | - | 回收卡池[MasterDraw] |
| wildcard_id | string | - | 万能卡[point] |
| shop_id | string | - | 万能卡商店[shop] |
| popup_cd | duration | - | 万能卡强弹CD |
| album_reward_first | Reward | array | 收集进度奖-首次，引用 Reward 子表 |
| album_reward_cycle | Reward | array | 收集进度奖-循环，引用 Reward 子表 |
| round_chip_bonus | float | - | 每轮金币膨胀系数 |
| bonus_max_round | int | - | 膨胀的轮数上限 |
| point_mail_id | string | - | 积分回收邮件 |
| reward_mail_id | string | - | 奖励补发邮件 |
| get_way | string | array | 获取途径，填写GetWaySetting的id |
| rule | string | - | 规则描述 |
| umg | string | - | 主页umg，未使用 |

### Sheet: Album

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 卡册ID |
| comment | string | - | 注释 |
| entry_pic | string | - | 入口资源图 |
| book_name | string | - | 卡册名称i18N |
| collect_reward | yield | array | 集齐奖励（是否含增益） |
| card_id | Card | array | 包含卡片id，引用 Card 子表 |

### Sheet: Card

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 卡片ID |
| comment | string | - | 注释 |
| card_pic | string | - | 卡面资源图标 |
| star_quality | int | - | 卡片边框 |
| card_name | string | - | 卡牌名称i18N |
| recycle | yield | array | 重复回收奖励 |
| reward_icon | string | - | 抽卡界面展示图标 |

### Sheet: Reward

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一ID |
| comment | string | - | 注释 |
| card_num | int | - | 收集卡牌数量 |
| reward | yield | array | 奖励 |
| shop_unlock | int | - | 领取后解锁万能卡商店 |
