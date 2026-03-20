# -*- coding: utf-8 -*-
"""Version status digest - fetch from PmSystem dashboard and push via webhook.

Usage:
    py version_digest.py              # fetch + send
    py version_digest.py --dry-run    # fetch + print only
    py version_digest.py --output x.md  # save to file
"""
import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, date, timedelta

_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_DIR, 'digest_config.json')
_TEMPLATE_PATH = os.path.join(_DIR, 'message_templates.json')

_DEFAULT_TEMPLATE = {
    'title': '## 版本状态 [{timestamp}]',
    'version': {
        'header': '**{name}** | {phase}',
        'countdown': {
            'overdue': '**[超期]** 已到/超过发版日',
            'urgent': '**[紧]** {days}天后发版',
            'normal': '{days}天后发版',
            'urgent_threshold_days': 7,
        },
        'feature_line': 'Feature: {summary}',
        'capacity_line': '容量: {pct}%',
        'milestone_line': '里程碑: {ms_name} ({ms_date})',
        'pipeline_line': '管线节点: {node_name} ({node_date})',
        'overdue_line': '**[超期节点]** {nodes}',
        'risk_line': '[风险] {text}',
    },
    'show': {
        'capacity': True,
        'milestone': True,
        'pipeline_current': True,
        'overdue_nodes': True,
        'risks': True,
    },
    'limits': {'risks': 3},
    'separator': '---',
    'footer': '<font color="#999999">小秘书提醒</font>',
}


def _load_template():
    if os.path.exists(_TEMPLATE_PATH):
        try:
            with open(_TEMPLATE_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # Support both unified file (version_digest key) and legacy flat file
            tmpl = data.get('version_digest', data)
            tmpl.pop('_comment', None)
            return tmpl
        except Exception as e:
            print(f'[warn] failed to load template: {e}, using defaults', flush=True)
    return _DEFAULT_TEMPLATE

PIPELINE_STAGES = [
    ('planning', '规划'),
    ('feasibility', '可行性初评'),
    ('capacity', '容量评估'),
    ('scoping', '规格锁定'),
    ('dev', '开发'),
    ('acceptance', '验收'),
    ('goLiveReview', '上线评审'),
    ('freezeConfirm', '封版确认'),
    ('releaseTesting', '发布测试'),
    ('release', '发版'),
    ('retro', '复盘'),
]

PHASE_LABELS = {
    'planning': '规划中',
    'estimation': '任务拆解',
    'dev': '开发期',
    'released': '已发布',
}

ALERT_ICONS = {
    'critical': '[红]',
    'warning': '[黄]',
    'normal': '',
}


def _load_config():
    try:
        with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _api_get(url, timeout=10, api_key=None):
    headers = {}
    if api_key:
        headers['X-Api-Key'] = api_key
    req = urllib.request.Request(url, headers=headers, method='GET')
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))


def fetch_dashboard(pm_url, api_key=None):
    try:
        data = _api_get(f'{pm_url}/api/dashboard', api_key=api_key)
        versions = data.get('data', {}).get('activeVersions', [])
        if versions:
            return versions
    except Exception as e:
        print(f'[warn] dashboard API failed: {e}', flush=True)
    return _fallback_from_json(pm_url)


def _fallback_from_json(pm_url):
    """Read pm_data.json directly when API returns empty or fails."""
    pm_data_path = os.path.join(
        os.path.dirname(_DIR), 'pm-system', 'backend', 'data', 'pm_data.json')
    if not os.path.exists(pm_data_path):
        return []
    print(f'[version-digest] fallback: reading {pm_data_path}', flush=True)
    with open(pm_data_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    today = date.today()
    versions = data.get('versions', [])
    result = []
    for v in versions:
        phase = v.get('phase', '')
        if phase == 'released':
            continue
        vid = v.get('id', '')
        rd_str = v.get('releaseDate')
        days_remaining = None
        if rd_str:
            try:
                rd = datetime.strptime(rd_str[:10], '%Y-%m-%d').date()
                days_remaining = (rd - today).days
            except ValueError:
                pass
        vf = v.get('features', [])
        done = sum(1 for f in vf if f.get('stage') in ('done', 'released'))
        blocked = sum(1 for f in vf if f.get('isBlocked') or f.get('stage') == 'blocked')
        in_prog = sum(1 for f in vf if f.get('stage') in ('dev', 'qa', 'testing', 'in_progress'))
        not_started = len(vf) - done - blocked - in_prog
        total_cap = v.get('capacity') or 0
        allocated = sum(f.get('estimate') or 0 for f in vf)
        usage_pct = round(allocated / total_cap * 100, 1) if total_cap > 0 else 0.0
        alert = 'critical' if usage_pct > 100 else ('warning' if usage_pct > 80 else 'normal')
        risks = []
        for f in vf:
            if f.get('priority') == 'P0' and (f.get('isBlocked') or f.get('stage') == 'blocked'):
                risks.append(f"P0 Feature '{f.get('name','')}' is blocked")
        entry = {
            'id': vid,
            'name': v.get('name', '?'),
            'phase': phase,
            'releaseDate': rd_str,
            'daysRemaining': days_remaining,
            'featureSummary': {
                'total': len(vf), 'done': done,
                'inProgress': in_prog, 'blocked': blocked,
                'notStarted': not_started,
            },
            'capacitySummary': {'usagePct': usage_pct, 'alertLevel': alert},
            'risks': risks,
            '_pipeline_ddls': v.get('pipelineDdls', {}),
            '_pipeline_status': v.get('pipelineStatus', {}),
            '_pld': v.get('pldUserId', ''),
            '_ple': v.get('pleUserId', ''),
            '_plt': v.get('pltUserId', ''),
        }
        result.append(entry)
    return result


def fetch_version_detail(pm_url, version_id, api_key=None):
    data = _api_get(f'{pm_url}/api/versions/{version_id}', api_key=api_key)
    return data.get('data', {})


def filter_active(versions, limit=3):
    active = [v for v in versions if v.get('phase') != 'released']
    active.sort(key=lambda v: v.get('releaseDate') or '9999-12-31')
    return active[:limit]


def enrich_pipeline(pm_url, version):
    """Add pipeline overdue info from version detail."""
    ddls = version.get('_pipeline_ddls') or {}
    status = version.get('_pipeline_status') or {}

    if not ddls and not status:
        vid = version.get('id')
        if not vid:
            return
        api_key = version.get('_api_key')
        try:
            detail = fetch_version_detail(pm_url, vid, api_key=api_key)
        except Exception as e:
            print(f'[warn] cannot fetch version {vid}: {e}', flush=True)
            return
        ddls = detail.get('pipeline_ddls') or {}
        status = detail.get('pipeline_status') or {}
        version.setdefault('_pld', detail.get('pld_user_id', ''))
        version.setdefault('_ple', detail.get('ple_user_id', ''))
        version.setdefault('_plt', detail.get('plt_user_id', ''))

    today = date.today()
    overdue = []
    current_node = None

    for stage_id, label in PIPELINE_STAGES:
        if stage_id == 'retro':
            continue
        done = status.get(stage_id, False)
        if done:
            continue
        ddl_str = ddls.get(stage_id)
        if ddl_str:
            try:
                ddl_date = datetime.strptime(ddl_str[:10], '%Y-%m-%d').date()
                if ddl_date < today:
                    days_over = (today - ddl_date).days
                    overdue.append(f'{label} (超{days_over}天)')
                elif current_node is None:
                    days_until = (ddl_date - today).days
                    current_node = (label, ddl_str[:10], days_until)
            except ValueError:
                pass
        if current_node is None and not done:
            current_node = (label, ddl_str[:10] if ddl_str else '?', None)

    version['_pipeline_overdue'] = overdue
    version['_pipeline_current'] = current_node


def _render_version(v, tmpl=None):
    if tmpl is None:
        tmpl = _load_template()
    vt = tmpl.get('version', {})
    show = tmpl.get('show', {})
    limits = tmpl.get('limits', {})
    cd_tmpl = vt.get('countdown', {})
    urgent_days = cd_tmpl.get('urgent_threshold_days', 7)

    name = v.get('name', '?')
    phase = PHASE_LABELS.get(v.get('phase', ''), v.get('phase', '?'))
    days_rem = v.get('daysRemaining')

    if days_rem is not None and days_rem <= 0:
        countdown = cd_tmpl.get('overdue', '**[超期]** 已到/超过发版日')
    elif days_rem is not None and days_rem <= urgent_days:
        countdown = cd_tmpl.get('urgent', '**[紧]** {days}天后发版').format(days=days_rem)
    elif days_rem is not None:
        countdown = cd_tmpl.get('normal', '{days}天后发版').format(days=days_rem)
    else:
        countdown = ''

    lines = [vt.get('header', '**{name}** | {phase}').format(name=name, phase=phase)]
    if countdown:
        lines.append(countdown)

    fs = v.get('featureSummary', {})
    total = fs.get('total', 0)
    done = fs.get('done', 0)
    in_prog = fs.get('inProgress', 0)
    blocked = fs.get('blocked', 0)
    not_started = fs.get('notStarted', 0)

    parts = [f'{total}总']
    if done:
        parts.append(f'{done}完成')
    if in_prog:
        parts.append(f'{in_prog}开发')
    if blocked:
        parts.append(f'{blocked}阻塞')
    if not_started:
        parts.append(f'{not_started}未开始')
    feature_summary = ' / '.join(parts)
    if total > 0:
        pct = round(done / total * 100)
        feature_summary += f' ({pct}%完成)'
    lines.append(vt.get('feature_line', 'Feature: {summary}').format(summary=feature_summary))

    if show.get('capacity', True):
        cs = v.get('capacitySummary', {})
        usage = cs.get('usagePct', 0)
        alert = ALERT_ICONS.get(cs.get('alertLevel', ''), '')
        cap_text = vt.get('capacity_line', '容量: {pct}%').format(pct=usage)
        if alert:
            cap_text += f' {alert}'
        lines.append(cap_text)

    if show.get('milestone', True):
        ms = v.get('nextMilestone')
        if ms:
            ms_name = ms.get('name', '?')
            ms_date = ms.get('date', '?')
            ms_days = ms.get('daysUntil')
            ms_str = vt.get('milestone_line', '里程碑: {ms_name} ({ms_date})').format(
                ms_name=ms_name, ms_date=ms_date)
            if ms_days is not None:
                suffix = f', {ms_days}天后' if ms_days > 0 else ', 已到期'
                ms_str = ms_str.rstrip(')') + suffix + ')'
            lines.append(ms_str)

    if show.get('pipeline_current', True):
        current = v.get('_pipeline_current')
        if current:
            node_label, node_ddl, node_days = current
            node_str = vt.get('pipeline_line', '管线节点: {node_name} ({node_date})').format(
                node_name=node_label, node_date=node_ddl)
            if node_days is not None:
                suffix = f', {node_days}天后' if node_days > 0 else ', 已到期'
                node_str = node_str.rstrip(')') + suffix + ')'
            lines.append(node_str)

    if show.get('overdue_nodes', True):
        overdue = v.get('_pipeline_overdue', [])
        if overdue:
            lines.append(vt.get('overdue_line', '**[超期节点]** {nodes}').format(
                nodes=', '.join(overdue)))

    if show.get('risks', True):
        risks = v.get('risks', [])
        max_risks = limits.get('risks', 3)
        for r in risks[:max_risks]:
            lines.append(vt.get('risk_line', '[风险] {text}').format(text=r))

    return '\n\n'.join(lines)


def render_digest(versions):
    tmpl = _load_template()
    now_str = datetime.now().strftime('%m/%d %H:%M')
    title = tmpl.get('title', '## 版本状态 [{timestamp}]').format(timestamp=now_str)
    separator = '\n\n' + tmpl.get('separator', '---') + '\n\n'
    footer = '\n\n' + tmpl.get('separator', '---') + '\n\n' + tmpl.get(
        'footer', '<font color="#999999">小秘书提醒</font>')

    blocks = [_render_version(v, tmpl) for v in versions] or ['（无活跃版本）']
    return title + '\n\n' + separator.join(blocks) + footer


def send_via_webhook(text, webhook_url, *, quiet=False):
    body = json.dumps({
        'msgtype': 'markdown',
        'markdown': {
            'title': '版本状态',
            'text': text,
        },
    }).encode('utf-8')
    req = urllib.request.Request(
        webhook_url, data=body,
        headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            if result.get('errcode') == 0:
                if not quiet:
                    print('[send] webhook OK', flush=True)
                return {'success': True}
            if not quiet:
                print(f'[send] webhook error: {result}', flush=True)
            return {'success': False, 'error': str(result)}
    except Exception as e:
        if not quiet:
            print(f'[send] webhook exception: {e}', flush=True)
        return {'success': False, 'error': str(e)}


def run_version_digest_send(*, send_webhook=True, log_to_stdout=True):
    """拉取活跃版本、渲染摘要；可选发 webhook。供 skill_router 与 CLI 共用。

    log_to_stdout=False 时不打印正文（避免 skill_router 线程里 GBK 控制台问题）。
    返回 dict: ok（已配置 webhook 且发送成功时为 True）、versions_count、digest、error（可选）
    """
    config = _load_config()
    pm_url = config.get('pm_system_url', 'http://127.0.0.1:8000').rstrip('/')
    api_key = config.get('pm_system_api_key', '')
    limit = config.get('version_digest_limit', 3)
    webhook_url = config.get('version_digest_webhook', '') or config.get('webhook_url', '')

    if log_to_stdout:
        print(f'[version-digest] fetching from {pm_url}', flush=True)

    try:
        all_versions = fetch_dashboard(pm_url, api_key=api_key or None)
    except Exception as e:
        if log_to_stdout:
            print(f'[error] cannot reach PmSystem: {e}', flush=True)
        return {'ok': False, 'versions_count': 0, 'digest': '', 'error': str(e)}

    versions = filter_active(all_versions, limit)
    if log_to_stdout:
        print(f'[version-digest] {len(versions)} active version(s)', flush=True)

    for v in versions:
        v['_api_key'] = api_key or None
        enrich_pipeline(pm_url, v)

    digest = render_digest(versions)
    if log_to_stdout:
        try:
            print(f'\n{digest}\n', flush=True)
        except UnicodeEncodeError:
            enc = getattr(sys.stdout, 'encoding', None) or 'utf-8'
            safe = (digest + '\n').encode(enc, errors='replace').decode(enc, errors='replace')
            print(f'\n{safe}\n', flush=True)

    if not send_webhook:
        return {'ok': True, 'versions_count': len(versions), 'digest': digest, 'error': None}

    if not webhook_url:
        if log_to_stdout:
            print('[version-digest] no webhook configured, skipping send', flush=True)
        return {'ok': False, 'versions_count': len(versions), 'digest': digest,
                'error': 'no_webhook'}

    quiet = not log_to_stdout
    result = send_via_webhook(digest, webhook_url, quiet=quiet)
    ok = bool(result and result.get('success'))
    if log_to_stdout:
        if ok:
            print('[version-digest] sent via webhook', flush=True)
        else:
            print('[version-digest] send failed', flush=True)
    err = None if ok else (result or {}).get('error', 'send failed')
    return {'ok': ok, 'versions_count': len(versions), 'digest': digest, 'error': err}


def main():
    parser = argparse.ArgumentParser(description='Version status digest')
    parser.add_argument('--dry-run', action='store_true',
                        help='Print digest without sending')
    parser.add_argument('--output', default=None,
                        help='Save digest to file')
    args = parser.parse_args()

    r = run_version_digest_send(send_webhook=not args.dry_run, log_to_stdout=True)

    digest = r.get('digest') or ''
    if args.output and digest:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(digest)
        print(f'[version-digest] saved to {args.output}', flush=True)


if __name__ == '__main__':
    main()
