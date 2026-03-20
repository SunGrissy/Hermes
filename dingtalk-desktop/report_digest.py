# -*- coding: utf-8 -*-
"""
daily report digest -- fetch team daily reports, analyze quality via LLM,
send summary to producer via dingtalk-daemon.

Usage:
    py report_digest.py                         # analyze today's reports
    py report_digest.py --date 2026-03-15       # analyze specific date
    py report_digest.py --dry-run               # print summary, don't send
    py report_digest.py --output digest.md      # save to file
    py report_digest.py --date ... --full-content --notify-default
        # progress pings to webhook_config.json \"default\" during fetch/analyze/send
"""
import os
import sys
import io
import json
import time
import argparse
import urllib.request
from datetime import datetime, timedelta

# Windows 终端默认 GBK 编码无法输出 Unicode 字符，强制 stdout 使用 UTF-8
if sys.platform == 'win32' and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

DAEMON_URL = os.environ.get('DINGTALK_DAEMON_URL', 'http://127.0.0.1:19200')
NOTIFY_TARGET = os.environ.get('REPORT_NOTIFY_TARGET', '')

# --notify-default: webhook_config.json key \"default\"，拉取/分析/推送各阶段进度
_PROGRESS_WEBHOOK_URL = ''
_PROGRESS_KW = '小秘书提醒'


def _set_progress_webhook(url: str) -> None:
    global _PROGRESS_WEBHOOK_URL
    _PROGRESS_WEBHOOK_URL = (url or '').strip()


def _load_default_webhook_url() -> str:
    try:
        root = os.path.dirname(os.path.abspath(__file__))
        if root not in sys.path:
            sys.path.insert(0, root)
        from lib.utils import get_webhook_url  # noqa: E402

        return (get_webhook_url('default', '') or '').strip()
    except Exception:
        return ''


def _notify_progress(title: str, lines: list) -> None:
    """Markdown to default robot; no-op if _PROGRESS_WEBHOOK_URL empty."""
    if not _PROGRESS_WEBHOOK_URL:
        return
    body = '\n'.join(str(x) for x in lines if x is not None)
    text = (
        f'### {_PROGRESS_KW} · 日报进度\n'
        f'**{title}**\n\n{body}\n\n'
        f'---\n###### ※ {_PROGRESS_KW}'
    )
    payload = json.dumps(
        {
            'msgtype': 'markdown',
            'markdown': {
                'title': f'{_PROGRESS_KW} · 日报进度',
                'text': text,
            },
        },
        ensure_ascii=False,
    ).encode('utf-8')
    req = urllib.request.Request(
        _PROGRESS_WEBHOOK_URL,
        data=payload,
        method='POST',
        headers={'Content-Type': 'application/json; charset=utf-8'},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            out = json.loads(resp.read().decode('utf-8', errors='replace'))
        if out.get('errcode') != 0:
            print(f'[progress] webhook err: {out}', flush=True)
    except Exception as e:
        print(f'[progress] webhook fail: {e}', flush=True)


def _safe(s):
    """Strip chars that can't be printed on Windows GBK terminals."""
    try:
        s.encode('gbk')
        return s
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s.encode('gbk', errors='replace').decode('gbk')

def _resolve_llm_config():
    """Resolve LLM config: own env vars > palace .env > defaults"""
    key = os.environ.get('LLM_API_KEY', '')
    base = os.environ.get('LLM_API_BASE', '')
    model = os.environ.get('LLM_MODEL', '')

    if not key:
        palace_env = os.path.join(
            os.path.dirname(__file__), '..', 'palace', '.env')
        if os.path.exists(palace_env):
            try:
                with open(palace_env, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith('#') or '=' not in line:
                            continue
                        k, v = line.split('=', 1)
                        k, v = k.strip(), v.strip()
                        if k == 'PALACE_API_KEY' and v and not key:
                            key = v
                        elif k == 'PALACE_API_BASE' and v and not base:
                            base = v
                        elif k == 'PALACE_MODEL' and v and not model:
                            model = v
            except Exception:
                pass

    return (
        key,
        base or 'https://api.openai.com/v1',
        model or 'gpt-4o-mini',
    )

LLM_API_KEY, LLM_API_BASE, LLM_MODEL = _resolve_llm_config()

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'digest_config.json')
_REPORT_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), 'message_templates.json')

_DEFAULT_REPORT_TEMPLATE = {
    'title': '{date} 日报摘要 {window}',
    'submission': {
        'submitted_line': '✅ 已提交 {count}/{total} 人',
        'missing_line': '❌ 未交：{names}',
        'missing_sep': ' / ',
    },
    'sections': {
        'summary':        {'header': '【总览】',    'show': True},
        'tech_updates':   {'header': '【技术动态】', 'item_format': '· {name}：{doing}',         'show': True},
        'quality_flags':  {'header': '⚠️ 质量标记', 'item_format': '• {name}：{issue}',          'show': True, 'max_items': 8},
        'attention_items':{'header': '【关注】',    'item_format': '→ [{source}] {content}',     'show': True, 'max_items': 8},
    },
    'llm': {'text_limit_per_person': 6000},
}


def _load_report_template():
    if os.path.exists(_REPORT_TEMPLATE_PATH):
        try:
            with open(_REPORT_TEMPLATE_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # Support unified file (report_digest key) and legacy flat file
            tmpl = data.get('report_digest', data)
            tmpl.pop('_comment', None)
            # strip inner _note/_comment keys
            for v in tmpl.values():
                if isinstance(v, dict):
                    v.pop('_comment', None)
                    v.pop('_note', None)
            return tmpl
        except Exception as e:
            print(f'[warn] failed to load report template: {e}', flush=True)
    return _DEFAULT_REPORT_TEMPLATE


def _load_config():
    defaults = {
        'team_members': [],
        'notify_target': NOTIFY_TARGET,
        'report_cids': [],
        'discover_marker': '#日报收集',
    }
    if os.path.exists(_CONFIG_PATH):
        try:
            with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            defaults.update(cfg)
        except Exception:
            pass
    return defaults


def _save_config(config):
    with open(_CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    print(f'[config] saved to {_CONFIG_PATH}', flush=True)


def _daemon_request(path, body=None):
    url = f'{DAEMON_URL}{path}'
    data = json.dumps(body).encode('utf-8') if body else None
    req = urllib.request.Request(
        url, data=data,
        headers={'Content-Type': 'application/json'} if data else {},
        method='POST' if data else 'GET',
    )
    try:
        with urllib.request.urlopen(req, timeout=75) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        return {'success': False, 'error': str(e)}


def fetch_reports(target_date, report_cids):
    if not report_cids:
        print('[error] no report_cids configured -- run with --discover first',
              flush=True)
        return []

    # 日报收集窗口：当天 18:30 → 次日 12:00（覆盖晚间提交和隔夜补交）
    dt = datetime.strptime(target_date, '%Y-%m-%d')
    after = (dt.replace(hour=18, minute=30, second=0)).strftime('%Y-%m-%d %H:%M:%S')
    before = (dt + timedelta(days=1)).replace(hour=12, minute=0, second=0).strftime('%Y-%m-%d %H:%M:%S')
    all_msgs = []
    seen_keys = set()

    for entry in report_cids:
        cid = entry['cid'] if isinstance(entry, dict) else entry
        name = entry.get('name', cid) if isinstance(entry, dict) else cid
        result = _daemon_request('/fetch_reports', {
            'cid': cid,
            'count': 80,
            'after': after,
            'before': before,
            'max_pages': 30,
            'max_seconds': 60,
        })
        if not result.get('success'):
            err = result.get('error', '') or ''
            print(f'[warn] fetch from {_safe(name)} failed: '
                  f'{err}', flush=True)
            time.sleep(3)   # 给 JSAPI browser 短暂恢复时间
            continue
        fetched = result.get('messages', [])
        for m in fetched:
            key = f'{m.get("ts", 0)}_{m.get("sender", "")}'
            if key not in seen_keys:
                seen_keys.add(key)
                m['_source_group'] = name
                all_msgs.append(m)
        print(f'[fetch] {_safe(name)}: {len(fetched)} reports', flush=True)

    all_msgs.sort(key=lambda m: m.get('ts', 0))

    # 内容去重：同一发件人文本前80字相同视为重复（多群转发场景）
    # 保留有 report_url 的那条，否则保留先出现的
    dedup_result = []
    seen_content_keys = {}  # (sender, text_prefix) -> index in dedup_result
    for m in all_msgs:
        sender = m.get('sender', '')
        text = (m.get('text') or '').strip()[:80]
        ck = (sender, text)
        if ck in seen_content_keys and text:
            existing_idx = seen_content_keys[ck]
            existing = dedup_result[existing_idx]
            # 如果新条目有 report_url 而旧的没有，替换
            if m.get('report_url') and not existing.get('report_url'):
                dedup_result[existing_idx] = m
        else:
            seen_content_keys[ck] = len(dedup_result)
            dedup_result.append(m)

    removed = len(all_msgs) - len(dedup_result)
    if removed:
        print(f'[fetch] dedup removed {removed} duplicate(s)', flush=True)
    return dedup_result


def _enrich_from_monitor_log(messages, target_date, report_cids):
    """Supplement JSAPI results with Monitor native hook log.

    Monitor captures all messages in real-time including those JSAPI misses
    after DingTalk restart. For each report in the log that JSAPI didn't return,
    add it with report_url extracted from card_ext so --full-content can fetch it.
    """
    if not os.path.exists(_MSG_LOG):
        return messages

    dt = datetime.strptime(target_date, '%Y-%m-%d')
    after_ts = dt.replace(hour=18, minute=30).timestamp() * 1000
    before_ts = (dt + timedelta(days=1)).replace(hour=12, minute=0).timestamp() * 1000

    tracked_cids = set()
    for entry in report_cids:
        cid = entry['cid'] if isinstance(entry, dict) else entry
        tracked_cids.add(cid)

    existing_keys = set()
    for m in messages:
        existing_keys.add(f'{m.get("ts", 0)}_{m.get("sender", "")}')

    added = 0
    try:
        with open(_MSG_LOG, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                ts = obj.get('ts', 0)
                if ts < after_ts or ts > before_ts:
                    continue
                cid = obj.get('cid', '')
                if cid not in tracked_cids:
                    continue
                text = obj.get('text', '') or ''
                if '[日志]' not in text or '日报' not in text:
                    continue

                card_ext = obj.get('card_ext') or {}
                action_url = card_ext.get('biz_custom_action_url', '') or ''
                report_url = ''
                if 'url=' in action_url:
                    try:
                        from urllib.parse import unquote
                        report_url = unquote(action_url.split('url=', 1)[1])
                    except Exception:
                        pass

                title = card_ext.get('biz_custom_title', '') or text
                sender_name = ''
                for pat in ('[日志] ', ):
                    if pat in title:
                        rest = title.split(pat, 1)[1]
                        sender_name = rest.replace('的日报', '').replace('的周报', '').strip()
                        break
                if not sender_name:
                    sender_name = obj.get('sender', '')

                key = f'{ts}_{sender_name}'
                if key in existing_keys:
                    continue
                existing_keys.add(key)

                messages.append({
                    'ts': ts,
                    'sender': sender_name,
                    'text': card_ext.get('biz_custom_desc', '') or text,
                    'report_url': report_url,
                    '_source': 'monitor_log',
                    '_source_group': cid,
                })
                added += 1
    except Exception as e:
        print(f'[monitor-enrich] error reading log: {e}', flush=True)

    if added:
        messages.sort(key=lambda m: m.get('ts', 0))
        print(f'[monitor-enrich] added {added} reports from monitor log',
              flush=True)
    return messages


def _extract_report_text(m):
    """从消息中提取日报全文。

    优先使用 CEF /fetch_report_content 写入的 _report_body（完整正文），
    避免 bf/b_form 里只有模板标题行时盖住已拉取的全文。
    否则解析 bf (b_form JSON)，最后回退 text。
    """
    full_body = (m.get('_report_body') or '').strip()
    if full_body:
        return full_body

    bf_raw = m.get('bf') or m.get('b_form') or ''
    if bf_raw:
        try:
            if isinstance(bf_raw, str):
                bf = json.loads(bf_raw)
            else:
                bf = bf_raw
            if isinstance(bf, list) and bf:
                parts = []
                for item in bf:
                    if isinstance(item, dict):
                        k = item.get('k', '')
                        v = item.get('v', '')
                        if v and v.strip() and v.strip() != '-':
                            parts.append(f'{k}:\n{v}')
                if parts:
                    return '\n\n'.join(parts)
        except (json.JSONDecodeError, TypeError):
            pass
    return m.get('text', '') or ''


def analyze_reports(messages, team_members, target_date, member_roles=None):
    if not LLM_API_KEY:
        print('[warn] LLM_API_KEY not set, skipping analysis', flush=True)
        return _fallback_analysis(messages, team_members, target_date)

    if member_roles is None:
        member_roles = _load_config().get('member_roles', {})

    tmpl = _load_report_template()
    text_limit = tmpl.get('llm', {}).get('text_limit_per_person', 2500)

    submitters = set()
    report_texts = []
    for m in messages:
        sender = m.get('sender', '')
        text = _extract_report_text(m)
        if not text or not sender:
            continue
        submitters.add(sender)
        report_texts.append(f'[{sender}]\n{text[:text_limit]}')

    missing = [n for n in team_members if n not in submitters] if team_members else []

    prompt = _build_analysis_prompt(
        report_texts, list(submitters), missing, target_date, member_roles)

    try:
        result = _call_llm(prompt)
        cleaned = result.strip()
        if cleaned.startswith('```'):
            first_nl = cleaned.find('\n')
            if first_nl > 0:
                cleaned = cleaned[first_nl + 1:]
            if cleaned.endswith('```'):
                cleaned = cleaned[:-3].strip()
        parsed = json.loads(cleaned)
        team_set = set(team_members) if team_members else set()
        team_submitters = submitters & team_set if team_set else submitters
        parsed['submission'] = {
            'submitted': sorted(team_submitters),
            'missing': sorted(missing),
            'total': len(team_members) if team_members else len(submitters),
            'submitted_count': len(team_submitters),
        }
        return parsed
    except (json.JSONDecodeError, Exception) as e:
        print(f'[warn] LLM parse error: {e}, using fallback', flush=True)
        analysis = _fallback_analysis(messages, team_members, target_date)
        analysis['llm_raw'] = result if 'result' in dir() else ''
        return analysis


def _build_analysis_prompt(report_texts, submitters, missing, target_date,
                           member_roles=None):
    reports_block = '\n---\n'.join(report_texts[:40])
    missing_str = ', '.join(missing) if missing else '(none)'

    roles_block = ''
    if member_roles:
        lines = []
        for role_info in member_roles.values():
            members = role_info.get('members', [])
            focus = role_info.get('focus', '')
            if members and focus:
                lines.append(f'- {", ".join(members)}：{focus}')
        if lines:
            roles_block = (
                '\n## 角色差异化评判\n'
                '不同角色的日报评判标准不同，不要用统一模板项检查所有人：\n'
                + '\n'.join(lines)
                + '\n未在上面列出的成员按通用标准评判。\n'
            )

    # 提取 tech_leader 成员名单用于 prompt
    tech_leaders = []
    if member_roles:
        tl = member_roles.get('tech_leader', {})
        tech_leaders = tl.get('members', [])
    tech_str = '、'.join(tech_leaders) if tech_leaders else '技术leader'

    return f"""你是一位游戏研发团队的管理助手。以下是 {target_date} 收到的团队日报。
请从制作人视角分析这些日报，输出 JSON 格式结果。

## 分析维度

1. **summary**: 一句话总结今日团队整体状态（30字内）
2. **quality_flags**: 日报质量问题标记，每项含 name(人名) 和 issue(问题描述)
   - 内容过于笼统，无具体产出或数据（如"推进中""对齐中"无实质内容）
   - 明显敷衍（极短、复制昨天内容等）
   - 按角色标准判断（见下方角色差异化评判），不要用通用模板项去标记不适用的角色
   - 若正文已包含多段实质描述（具体事项、产出、数据），**不要**仅因模板标题行而标记「被截断」
3. **attention_items**: 值得制作人关注的事项，每项含 source(来源人名) 和 content(具体内容)
   - 提到阻塞、卡点、等待审批
   - 提到延期风险、排期冲突、资源不足
   - 跨团队/跨职能依赖或协调需求
   - 技术风险、线上问题、数据异常
   - 重要决策待定或方向分歧
4. **tech_updates**: 技术方向今日动态，每项含 name(人名) 和 doing(在做什么，15字内精炼描述)
   - 仅针对 {tech_str}
   - 用最精炼的语言陈述他们在做什么，不评价质量，不添加建议
   - 若日报内容截断无法判断，如实填"日报内容不全，无法提炼"
{roles_block}
## 已提交: {', '.join(submitters)}
## 未提交: {missing_str}

## 日报内容

{reports_block}

## 输出格式（严格 JSON）

{{
  "summary": "...",
  "quality_flags": [
    {{"name": "张三", "issue": "日报仅一句话，无具体产出"}}
  ],
  "attention_items": [
    {{"source": "李四", "content": "客户端 A 模块性能问题阻塞 QA 测试"}}
  ],
  "tech_updates": [
    {{"name": "杨玉涛", "doing": "调试回归energy，补充单元测试"}}
  ]
}}

规则：
- quality_flags 只标记确实有问题的，正常日报不标记
- 同一人在多个群提交日报属正常行为，不要标记为重复提交
- attention_items 只提取真正值得制作人关注的信号，不要罗列日常工作
- tech_updates 必须有内容，即使只是简短陈述"在做XX"
- 如果所有日报质量都正常且无特殊事项，对应数组留空
- 输出纯 JSON，不要包含 markdown 代码块标记"""


def _call_llm(prompt):
    url = f'{LLM_API_BASE}/chat/completions'
    body = json.dumps({
        'model': LLM_MODEL,
        'messages': [{'role': 'user', 'content': prompt}],
        'temperature': 0.3,
        'response_format': {'type': 'json_object'},
    }).encode('utf-8')
    req = urllib.request.Request(url, data=body, headers={
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {LLM_API_KEY}',
    })
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    return data['choices'][0]['message']['content']


def _fallback_analysis(messages, team_members, target_date):
    submitters = set()
    for m in messages:
        if m.get('sender'):
            submitters.add(m['sender'])
    missing = [n for n in team_members if n not in submitters] if team_members else []
    team_set = set(team_members) if team_members else set()
    team_submitters = submitters & team_set if team_set else submitters
    return {
        'submission': {
            'submitted': sorted(team_submitters),
            'missing': sorted(missing),
            'total': len(team_members) if team_members else len(submitters),
            'submitted_count': len(team_submitters),
        },
        'quality_flags': [],
        'attention_items': [],
        'summary': f'{target_date} 共收到 {len(messages)} 条日报，'
                   f'{len(submitters)} 人提交。(LLM 未配置，仅统计)',
    }


def format_digest(analysis, target_date):
    tmpl = _load_report_template()
    secs = tmpl.get('sections', {})
    sub_tmpl = tmpl.get('submission', {})

    try:
        dt = datetime.strptime(target_date, '%Y-%m-%d')
        dt_next = dt + timedelta(days=1)
        window_str = f'（{dt.month}/{dt.day} 18:30 - {dt_next.month}/{dt_next.day} 12:00）'
    except Exception:
        window_str = ''

    title_fmt = tmpl.get('title', '{date} 日报摘要 {window}')
    lines = [title_fmt.format(date=target_date, window=window_str)]

    sub = analysis.get('submission', {})
    total = sub.get('total', 0)
    count = sub.get('submitted_count', 0)
    missing = sub.get('missing', [])
    sep = sub_tmpl.get('missing_sep', ' / ')

    lines.append('')
    lines.append(sub_tmpl.get('submitted_line', '✅ 已提交 {count}/{total} 人').format(
        count=count, total=total))
    if missing:
        names = sep.join(missing[:15])
        if len(missing) > 15:
            names += f' ...等{len(missing)}人'
        lines.append(sub_tmpl.get('missing_line', '❌ 未交：{names}').format(names=names))

    # 【总览】
    sec = secs.get('summary', {})
    summary = analysis.get('summary', '')
    if summary and sec.get('show', True):
        lines.append('')
        lines.append(sec.get('header', '【总览】'))
        lines.append(summary)

    # 【技术动态】
    sec = secs.get('tech_updates', {})
    tech = analysis.get('tech_updates', [])
    if tech and sec.get('show', True):
        lines.append('')
        lines.append(sec.get('header', '【技术动态】'))
        fmt = sec.get('item_format', '· {name}：{doing}')
        for t in tech:
            lines.append(fmt.format(name=t.get('name', '?'), doing=t.get('doing', '')))

    # 质量标记
    sec = secs.get('quality_flags', {})
    flags = analysis.get('quality_flags', [])
    if flags and sec.get('show', True):
        lines.append('')
        lines.append(sec.get('header', '⚠️ 质量标记'))
        fmt = sec.get('item_format', '• {name}：{issue}')
        for f in flags[:sec.get('max_items', 8)]:
            lines.append(fmt.format(name=f.get('name', '?'), issue=f.get('issue', '')))

    # 【关注】
    sec = secs.get('attention_items', {})
    items = analysis.get('attention_items', [])
    if items and sec.get('show', True):
        lines.append('')
        lines.append(sec.get('header', '【关注】'))
        fmt = sec.get('item_format', '→ [{source}] {content}')
        for item in items[:sec.get('max_items', 8)]:
            lines.append(fmt.format(
                source=item.get('source', '?'), content=item.get('content', '')))

    return '\n'.join(lines)


_MSG_LOG = os.path.join(
    os.path.dirname(__file__), 'data', 'dingtalk', '_msg_log.jsonl')
_CONTACTS_FILE = os.path.join(
    os.path.dirname(__file__), 'data', 'dingtalk', 'contacts.json')


def _load_contacts_db():
    """Load contacts DB from disk + daemon API, merge into {cid: name}."""
    merged = {}
    if os.path.exists(_CONTACTS_FILE):
        try:
            with open(_CONTACTS_FILE, 'r', encoding='utf-8') as f:
                cdb = json.load(f)
            for sec in ('p2p', 'group'):
                for cid, entry in cdb.get(sec, {}).items():
                    name = entry.get('name', '')
                    if name:
                        merged[cid] = name
        except Exception:
            pass
    result = _daemon_request('/contacts')
    if result and isinstance(result, dict):
        for r in result.get('results', []):
            cid = r.get('cid', '')
            name = r.get('name', '')
            if cid and name:
                merged[cid] = name
    return merged


def discover_groups(marker=None, name_pattern=None):
    """Find report groups by marker keyword in messages and/or group name pattern.

    --marker: find groups where someone sent a message containing the marker
    --name:   find groups whose name matches the pattern (substring match)
    Both can be used together; results are merged.
    """
    config = _load_config()
    found = {}

    if not os.path.exists(_MSG_LOG):
        print('[discover] message log not found -- is daemon running?',
              flush=True)
        return []

    if marker is not False:
        effective_marker = marker or config.get('discover_marker', '#日报收集')
        print(f'[discover] scanning log for marker: {_safe(effective_marker)}',
              flush=True)
        with open(_MSG_LOG, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                text = obj.get('text', '') or ''
                if effective_marker in text:
                    cid = obj.get('cid', '')
                    if cid and ':' not in cid:
                        found[cid] = True

    contacts = _load_contacts_db()

    if name_pattern:
        print(f'[discover] searching group names for: {_safe(name_pattern)}',
              flush=True)
        for cid, name in contacts.items():
            if ':' in cid:
                continue
            if name_pattern in name:
                found[cid] = True
                print(f'  [name] {cid}  {_safe(name)}', flush=True)

        log_cids = set()
        with open(_MSG_LOG, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                cid = obj.get('cid', '')
                if cid and ':' not in cid:
                    log_cids.add(cid)

        unresolved = log_cids - set(contacts.keys())
        if unresolved:
            print(f'[discover] {len(unresolved)} groups in log without '
                  f'resolved names (daemon may need more time)', flush=True)

    if not found:
        tips = []
        if name_pattern:
            tips.append(f'no groups matching "{_safe(name_pattern)}" found')
            tips.append('the daemon may not have seen those groups yet')
            tips.append('try: send any message in target groups while daemon '
                        'is running, then --discover again')
        else:
            tips.append('no marker messages found')
            tips.append('send the marker in target groups, then --discover')
        for t in tips:
            print(f'[discover] {t}', flush=True)
        return []

    discovered = []
    for cid in found:
        name = contacts.get(cid, '') or f'group_{cid}'
        discovered.append({'cid': cid, 'name': name})

    existing_cids = {
        (e['cid'] if isinstance(e, dict) else e)
        for e in config.get('report_cids', [])
    }
    new_entries = [d for d in discovered if d['cid'] not in existing_cids]

    if new_entries:
        config.setdefault('report_cids', [])
        config['report_cids'].extend(new_entries)
        _save_config(config)
        for e in new_entries:
            print(f'  [+] {e["cid"]}  {_safe(e["name"])}', flush=True)
        print(f'[discover] added {len(new_entries)} group(s) to config',
              flush=True)
    else:
        print('[discover] all found groups already in config', flush=True)

    all_cids = config.get('report_cids', [])
    print(f'[discover] total report groups: {len(all_cids)}', flush=True)
    for e in all_cids:
        n = e['name'] if isinstance(e, dict) else e
        c = e['cid'] if isinstance(e, dict) else e
        print(f'  {c}  {_safe(n)}', flush=True)
    return discovered


def resolve_cid_names():
    """对 config 中名称为 group_XXXX 的群调用 /conv_info 补全群名。"""
    config = _load_config()
    updated = 0
    for entry in config.get('report_cids', []):
        if not isinstance(entry, dict):
            continue
        cid = entry.get('cid', '')
        name = entry.get('name', '')
        if not name.startswith('group_'):
            continue
        print(f'[resolve] {cid} 查询群名 ...', flush=True)
        result = _daemon_request('/conv_info', {'cid': cid})
        if result.get('success') and result.get('name'):
            entry['name'] = result['name']
            print(f'  -> {_safe(result["name"])}', flush=True)
            updated += 1
        else:
            print(f'  -> failed: {_safe(str(result.get("error", "timeout")))}',
                  flush=True)
    if updated:
        _save_config(config)
        print(f'[resolve] updated {updated} group name(s)', flush=True)
    else:
        print('[resolve] no updates (all names already resolved or daemon unavailable)',
              flush=True)
    return updated


_ERROR_PATTERNS = ('400', '403', '404', '500', 'bad request', 'forbidden',
                   'not found', 'error', 'unauthorized', 'token', 'expired',
                   'invalid', '<!doctype', '<html')

def _looks_like_error_page(content):
    """判断 fetch_report_content 返回的内容是否是错误页而非真实日报。
    条件：内容过短（<80字），或全是 HTTP/HTML 错误关键词。
    """
    if not content:
        return True
    c = content.strip()
    if len(c) < 80:
        return True
    cl = c.lower()
    error_hits = sum(1 for p in _ERROR_PATTERNS if p in cl)
    if error_hits >= 2 and len(c) < 300:
        return True
    return False


def fetch_full_contents(messages):
    """对有 report_url 的消息通过 daemon 拉取日报详情页正文（--full-content）。

    说明：
    - 以前用 len(text)>300 跳过拉取，但钉钉卡片 biz_custom_desc 预览常 >300
      却仍非全文，导致 LLM 误判「仅标题、被截断」。
    - 拉取成功后写入 _report_body，_extract_report_text 优先用它，避免短 bf 覆盖。
    """
    enriched = 0
    skipped_error = 0
    need_urls = [m for m in messages if (m.get('report_url') or '').strip()]
    total_url = len(need_urls)
    for m in messages:
        url = m.get('report_url', '') or ''
        if not url:
            continue
        sender = m.get('sender', '?')
        preview_len = len((_extract_report_text(m) or '').strip())
        print(f'[full-content] {_safe(sender)} (preview ~{preview_len} chars) ...',
              flush=True)
        result = _daemon_request('/fetch_report_content', {'url': url})
        if result.get('success') and result.get('content'):
            content = result['content']
            if _looks_like_error_page(content):
                # URL 可能已过期，保留原始截断文本，不覆盖
                print(f'  -> skipped (error page, {len(content)} chars): '
                      f'{_safe(content[:60])}', flush=True)
                skipped_error += 1
            else:
                m['_report_body'] = content
                m['text'] = content
                enriched += 1
                tl = result.get('text_length', 0)
                print(f'  -> {tl} chars '
                      f'({result.get("extraction_method", "")})', flush=True)
        else:
            err = str(result.get('error', '') or '')
            print(f'  -> failed: {_safe(err)}',
                  flush=True)
    if _PROGRESS_WEBHOOK_URL:
        if total_url:
            _notify_progress(
                '全文拉取完成',
                [
                    f'成功 **{enriched}** / 有 URL **{total_url}** 条',
                    f'疑似过期/错误页跳过 **{skipped_error}**',
                ],
            )
        else:
            _notify_progress(
                '全文拉取完成',
                ['本轮无 **report_url**，未走 CEF 详情页'],
            )
    print(f'[full-content] enriched {enriched}/{len(messages)} reports'
          f'{f", {skipped_error} skipped (expired URL)" if skipped_error else ""}',
          flush=True)
    return messages


def manage_members(add=None, remove=None, discover_date=None, yes=False):
    """Update team_members in config."""
    config = _load_config()
    members = list(config.get('team_members', []))

    if add:
        if add not in members:
            members.append(add)
            config['team_members'] = members
            _save_config(config)
            print(f'[members] added: {_safe(add)}', flush=True)
        else:
            print(f'[members] already exists: {_safe(add)}', flush=True)
        return

    if remove:
        if remove in members:
            members.remove(remove)
            config['team_members'] = members
            _save_config(config)
            print(f'[members] removed: {_safe(remove)}', flush=True)
        else:
            print(f'[members] not found: {_safe(remove)}', flush=True)
        return

    if discover_date is not None:
        target = discover_date or datetime.now().strftime('%Y-%m-%d')
        report_cids = config.get('report_cids', [])
        print(f'[members] discovering from {target} reports ...', flush=True)
        msgs = fetch_reports(target, report_cids)
        found = {m.get('sender', '') for m in msgs
                 if m.get('sender') and not m.get('is_self')}
        found.discard('')
        found.discard('我')
        new_members = sorted(found - set(members))
        if new_members:
            print(f'[members] found {len(new_members)} new sender(s):')
            for n in new_members:
                print(f'  + {_safe(n)}', flush=True)
            if yes:
                members.extend(new_members)
                config['team_members'] = sorted(members)
                _save_config(config)
                print(f'[members] added {len(new_members)} member(s)', flush=True)
            else:
                print('[members] rerun with --yes to add them', flush=True)
        else:
            print('[members] no new senders found in fetched reports', flush=True)
        return

    # Default: list current members
    print(f'[members] current team_members ({len(members)}):')
    for name in members:
        print(f'  {_safe(name)}', flush=True)


def send_via_webhook(text, webhook_url):
    """通过钉钉自定义机器人 webhook 发送消息"""
    import urllib.request as _urllib_req
    body = json.dumps({'msgtype': 'text', 'text': {'content': f'小秘书提醒\n{text}'}}).encode('utf-8')
    req = _urllib_req.Request(
        webhook_url,
        data=body,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with _urllib_req.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            if result.get('errcode') == 0:
                print('[send] webhook OK', flush=True)
                return {'success': True}
            else:
                print(f'[send] webhook error: {result}', flush=True)
                return {'success': False, 'error': str(result)}
    except Exception as e:
        print(f'[send] webhook exception: {e}', flush=True)
        return {'success': False, 'error': str(e)}


def send_digest(text, target_name, webhook_url=None):
    # 优先走 webhook（机器人身份，有通知气泡）
    if webhook_url:
        return send_via_webhook(text, webhook_url)
    if not target_name:
        print('[skip] no notify target configured', flush=True)
        return None
    payload = {'message': text}
    if target_name.isdigit():
        payload['cid'] = target_name
    else:
        payload['name'] = target_name
    result = _daemon_request('/send', payload)
    return result


def main():
    parser = argparse.ArgumentParser(description='Daily report digest')
    parser.add_argument('--date', default=None,
                        help='Target date YYYY-MM-DD (default: today)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Print digest without sending')
    parser.add_argument('--output', default=None,
                        help='Save digest to file')
    parser.add_argument('--discover', action='store_true',
                        help='Find and register report group CIDs')
    parser.add_argument('--marker', default=None,
                        help='Marker keyword in messages (default from config)')
    parser.add_argument('--name', default=None,
                        help='Search groups by name pattern (substring match)')
    parser.add_argument('--resolve-cids', action='store_true',
                        help='Resolve group names for unresolved CIDs in config')
    parser.add_argument('--full-content', action='store_true',
                        help='Fetch full report content via CEF for ct=2950 cards with report_url')
    parser.add_argument('--members', action='store_true',
                        help='List current team_members')
    parser.add_argument('--add-member', default=None, metavar='NAME',
                        help='Add a member to team_members list')
    parser.add_argument('--remove-member', default=None, metavar='NAME',
                        help='Remove a member from team_members list')
    parser.add_argument('--discover-members', action='store_true',
                        help='Discover new members from fetched reports (use with --date)')
    parser.add_argument('--yes', action='store_true',
                        help='Auto-confirm prompts (e.g. for --discover-members)')
    parser.add_argument(
        '--notify-default',
        action='store_true',
        help='Send progress to webhook_config.json key "default" (also env REPORT_DIGEST_NOTIFY_DEFAULT=1)',
    )
    args = parser.parse_args()

    if args.discover:
        use_marker = args.marker if args.marker else (False if args.name else None)
        discover_groups(marker=use_marker, name_pattern=args.name)
        return

    if args.resolve_cids:
        resolve_cid_names()
        return

    if args.members or args.add_member or args.remove_member or args.discover_members:
        discover_date = args.date if args.discover_members else None
        manage_members(
            add=args.add_member,
            remove=args.remove_member,
            discover_date=discover_date,
            yes=args.yes,
        )
        return

    target_date = args.date or datetime.now().strftime('%Y-%m-%d')
    config = _load_config()
    team = config.get('team_members', [])
    notify = config.get('notify_target', '') or NOTIFY_TARGET
    webhook_url = config.get('webhook_url', '') or ''
    report_cids = config.get('report_cids', [])

    env_notify = os.environ.get('REPORT_DIGEST_NOTIFY_DEFAULT', '').strip().lower()
    want_progress = bool(args.notify_default or env_notify in ('1', 'true', 'yes', 'on'))
    if want_progress:
        dw = _load_default_webhook_url()
        if dw:
            _set_progress_webhook(dw)
            _notify_progress(
                '日报进度',
                [
                    f'任务开始 · 统计日期 **{target_date}**',
                    f'团队 **{len(team)}** 人，监听群 **{len(report_cids)}**',
                    '时间窗口：当日 **18:30** → 次日 **12:00**',
                ],
            )
        else:
            print('[warn] --notify-default set but webhook_config default URL is empty',
                  flush=True)

    print(f'[report-digest] date={target_date}, team={len(team)} members, '
          f'groups={len(report_cids)}', flush=True)

    messages = fetch_reports(target_date, report_cids)
    jsapi_count = len(messages)
    messages = _enrich_from_monitor_log(messages, target_date, report_cids)
    print(f'[report-digest] fetched {jsapi_count} via JSAPI, '
          f'{len(messages)} total (after monitor enrichment)', flush=True)
    if _PROGRESS_WEBHOOK_URL:
        _notify_progress(
            '阶段拉取完成',
            [
                f'JSAPI 去重后 **{jsapi_count}** 条',
                f'合并监控日志后 **{len(messages)}** 条',
            ],
        )

    if not messages:
        print('[report-digest] no reports found, exiting', flush=True)
        return

    if args.full_content:
        messages = fetch_full_contents(messages)

    if _PROGRESS_WEBHOOK_URL:
        _notify_progress('LLM分析', ['正在汇总日报并请求模型，请稍候…'])

    analysis = analyze_reports(messages, team, target_date)
    digest_text = format_digest(analysis, target_date)

    print('\n' + digest_text + '\n', flush=True)

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(digest_text)
            f.write('\n\n---\nRaw analysis:\n')
            f.write(json.dumps(analysis, ensure_ascii=False, indent=2))
        print(f'[report-digest] saved to {args.output}', flush=True)

    if _PROGRESS_WEBHOOK_URL:
        extra = []
        if args.dry_run:
            extra.append('（dry-run，未发主摘要）')
        _notify_progress(
            '分析完成',
            [f'摘要约 **{len(digest_text)}** 字'] + extra,
        )

    if not args.dry_run and notify:
        result = send_digest(digest_text, notify, webhook_url=webhook_url or None)
        if result and result.get('success'):
            print(f'[report-digest] sent to {notify}', flush=True)
        else:
            print(f'[report-digest] send failed: {result}', flush=True)
    elif args.dry_run:
        print('[report-digest] dry-run mode, not sending', flush=True)


if __name__ == '__main__':
    main()
