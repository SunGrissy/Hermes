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

# ── LLM 配置（复用 report_digest 的解析逻辑） ─────────────────

def _resolve_llm():
    key  = os.environ.get('LLM_API_KEY', '')
    base = os.environ.get('LLM_API_BASE', '')
    model = os.environ.get('LLM_MODEL', '')
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
    return key, base or 'https://api.openai.com/v1', model or 'gpt-4o-mini'


# ── 岗位猜测 ────────────────────────────────────────────────

_ROLE_KEYWORDS = {
    '运营策划': ['运营', '活动运营', '游戏运营', 'ops'],
    '系统策划': ['系统策划', '系统', '数值', 'sys'],
    '战斗策划': ['战斗', '关卡', 'pvp', 'pve', 'combat'],
    'PM':       ['pm', 'pmo', '项目管理', '项目经理', '管线'],
}

def _guess_role(file_name: str, text: str) -> str:
    name_lower = file_name.lower()
    text_head  = text[:500].lower()
    for role, kws in _ROLE_KEYWORDS.items():
        for kw in kws:
            if kw in name_lower or kw in text_head:
                return role
    return '未知'


# ── 加载初筛清单 ──────────────────────────────────────────────

def _load_checklist(role: str) -> str:
    mapping = {
        '运营策划': '简历初筛清单_运营策划.md',
        '系统策划': '简历初筛清单_系统策划.md',
        '战斗策划': '简历初筛清单_战斗策划.md',
    }
    fname = mapping.get(role)
    if not fname:
        return ''
    path = os.path.join(_CHECKLIST_DIR, fname)
    if not os.path.exists(path):
        return ''
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


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
        'max_tokens': 800,
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


def _build_prompt(resume_text: str, role: str, checklist: str) -> tuple:
    system = (
        '你是一位游戏公司的人力资源专家，擅长简历初筛。'
        '请根据提供的初筛清单和简历内容，给出客观、简洁的初筛结论。'
        '输出格式严格遵守要求，不要添加额外说明。'
    )
    checklist_section = (
        f'\n\n【初筛清单 · {role}】\n{checklist}\n' if checklist
        else f'\n\n【岗位】{role}（无专项清单，请综合判断）\n'
    )
    user = (
        f'请对以下简历进行初筛，岗位：{role}。'
        f'{checklist_section}'
        '\n\n【简历内容】\n' + resume_text[:4000] +
        '\n\n'
        '请严格按如下格式输出（不要多余文字）：\n'
        '结论：[通过 / 待定 / 不通过]\n'
        '理由：[1-2句话，聚焦最关键的依据]\n'
        '亮点：[命中的优先信号，逗号分隔，没有则写"无"]\n'
        '红线：[触发的红线，逗号分隔，没有则写"无"]\n'
    )
    return system, user


def _parse_llm_output(text: str) -> dict:
    """从 LLM 输出中解析结构化字段"""
    result = {
        'verdict': '待定',
        'reason': '',
        'highlights': '',
        'redlines': '',
        'focus': '',
    }
    patterns = {
        'verdict':    r'结论[：:]\s*(.+)',
        'reason':     r'理由[：:]\s*(.+)',
        'highlights': r'亮点[：:]\s*(.+)',
        'redlines':   r'红线[：:]\s*(.+)',
        'focus':      r'建议考察[：:]\s*(.+)',
    }
    for key, pat in patterns.items():
        m = re.search(pat, text)
        if m:
            result[key] = m.group(1).strip()
    return result


# ── 发消息 ────────────────────────────────────────────────────

def _send_to_group(cid: str, text: str) -> bool:
    payload = json.dumps({'cid': cid, 'message': text}, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(
        DAEMON_URL.rstrip('/') + '/send',
        data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
        return result.get('success', False)
    except Exception as e:
        print(f'[resume_screen] 发消息失败: {e}')
        return False


def _format_reply(file_name: str, role: str, parsed: dict) -> str:
    verdict_mark = {'通过': '[通过]', '待定': '[待定]', '不通过': '[不通过]'}.get(
        parsed['verdict'], '[待定]')
    lines = [
        f'简历初筛 | {file_name}',
        f'岗位推断：{role}',
        f'结论：{verdict_mark}',
    ]
    if parsed['reason']:
        lines.append(f'理由：{parsed["reason"]}')
    if parsed['highlights'] and parsed['highlights'] != '无':
        lines.append(f'亮点：{parsed["highlights"]}')
    if parsed['redlines'] and parsed['redlines'] != '无':
        lines.append(f'红线：{parsed["redlines"]}')
    return '\n'.join(lines)


# ── 主入口 ────────────────────────────────────────────────────

def process_resume_message(msg_id: str, group_cid: str, sender_uid: str,
                            file_name: str, file_path: str) -> bool:
    """
    处理一条 ct=502 简历消息。
    返回 True 表示成功处理并回复，False 表示跳过（已处理或失败）。
    """
    if is_resume_processed(msg_id):
        return False

    print(f'[resume_screen] 开始处理: {file_name}')

    # 1. 读 PDF
    if not os.path.exists(file_path):
        print(f'[resume_screen] 文件不存在: {file_path}')
        save_resume_result(msg_id, group_cid, sender_uid, file_name, file_path,
                           '未知', '跳过', '文件不存在', reply_sent=False)
        return False

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

    # 2. 猜岗位 + 加载清单
    role = _guess_role(file_name, resume_text)
    checklist = _load_checklist(role)
    print(f'[resume_screen] 猜测岗位: {role}, 清单: {"有" if checklist else "无"}')

    # 3. LLM 初筛
    system_prompt, user_prompt = _build_prompt(resume_text, role, checklist)
    llm_output = _call_llm(user_prompt, system=system_prompt)
    print(f'[resume_screen] LLM输出:\n{llm_output}')

    # 4. 解析结果
    parsed = _parse_llm_output(llm_output)
    summary = f"结论:{parsed['verdict']} | 理由:{parsed['reason']} | 亮点:{parsed['highlights']}"

    # 5. 仅「通过」时发消息并入库，其余丢弃
    if parsed['verdict'] != '通过':
        print(f'[resume_screen] 结论={parsed["verdict"]}，丢弃')
        return False

    reply_text = _format_reply(file_name, role, parsed)
    sent = _send_to_group(group_cid, reply_text)
    print(f'[resume_screen] 消息发送: {"成功" if sent else "失败"}')

    # 6. 写 DB（仅通过）
    save_resume_result(msg_id, group_cid, sender_uid, file_name, file_path,
                       role, parsed['verdict'], summary, reply_sent=sent)

    return True
