<!--
参考代码文件:
- lua/framework/components/game_module/module_impl/master_play_module/master_play_quiz_module.lua
最后参考时间: 2026-04-16
-->
================================================================================
                        MasterQuiz 玩法开发规范
================================================================================
                           版本: 2026-02-04
================================================================================

目录
----
1. 玩法概述
2. 核心数据结构
3. 逻辑模块 (MasterPlayQuizModule)
4. UI实现
5. 事件系统
6. 红点系统
7. 开发新MasterQuiz活动的完整步骤
8. 常见问题与注意事项

================================================================================
1. 玩法概述
================================================================================

MasterQuiz 是 Master 活动系统中的"每日答题"玩法类型，用于实现问答互动类活动。

玩法标识：MasterPlayType.Quiz = "MasterQuiz"

典型应用场景：
- 大话西游主题答题（dahuaquiz）
- 知识问答活动
- 每日签到问答

核心特点：
1. 每天一题，每日0点刷新
2. 支持连续答对天数统计
3. 题目从题库中按天数轮换
4. 答案随机排列（正确/错误答案位置随机）
5. 答题后显示全服正确率统计
6. 支持双档奖励（答对奖励 + 活动积分）

玩法流程：
1. 玩家打开答题界面
2. 系统根据活动天数从题库抽取当日题目
3. 正确/错误答案随机排列展示
4. 玩家选择答案后提交服务器
5. 服务器返回答题结果和全服统计
6. 显示正确答案和答题比例
7. 发放奖励并更新连续答对天数

================================================================================
2. 核心数据结构
================================================================================

2.1 XLS表结构 (MasterQuiz.xls)
------------------------------

表文件路径：`D:\FishUE4L3\FishUE4\Tables\server_data\Master\MasterQuiz.xls`

Quiz Sheet（主表）：
| 字段    | 类型     | 说明                                         |
|---------|----------|----------------------------------------------|
| id      | string   | 唯一ID                                       |
| comment | string   | 备注                                         |
| pool    | [Pool]   | 题库（数组，引用Pool表）                     |

Pool Sheet（题目表）：
| 字段     | 类型     | 说明                                        |
|----------|----------|---------------------------------------------|
| id       | string   | 唯一ID                                      |
| comment  | string   | 备注                                        |
| question | string   | 问题文本的i18n                              |
| answer   | string   | 正确答案的i18n                              |
| mistake  | string   | 错误答案的i18n                              |
| reward   | [yield]  | 奖励                                        |

2.2 生成的Lua配置结构 (MasterQuiz.lua)
--------------------------------------

配置中除了 `pool`（题目 ID 数组）外，还有 `all_quiz`（ID → 题目对象的映射表）。实际使用时通过 `play_info.conf.all_quiz[quiz_id]` 获取具体题目信息。

MasterQuiz 配置表结构：
{
    ['dahuaquiz'] = {
        ['id'] = 'dahuaquiz',           -- 玩法配置ID
        ['pool'] = {                     -- 题库（数组）
            {
                ['id'] = 'dahua_1_set01',           -- 题目ID
                ['question'] = 'dahua_1_Q01',       -- 问题文本（i18n key）
                ['answer'] = 'dahua_1_A01',         -- 正确答案（i18n key）
                ['mistake'] = 'dahua_1_M01',        -- 错误答案（i18n key）
                ['reward'] = {                      -- 奖励配置（多档位）
                    {   -- 第一档奖励
                        {
                            ['User:Chip'] = 100000,     -- 金币奖励
                            ['weight'] = 100            -- 权重
                        }
                    },
                    {   -- 第二档奖励
                        {
                            ['master_point:mp_dahua_box_1'] = 1,  -- 活动积分/宝箱
                            ['weight'] = 100
                        }
                    }
                }
            },
            -- ... 更多题目
        }
    }
}

2.3 运行时数据结构 (play_info.info)
------------------------------------

play_info.info = {
    last_quiz_time = 1704067200,    -- 最后答题时间戳
    right_days = 5,                  -- 连续答对天数
}

2.4 配置字段说明
----------------

题目配置字段：
| 字段      | 类型   | 说明                           |
|-----------|--------|--------------------------------|
| id        | string | 题目唯一ID                     |
| question  | string | 问题文本的 i18n key            |
| answer    | string | 正确答案的 i18n key            |
| mistake   | string | 错误答案的 i18n key            |
| reward    | array  | 奖励配置，支持多档位权重奖励    |

运行时字段：
| 字段           | 类型   | 说明                           |
|----------------|--------|--------------------------------|
| last_quiz_time | number | 最后答题时间戳                 |
| right_days     | number | 连续答对天数                   |

================================================================================
3. 逻辑模块 (MasterPlayQuizModule)
================================================================================

文件位置: lua/framework/components/game_module/module_impl/master_play_module/
          master_play_quiz_module.lua

继承关系: MasterPlayQuizModule <- MasterPlayModuleBase <- GameModule

3.1 获取模块实例
----------------

MasterPlayQuizModule.Instance

3.2 获取数据的API
-----------------

-- 获取玩法信息
MasterPlayQuizModule.Instance:GetMasterPlayInfo(master_play_id)
    返回: play_info = {conf = {...}, info = {...}}

-- 获取红点Key
MasterPlayQuizModule.Instance:GetRedDotKey(master_play_id)
    返回: "dahua_quiz_{master_play_id}"

-- 检查是否正在请求答题
MasterPlayQuizModule.Instance:IsRequesingQuiz()
    返回: boolean

3.3 请求API
-----------

-- 提交答题请求
MasterPlayQuizModule.Instance:RequestDoQuiz(play_id, bis_right)
    play_id:   玩法ID
    bis_right: boolean，是否答对

3.4 数据更新API
---------------

-- 更新最后答题时间
MasterPlayQuizModule.Instance:SetMasterInfo(master_play_id, newTime)

-- 更新连续答对天数
MasterPlayQuizModule.Instance:SetMasterConsecutiveDays(master_play_id, days)

-- 计算红点
MasterPlayQuizModule.Instance:CalcRedDotNumber(master_play_id)

3.5 消息类型
------------

MessageType.MasterQuizDoAnswer = {'game', "master_quiz_do_quiz"}

请求参数：
- params.is_right: 1=答对，0=答错

返回结果：
- res.right_num:      全服答对人数
- res.wrong_num:      全服答错人数
- res.last_quiz_time: 本次答题时间戳

================================================================================
4. UI实现
================================================================================

4.1 主界面 (MasterDaHuaQuizMain)
--------------------------------

文件: lua/product/components/ui_item/master/dhxy/dahua_quiz/master_dahuaquiz_main.lua

职责：答题主界面的显示和交互管理

关键成员变量：
- self.parent_dialog    -- 父弹窗
- self.master_data      -- 活动数据
- self.play_info        -- 玩法信息
- self.play_id          -- 玩法ID
- self.start_time       -- 活动开始时间
- self.current_time     -- 打开界面时的服务器时间
- self.consecutive_correct_days -- 连续答对天数
- self.last_refresh_time -- 最后答题时间
- self.bselect_correct  -- 用户是否选择了正确答案
- self.correct_item     -- 正确答案选项组件
- self.wrong_item       -- 错误答案选项组件
- self.cd_taskid        -- 倒计时任务ID

核心方法：

-- 初始化主界面
InitMain(play_info)
    逻辑：
    1. 计算今日题目索引：(当前时间 - 活动开始时间) / 86400 % 题库长度 + 1
    2. 从题库获取今日题目
    3. 设置问题文本和连续天数
    4. 随机排列正确/错误答案
    5. 启动剩余时间倒计时

-- 显示答题结果
OnShowResult(master_play_id, correct, wrong, last_quiz_time)
    逻辑：
    1. 计算并显示答题比例
    2. 更新本地数据
    3. 播放正确/错误答案动画
    4. 更新连续答对天数显示
    5. 刷新红点

-- 判断是否可以答题
bIsRefreshed()
    返回: 服务器0点时间 > 最后答题时间

-- 判断是否跨天失效
OnIsNewDay()
    返回: 服务器0点时间 > 打开界面时间

4.2 答案选项 (MasterDaHuaQuizItem)
----------------------------------

文件: lua/product/components/ui_item/master/dhxy/dahua_quiz/master_dahuaquiz_item.lua

职责：单个答案选项的显示和交互

关键成员变量：
- self.main_widget   -- 主界面引用
- self.play_data     -- 玩法数据
- self.bis_correct   -- 是否为正确答案
- self.has_answered  -- 是否已答题

核心方法：

-- 点击答案按钮
AnswerBtnOnClicked()
    逻辑：
    1. 检查是否已答题
    2. 检查是否跨天失效（弹窗提示）
    3. 调用 RequestDoQuiz 提交答题

-- 设置已答题状态
SetAnswered()
    self.has_answered = true

-- 显示正确答案（用户选中）
ShowCorrectAnwser()
    播放动画: ShowTrueResults

-- 显示错误答案（用户选中）
ShowWrongAnswer()
    播放动画: ShowFalseResults

-- 显示正确答案（用户未选中）
ShowCorrectAnwserSelectionFalse()
    播放动画: ShowTrueResultsSF

-- 显示错误答案（用户选中正确答案）
ShowWrongAnswerSelectionTrue()
    播放动画: ShowFalseResultsST

4.3 UMG资源
-----------

主界面UMG: UMG_MasterQuizMain
答案选项UMG: UMG_MasterQuizItem

UMG需要实现的组件：
- QuestionText:        问题文本
- consecutive_days:    连续天数文本
- LeftTimeText:        剩余时间文本
- AnswerBoxHB:         答案容器（HorizontalBox）
- FullScreen_CloseBtn: 全屏关闭按钮
- CloseBtn:            关闭按钮
- closeTipTxt:         关闭提示文本
- ShowTreasureRewardListBtn: 查看奖励按钮
- UMG_XYDrawTreasureRewardMain: 奖励列表界面

答案选项UMG需要实现：
- AnswerBtn:          答案按钮
- SelectionAnwserText: 答案文本
- AnswerRate:         答题比例文本
- ShowTrueResults:    正确答案动画（选中）
- ShowFalseResults:   错误答案动画（选中）
- ShowTrueResultsSF:  正确答案动画（未选中）
- ShowFalseResultsST: 错误答案动画（选中正确时）

================================================================================
5. 事件系统
================================================================================

5.1 答题相关事件
----------------

-- 答题完成事件
GameEventType.QuizDoAnswerComplete
    参数: master_play_id, correct_num, wrong_num, last_quiz_time
    触发时机: 服务器返回答题结果后
    用途: 刷新UI显示答题结果

-- 新一天事件（框架事件）
GameEventType.ANewDay
    用途: 跨天后刷新所有玩法的红点

5.2 事件监听示例
----------------

function YourClass:Constructor(UMG)
    -- 注册答题完成事件
    self:AttachEvent(GameEventType.QuizDoAnswerComplete, self.OnShowResult)
end

function YourClass:OnShowResult(master_play_id, correct, wrong, last_quiz_time)
    if master_play_id ~= self.play_id then return end
    if last_quiz_time == -1 then return end  -- 请求失败
    
    -- 处理答题结果...
end

================================================================================
6. 红点系统
================================================================================

6.1 红点规则
------------

红点显示条件：
1. 今日未答题：服务器0点时间 >= 最后答题时间
2. 活动未结束：当前时间 <= 活动结束时间

红点Key格式: "dahua_quiz_{master_play_id}"

6.2 红点API
-----------

-- 获取红点Key
MasterPlayQuizModule.Instance:GetRedDotKey(master_play_id)

-- 初始化红点
MasterPlayQuizModule.Instance:InitRedDot(master_play_id)

-- 计算并刷新红点
MasterPlayQuizModule.Instance:CalcRedDotNumber(master_play_id)

注意事项：当前实现中 CalcRedDotNumber 内部调用 GetRedDotKey() 时未传入 master_play_id，在多实例场景下可能使用错误的 key。

6.3 红点使用示例
----------------

-- 在入口绑定红点
function YourEntry:SetRedDot()
    local red_dot_key = MasterPlayQuizModule.Instance:GetRedDotKey(self.master_play_id)
    self.red_dot_widget:SetKey(red_dot_key)
end

================================================================================
7. 开发新MasterQuiz活动的完整步骤
================================================================================

7.1 配置步骤
------------

1) 配置题库表 (MasterQuiz.lua):
   - 添加新的题库ID
   - 配置题目池（question/answer/mistake/reward）
   - 确保i18n文本已配置

2) 配置活动表 (MasterAct.lua):
   - 设置 class_type = 'MasterQuiz'
   - 设置 main_umg = 'UMG_MasterQuizMain' 或自定义UMG
   - 配置活动时间和其他参数

7.2 代码步骤
------------

1) 创建主界面类（如需自定义）:

_class("YourQuizMain", UIWidget)
YourQuizMain = YourQuizMain

function YourQuizMain:ReceivedOnCreated(dialog, master_data, default_show_master_play_type, bi_args)
    self.parent_dialog = dialog
    self.master_data = master_data
    
    -- 获取玩法信息
    self.play_info = master_data:GetMasterPlayInfo(MasterPlayType.Quiz)
    self.play_id = master_data:GetMasterPlayID(MasterPlayType.Quiz)
    self.start_time = self.master_data:Conf().start_time
    
    -- 注册事件
    self:AttachEvent(GameEventType.QuizDoAnswerComplete, self.OnShowResult)
    
    self:InitMain(self.play_info)
end

function YourQuizMain:InitMain(play_info)
    if not play_info then return end
    
    -- 计算今日题目索引
    local current_time = LoginModule.Instance:GetServerTime()
    local quiz_pool = play_info.conf.pool
    local today_index = tointeger(math.ceil((current_time - self.start_time) / 86400)) % #quiz_pool + 1
    
    -- 获取题目信息
    local quiz_id = quiz_pool[today_index]
    local quiz_info = play_info.conf.all_quiz[quiz_id]
    
    -- 设置问题文本
    local question_text = UIHelper.FormatI18NTextWithLatentArguments(quiz_info.question)
    self.UMG.QuestionText:SetText(question_text)
    
    -- 创建答案选项（随机排列）
    -- ...
end

2) 创建答案选项类（如需自定义）:

_class("YourQuizItem", UIWidget)
YourQuizItem = YourQuizItem

function YourQuizItem:ReceivedOnCreated(main_widget, play_data, bis_correct, answer)
    self:AddCallback("AnswerBtn", "OnClicked")
    self.main_widget = main_widget
    self.bis_correct = bis_correct
    self.has_answered = false
    
    self.UMG.SelectionAnwserText:SetText(UIHelper.FormatI18NTextWithLatentArguments(answer))
end

function YourQuizItem:AnswerBtnOnClicked()
    if self.has_answered then return end
    
    if not MasterPlayQuizModule.Instance:IsRequesingQuiz() then
        self.main_widget.bselect_correct = self.bis_correct
        MasterPlayQuizModule.Instance:RequestDoQuiz(self.main_widget.play_id, self.bis_correct)
    end
end

7.3 文件结构
------------

lua/product/components/ui_item/master/{活动名}/
    ├── {活动名}_quiz_main.lua       -- 主界面
    └── {活动名}_quiz_item.lua       -- 答案选项

UE蓝图目录：
Content/UI/Master/{活动名}/
    ├── UMG_{活动名}_QuizMain.uasset
    └── UMG_{活动名}_QuizItem.uasset

================================================================================
8. 常见问题与注意事项
================================================================================

8.1 题目轮换机制
----------------

题目索引计算公式：
today_index = ((当前时间戳 - 活动开始时间戳) / 86400) % 题库长度 + 1

注意：
- 使用 math.ceil 向上取整
- 索引从1开始（Lua数组）
- 题库会循环使用

8.2 跨天处理
------------

需要处理两种跨天情况：

1. 玩家在界面打开期间跨天：
   - 使用 OnIsNewDay() 检查
   - 点击答题时弹窗提示"答题已失效"

2. 玩家跨天后重新打开：
   - 使用 bIsRefreshed() 检查
   - 红点会自动刷新

8.3 防重复点击
--------------

使用两层防护：
1. UI层：self.has_answered 标记
2. 模块层：self.is_requesting_quiz 标记

点击答案后立即设置 has_answered = true，防止重复提交。

8.4 答案随机排列
----------------

使用 math.random(1, 2) 决定正确/错误答案的显示顺序：

local seed = math.random(1, 2)
if seed == 1 then 
    -- 正确答案在前
    self.UMG.AnswerBoxHB:AddChild(self.correct_item.UMG)
    self.UMG.AnswerBoxHB:AddChild(self.wrong_item.UMG)
else
    -- 错误答案在前
    self.UMG.AnswerBoxHB:AddChild(self.wrong_item.UMG)
    self.UMG.AnswerBoxHB:AddChild(self.correct_item.UMG)
end

8.5 答题结果动画
----------------

根据用户选择和正确答案，播放不同动画：

| 用户选择 | 动画效果                                    |
|----------|---------------------------------------------|
| 选对     | 正确项: ShowTrueResults, 错误项: ShowFalseResultsST |
| 选错     | 正确项: ShowTrueResultsSF, 错误项: ShowFalseResults |

8.6 连续天数统计
----------------

连续天数由服务器维护，客户端只做显示：
- 答对后：right_days + 1
- 答错后：right_days 重置为0（服务器处理）

客户端更新：
MasterPlayQuizModule.Instance:SetMasterConsecutiveDays(play_id, new_days)

8.7 答题比例显示
----------------

使用 UIHelper.FormatPercent 格式化百分比：

local right_percent = correct_num / (correct_num + wrong_num)
self.correct_item.UMG.AnswerRate:SetText(UIHelper.FormatPercent(right_percent, 1, false))

8.8 倒计时显示
--------------

使用 GameGlobal.TaskManager() 创建定时任务：

self.cd_taskid = GameGlobal.TaskManager():StartTask(function(TT)
    local remain_time = LoginModule.Instance:GetTodayLeftTime()
    while remain_time >= 0 do
        local left_time = UIHelper.FormatTimeSpanNormal(remain_time)
        self.UMG.LeftTimeText:SetText(left_time)
        remain_time = remain_time - 1
        YIELD(TT, 1)
    end
end, self)

-- 销毁时停止任务
function YourClass:ReceivedOnRemoved()
    GameGlobal.TaskManager():StopTask(self.cd_taskid)
end

================================================================================
9. 配表结构（MasterQuiz.xls）
================================================================================

### Sheet: Quiz

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一id |
| comment | string | - | 备注 |
| pool | Pool | array | 题库 / *默认每日一题，按照次序逐个进行，全部答完后从头开始再答一遍，引用 Pool 子表 |

### Sheet: Pool

| 字段名 | 类型 | 容器 | 说明 |
|--------|------|------|------|
| id | string | - | 唯一id |
| comment | string | - | 备注 |
| question | string | - | 问题文本的i18n |
| answer | string | - | 正确答案的i18n |
| mistake | string | - | 错误答案的i18n |
| reward | yield | array | 奖励 |

================================================================================
                               文档结束
================================================================================
