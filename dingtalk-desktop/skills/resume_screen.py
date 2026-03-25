# -*- coding: utf-8 -*-
"""
简历 AI 初筛技能

触发条件：招聘群内收到 ct=502 PDF 文件消息
流程：
  1. 从本地路径读取 PDF 文本（DingTalk 收件时已缓存到磁盘）
  2. 按文件名/内容猜测岗位，加载对应初筛清单
  3. 调 LLM 做初筛，输出结论 + 要点
  4. 发文字消息到原群
  5. 写入 DB
"""
import os
import sys
import json
import re
import urllib.request

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT     = os.path.join(_THIS_DIR, '..')
_CHECKLIST_DIR = os.path.join(_ROOT, '..', 'performeval', '面试', '简历初筛')

sys.path.insert(0, _ROOT)
from db.store import is_resume_processed, save_resume_result

DAEMON_URL = os.environ.get('DINGTALK_DAEMON_URL', 'http://127.0.0.1:19200')

# ── LLM 配置 ─────────────────────────────────────────────────
# 优先级：RESUME_LLM_* > LLM_* > palace/.env > 硬编码默认值

_DEFAULT_MODEL = 'claude-opus-4.6'

def _resolve_llm():
    key   = os.environ.get('RESUME_LLM_API_KEY') or os.environ.get('LLM_API_KEY', '')
    base  = os.environ.get('RESUME_LLM_API_BASE') or os.environ.get('LLM_API_BASE', '')
    model = os.environ.get('RESUME_LLM_MODEL') or os.environ.get('LLM_MODEL', '')
    if not key:
        palace_env = os.path.join(_ROOT, '..', 'palace', '.env')
        if os.path.exists(palace_env):
            with open(palace_env, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#') or '=' not in line:
                        continue
                    k, v = line.split('=', 1)
                    k, v = k.strip(), v.strip()
                    if k == 'PALACE_API_KEY' and not key:   key   = v
                    elif k == 'PALACE_API_BASE' and not base: base  = v
                    elif k == 'PALACE_MODEL' and not model:  model = v
    return key, base or 'https://api.openai.com/v1', model or _DEFAULT_MODEL


# ── 岗位猜测 + 应届识别 ───────────────────────────────────────

_ROLE_KEYWORDS = {
    '运营策划': ['运营', '活动运营', '游戏运营', 'ops'],
    '系统策划': ['系统策划', '系统', '数值', 'sys'],
    '战斗策划': ['战斗', '关卡', 'pvp', 'pve', 'combat'],
    'PM':       ['pm', 'pmo', '项目管理', '项目经理', '管线'],
}

# 应届判断：毕业年份在当前年份 ±1 范围内，或含应届关键词
import datetime as _dt
_CURRENT_YEAR = _dt.datetime.now().year
_FRESH_YEAR_RANGE = {str(y) for y in range(_CURRENT_YEAR - 1, _CURRENT_YEAR + 3)}
_FRESH_KEYWORDS = ['应届', '在读', '预计毕业', '即将毕业', 'fresh graduate', '届毕业生']

def _is_fresh_graduate(file_name: str, text: str) -> bool:
    """简单启发式判断是否为应届/准应届候选人。"""
    combined = (file_name + ' ' + text[:1000]).lower()
    for kw in _FRESH_KEYWORDS:
        if kw in combined:
            return True
    # 检测毕业年份：近两年或未来一年
    for yr in _FRESH_YEAR_RANGE:
        if yr in combined and ('届' in combined or '毕业' in combined or 'graduate' in combined):
            return True
    return False

def _guess_role(file_name: str, text: str) -> str:
    name_lower = file_name.lower()
    text_head  = text[:500].lower()
    for role, kws in _ROLE_KEYWORDS.items():
        for kw in kws:
            if kw in name_lower or kw in text_head:
                return role
    return '未知'


# ── 加载初筛清单 ──────────────────────────────────────────────

def _load_checklist(role: str, is_fresh: bool = False) -> str:
    # 应届生：优先加载应届清单，岗位清单作为补充附后
    fresh_path = os.path.join(_CHECKLIST_DIR, '简历初筛清单_应届生.md')
    role_mapping = {
        '运营策划': '简历初筛清单_运营策划.md',
        '系统策划': '简历初筛清单_系统策划.md',
        '战斗策划': '简历初筛清单_战斗策划.md',
    }

    def _read(path):
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        return ''

    if is_fresh:
        fresh_content = _read(fresh_path)
        role_fname = role_mapping.get(role)
        role_content = _read(os.path.join(_CHECKLIST_DIR, role_fname)) if role_fname else ''
        if role_content:
            return fresh_content + '\n\n---\n\n【岗位补充参考（非硬性要求）】\n' + role_content
        return fresh_content

    fname = role_mapping.get(role)
    if not fname:
        return ''
    return _read(os.path.join(_CHECKLIST_DIR, fname))


# ── LLM 调用 ─────────────────────────────────────────────────

def _call_llm(prompt: str, system: str = '') -> str:
    key, base, model = _resolve_llm()
    if not key:
        return '[LLM未配置：缺少 API Key]'

    url = base.rstrip('/') + '/chat/completions'
    messages = []
    if system:
        messages.append({'role': 'system', 'content': system})
    messages.append({'role': 'user', 'content': prompt})

    payload = json.dumps({
        'model': model,
        'messages': messages,
        'max_tokens': 1200,
        'temperature': 0.3,
    }).encode('utf-8')

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + key,
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        return data['choices'][0]['message']['content'].strip()
    except Exception as e:
        return f'[LLM调用失败: {e}]'


def _build_prompt(resume_text: str, role: str, checklist: str,
                  is_fresh: bool = False) -> tuple:
    if is_fresh:
        system = (
            '你是一位游戏公司的人力资源专家，正在筛选应届/准应届候选人。'
            '应届生缺乏生产经验是正常的，不要以社招标准卡年限或产出项目数量。'
            '核心判断维度：思维逻辑、游戏热情、学习速度、协作意识。'
            '若有亮点但信息不足，结论给"待定"而非"不通过"，建议初试核实。'
            '输出格式严格遵守要求，不要添加额外说明。'
        )
        checklist_section = (
            f'\n\n【应届生初筛清单】\n{checklist}\n' if checklist
            else f'\n\n【候选人类型】应届/准应届（无专项清单，请按思维/潜力综合判断）\n'
        )
        output_hint = (
            '请严格按如下格式输出（不要多余文字）：\n'
            '结论：[通过 / 待定 / 不通过]\n'
            '核心判定：[一句话≤20字，说明该结论的决定性依据，聚焦思维/潜力/热情]\n'
            '理由：[1-2句话，说明亮点或不足]\n'
            '潜力信号：[能体现思维/学习力/游戏热情的具体表现，逗号分隔，没有则写"无"]\n'
            '红线：[触发的红线，逗号分隔，没有则写"无"]\n'
        )
    else:
        system = (
            '你是一位游戏公司的人力资源专家，擅长系统策划岗简历初筛。\n'
            '本次筛选的目标定级为 **L3 系统策划**，请严格按以下标准评估。\n\n'
            '【L3 核心能力要求】\n'
            '1. 多系统耦合：有设计多个系统之间数据流转、接口定义、耦合边界的经验\n'
            '2. 框架扩展：能从具体系统中抽象可复用框架，设计可扩展的系统架构\n'
            '3. 快轨复用：能设计配置化/模板化机制，让同类系统快速搭建而非每次从零开始\n'
            '4. WHAT->HOW->BUILD 全链路：能独立定义需求(WHAT)、拆解方案(HOW)、'
            '产出 Spec 级文档让程序直接开发(BUILD)\n'
            '5. Spec 级文档：有明确的方案文档/需求规格/配表设计产出经验\n\n'
            '【L3 vs L2 判定规则】\n'
            '- 简历中有多系统耦合/框架设计/架构扩展证据 -> 可能达到 L3\n'
            '- 简历仅体现单系统独立完成全流程，无跨系统架构证据 -> L2 水平\n'
            '- 简历以"参与/协助"为主、无独立主导经验 -> L1 水平\n'
            '- L2 扎实但 L3 证据不足 -> 结论给"待定"，注明"L2扎实、L3待面试验证"\n'
            '- 简历无法体现 L2 以上能力 -> 结论给"不通过"\n\n'
            '【禁止臆测】简历中没有明确的需求定义、架构设计、框架抽象等表述时，'
            '不得判定为"体现 L3 思维"。\n'
            '输出格式严格遵守要求，不要添加额外说明。'
        )
        checklist_section = (
            f'\n\n【初筛清单 · {role}】\n{checklist}\n' if checklist
            else f'\n\n【岗位】{role}（无专项清单，请综合判断）\n'
        )
        output_hint = (
            '请严格按如下格式输出（不要多余文字）：\n'
            '结论：[通过 / 待定 / 不通过]\n'
            '核心判定：[一句话<=20字，说明该结论的决定性原因]\n'
            'L3评估：[简历是否体现L3核心能力（多系统耦合/框架扩展/快轨复用/Spec文档），'
            '<=40字，无证据则写"简历未体现L3架构能力"]\n'
            '定级判断：[L3可能 / L2扎实L3待验 / L2 / L1+ / 不达标]\n'
            '理由：[1-2句话，聚焦最关键的依据]\n'
            '亮点：[命中的优先信号，逗号分隔，没有则写"无"]\n'
            '红线：[触发的红线，逗号分隔，没有则写"无"]\n'
        )

    label = f'应届生（目标岗位：{role}）' if is_fresh else role
    user = (
        f'请对以下简历进行初筛，候选人类型：{label}。'
        f'{checklist_section}'
        '\n\n【简历内容】\n' + resume_text[:4000] +
        '\n\n' + output_hint
    )
    return system, user


def _parse_llm_output(text: str) -> dict:
    """从 LLM 输出中解析结构化字段"""
    result = {
        'verdict': '待定',
        'core': '',
        'reason': '',
        'highlights': '',
        'redlines': '',
        'focus': '',
        'potential': '',   # 应届生专用：潜力信号
        'l3_assess': '',   # 社招专用：L3 架构能力评估
        'level': '',       # 社招专用：定级判断
    }
    patterns = {
        'verdict':    r'结论[：:]\s*(.+)',
        'core':       r'核心判定[：:]\s*(.+)',
        'reason':     r'理由[：:]\s*(.+)',
        'highlights': r'亮点[：:]\s*(.+)',
        'redlines':   r'红线[：:]\s*(.+)',
        'focus':      r'建议考察[：:]\s*(.+)',
        'potential':  r'潜力信号[：:]\s*(.+)',
        'l3_assess':  r'L3评估[：:]\s*(.+)',
        'level':      r'定级判断[：:]\s*(.+)',
    }
    for key, pat in patterns.items():
        m = re.search(pat, text)
        if m:
            result[key] = m.group(1).strip()
    return result


# ── 加载 webhook 配置 ────────────────────────────────────────

def _load_resume_webhook() -> str:
    # 优先从 webhook_config.json 的 resume_notify 读取，无则回退 digest_config
    try:
        sys.path.insert(0, _ROOT)
        from lib.utils import get_webhook_url
        fallback = ''
        try:
            with open(os.path.join(_ROOT, 'digest_config.json'), 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            fallback = cfg.get('resume_notify_webhook', '')
        except Exception:
            pass
        return get_webhook_url('resume_notify', fallback)
    except Exception:
        return ''


# ── 发消息（机器人 webhook） ──────────────────────────────────

def _send_via_webhook(title: str, text: str) -> bool:
    """通过钉钉机器人 webhook 发送 markdown 消息（关键字：小秘书提醒）。"""
    webhook_url = _load_resume_webhook()
    if not webhook_url:
        print('[resume_screen] 未配置 resume_notify_webhook，跳过发送')
        return False
    payload = json.dumps(
        {'msgtype': 'markdown', 'markdown': {'title': title, 'text': text}},
        ensure_ascii=False,
    ).encode('utf-8')
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
        ok = result.get('errcode', -1) == 0
        if not ok:
            print(f'[resume_screen] webhook 返回: {result}')
        return ok
    except Exception as e:
        print(f'[resume_screen] webhook 发送失败: {e}')
        return False


def _load_resume_template() -> dict:
    # 优先读统一模板文件，兼容旧的 version_digest_template.json
    for fname in ('message_templates.json', 'version_digest_template.json'):
        tpl_path = os.path.join(_ROOT, fname)
        if not os.path.exists(tpl_path):
            continue
        try:
            with open(tpl_path, 'r', encoding='utf-8') as f:
                return json.load(f).get('resume_screen', {})
        except Exception as e:
            print(f'[resume_screen] 模板加载失败({fname}): {e}')
    return {}

_DEFAULT_TEMPLATE = {
    'title': {
        'pass':    '✅ 简历初筛通过 | {candidate} · {role}',
        'pending': '❓ 简历初筛待定 | {candidate} · {role}',
        'fail':    '❌ 简历初筛不通过 | {candidate} · {role}',
    },
    'lines': [
        {'key': 'core',       'show': True,  'tpl': '** **核心判定：** {core}'},
        {'key': 'l3_assess',  'show': True,  'tpl': '** **L3评估：** {l3_assess}'},
        {'key': 'level',      'show': True,  'tpl': '** **定级判断：** {level}'},
        {'key': 'highlights', 'show': True,  'tpl': '** **亮点：** {highlights}'},
        {'key': 'redlines',   'show': True,  'tpl': '** **红线：** {redlines}'},
        {'key': 'reason',     'show': True,  'tpl': '** **详细理由：** {reason}'},
    ],
}


def _format_reply(file_name: str, role: str, parsed: dict,
                  is_fresh: bool = False, source_name: str = '') -> tuple:
    """从 message_templates.json 读模板，返回 (title, markdown_text)。"""
    tpl = _load_resume_template() or _DEFAULT_TEMPLATE
    candidate = file_name.replace('.pdf', '').replace('.PDF', '')

    verdict_key = {'通过': 'pass', '待定': 'pending', '不通过': 'fail'}.get(parsed['verdict'], 'pending')
    title_section = 'title_fresh' if is_fresh else 'title'
    title_tpl = tpl.get(title_section, tpl.get('title', _DEFAULT_TEMPLATE['title'])).get(
        verdict_key, '{candidate} · {role}')
    title = title_tpl.format(candidate=candidate, role=role)

    ctx = {
        'candidate':  candidate,
        'role':       role,
        'source':     source_name,
        'core':       parsed.get('core', ''),
        'l3_assess':  parsed.get('l3_assess', ''),
        'level':      parsed.get('level', ''),
        'highlights': parsed.get('highlights', ''),
        'potential':  parsed.get('potential', ''),
        'redlines':   parsed.get('redlines', ''),
        'reason':     parsed.get('reason', ''),
    }

    lines_key = 'fresh_lines' if is_fresh else 'lines'
    line_defs = tpl.get(lines_key, _DEFAULT_TEMPLATE['lines'])

    body_lines = [f'### {title}', '---']

    # 来源行（有值才显示）
    if source_name:
        source_tpl = tpl.get('source_line', '► **来源：** {source}')
        body_lines.append('\n' + source_tpl.format(**ctx))

    for item in line_defs:
        if not item.get('show', True):
            continue
        val = ctx.get(item['key'], '')
        if not val or val == '无':
            continue
        body_lines.append('\n' + item['tpl'].format(**ctx))

    body_lines.append('\n---')
    body_lines.append(_load_footer())
    return title, '\n'.join(body_lines)


def _load_footer() -> str:
    for fname in ('message_templates.json', 'version_digest_template.json'):
        tpl_path = os.path.join(_ROOT, fname)
        if not os.path.exists(tpl_path):
            continue
        try:
            with open(tpl_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return (data.get('resume_screen', {}).get('footer')
                    or data.get('footer', '*小秘书提醒*'))
        except Exception:
            pass
    return '*小秘书提醒*'


# ── 本地文件查找 ───────────────────────────────────────────────

_SEARCH_DIRS = [
    'D:/DownLoads',
    'D:/DownLoads/DingDingDownLoads',
    'D:/Downloads',
    os.path.expanduser('~/Downloads'),
]

def _trigger_download(cid: str, msg_id: str, file_name: str) -> str:
    """调用 daemon /trigger_download，让 DingTalk 自动下载文件，返回本地路径。"""
    import urllib.request
    daemon_url = os.environ.get('DINGTALK_DAEMON_URL', 'http://127.0.0.1:19200')
    payload = json.dumps({'cid': cid, 'msg_id': msg_id, 'file_name': file_name, 'wait': 15}).encode('utf-8')
    req = urllib.request.Request(
        daemon_url.rstrip('/') + '/trigger_download',
        data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
        path = data.get('file_path', '')
        if path:
            print(f'[resume_screen] trigger_download 成功: {path}')
        return path
    except Exception as e:
        print(f'[resume_screen] trigger_download 失败: {e}')
        return ''


def _find_local_pdf(file_name: str) -> str:
    """在常见下载目录里按文件名搜索 PDF，找到返回路径，否则返回空字符串。"""
    for base in _SEARCH_DIRS:
        if not os.path.isdir(base):
            continue
        # 精确匹配
        exact = os.path.join(base, file_name)
        if os.path.exists(exact):
            return exact
        # 遍历一层子目录
        try:
            for entry in os.scandir(base):
                if entry.is_dir():
                    candidate = os.path.join(entry.path, file_name)
                    if os.path.exists(candidate):
                        return candidate
        except OSError:
            pass
    return ''


# ── 主入口 ────────────────────────────────────────────────────

def process_resume_message(msg_id: str, group_cid: str, sender_uid: str,
                            file_name: str, file_path: str, source_name: str = ''):
    """
    处理一条 ct=502 简历消息。
    返回值：
      True  — 处理完成，结论=通过，已回复并写 DB
      False — 结论为待定/不通过，已完成 LLM 判断，不回复（不重试）
      None  — 文件未在本地找到，下次 poll 重试
    """
    if is_resume_processed(msg_id):
        return False

    print(f'[resume_screen] 开始处理: {file_name}')

    # 1. 读 PDF — file_path 可能为空（文件未被打开过）或路径不存在（未下载）
    #    fallback：按文件名在常见下载目录里搜索
    if not file_path or not os.path.exists(file_path):
        file_path = _find_local_pdf(file_name)
    if not file_path:
        # 尝试通过 daemon 触发 DingTalk 下载（需要群窗口在 DingTalk 中保持打开）
        file_path = _trigger_download(group_cid, msg_id, file_name)
    if not file_path:
        print(f'[resume_screen] 文件未在本地找到（待下载）: {file_name}')
        return None   # 不写 DB，下次 poll 继续重试

    try:
        import pdfplumber
        with pdfplumber.open(file_path) as pdf:
            resume_text = '\n'.join(
                (page.extract_text() or '') for page in pdf.pages
            ).strip()
    except Exception as e:
        print(f'[resume_screen] PDF读取失败: {e}')
        save_resume_result(msg_id, group_cid, sender_uid, file_name, file_path,
                           '未知', '跳过', f'PDF读取失败:{e}', reply_sent=False)
        return False

    if len(resume_text) < 50:
        print('[resume_screen] PDF内容过短，可能是扫描件')
        save_resume_result(msg_id, group_cid, sender_uid, file_name, file_path,
                           '未知', '跳过', 'PDF内容过短/扫描件', reply_sent=False)
        return False

    # 2. 猜岗位 + 应届识别 + 加载清单
    role = _guess_role(file_name, resume_text)
    is_fresh = _is_fresh_graduate(file_name, resume_text)
    checklist = _load_checklist(role, is_fresh=is_fresh)
    tag = '应届' if is_fresh else '社招'
    print(f'[resume_screen] 猜测岗位: {role}, 候选人类型: {tag}, 清单: {"有" if checklist else "无"}')

    # 3. LLM 初筛
    system_prompt, user_prompt = _build_prompt(resume_text, role, checklist, is_fresh=is_fresh)
    llm_output = _call_llm(user_prompt, system=system_prompt)
    print(f'[resume_screen] LLM输出:\n{llm_output}')

    # 4. 解析结果
    parsed = _parse_llm_output(llm_output)
    summary = f"结论:{parsed['verdict']} | 理由:{parsed['reason']} | 亮点:{parsed['highlights']}"

    # 5. 发消息 + 入库
    #    通过 → 详细格式；待定/不通过 → ❓/❌ 通知（含核心判定）
    if parsed['verdict'] != '通过':
        title, notify_text = _format_reply(file_name, role, parsed, is_fresh=is_fresh, source_name=source_name)
        sent = _send_via_webhook(title, notify_text)
        print(f'[resume_screen] 结论={parsed["verdict"]}，通知已发: {"成功" if sent else "失败"}')
        save_resume_result(msg_id, group_cid, sender_uid, file_name, file_path,
                           role, parsed['verdict'], summary, reply_sent=sent)
        return False

    title, reply_text = _format_reply(file_name, role, parsed, is_fresh=is_fresh, source_name=source_name)
    sent = _send_via_webhook(title, reply_text)
    print(f'[resume_screen] 消息发送: {"成功" if sent else "失败"}')

    # 6. 写 DB
    save_resume_result(msg_id, group_cid, sender_uid, file_name, file_path,
                       role, parsed['verdict'], summary, reply_sent=sent)

    return True
