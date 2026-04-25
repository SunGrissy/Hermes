<!--
参考代码文件:
- lua/framework/components/game_module/module_impl/master_play_module/master_play_shops_module.lua
最后参考时间: 2026-04-16
-->
================================================================================
                        商店（MasterShops）玩法说明
================================================================================
                           版本: 2026-04-16
================================================================================

1. 适用场景与需求匹配

### 核心玩法模式
在 Master 活动内挂载 **BusinessModule 商店页**：通过配置的 `tab_type` 与刷新周期，把付费/免费商品入口统一到活动框架，由商店系统负责下单、价格与限购展示。

### 典型需求场景
活动限时商店、VIP 商店、按日/周/月刷新的 tab、带免费领取项的商店入口；需要在活动 HUD 上显示「商店红点」但不做独立 Master 协议。

### 能力标签
付费购买、商店页对接、定时刷新（日/周/月）、免费商品红点、`cvt_shop` 映射。

### 与相似玩法的区别
本玩法 **不实现独立兑换协议**，核心是 **映射到 `BusinessModule:RequestShopPageInfo`**；与积分兑换类（Exchange / PoolExchange）不同，商品与计费走商店域。与 **Package** 直购页相比：本玩法强调 **Master 配置驱动多 tab** 与活动生命周期。

---

2. 玩法概述
`MasterPlayShopsModule` 在 `OnMasterPlayInfoRefresh` 中把 `conf.shops` 转为运行时 `cvt_shop`（`refresh_type → tab_type`），监听商店页与跨天事件以刷新免费项红点；单例 `MasterPlayShopsModule.Instance` 供全局判断某 `tab_type` 是否归属 Master 商店。

**数据流（概念）**
1. 配表 `shops` 多行 → 展平为 `cvt_shop`。
2. 若 `has_free` 非空 → 延迟请求各 `tab_type` 的 `RequestShopPageInfo`。
3. `ShopPageInfoChanged` → 若 tab 在 `has_free` 中，根据 `free_charge_id` 剩余次数刷新红点。

---

3. 玩法类型定义
- **类名**：`MasterShops`
- **模块**：`MasterPlayShopsModule`（单例）
- **关键配置**：`shops`、`has_free`、`ignore_last_round_hide`（具体字段以配表为准）

---

4. 核心模块说明
| 职责 | 说明 |
|------|------|
| 积分注册 | `IsRegisterPointRequired` → `false` |
| 商店数据 | `GetShops` 返回 `cvt_shop`；`IsMasterShopTabType` 遍历所有玩法配置判断 tab |
| 红点 | `RefreshShopRedDot`、`OnShopPageInfoChanged`；日/周/月事件调用 `RefreshShopRedDot` |
| 刷新时间 | `GetNextRefreshTime` 供 UI 展示倒计时（实现依赖 `ShopTabRefreshType`） |
| 协议 | **无** `RegisterPushHandler`；依赖 `BusinessModule` |

---

5. 数据结构
- **`master_play_info.cvt_shop`**：`refresh_type`（如 Daily/Weekly）→ `tab_type`（商店页类型枚举）
- **`has_free`**：需要拉取商店页以计算免费商品可领状态；与 `BusinessModule.Instance.shop_page_info[tab_type]` 联动

---

6. 协议与接口
- Master 专用推送：**无**
- 对外：通过 `BusinessModule.Instance:RequestShopPageInfo(tab_type)` 拉页；计费结果由商店模块回调，本模块主要消费 `ShopPageInfoChanged`

---

7. 红点系统
- `GetRedDotKey`：优先 `"master_shop:" .. master_data:ID() .. ":" .. master_play_class_id`（与后端统一）；`master_data` 缺失时回退 `"master_shop:" .. master_play_id`
- `InitRedDot`：单个 Common 类型 key
- **免费逻辑**：`free_charge_id` 存在且 `max_times - times != 0`（或无限购）时红点为 1

---

8. 完成条件
未覆写 `CheckComplete`，沿用基类默认。

---

9. 开发注意事项
- **key 必须使用 class_id**：源码注释明确：前端曾用 `master_play.id` 导致与后端不一致，现强制 `master_shop:{act_id}:{master_play_class_id}`。
- 配了 `has_free` 时会在刷新时 **延迟 PushMsg** 请求商店页，避免首帧红点缺数据。
- 本模块 **不向 Master 派发专属业务完成事件**，UI 以商店与活动通用事件为准。
- 新增 `tab_type` 时同步核对 `IsMasterShopTabType` 与后台商店配置是否一致。

**联调与测试建议**
- 切换活动或 `master_play_id` 后，确认 `GetRedDotKey` 仍解析到正确 `MasterData`，避免红点串活动。
- `OnNewDayBegin` / `OnNewWeekBegin` / `OnNewMonthBegin` 三连调时，免费次数刷新是否与服务器日界一致。
- 无 `master_data` 回退分支仅用于异常，日志中若频繁出现应排查注册顺序。

**依赖模块**
- `BusinessModule`：商店页缓存、`GetChargeInfo`；改动商店数据结构时需回归本模块 `OnShopPageInfoChanged`。

10. 配表结构（MasterShops.xls）

### Sheet: MasterShops

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 玩法id |
| comment | string | - | 自己看的备注 |
| shops | object | array | key，normal:不刷的，weekly:每周刷的，daily:每日刷的，value = shop id |
| main_ui | string | - | shop作为独立页面时配置，商店主页的umg名 |
| main_ui_class | string | - | shop作为独立页面时配置，商店主页的lua类名，不配走默认类 |
| ignore_last_round_hide | int | - | 1：永远显示礼包刷新倒计时 / 0或不配：保持现状，当本轮为最后一轮刷新时，不显示刷新倒计时 |
