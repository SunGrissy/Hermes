import os
from pathlib import Path
import win32com.client
from win32com.client import constants

OUT = Path(r"D:/MyAgents/会议材料/驯化野生硅基伙伴_渐进披露版.pptx")
EXPORT_DIR = Path(r"D:/MyAgents/tmp/ai_share_ppt_preview")
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

# PowerPoint constants fallback
ppLayoutBlank = 12
msoShapeRectangle = 1
msoShapeRoundedRectangle = 5
msoShapeOval = 9
msoShapeRightArrow = 33
msoTrue = -1
msoFalse = 0
msoAnimEffectFade = 10
msoAnimTriggerOnPageClick = 1
msoAnimTriggerAfterPrevious = 3
ppSaveAsOpenXMLPresentation = 24
ppFixedFormatTypePDF = 2

# 16:9 canvas in points. 1280x720 ratio, easier to map from HTML.
W, H = 1280, 720

def rgb(hexstr):
    hexstr = hexstr.strip('#')
    r = int(hexstr[0:2], 16); g = int(hexstr[2:4], 16); b = int(hexstr[4:6], 16)
    return r + (g << 8) + (b << 16)

COL = {
    'bg': '070B13', 'bg2': '0C1220', 'card': '111A2B', 'card2': '151F32',
    'text': 'EFECE5', 'sub': 'A7ADBB', 'muted': '697184', 'line': '293241',
    'gold': 'D6AD61', 'amber': 'F59E0B', 'teal': '20C7AE', 'blue': '4C8DFF',
    'violet': '9B75FF', 'rose': 'FF5F7D', 'paper': 'F5F1E7'
}
ACCENT = {'gold': COL['gold'], 'teal': COL['teal'], 'violet': COL['violet'], 'rose': COL['rose'], 'blue': COL['blue'], 'amber': COL['amber']}

slides_data = [
    dict(kind='cover', kicker='AI Practical Sharing / Product Team', title='驯化野生\n硅基伙伴', subtitle='从真实痛点出发，把 AI 训练成能帮你做事、甚至帮你造工具的伙伴', footer='面向：中心内部产品岗 / 对 AI 实用有困惑的同学\n分享人：孙懿（猫姐）'),
    dict(kicker='Opening', title='今天不做“AI 工具大全”', subtitle='只讲一件事：怎么把通用 AI 驯化成自己的硅基伙伴', quote='真正的变化不是多了一个聊天工具，而是每个人都有机会把通用 AI 驯化成自己的伙伴，甚至把长期存在的痛点变成工具、模板和流程。', cards=[('Question 01','为什么很多人觉得 AI 不好用？','gold'),('Question 02','工作里真正的“钉子”是什么？','teal'),('Question 03','确定性硅基和概率性硅基怎么配合？','violet'),('Question 04','产品岗今天怎么跑通一轮驯化？','blue')]),
    dict(kind='section', kicker='Core Thesis', title='AI 好不好用，差别不只在工具', quote='差别在于：你有没有给它成为伙伴的条件。', cards=[('不要从“我能用 AI 做什么”开始','这会变成拿着锤子找钉子，最后停在炫技和浅尝辄止。','gold'),('要从“哪颗钉子长期扎着我”开始','真实痛点先存在，新锤子才有用武之地。','teal')]),
    dict(kicker='Pain', title='为什么你觉得 AI 不好用？', subtitle='不是你笨，也不是 AI 完全没用，而是期待和使用方式错位', cards=[('期望错位','把通用 AI 当万能答案机，期待一句话直接交付成品。','rose'),('磨合不足','抛一句话，不满意就换工具；连完整迭代都没跑完。','gold'),('场景错配','先想“我能问它什么”，而不是先找反复刺痛的工作问题。','violet')], callout='关键句：好用的新同事是带出来的，不是招来的；好用的 AI 也是驯化出来的，不是换来的。'),
    dict(kicker='Cognitive Load', title='AI 省掉执行时间，但新增判断负荷', subtitle='人的责任没有消失，只是位置变了', flow=[('PAST','过去累在亲手做','自己写、自己查、自己整理、自己搬运。'),('NOW','现在累在连续判断','判断方向、质量、边界、风险、是否可用。'),('SHIFT','责任前后迁移','前移到目标定义，后移到结果验收。')], quote='AI 没有让人天然更轻松，它只是把工作从执行迁移到了判断。'),
    dict(kind='section', kicker='The Real Nail', title='真正的钉子：信息差、时间差、流程摩擦', statcards=[('信息差','不知道信息在哪、事实散在群聊/文档/私聊/系统里。','gold'),('时间差','等待确认、等待同步、等待转发，流程被人肉中继卡住。','teal'),('流程摩擦','重复整理、格式不统一、同类风险反复漏。','violet')], callout='判断：这些损耗不一定靠大模型回答一句话解决。很多时候，最终靠工具、流程、模板、规则系统和自动化解决。'),
    dict(kicker='Change', title='AI 的真正变化：降低“造工具”的门槛', subtitle='很多过去只能忍掉的小痛点，现在值得重新看一遍', split=[('过去的两种选择',['找现成工具：经常不贴合自己的业务。','排研发定制：投入大、排期贵、沟通成本高。'],'rose'),('现在多了一条路',['AI 追问痛点','AI 拆流程、补需求','AI 写脚本、搭表格、做网页小工具','AI 生成 Checklist、模板、SOP'],'teal')], quote='只要一线同学能把痛点说清楚，就有机会通过 AI 和 Vibe Coding 把工具做出来。'),
    dict(kicker='Checklist', title='产品岗最常见的低效痛点', subtitle='现场可以让听众对照：哪颗钉子正在扎着我？', split=[('', ['每周重复整理数据、周报、日报','会议纪要没人转成行动项','需求文档格式总是不统一','评审问题反复漏同类风险','用户反馈散在群聊、表格、文档里'],'gold'),('', ['竞品资料难沉淀成可复用结构','流程靠人提醒，没人提醒就断','信息靠私聊传递，换个人就断档','新人不知道去哪找标准、模板、案例','每次从零问、从零写、从零整理'],'teal')]),
    dict(kind='section', kicker='Two Silicon Capabilities', title='两类硅基能力：确定性硅基 × 概率性硅基', mapnodes=[('人','目标 / 标准 / 责任','gold'),('概率性硅基','理解 / 追问 / 生成','violet'),('确定性硅基','稳定 / 流转 / 校验','teal')], quote='AI 不一定直接解决组织损耗，但 AI 可以帮你制造解决损耗的工具。'),
    dict(kicker='Division', title='确定性硅基压低损耗，概率性硅基扩大半径', table=[['角色','负责什么','不负责什么'],['人','目标、价值、标准、取舍、验收、责任','不该长期做人肉中继和重复搬运'],['概率性硅基','理解、追问、生成、整理、挑战、扩展视角','不替人做最终判断'],['确定性硅基','稳定执行、自动流转、提醒、校验、沉淀','不处理模糊取舍和价值判断']], callout='一句话：模糊探索交给概率性硅基，稳定事实和执行交给确定性工具，人守住目标、标准和责任。'),
    dict(kicker='Vibe Coding', title='Vibe Coding 不是人人都要变程序员', subtitle='它真正的意义是：让懂业务痛点的人，第一次可以直接参与制造工具', split=[('不是',['不是炫技','不是替代研发','不是每个人都去写复杂工程','不是没想清楚就让 AI 瞎做'],'violet'),('而是',['把“我知道这里很痛”推进到“我能做出一个小工具试试”。','让 AI 帮你追问需求、拆流程、生成原型、沉淀模板。','让业务一线不再只能等工具、等平台、等排期。'],'teal')], quote='Vibe Coding 不是让产品变程序员，而是让最懂钉子的人，也能参与造锤子。'),
    dict(kicker='Method', title='从痛点到工具的六步', subtitle='不要直接让 AI 写方案，先让它补齐缺失信息', steps=[('1','找钉子','哪件事反复痛、每周重复、靠人肉同步？'),('2','讲痛点','谁在何时遇到什么问题？错了会怎样？'),('3','让 AI 追问','先补上下文，不急着写代码或方案。'),('4','形成流程','哪些步骤规则化？哪些判断必须人做？'),('5','做成工具','提示词、Checklist、表格、小网页、脚本。'),('6','复用迭代','跑一次不算提效，下次复用才是提效。')]),
    dict(kicker='Demo Options', title='现场可以演示的三个小案例', subtitle='选一个真实案例跑，不要只讲概念', cards=[('会议纪要 → 行动项工具','输入会议纪要，输出“谁 / 什么时间 / 做什么 / 到什么程度”。','gold'),('方案评审 → Checklist 生成器','从用户、研发、测试、运营、制作人五个视角生成评审问题。','teal'),('周报素材 → 汇报草稿','把任务、会议、待办压成给上级看的结论、风险、下周重点。','violet')], callout='演示重点：展示“痛点 → AI 追问 → 流程化 → 可复用产物”，而不是展示某个工具多神。'),
    dict(kicker='Taming', title='如何驯化自己的专属硅基伙伴', subtitle='从“让 AI 写”升级到“让 AI 追问、质检、沉淀”', cards=[('角色','资料整理员、方案挑战者、表达润色员、流程检查员、需求追问员。','gold'),('记忆','把稳定偏好和项目背景沉下来：格式、黑话、标准、禁区。','teal'),('工作流','读材料 → 提炼观点 → 诊断结构 → 生成提纲 → 质检 → 行动项。','violet')], quote='不要只让 AI 给答案，要让 AI 帮你暴露盲区。'),
    dict(kicker='Practical Use', title='结合我们自己的工作：AI 擅长什么？', subtitle='不是替人做最终决定，而是把中间产物变得可见、可追问、可复用', cards=[('把散落信息压缩成判断材料','PM 系统、钉钉群、会议纪要、需求文档、周报日报、候选人材料。','gold'),('把空白页变成 60 分初稿','需求文档、复盘提纲、汇报材料、面试评价、方案评审意见。','teal'),('穷举、反问、找盲区','用户、研发、测试、运营、制作人多视角挑战方案。','violet'),('把一次经验沉淀成流程','Skill / SOP / 模板 / Checklist / 工作流，下一次不用重来。','blue')]),
    dict(kicker='Boundary', title='AI 不擅长：替人做价值判断和责任判断', subtitle='越贴近我们的工作，越不能神化 AI', split=[('不能替人负责',['不能替制作人决定版本取舍','不能替管理者判断人怎么培养','不能替负责人承担上线风险'],'rose'),('不能当事实数据源',['排期要看 PM 系统','日程、待办、文档状态要查系统','代码脚本要跑测试','人事评价要回到事实证据'],'gold')], callout='边界：AI 可以帮你想得更全，但不能替你负责。涉及事实、数字、排期、权限和执行结果，必须回到系统校验。'),
    dict(kicker='Action', title='行动指南：今天下班前完成一轮驯化', subtitle='选一个 30 分钟以上、以后还会重复出现的真实任务', split=[('最小行动',['写下它痛在哪里','让 AI 先问 3-5 个关键问题','判断适合模板、Checklist、小工具还是系统','出第一版产物，至少反馈两轮','把有效提示词或工具雏形存下来，明天复用一次'],'teal'),('提示词模板',['我有一个反复出现的工作痛点：\n【描述场景】','现在的做法是：\n【谁在什么时候，用什么方式处理】','请先不要直接给方案。先问我 5 个关键问题，帮我判断真正的钉子是什么、哪些可规则化、第一版最小可用方案是什么。'],'blue')]),
    dict(kind='section', kicker='Closing', title='别从“学 AI 工具”开始', quote='从找一颗真实钉子，训练一个能帮你解决它的硅基伙伴开始。', cards=[('AI 是放大器，不是灵魂','不要把思考外包给 AI。我们训练硅基伙伴，不是为了让它替我们思考，而是为了把人从重复劳动里解放出来。','gold'),('人的价值','找到真问题，定义好标准，做出取舍，并把一次解决变成可复用生产力。','teal')], callout='最终收束：概率性硅基负责理解、生成、追问和辅助判断；确定性硅基负责稳定执行、自动流转和降低损耗。判断、选择和创造，仍然是人的责任。'),
]

class DeckBuilder:
    def __init__(self):
        self.app = win32com.client.Dispatch('PowerPoint.Application')
        self.app.Visible = True
        self.pres = self.app.Presentations.Add()
        self.pres.PageSetup.SlideWidth = W
        self.pres.PageSetup.SlideHeight = H
        self.reveal_groups = []

    def add_bg(self, slide, idx):
        bg = slide.Shapes.AddShape(msoShapeRectangle, 0, 0, W, H)
        bg.Fill.ForeColor.RGB = rgb(COL['bg'])
        bg.Line.Visible = msoFalse
        bg.Name = f'bg_{idx}'
        # subtle top bar
        bar = slide.Shapes.AddShape(msoShapeRectangle, 0, 0, W, 5)
        bar.Fill.ForeColor.RGB = rgb(COL['gold'])
        bar.Line.Visible = msoFalse
        # decorative orbs
        for x,y,w,h,c,t in [(60,45,310,310,'gold',82),(900,70,280,280,'teal',84),(820,470,260,260,'violet',88)]:
            o = slide.Shapes.AddShape(msoShapeOval, x, y, w, h)
            o.Fill.ForeColor.RGB = rgb(COL[c]); o.Fill.Transparency = t / 100.0
            o.Line.Visible = msoFalse
        # grid hints
        for x in range(0, W, 64):
            ln = slide.Shapes.AddLine(x, 0, x, H)
            ln.Line.ForeColor.RGB = rgb('151B2A'); ln.Line.Transparency = 0.75; ln.Line.Weight = 0.25
        for y in range(0, H, 64):
            ln = slide.Shapes.AddLine(0, y, W, y)
            ln.Line.ForeColor.RGB = rgb('151B2A'); ln.Line.Transparency = 0.75; ln.Line.Weight = 0.25

    def text(self, slide, txt, x, y, w, h, size=24, color='text', bold=False, font='Microsoft YaHei UI', align=1, valign=1):
        sh = slide.Shapes.AddTextbox(1, x, y, w, h)
        sh.TextFrame2.MarginLeft = 0; sh.TextFrame2.MarginRight = 0; sh.TextFrame2.MarginTop = 0; sh.TextFrame2.MarginBottom = 0
        sh.TextFrame2.WordWrap = msoTrue
        tr = sh.TextFrame2.TextRange
        tr.Text = txt
        tr.Font.NameFarEast = font; tr.Font.Name = font
        tr.Font.Size = size; tr.Font.Fill.ForeColor.RGB = rgb(COL[color] if color in COL else color)
        tr.Font.Bold = msoTrue if bold else msoFalse
        tr.ParagraphFormat.Alignment = align
        sh.TextFrame2.VerticalAnchor = valign
        sh.Line.Visible = msoFalse
        sh.Fill.Visible = msoFalse
        return sh

    def add_header(self, slide, data, idx):
        self.text(slide, data.get('kicker',''), 72, 48, 900, 24, 14, 'gold', False, 'Consolas')
        self.text(slide, data['title'], 72, 78, 1040, 70, 36 if len(data['title']) < 24 else 32, 'text', True, 'SimSun')
        if data.get('subtitle'):
            self.text(slide, data['subtitle'], 72, 150, 1000, 32, 18, 'sub')
        self.text(slide, '驯化野生硅基伙伴', 72, 684, 260, 18, 11, 'muted')
        self.text(slide, f'{idx:02d} / {len(slides_data):02d}', 1160, 684, 70, 18, 11, 'muted', False, 'Consolas', align=3)
        prog = slide.Shapes.AddShape(msoShapeRectangle, 0, H-4, W*idx/len(slides_data), 4)
        prog.Fill.ForeColor.RGB = rgb(COL['teal']); prog.Line.Visible = msoFalse

    def group(self, slide, shapes, name):
        names = [s.Name for s in shapes]
        grp = slide.Shapes.Range(names).Group()
        grp.Name = name
        return grp

    def animate(self, slide, shape, after=False):
        trig = msoAnimTriggerAfterPrevious if after else msoAnimTriggerOnPageClick
        try:
            eff = slide.TimeLine.MainSequence.AddEffect(shape, msoAnimEffectFade, 0, trig)
            try:
                eff.Timing.Duration = 0.35
            except Exception:
                pass
        except Exception:
            shape.AnimationSettings.Animate = True
            shape.AnimationSettings.EntryEffect = 513  # fallback fade
        self.reveal_groups.append(shape.Name)

    def card(self, slide, x, y, w, h, title, body, accent='gold', label=None, fs_title=23, fs_body=17):
        shapes=[]
        base = slide.Shapes.AddShape(msoShapeRoundedRectangle, x, y, w, h)
        base.Fill.ForeColor.RGB = rgb(COL['card']); base.Fill.Transparency = 0.07
        base.Line.ForeColor.RGB = rgb('283245'); base.Line.Transparency = 0.10; base.Line.Weight = 1
        shapes.append(base)
        strip = slide.Shapes.AddShape(msoShapeRectangle, x, y, 5, h)
        strip.Fill.ForeColor.RGB = rgb(ACCENT.get(accent, COL['gold'])); strip.Line.Visible = msoFalse
        shapes.append(strip)
        yy = y + 22
        if label:
            shapes.append(self.text(slide, label, x+26, yy, w-44, 18, 11, 'muted', False, 'Consolas'))
            yy += 23
        if title:
            shapes.append(self.text(slide, title, x+26, yy, w-44, 34, fs_title, 'text', True, 'SimSun'))
            yy += 43
        shapes.append(self.text(slide, body, x+26, yy, w-44, max(30, h-(yy-y)-18), fs_body, 'sub'))
        return self.group(slide, shapes, f'card_{len(self.reveal_groups)+1}')

    def list_card(self, slide, x, y, w, h, title, items, accent='gold', prompt=False):
        shapes=[]
        base = slide.Shapes.AddShape(msoShapeRoundedRectangle, x, y, w, h)
        base.Fill.ForeColor.RGB = rgb('050812' if prompt else COL['card']); base.Fill.Transparency = 0 if prompt else 0.07
        base.Line.ForeColor.RGB = rgb(ACCENT.get(accent, COL['gold'])); base.Line.Transparency = 0.35; base.Line.Weight = 1
        shapes.append(base)
        strip = slide.Shapes.AddShape(msoShapeRectangle, x, y, 5, h)
        strip.Fill.ForeColor.RGB = rgb(ACCENT.get(accent, COL['gold'])); strip.Line.Visible = msoFalse
        shapes.append(strip)
        yy = y + 22
        if title:
            shapes.append(self.text(slide, title, x+26, yy, w-44, 34, 24, 'text', True, 'SimSun'))
            yy += 48
        bullet_text = '\n'.join([('• ' + it) for it in items])
        shapes.append(self.text(slide, bullet_text, x+28, yy, w-54, h-(yy-y)-18, 16 if len(items) >= 5 else 17, 'sub', False, 'Microsoft YaHei UI'))
        return self.group(slide, shapes, f'list_{len(self.reveal_groups)+1}')

    def quote(self, slide, txt, x, y, w, h, accent='gold', size=27):
        shapes=[]
        base = slide.Shapes.AddShape(msoShapeRoundedRectangle, x, y, w, h)
        base.Fill.ForeColor.RGB = rgb(ACCENT.get(accent, COL['gold'])); base.Fill.Transparency = 0.88
        base.Line.ForeColor.RGB = rgb(ACCENT.get(accent, COL['gold'])); base.Line.Transparency = 0.45; base.Line.Weight = 1
        shapes.append(base)
        strip = slide.Shapes.AddShape(msoShapeRectangle, x, y, 6, h)
        strip.Fill.ForeColor.RGB = rgb(ACCENT.get(accent, COL['gold'])); strip.Line.Visible = msoFalse
        shapes.append(strip)
        shapes.append(self.text(slide, txt, x+28, y+16, w-52, h-24, size, 'text', False, 'SimSun'))
        return self.group(slide, shapes, f'quote_{len(self.reveal_groups)+1}')

    def callout(self, slide, txt, y=604):
        g = self.quote(slide, txt, 72, y, 1136, 70, 'teal', 18)
        return g

    def build_slide(self, idx, data):
        slide = self.pres.Slides.Add(idx, ppLayoutBlank)
        self.add_bg(slide, idx)
        if data.get('kind') == 'cover':
            self.text(slide, data['kicker'], 92, 105, 900, 24, 15, 'teal', False, 'Consolas')
            self.text(slide, data['title'], 92, 150, 760, 180, 64, 'text', True, 'SimSun')
            self.text(slide, data['subtitle'], 92, 350, 830, 76, 25, 'sub')
            self.text(slide, data['footer'], 92, 604, 680, 42, 15, 'muted')
            orb = slide.Shapes.AddShape(msoShapeOval, 952, 430, 220, 220)
            orb.Fill.ForeColor.RGB = rgb(COL['teal']); orb.Fill.Transparency = 0.30
            orb.Line.ForeColor.RGB = rgb(COL['gold']); orb.Line.Transparency = 0.30
            self.text(slide, f'{idx:02d} / {len(slides_data):02d}', 1130, 672, 80, 18, 11, 'muted', False, 'Consolas', align=3)
            prog = slide.Shapes.AddShape(msoShapeRectangle, 0, H-4, W*idx/len(slides_data), 4)
            prog.Fill.ForeColor.RGB = rgb(COL['teal']); prog.Line.Visible = msoFalse
            return
        self.add_header(slide, data, idx)
        top = 205
        # components per data type
        if data.get('quote') and not data.get('cards') and not data.get('statcards') and not data.get('mapnodes'):
            g = self.quote(slide, data['quote'], 112, 226, 1056, 110 if data.get('kind') == 'section' else 90, 'gold', 30 if data.get('kind')=='section' else 25)
            self.animate(slide, g)
        elif data.get('quote') and data.get('cards'):
            g = self.quote(slide, data['quote'], 92, top, 1096, 100, 'gold', 26)
            self.animate(slide, g)
            cards = data['cards']
            cols = len(cards)
            cw = (1096 - (cols-1)*18)/cols
            y = top + 128
            for i,(a,b,c) in enumerate(cards):
                cg = self.card(slide, 92+i*(cw+18), y, cw, 180 if idx != 18 else 150, a, b, c, label=a if a.startswith('Question') else None, fs_title=21 if cols>=4 else 24, fs_body=16 if cols>=4 else 17)
                self.animate(slide, cg)
            if data.get('callout'):
                self.animate(slide, self.callout(slide, data['callout'], 614))
        elif data.get('cards'):
            cards = data['cards']; cols = 4 if len(cards)==4 else 3
            cw = (1096 - (cols-1)*18)/cols
            ch = 210 if len(cards) <= 3 else 170
            y = top + 20
            for i,(a,b,c) in enumerate(cards):
                row = i//cols; col=i%cols
                cg = self.card(slide, 92+col*(cw+18), y+row*(ch+20), cw, ch, a, b, c, fs_title=21 if cols>=4 else 24, fs_body=16 if cols>=4 else 17)
                self.animate(slide, cg)
            if data.get('callout'):
                self.animate(slide, self.callout(slide, data['callout'], 604))
        elif data.get('flow'):
            x = 88; y=240; cw=306; gap=64
            for i,(label,t,b) in enumerate(data['flow']):
                cg = self.card(slide, x+i*(cw+gap), y, cw, 190, t, b, ['gold','violet','teal'][i], label=label)
                self.animate(slide, cg)
                if i<2:
                    arr = self.text(slide, '→', x+cw+i*(cw+gap)+15, y+66, 40, 50, 40, 'gold', True, 'SimSun', align=2)
                    self.animate(slide, arr, after=True)
            q = self.quote(slide, data['quote'], 132, 492, 1016, 70, 'gold', 23)
            self.animate(slide, q)
        elif data.get('statcards'):
            cw = (1096-36)/3
            for i,(t,b,c) in enumerate(data['statcards']):
                cg = self.card(slide, 92+i*(cw+18), 245, cw, 190, t, b, c, fs_title=38, fs_body=17)
                self.animate(slide, cg)
            self.animate(slide, self.callout(slide, data['callout'], 548))
        elif data.get('split'):
            splits=data['split']; cw=(1096-22)/2
            for i,(t,items,c) in enumerate(splits):
                prompt = ('提示词' in t)
                cg = self.list_card(slide, 92+i*(cw+22), 230, cw, 310 if idx != 17 else 350, t, items, c, prompt=prompt)
                self.animate(slide, cg)
            if data.get('quote'):
                self.animate(slide, self.quote(slide, data['quote'], 112, 585, 1056, 64, 'gold', 22))
            if data.get('callout'):
                self.animate(slide, self.callout(slide, data['callout'], 604))
        elif data.get('mapnodes'):
            # connector first as after previous with first node? better reveal nodes then quote
            positions=[(135,270,210,210),(524,245,230,230),(910,270,230,230)]
            for i,((t,b,c),(x,y,w,h)) in enumerate(zip(data['mapnodes'],positions)):
                shapes=[]
                o=slide.Shapes.AddShape(msoShapeOval,x,y,w,h)
                o.Fill.ForeColor.RGB=rgb(ACCENT[c]); o.Fill.Transparency=0.88; o.Line.ForeColor.RGB=rgb(ACCENT[c]); o.Line.Transparency=0.15; o.Line.Weight=1.5
                shapes.append(o)
                shapes.append(self.text(slide,t+'\n'+b,x+22,y+64,w-44,95,24 if i else 27, c, True, 'SimSun', align=2))
                cg=self.group(slide,shapes,f'map_{i+1}')
                self.animate(slide,cg)
            line=slide.Shapes.AddLine(340,375,910,375); line.Line.ForeColor.RGB=rgb(COL['gold']); line.Line.Weight=3; line.Line.Transparency=0.20
            self.animate(slide,line,after=True)
            self.animate(slide,self.quote(slide,data['quote'],160,555,960,70,'gold',22))
        elif data.get('table'):
            table=data['table']; rows=len(table); cols=len(table[0]); x=92; y=225; tw=1096; rh=62
            groups=[]
            widths=[180,470,446]
            for r,row in enumerate(table):
                shapes=[]
                xx=x
                for c,cell in enumerate(row):
                    rect=slide.Shapes.AddShape(msoShapeRectangle,xx,y+r*rh,widths[c],rh)
                    rect.Fill.ForeColor.RGB=rgb(COL['card2'] if r==0 else COL['card']); rect.Fill.Transparency=0 if r==0 else 0.10
                    rect.Line.ForeColor.RGB=rgb('2B3447'); rect.Line.Weight=.75
                    shapes.append(rect)
                    shapes.append(self.text(slide,cell,xx+14,y+r*rh+13,widths[c]-24,rh-18,14 if r==0 else 16,'gold' if r==0 else ('text' if c==0 else 'sub'),r==0 or c==0,'Microsoft YaHei UI'))
                    xx+=widths[c]
                g=self.group(slide,shapes,f'table_row_{r}')
                if r>0: self.animate(slide,g)
            self.animate(slide,self.callout(slide,data['callout'],548))
        elif data.get('steps'):
            steps=data['steps']; cw=(1096-5*10)/6; y=255
            for i,(n,t,b) in enumerate(steps):
                shapes=[]; x=92+i*(cw+10)
                base=slide.Shapes.AddShape(msoShapeRoundedRectangle,x,y,cw,190)
                base.Fill.ForeColor.RGB=rgb(COL['card']); base.Fill.Transparency=0.07; base.Line.ForeColor.RGB=rgb('2B3447')
                shapes.append(base)
                circ=slide.Shapes.AddShape(msoShapeOval,x+18,y+18,36,36)
                circ.Fill.Visible=msoFalse; circ.Line.ForeColor.RGB=rgb(COL['gold']); circ.Line.Weight=1.2
                shapes.append(circ)
                shapes.append(self.text(slide,n,x+18,y+24,36,20,13,'gold',True,'Consolas',align=2))
                shapes.append(self.text(slide,t,x+18,y+68,cw-32,28,19,'text',True,'SimSun'))
                shapes.append(self.text(slide,b,x+18,y+104,cw-30,70,13,'sub'))
                cg=self.group(slide,shapes,f'step_{n}')
                self.animate(slide,cg)
        return slide

    def finish(self):
        if OUT.exists():
            OUT.unlink()
        self.pres.SaveAs(str(OUT), ppSaveAsOpenXMLPresentation)
        # export first few/all slides to PNG for visual sanity
        export_base = str(EXPORT_DIR / 'slide')
        try:
            self.pres.Export(str(EXPORT_DIR), 'PNG', 1280, 720)
        except Exception as e:
            print('EXPORT_WARN', e)
        self.pres.Close()
        self.app.Quit()

b = DeckBuilder()
for i,d in enumerate(slides_data, start=1):
    b.build_slide(i,d)
b.finish()
print('WROTE', OUT)
print('SLIDES', len(slides_data))
print('REVEAL_GROUPS', len(b.reveal_groups))
print('PREVIEW_DIR', EXPORT_DIR)
