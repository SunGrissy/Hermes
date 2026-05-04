<!--
参考代码文件:
- lua/framework/components/game_module/module_impl/master_play_module/master_play_exchange_module.lua
最后参考时间: 2026-04-16
-->
================================================================================
                        MasterExchange 玩法开发规范（客户端）
================================================================================
版本: 2026-01-20
适用范围: Master 系统下 class_type = "MasterExchange" 的玩法

目录
----
1. 概述
2. 关键数据结构与配置字段
3. 逻辑模块 (MasterPlayExchangeModule)
4. 红点规则
5. 提醒(formula_tips)与批量操作
6. 完成判定
7. 通用 UI 模板 (MasterPlayExchangeMain + Item)
8. 专用商店模板 (Spirit/Artifact/Humanoid)
9. 事件与交互流程
10. 开发步骤清单
11. 常见注意点

================================================================================
1. 概述
--------------------------------------------------------------------------------
MasterExchange 负责“积分兑换”类玩法，支持单列表配置和分组配置(如神器/炮灵商店)。
玩法特点：
- 统一使用 exchange_point 消耗积分完成兑换。
- 支持二次确认、批量兑换、红点提醒、倒计时提醒。
- 支持“新物品”提醒、配方提醒开关、动态注册确认/批量 Dialog。

核心文件：
- 逻辑：lua/framework/components/game_module/module_impl/master_play_module/master_play_exchange_module.lua
- 通用 UI：lua/product/components/ui_item/master/common/master_play_exchange_main.lua
- 通用 Item：lua/product/components/ui_item/master/common/master_play_exchange_item.lua
- 分组商店：lua/product/components/ui_item/master/level_equip_exchange/ 目录下的 spirit/artifact…*

================================================================================
2. 关键数据结构与配置字段
--------------------------------------------------------------------------------
2.1 基础配置 (master_play_info.conf) —— 来自 MasterExchange.xls/Main
- id                        配方组ID（玩法ID后缀）
- type                      exchange 类型：artifact / cannon / spirit
- group[]                   分组兑换（数组，引用 Group 表）
- exchanges[]               非分组的配方列表（引用 Formula 表，按顺序）
- exchange_point            消耗积分ID（Point）
- deduct_point[]            可用于抵扣的积分ID列表（按 index 优先级：越小优先级越高）
- deduct_rate[]             抵扣比例：deduct_point[i] 需要多少个可抵扣 1 个 exchange_point（与 deduct_point 一一对应）
- deduct_first_only         是否仅列表第一个兑换项可使用抵扣（0/1）
- point_mail                积分不足邮件（可选）
- fish_drop[]               掉落ID列表（历史字段，新策不建议再用）
- drop_show                 掉落展示策略：day / all
- main_umg / main_umg_class 主界面资源/脚本
- confirm_umg               二次确认 UMG 资源名
- batch_exchange_umg        批量兑换 UMG 资源名
- entry_umg                 入口 UMG（需要时配置）
- packages[]                临时包ID
- have_new_red_dot          是否启用“新”红点（1 开启）
- have_time_remind_dot      是否启用倒计时提醒红点（1 开启）
- inflation_type            价格膨胀类型：0 默认；1 折扣；2 其他扩展
- is_complete               1 表示需全部配方兑空才算完成

2.2 Group 表（分组兑换）
- id / comment              唯一ID、备注
- unlock_time               组解锁时间（int，时间戳，由后端处理）
                            为空或 0 表示不限制；非空时，只有当前服务器时间 >= unlock_time 该组才解锁可兑换
- item_id                   关联的神器/炮灵/武器ID（用于满级、展示）
- background_bp             背景 BP
- image                     Tab 图
- exchanges[]               本组配方列表（引用 Formula）
- umg                       Tab 对应的 UMG（可自定义）

2.3 Formula 表（兑换配方）
- id / comment              唯一ID、备注
- input                     积分A消耗
- discounts                 原价或折扣展示用数值
- output[]                  奖励列表（yield，支持 break_through_inflate）
- limit                     兑换上限，-1 表示不限
- limit_reg                 限制等级（神器/炮灵等）；0 不限制
- is_reminder               默认提醒（1 开启）
- ui_background             UI 背景/边框
- exchange_umg              配方自定义 UMG
- panel_size                大中小卡片：0/1/2
- is_full_level             满级提示策略（>0 需要额外确认/提示）
- banner_icon               顶部横幅
- limit_type/param1/param2  复杂限制的类型与参数（自定义，需前后端协同）

2.2 运行时数据 (master_play_info.info)
- formula_times[formula_id] 已兑换次数
- formula_tips[formula_id]  配方提醒开关（0/1）
- daily_limit[formula_id]   每日兑换上限（来自 msg.res.daily_limit，服务器回包写入 info.daily_limit）
- temp_formula_tips         UI 临时态，关闭界面时提交

2.3 枚举
- MasterExchangeType: spirit / artifact / humanoid
- MasterExchangeStatus: Lockd(-2) / Exhausted(-1) / Exchangeable(0) / Insufficient(1)

================================================================================
3. 逻辑模块 (MasterPlayExchangeModule)
--------------------------------------------------------------------------------
- Init：注册 MasterExchange / MasterChangeFormulaTips 协议推送。
- 请求：
    RequestExchangeSingle(master_play_id, formula_id, use_deduct_point)  -- use_deduct_point 可选，表示是否使用抵扣积分
    RequestExchangeMultiple(master_play_id, formula_id_dict)
    RequestChangeFormulaTips(master_play_id, formula_tips) -- 只提交与默认值不同的项
- 推送处理：
    OnMasterExchange(msg):
        * 更新 formula_times
        * 同步积分 MasterPointModule.SyncMasterPointCount
        * 重算红点 CalcRedDotNumber
        * 派发 GameEventType.MasterExchangeReceived
        * 若 CheckComplete 通过，派发 MasterPlayComplete + MasterTestCloseMainUI
    OnMasterChangeFormulaTips(msg): 更新 info.formula_tips
- OnMasterPlayInfoRefresh:
    * InitRedDot，校验 conf.fish_drop 不再支持
    * 读取父活动 popup_params.click_btn_audio 作为点击音效
    * 若配置 confirm_umg / batch_exchange_umg，动态注册对应 Dialog
- GetAllExchangeFormulas(master_play_id): 汇总 conf.exchanges 或 conf.group.*.exchanges，调用此方法避免只读 exchanges。
- CheckComplete(master_play_id): conf.is_complete == 1 且所有配方状态为 Exhausted 才算完成。
- GetFormulaExchangeStatus(play_id, formula): 返回 MasterExchangeStatus 及缺少积分数。
- IsFomulaLimited: 校验限制条件（artifact/humanoid/spirit 最高级、master_point、依赖配方库存等）；还包含 fomula_stock 的 limit_type 检查（如 limit_type == "master_point" 时使用 limit_param1/limit_param2）。
- IsGroupUnlocked(group): 判断兑换组是否已解锁（基于 unlock_time 时间戳）。
- ExtraCheckRedDot: 神器/炮灵在满级时不触发红点；会使用 formula.daily_limit 判断每日兑换上限。

其他常用接口：
- GetFormulaRemain(master_play_id, formula_id)            -- 剩余兑换次数
- CalcFormulaDiscountUsage(master_play_id, formula_id)   -- 计算抵扣积分使用情况
- IsNeedExchangeConfirm(master_play_id)                  -- 是否需要二次确认
- IsCanBatchExchange(master_play_id)                    -- 是否支持批量兑换
- GetExchangeConfirmDialogName(master_play_id)          -- 确认弹窗名
- GetBatchExchangeDialogName(master_play_id)            -- 批量兑换弹窗名
- GetFormulaInfoByFormulaId(master_play_id, formula_id) -- 按 formula_id 获取配方
- MasterPlayExchangeModule.GetOwnedInfo(equipId, exchangeType) -- 静态方法，获取装备拥有信息

================================================================================
4. 红点规则
--------------------------------------------------------------------------------
- GetRedDotKey(master_play_id) = TimeRemindRedDot | ExchangeRedDot
- Exchange 红点由 Lidx 方案维护：
    InitRedDot_Lidx -> key: Master_Play_Exchange_{master_play_id}
    CalcRedDotNumber_Lidx: 只要有“提醒=1 且积分足够 且未达 limit 且未受限制”的配方即亮红点。
- “新”红点：
    have_new_red_dot==1 时创建 key: Master_Ex_New_Rd_{master_play_id}，数量取配方总数。仅在 conf.group 存在时创建，仅有 conf.exchanges 而无 group 时不会创建。
- 倒计时提醒红点：
    have_time_remind_dot==1 且父活动配置 countdown>0 且当前时间+countdown>结束时间 时创建，
    key: MP_Exc_Time_Remind_{master_play_id}，积分>1 时点亮。
- 入口/Tab 可拼接活动红点：MasterData:GetRedDotKey() 会合并。

================================================================================
5. 提醒(formula_tips)与批量操作
--------------------------------------------------------------------------------
- formula_tips 含义：1=关注/提醒，0=不提醒；决定红点与“提醒”复选框状态。
- UI 使用 temp_formula_tips 保存会话内修改，关闭界面时调用 RequestChangeFormulaTips 提交差异。
- SetFormulaTips API：MasterPlayExchangeModule:SetFormulaTips(master_play_id, formula_id, status) 仅写入本地 info。依赖 info.formula_tips 已初始化，若该字段不存在会报错。
- 批量兑换：配置 batch_exchange_umg 后，主界面显示“BatchExchangeBtn”并打开批量 Dialog 名称：
    DialogMasterPlayBatchExchange_{master_play_id}_Controller
- 二次确认 Dialog 名称：
    DialogMasterPlayExchangeConfirm_{master_play_id}_Controller

================================================================================
6. 完成判定
--------------------------------------------------------------------------------
- 只有 conf.is_complete == 1 的玩法会检查完成。
- 所有配方 GetFormulaExchangeStatus == Exhausted 才算完成。
- 完成后 MasterPlayExchangeModule 会派发 GameEventType.MasterPlayComplete，并尝试关闭主 UI。

================================================================================
7. 通用 UI 模板 (master_play_exchange_main.lua)
--------------------------------------------------------------------------------
- 入口参数：parent(UIWidget/MasterHud)、master_play_id
- 功能：
    * 显示积分、积分图标；MoreBtn 可跳转同活动的 MasterPlayType.Shops。
    * 根据 panel_size 创建不同大小的 MasterPlayExchangeItem。
    * ReminderCbx 顶层全选/全不选，逐项回写 formula_tips 并立刻重算红点。
    * BatchExchangeBtn 受 IsCanBatchExchange 判定。
    * OnRemoved 时调用 TryCommitFormulaTips 提交与默认 is_reminder 不同的项。
- MasterPlayExchangeItem：
    * 展示产出、限制、剩余次数、提醒勾选、红点。
    * ExchangeBtn：积分不足提示；需要确认则弹确认框，否则直接 RequestExchangeSingle。
    * 红点显隐：Reminder 勾选且积分足够且未售罄时显示。

================================================================================
8. 专用商店模板 (level_equip_exchange/*)
--------------------------------------------------------------------------------
SpiritExchangeShopMain / ArtifactExchangeShopMain / (Humanoid 同理)
- 适用于 conf.group 多分组配方：
    * 左侧 Tab/列表按拥有度与售罄排序(未满级>售罄/满级)。
    * 右侧 SpiritExchangeShopGroupItem / ArtifactExchangeShopGroupItem 展示具体档位，支持折扣、满级提示。
    * 复选框批量开关提醒：跳过已达上限或已满级的配方，实时刷新红点。
    * ExchangeBtn：满级时用不同提示文案；其余弹确认框。
    * 使用 master_play_info.temp_formula_tips 驱动勾选状态。
- 事件：MasterExchangeNotifyStateChanged 用于刷新列表勾选；ItemDataChangeReceiveEvent 触发刷新。

================================================================================
9. 事件与交互流程
--------------------------------------------------------------------------------
- MasterPointChanged(point_id, remain): 刷新积分与红点。
- MasterExchangeReceived(master_play_id, record): 更新剩余次数、红点、UI。
- MasterExchangeItemClicked / MasterExchangeBatchCostChanged 等：业务端可选事件。
- 登录/跨天：MasterPlayModuleBase 会在 Refresh 时调用 OnMasterPlayInfoRefresh，自动初始化红点与 Dialog 注册。

================================================================================
10. 开发步骤清单
--------------------------------------------------------------------------------
1) 配置：
   - master_play.conf.exchange_point / exchanges 或 group.exchanges，视需求配置 panel_size、banner_icon、is_reminder、limit 等。
   - 需要完成判定则设置 conf.is_complete=1；需“新”红点/倒计时红点则设置 have_new_red_dot / have_time_remind_dot。
   - 需要确认框/批量框配置 confirm_umg / batch_exchange_umg。
2) 逻辑：
   - 确保模块已注册（框架已默认注册 MasterPlayExchangeModule）。
   - 若有额外限制，在 IsFomulaLimited/ExtraCheckRedDot 之外新增判断。
3) UI：
   - 简单兑换用 MasterPlayExchangeMain + MasterPlayExchangeItem。
   - 分组/多档位兑换用 Spirit/Artifact/Humanoid 继承的商店模板，自定义 UMG 名称即可。
   - 绑定红点：入口使用 MasterPlayExchangeModule:GetRedDotKey(master_play_id)；分组项可用自定义 key "Master_Ex_Rd_{play_id}_{formula_id}"。
4) 交互：
   - 勾选提醒修改 temp_formula_tips；界面关闭前会自动提交差异。
   - 需要一键刷新红点时调用 CalcRedDotNumber_Lidx(master_play_id)。

================================================================================
11. 常见注意点
--------------------------------------------------------------------------------
- 不再支持在 Exchange 配置 fish_drop；若存在将打印错误。
- 读取配方请使用 GetAllExchangeFormulas，不要只遍历 conf.exchanges。
- CheckComplete 仅在 conf.is_complete==1 时生效；limit=-1 的配方永远不会“耗尽”，慎用。
- ExtraCheckRedDot 会在神器/炮灵满级时抑制红点；如需强制提示需自定义。
- temp_formula_tips 仅在 UI 会话内有效，退出前必须 RequestChangeFormulaTips 才会持久。
- 红点 key 是按玩法实例生成，活动入口红点由 MasterData 聚合；不要复用全局常量。
- 二次确认/批量 Dialog 名称依赖 master_play_id，动态注册后方可 ShowDialog。

补充：兑换组解锁时间（unlock_time）
--------------------------------------------------------------------------------
- Group 表新增 unlock_time 字段，用于控制兑换组的解锁时间。
- 格式：int（时间戳），由后端处理；为空或 0 表示不限制，组始终解锁。
- 判断逻辑：当前服务器时间 >= unlock_time 时，该组解锁可兑换；否则组内配方不可兑换。

代码实现（MasterPlayExchangeModule）：
- IsGroupUnlocked(group): 判断组是否已解锁
    * 参数：group 为 Group 配置表项
    * 返回：boolean，true=已解锁，false=未解锁
    * 逻辑：unlock_time 为空/0/nil 返回 true；否则比较 LoginModule.Instance:GetServerTime() >= unlock_time
- CalcRedDotNumber_Lidx: 遍历 group 时调用 IsGroupUnlocked，未解锁组不触发红点
- CalcNewItemRedDot: 遍历 group 时调用 IsGroupUnlocked，只统计已解锁组的配方数量

UI 层建议：
    * 调用 MasterPlayExchangeModule.Instance:IsGroupUnlocked(group) 判断组状态
    * 未解锁的组可显示倒计时或锁定状态
    * 未解锁组内的配方应禁用兑换按钮，可提示"即将开放"或显示解锁时间

红点规则：未解锁的组内配方不触发红点（CalcRedDotNumber_Lidx 和 CalcNewItemRedDot 均已过滤）。

注意：unlock_time 是组级别的解锁，与单个配方的 limit_type 限制相互独立。

补充：抵扣积分的实际消耗口径（deduct_*）
- 当选择“使用抵扣积分”时，客户端应按 `deduct_point` 的优先级（index 从小到大）依次尝试抵扣兑换积分。
- 兑换积分的抵扣量按 `floor(deduct_point_count / deduct_rate)` 计算，可抵扣的兑换积分上限为 `max(0, discounts - input)`（原价-折扣价）。
- 抵扣积分用尽后，不足部分由 `exchange_point` 补足；也可能完全由抵扣积分覆盖（此时兑换积分消耗为 0）。

================================================================================

12. 配表结构（MasterExchange.xls）

### Sheet: Main

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 玩法id |
| comment | string | - | 自己看的备注 |
| type | string | - | 兑换的类型，artifact、cannon、spirit |
| group | Group | array | 兑换的分组，引用 Group 子表 |
| exchanges | Formula | array | 可兑换的物品，list顺序，引用 Formula 子表 |
| exchange_point | string | - | 积分id / #R:Point |
| deduct_point | string | array | 可以用来抵扣的积分 |
| deduct_rate | int | array | 多少个deduct_point可以抵扣一个exchange_point |
| deduct_first_only | int | - | 是否仅能抵扣列表里的第一个礼包，填0或者1 |
| overdue_auto_exchange | int | - | 过期是否自动兑换礼包 |
| point_mail | string | - | 积分回收邮件 |
| fish_drop | string | array | 此字段需留空，已弃用，掉落改为masterfishdrop编辑 |
| drop_show | string | - | 掉落限制的显示,day表示每天，all表示总数 |
| main_umg | string | - | 主页umg |
| main_umg_class | string | - | umg逻辑 |
| confirm_umg | string | - | 兑换确认框资源 |
| batch_exchange_umg | string | - | 批量兑换主UMG资源，配置则代表该活动有批量兑换功能，没配则没有 |
| entry_umg | string | - | 兑换入口的UMG，不配则不需要 |
| packages | string | array | 限时礼包的id |
| have_new_red_dot | int | - | 是否有“新”红点 |
| have_time_remind_dot | int | - | 兑换是否有过期提示的红点 |
| inflation_type | int | - | 奖励中金币的膨胀属性 / 不膨胀：0 / 付费膨胀：1 / 免费膨胀：2 |
| charge_chip_bonus | int | - | 奖励中金币是否受充值金币增益影响 / 0 = 不影响 / 1 = 享受充值金币增益 |
| is_complete | int | - | 全部兑换后活动 |

### Sheet: Group

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一id |
| comment | string | - | 自己看的备注 |
| unlock_time | time | - | 解锁时间，为空不限制 |
| item_id | string | - | 对应物品的id |
| background_bp | string | - | 场景 |
| image | string | - | 对应的tab页图 |
| exchanges | Formula | array | 可兑换的物品，list顺序，引用 Formula 子表 |
| umg | string | - | tab对应的umg |

### Sheet: Formula

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | - |
| comment | string | - | 备注 |
| input | int | - | 兑换需要的积分数量 |
| discounts | int | - | 兑换原价显示 |
| output | yield | array | 兑换的产出内容 |
| limit | int | - | 兑换次数，-1表示无限次数 |
| daily_limit | int | - | 0代表不限制 / >0代表每日刷新的限制数量 |
| limit_reg | int | - | 限制参数，0代表不限制，1-N代表等级 / 读取output中配置的第一个item的id / Chest暂不支持此条件限制 |
| is_reminder | int | - | 1默认开启兑换提示，0不开 |
| ui_background | string | - | 资源底板，区分低级/高级 |
| exchange_umg | string | - | 兑换使用的umg |
| panel_size | int | - | 这个item在兑换界面需要显示为多大，0表示大，1表示中，2表示小 |
| is_full_level | int | - | 是否需要检测该奖励玩家的等级，如果需要，则该奖励玩家已满级时不可兑换，配置1需要检测，不配则不需要 |
| banner_icon | string | - | banner上方显示的图片 |
| limit_type | string | - | 限制兑换类型 |
| limit_param1 | string | - | 限制兑换参数1 / 与limit_type结合使用 |
| limit_param2 | string | - | 限制兑换参数2 / 与limit_type结合使用 |
