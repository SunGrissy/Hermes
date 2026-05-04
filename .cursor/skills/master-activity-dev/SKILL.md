---
name: master-activity-dev
description: Develop Master activity system features including new activities, plays, entries, popups, red dots, and points. Also supports reviewing requirement documents from DingTalk for field mapping completeness. Use when the user works on Master activities, MasterModule, MasterData, MasterPlay, master_play_module code, or asks to review/audit a master activity requirement document.
---

# Master 活动系统开发

Master 系统是统一的限时活动管理框架，支持独立活动(Act)和活动集群(ActGroup)，每个活动可包含多种玩法(MasterPlay)。

## 前置条件

使用本 skill 前，用户必须提供**项目根路径**（即包含 `Content/` 和 `Tables/` 的目录，例如 `D:\FishUE4L3\FishUE4`）。
Agent 应在首次使用时主动询问，并在后续操作中以此路径为基准解析所有相对路径。

路径映射关系（`{ROOT}` = 项目根路径）：

| 资源 | 路径 |
|------|------|
| Lua 代码根 | `{ROOT}/Content/Scripts/` |
| 配表目录 | `{ROOT}/Tables/server_data/` |

本文件及 `reference/` 下所有文档中出现的相对路径（如 `lua/framework/...`）均相对于上述 Lua 代码根。如果路径不存在，应提示用户确认后再继续。

本 skill 自带 SVN 变更查询脚本 `scripts/svn_file_changes.py`（位于本 skill 目录下，无外部依赖），用于文档过期检查。

## 开发活动页面的流程

活动页面是玩家看到的主界面，框架会通过 `UIRegister.DynamicRegister` 自动注册 Dialog，开发者无需手动注册。

1. **配置活动**: 服务器配表 MasterAct / MasterActGroup，配置 id、时间、master_plays、解锁条件、强弹规则等
2. **创建主界面**:
   - 创建 UMG 资源
   - 创建 Lua 脚本类，继承 `UIWidget`（单玩法）或 `MasterPlayHudBase`（多玩法 Tab 切换）
   - `ReceivedOnCreated(dialog, master_data, default_show_play_type, bi_args)` 接收参数
3. **创建入口** (可选): 继承 `MasterEntryBase`，重写 `InitSpecial / RegisterEvents / SetRedDotKey`
4. **创建强弹助手** (可选): 继承 `MasterPopUpAssisterBase`，重写 `ExecPopUp`

## 开发新玩法的流程

玩法是活动内的功能单元（如抽奖、兑换、任务等），一个活动可包含多个玩法。

1. **定义玩法类型**: 在 `MasterPlayType` 枚举中添加新类型
2. **创建玩法模块**: 继承 `MasterPlayModuleBase`，必须重写:
   - `InitRedDot` / `GetRedDotKey` / `CalcRedDotNumber` — 红点
   - `CheckComplete` — 玩法完成判定
3. **注册模块**: `GameModule.ModuleType.MasterPlayXxxModule = MasterPlayXxxModule`
4. **协议处理**: 用 `CreateMsg` 创建消息（框架自动填充 act_id 和 master_play_id），注册 PushHandler 处理响应
5. **玩法完成**: 完成时必须 Dispatch `GameEventType.MasterPlayComplete`

## 文件组织规范

```
lua/framework/components/game_module/module_impl/master_play_module/
    master_play_xxx_module.lua              -- 玩法模块
lua/product/components/ui_item/master/{功能名}/
    master_{功能名}_main.lua                -- 主界面
    master_{功能名}_entry.lua               -- 入口（可选）
    master_{功能名}_xxx.lua                 -- 其他子组件
lua/game_mode/master_popup_assister/
    master_{规则}_popup_assister.lua         -- 强弹助手
```

## 命名规范

- 活动ID: 小写下划线，如 `act_xxx`、`act_group_xxx`
- 玩法实例ID: `"{活动id}:{玩法配置id}"`，框架自动拼接，不要手动拼
- 玩法模块类: `MasterPlay{类型}Module`（类型为配表名去掉 Master 前缀）
- 主界面类: `Dialog{Act/ActGroup}{theme_tag}Controller`
- 入口类: `MasterEntry{功能名}`
- 强弹助手: `{popup_rule}PopUpAssister`
- 强弹存档key: 必须以 `"MasterPopUp_"` 开头，且包含活动id

## 注意事项与禁止事项

1. **禁止写死 id**: 不要在代码中硬编码任何活动/玩法 id
2. **禁止特殊化逻辑**: 不要为某期特定活动写特殊分支
3. **使用框架接口**: 禁止直接访问成员变量，必须用 MasterModule / MasterData 提供的接口
4. **玩法实例隔离**: 框架允许同一玩法的不同实例同时存在，逻辑必须按 master_play_id 隔离
5. **事件处理过滤**: 事件回调中必须校验 master_play_id 或 master_id 是否匹配自己，避免处理其他活动的事件
6. **Dispose 调用父类**: MasterPlayModuleBase 子类重写 Dispose 必须调用父类方法，否则数据残留
7. **优先复用基类**: 各玩法目录中已有公共基类（如 Mission 的 Row/RowBox/Tab/TabBox），必须优先继承复用
8. **规则弹窗**: 统一使用 `master_data:StandardRuleMessageBoxName()` + `PopupManager.Alert`
9. **CreateMsg**: 发送协议必须用 `CreateMsg`，框架自动处理 ID 转换

## 配表查看

如需查看 Master 相关配表（MasterAct.xls、MasterExchange.xls 等）的字段结构，使用 `table-schema-preview` skill。
Master 配表目录：`{ROOT}/Tables/server_data/Master/`

## 玩法选择与文档查找流程

本 skill 采用两级文档结构，按以下流程使用：

1. **收到需求时** → 先读 `reference/play-index.md`（一级缓存），通过速查表和反向索引快速筛选候选玩法
2. **锁定候选后** → 读对应的 `reference/play-xxx.md`（二级详情）获取完整开发信息
3. **需要对比多个候选** → 用 `play-index.md` 中的「相似玩法对比速查」段落辅助决策
4. **无完美匹配时** → 按「需求降级匹配流程」处理
5. **部分需求无法用现有玩法实现时** → 按「拆分实现原则」处理
6. **玩法分析完成后** → 自动执行「需求分析与方案生成」，输出一份完整文档（见下方章节）
7. **如有新开发内容** → 与用户讨论后追加方案到文档中

### 一级缓存：`reference/play-index.md`

包含所有 46 个玩法的速查摘要：
- 每个玩法的中文名、核心模式、能力标签
- 按需求场景的反向索引（如"需要抽奖" → Draw/SpinDraw/LiftingDraw/...）
- 相似玩法的一句话区别对比
- 模块继承关系树

### 二级详情：各 `reference/play-xxx.md`

每个玩法的完整参考文档，包含：
1. 适用场景与需求匹配
2. 玩法概述与类型定义
3. 核心模块说明（继承、初始化、数据存储）
4. 协议与接口
5. 红点系统
6. 完成条件
7. 开发注意事项
8. 配表结构（完整字段说明，含字段名、类型、容器、说明）

### 需求降级匹配流程

当 `play-index.md` 中没有能力标签完全覆盖需求的玩法时，执行以下流程：

1. **筛选相近候选**：从 `play-index.md` 找出能力标签覆盖度最高的 2-3 个玩法
2. **差距分析**：读取候选玩法的二级详情，逐项对比需求与现有能力的差距，区分：
   - **配置可解决**：通过调整配表参数即可满足（如改消耗数量、增加奖励档位）
   - **小改造可解决**：需少量代码修改（如增加一个判断分支、扩展一个已有字段的取值）
   - **大改造才能解决**：需新增协议、新增数据结构、修改核心逻辑流
3. **输出改造方案**：向用户列出每个候选的改造成本，格式为：
   ```
   候选 A（Draw）：覆盖度 80%
   - ✅ 已支持：随机奖励、保底、连抽
   - 🔧 配置可解决：XXX（改 clear_condition 字段）
   - 🛠 需改造：XXX（需新增 YYY 协议）
   - 预估工作量：X 天
   ```
4. **等待用户决策**：不自行选择方案，由用户确认后再动手

### 拆分实现原则

**不要把所有需求都硬凑到现有玩法上。** 一个策划案中可能同时包含：
- 能用现有玩法**完全匹配**或**微调即可满足**的部分
- 现有玩法**完全无法实现**或**强行适配会严重扭曲**的部分

遇到这种情况时，按以下原则处理：

1. **逐个功能模块独立判定**：将策划案拆解为独立的功能模块，每个模块单独判断是否有合适的现有玩法
2. **只采纳真正匹配的**：只有"完全匹配"或"微调可满足"的模块才使用现有玩法；"大改造"或"强行适配"的不算
3. **明确标注新开发部分**：无法用现有玩法实现的模块，直接标注为"需要新开发"，说明原因和新开发内容清单
4. **区分"独立 MasterPlay"与"子模块"**：
   - 如果新功能具备独立玩法特征（独立入口、独立积分、独立生命周期）→ 建议新增 MasterPlayType
   - 如果新功能依附于其他玩法（由其他玩法触发、无独立入口、无独立数据）→ 作为现有玩法的 UI 子模块实现
5. **输出格式**：分两个表格呈现，一个列出"可用现有玩法实现"的部分，一个列出"需要新开发"的部分，附上理由

**反面案例**：策划案中有一个"签到触发的转盘小游戏"，不能因为 MasterDraw 也是"抽奖"就硬套 MasterDraw——MasterDraw 是独立入口+消耗货币的抽奖系统，与"签到内嵌的免费转盘"完全不同。

## 需求分析与方案生成

玩法分析完成后**自动执行**。整个流程输出**一份文档** `_master_doc_review.md`，包含两个部分：Part 1 文档分析、Part 2 技术与配表方案。如有新开发内容，与用户讨论后追加 Part 3。

### 总体流程

1. **获取文档** → 钉钉 MCP 获取内容（如需求来自钉钉文档则直接复用）
2. **玩法分析** → 前序步骤已完成，结论直接复用
3. **文档细节分析** → 下载示意图，逐组件检查与配表字段的对应关系
4. **生成技术与配表方案** → 基于分析结论，为已有玩法部分出方案
5. **输出文档** → 将 Part 1 + Part 2 写入 `_master_doc_review.md`
6. **如有新开发内容** → 与用户讨论，讨论完成后追加 Part 3 到文档

### Part 1：文档分析

#### 1.1 玩法使用分析

复用前序玩法分析结论：
- 哪些模块使用已有玩法（玩法类型 + 匹配理由）
- 哪些模块需要新开发（原因）
- 活动结构判定（Act / ActGroup，按下方「Act / ActGroup 判定规则」）

#### 1.2 页面字段映射分析

对**使用已有玩法**的每个页面，下载示意图进行分析：

1. 从文档 Markdown 中提取图片 URL，下载到本地临时文件
2. 用 Read 工具读取图片，识别 UI 组件
3. 对照 `play-xxx.md` 配表字段列表，逐组件检查

对每个组件，判定为以下三种情况之一：

| 情况 | 说明 | 文档中的处理 |
|------|------|------------|
| **映射清晰** | 文档已说明对应的配表字段 | 列入「映射清晰」表，确认无误 |
| **未说明，但配表有对应字段** | 文档没写，但配表中存在可用字段 | 列入「建议补充」表，**给出配置建议**（建议使用哪个字段、怎么配） |
| **未说明，配表也无对应字段** | 文档没写，配表中也没有现成字段 | 列入「无对应字段」表，**标注需要新增字段或前端硬编码** |

格式：
```markdown
### 页面：签到主界面（MasterSignIn）

#### 映射清晰的组件
| 组件 | 显示内容 | 配表字段 |
|------|---------|---------|

#### 建议补充（配表有字段，文档未说明）
| 组件 | 示意图表现 | 建议配表字段 | 建议配置方式 |
|------|-----------|------------|------------|
| 奖励背景等级 | 部分签到日背景更华丽 | SignReward.reward_level | 转盘日填 0（最高等级），普通日填 1 |

#### 无对应字段（需新增或硬编码）
| 组件 | 示意图表现 | 说明 |
|------|-----------|------|
| 碎片总数 "150" | 顶部图片字 | 配表无此字段，建议前端从所有转盘奖励累加计算，或新增配置字段 |
```

新开发 / 非 Master 部分直接跳过，简单提一句。

### Part 2：技术与配表方案

紧接文档分析之后，为**使用已有玩法**的部分生成方案。

#### 2.1 技术方案

1. **活动结构**：Act / ActGroup + 每个 Act 挂哪些 MasterPlay
2. **文件清单**：需要创建的 Lua 文件和 UMG 蓝图，按文件组织规范列出
3. **类继承关系**：每个类继承哪个基类
4. **核心实现要点**：
   - 框架接口调用
   - 事件监听
   - 红点绑定
   - 完成条件处理
5. **非 Master 部分**：简要说明技术思路

#### 2.2 配表方案

说明现有配表中**关键字段怎么配**，将需求功能映射为字段配置方式：

```markdown
#### MasterSignIn.xls

| 需求功能 | 配表字段 | 配置方式 |
|---------|---------|---------|
| 30天签到 | Main.signin_rewards | 配 30 条 SignReward |
| 登录即签到，累计天数 | Main.type | 填 "add" |
| 无补签 | Main.catch_up_type | 不配置 |
| 金币受超能膨胀加成 | Main.boost_free | 配置对应 boost 类型 |

#### MasterAct.xls

| 需求功能 | 配表字段 | 配置方式 |
|---------|---------|---------|
| 活动常驻 | start_time + end_time | 配一个足够远的结束时间 |
| 炮倍解锁 | unlock_requirements | 配炮倍条件 |
```

**不填具体值**（道具 id、金币数量等由策划填写），只说明字段用途和配置方式。

#### 2.3 Part 1 中「建议补充」的汇总

将文档分析中发现的「配表有字段但文档未说明」和「无对应字段」汇总为待确认清单，方便策划和程序逐条对齐：

```markdown
## 待确认清单

### 配表有字段，建议策划补充到文档
1. 【签到主界面·奖励背景】建议使用 SignReward.reward_level 控制
2. ...

### 配表无对应字段，需讨论
1. 【签到主界面·碎片总数 "150"】无配表字段，建议方案：A) 前端累加计算 B) 新增字段
2. ...
```

### Part 3：新开发内容方案（讨论后追加）

Part 1 + Part 2 输出后，如果存在需要新开发的内容：

1. **先与用户讨论**：列出需要新开发的模块，逐个确认需求细节和数据模型
2. **讨论完成后追加到文档**，包含：
   - **新配表结构设计**：字段名、类型、容器、说明（格式同 play-xxx.md 的「配表结构」章节）
   - **新增模块/协议/事件规划**
   - **与已有玩法的联动方式**
3. 不要在讨论前自行设计方案

### Act / ActGroup 判定规则

分析策划案时，必须判断活动使用单个 Act 还是 ActGroup 集群：

**使用单个 Act（MasterAct.xls）的场景**：
- 活动只有一个入口、一个主界面，内部包含 1~N 个 play
- 所有 play 共享同一时间窗口、同一解锁条件
- 一个 Act 的 `master_plays` 字段可引用多个 MasterPlay（不同 class_type），足以承载多玩法组合
- **典型例子**：惊喜魔术箱（ChestUpgrade + Exchange + Milestone + FishDrop 都挂在一个 Act 下）

**使用 ActGroup（MasterActGroup.xls）的场景**：
- 多个子活动需要**各自独立的时间窗口**（如 A 活动第 1~3 天，B 活动第 4~7 天）
- 多个子活动有**前后依赖关系**（Act.depend_on 引用其他 Act）
- 需要**统一入口但子活动独立展示**，且子活动有各自独立的完成判定
- 子活动之间需要**各自独立接取条件**（unlock_requirements 不同）
- **is_virtual=1**：虚拟集群，无集群入口，子活动各自独立显示入口
- **is_virtual=0**：实体集群，集群提供统一入口和主界面，子活动作为页签
- **典型例子**：庆典活动（多个独立子活动挂在一个集群下，各有页签）

**快速判断流程**：
1. 活动有几个**时间窗口**？→ 1 个用 Act，多个用 ActGroup
2. 子系统间有**前置依赖**？→ 有依赖用 ActGroup（depend_on 只能跨 Act）
3. 需要**各自独立的接取条件**？→ 是则 ActGroup
4. 以上都不是 → 用单个 Act，`master_plays` 挂多个 play

### 注意事项

1. **不要替策划猜测字段映射**：「建议补充」只是建议，最终由策划确认
2. **示意图分析要保守**：对不确定的组件标注「疑似」并描述位置
3. **字段名以 play-xxx.md 为准**：反映代码实际使用的字段名
4. **不填具体值**：不写道具 id、金币数量等业务数据
5. **新开发部分必须先讨论**：不要在未与用户讨论前自行设计方案
6. **临时文件清理**：完成后删除 `_review_mockup_*.png`

## 详细参考文档

- **系统完整文档**: `reference/master-system.md` — MasterModule / MasterData / MasterPlayModuleBase 接口详情、事件系统、红点系统、积分系统、生命周期、配表结构、规范化调用（如与现有代码冲突，以现有代码为准）
- **玩法索引**: `reference/play-index.md` — 全部玩法速查 + 需求→玩法映射
- **抽奖家族**: `play-draw.md` / `play-spindraw.md` / `play-liftingdraw.md` / `play-collectiondraw.md` / `play-combinedraw.md` / `play-threeimagedraw.md`
- **兑换/商店**: `play-exchange.md` / `play-poolexchange.md` / `play-shops.md` / `play-forge.md` / `play-transform.md`
- **任务/签到**: `play-task.md` / `play-mission.md` / `play-cycletask.md` / `play-signin.md` / `play-festivalsignin.md`
- **里程碑/免费**: `play-milestone.md` / `play-boostmilestone.md` / `play-freereward.md`
- **宝箱**: `play-chest.md` / `play-weeklychest.md` / `play-chestupgrade.md`
- **通行证/赛季**: `play-seasonbp.md` / `play-basebp.md` / `play-seasonrank.md` / `play-rankpoint.md` / `play-cardlevel.md`
- **Boss/挑战**: `play-bosschallenge.md` / `play-bossrush.md` / `play-catch.md`
- **金币/银行**: `play-coin.md` / `play-coinnewbie.md` / `play-piggybank.md` / `play-bank.md` / `play-chargereward.md` / `play-cyclepack.md`
- **其他**: `play-search.md` / `play-fishdrop.md` / `play-paint.md` / `play-minetreasure.md` / `play-saga.md` / `play-albumcard.md` / `play-quiz.md` / `play-advpopup.md` / `play-unlock.md` / `play-unlockpack.md`
- **辅助模块**: `play-ranking.md`（不在 MasterPlayType 枚举中）


## 文档过期检查（硬规则）

**核心原则：文档随时可能过时，必须在每次使用前主动验证，发现过期必须立即更新。**

每个 reference 文档顶部都有元数据注释，标明了参考的代码文件和最后参考时间：

```
<!--
参考代码文件:
- lua/game_mode/master_data.lua
- lua/framework/.../master_module.lua
最后参考时间: 2026-01-13
-->
```

### 何时必须检查

1. **每次读取 reference 文档时** — 读文档的第一步就是检查过期，不能跳过
2. **基于文档内容做开发决策前** — 如果决策依赖文档中的接口签名、字段含义、协议格式等，必须先确认这些信息是否仍然准确
3. **生成配表内容前** — 配表字段可能已经新增/删除/改义，必须用 `table-schema-preview` skill 重新验证当前配表结构与文档是否一致
4. **用户反馈"这个接口不对"或代码行为与文档描述不符时** — 立即触发过期检查

### 检查流程

1. 读取文档顶部的「最后参考时间」和「参考代码文件」列表
2. 用本 skill 自带的 SVN 变更脚本查询变更（脚本会同时检测 SVN 提交和本地未提交修改）：
   ```
   python <SKILL_DIR>/scripts/svn_file_changes.py -f <文件路径> --since <最后参考时间> -p <Lua代码根> -o _file_changes.txt
   ```
   其中 `<SKILL_DIR>` 为本 skill 目录的绝对路径，`<Lua代码根>` 即 `{ROOT}/Content/Scripts/`。
   - 报告中标记 `[LOCAL MODIFIED]` 的文件有本地未提交的修改
3. 根据变更类型选择检查方式：
   - **仅有 SVN 提交、无本地修改**：用 `svn diff -r <最后参考时间对应版本>:HEAD <文件>` 获取 diff，根据 diff 内容与文档对比即可，无需完整读取代码文件
   - **有本地修改**（标记 `[LOCAL MODIFIED]`）：需要完整读取代码文件与文档逐项对比
4. **发现过期时的处理**：
   - 立即更新文档中过时的内容（接口签名、字段说明、协议格式、配表结构等）
   - 将「最后参考时间」更新为当天日期
   - 向用户简要说明更新了什么（如"play-draw.md 中 Pool 子表新增了 xxx 字段，已同步更新"）

### 配表结构专项检查

配表字段变更频率高于代码接口，生成配表内容前必须额外验证：

1. 用 `table-schema-preview` skill 读取当前 `.xls` 文件的实际 schema
2. 与文档中「配表结构」章节逐字段对比
3. 如有差异（新增字段、删除字段、类型变更、说明变更），立即更新文档
4. 基于更新后的文档生成配表内容

### 禁止事项

- **禁止跳过过期检查直接信任文档内容**
- **禁止发现过期后不更新文档就继续使用旧内容**
- **禁止仅口头提醒"文档可能过时"而不执行检查流程**
