# -*- coding: utf-8 -*-
"""Version status digest - fetch from PmSystem dashboard and push via webhook.

正文与定时管线任务同源：`_push_versions_webhook_at_dm` 的 `render_version_status_markdown`
+ 管线 checklist / 内部清单后缀；仍发往 `digest_config.json` 的 version_digest_webhooks。
@ 人按 `version_digest_webhook_at_policy` 与 webhook 下标一一对应（见配置说明），不再对三群使用同一套管线 @。

Usage:
    py version_digest.py              # fetch + send
    py version_digest.py --dry-run    # fetch + print only
    py version_digest.py --output x.md  # save to file
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional, Tuple

_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_DIR, 'digest_config.json')
_TEMPLATE_PATH = os.path.join(_DIR, 'message_templates.json')
# VersionDigest 文末固定引导 PM 打开前台（与定时管线 digest 的 pm_system_url 可不同）
VERSION_DIGEST_PM_DETAIL_URL = 'http://192.168.20.160:8112/index.html'

_DEFAULT_TEMPLATE = {
    'title': '## 版本状态 [{timestamp}]',
    'top_separator': '---',
    'show': {
        'milestone': True,
        'overdue_nodes': True,
        'risks': True,
    },
    'limits': {'risks': 3, 'overdue_nodes': 5},
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

# 与 pm-system 前端 PIPELINE_STAGES 偏移一致，用于推算「按时间应处于」的节点
STAGE_SCHEDULE_SPEC: List[Tuple[str, str, str, int]] = [
    ('planning', '规划', 'start', -7),
    ('feasibility', '可行性初评', 'start', -3),
    ('capacity', '容量评估', 'start', -2),
    ('scoping', '规格锁定', 'start', -1),
    ('dev', '开发', 'release', -10),
    ('acceptance', '验收', 'release', -7),
    ('goLiveReview', '上线评审', 'release', -5),
    ('freezeConfirm', '封版确认', 'release', -3),
    ('releaseTesting', '发布测试', 'release', -1),
    ('release', '发版', 'release', 0),
]

# 钉钉 Markdown 对「emoji + **」粘连解析易错位，容量告警仅用文字标记
ALERT_ICONS = {
    'critical': '（容量透支）',
    'warning': '（容量偏高）',
    'normal': '',
}

# 钉钉机器人 Markdown 需用 <font color="#RRGGBB"> 才有颜色，纯中文「红/黄」不会着色
_DT_COLOR_RED = '#dc2626'
_DT_COLOR_AMBER = '#d97706'
_DT_COLOR_BLUE = '#2563eb'
_DT_COLOR_GRAY = '#64748b'
_DT_COLOR_GREEN = '#16a34a'
# 数据快照 #### 标题默认色（容量正常时），比浅灰更易辨认
_DT_COLOR_SNAPSHOT_NAVY = '#1e3a8a'


def _parse_iso_date(val: Any) -> Optional[date]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    s = str(val).strip()
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], '%Y-%m-%d').date()
    except ValueError:
        return None


def _dt_font(color_hex: str, inner: str) -> str:
    """为钉钉 Markdown 包一层字体颜色（避免与 ** 混用 emoji 导致错位）。"""
    if not inner:
        return inner
    return f'<font color="{color_hex}">{inner}</font>'


def _dt_font_bold(color_hex: str, inner: str) -> str:
    """着色行同时加粗（标题类更易扫读）。"""
    if not inner:
        return inner
    t = inner.strip()
    if not (t.startswith('**') and t.endswith('**')):
        t = f'**{t}**'
    return _dt_font(color_hex, t)


def _dt_heading4(color_hex: str, title: str) -> str:
    """四级标题：#### + 着色 + 加粗。"""
    return f'#### {_dt_font_bold(color_hex, title)}'


# 列表前缀（U+2022 实心圆点，比「·」更易辨认）
_VD_BULLET = '\u2022 '


class FetchAuthError(Exception):
    """Raised when PM API authentication fails."""


def _load_config():
    try:
        with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _load_webhook_config() -> dict:
    path = os.path.join(_DIR, 'webhook_config.json')
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            j = json.load(f)
        return j if isinstance(j, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _collect_version_digest_webhooks_urls_only(config: dict) -> List[str]:
    """仅解析 URL 列表（未用 webhook_config 键名时）。"""
    raw = config.get('version_digest_webhooks')
    urls: List[str] = []
    if isinstance(raw, list):
        for u in raw:
            s = str(u).strip()
            if s:
                urls.append(s)
    if urls:
        seen = set()
        out: List[str] = []
        for u in urls:
            if u not in seen:
                seen.add(u)
                out.append(u)
        return out
    main = (config.get('version_digest_webhook') or '').strip()
    if main:
        urls.append(main)
    extra = config.get('version_digest_webhook_extra') or []
    if isinstance(extra, list):
        for u in extra:
            s = str(u).strip()
            if s:
                urls.append(s)
    if not urls:
        fb = (config.get('webhook_url') or '').strip()
        if fb:
            urls.append(fb)
    seen = set()
    out = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _collect_version_digest_targets(config: dict) -> Tuple[List[str], List[Optional[str]]]:
    """返回 (urls, webhook_config 键名)；键名为 None 表示走 legacy URL 列表 + 下标对齐 @ 策略。"""
    wc = _load_webhook_config()
    keys = config.get('version_digest_webhook_keys')
    if isinstance(keys, list) and keys:
        urls: List[str] = []
        key_out: List[Optional[str]] = []
        for k in keys:
            rawk = str(k).strip()
            if not rawk:
                continue
            u = str(wc.get(rawk) or '').strip()
            if u:
                urls.append(u)
                key_out.append(rawk)
            else:
                print(
                    f'[version-digest] webhook_config.json 缺少键 {rawk!r}，已跳过',
                    flush=True,
                )
        if urls:
            return urls, key_out
    urls = _collect_version_digest_webhooks_urls_only(config)
    return urls, [None] * len(urls)


def _collect_version_digest_webhooks(config: dict) -> List[str]:
    """版本状态推送 URL 列表（兼容旧调用）。"""
    urls, _ = _collect_version_digest_targets(config)
    return urls


def _dingtalk_mobile_from_user(u: Optional[dict]) -> str:
    if not u or not isinstance(u, dict):
        return ''
    ext = u.get('externalIds') or u.get('external_ids') or {}
    if not isinstance(ext, dict):
        ext = {}
    return (str(ext.get('dingtalk_mobile') or '').strip()) or (str(u.get('phone') or '').strip())


def _normalize_person_name(s: str) -> str:
    return str(s or '').replace(' ', '').strip()


def _policy_for_target(
    config: dict, index: int, wc_key: Optional[str],
) -> Optional[str]:
    """优先 version_digest_webhook_at[键名]；否则 legacy 的 version_digest_webhook_at_policy 数组下标。"""
    d = config.get('version_digest_webhook_at')
    if isinstance(d, dict) and wc_key:
        if wc_key in d:
            v = d.get(wc_key)
            if v is None:
                return None
            s = str(v).strip()
            return s if s else None
    arr = config.get('version_digest_webhook_at_policy')
    if isinstance(arr, list) and index < len(arr):
        return str(arr[index]).strip()
    return None


def _ops_member_names_for_digest(config: dict) -> List[str]:
    explicit = config.get('version_digest_ops_member_names')
    if isinstance(explicit, list) and explicit:
        return [_normalize_person_name(x) for x in explicit if _normalize_person_name(x)]
    mr = config.get('member_roles') or {}
    for key in ('operations_team', 'operations'):
        ot = mr.get(key)
        if isinstance(ot, dict):
            mem = ot.get('members')
            if isinstance(mem, list):
                return [_normalize_person_name(x) for x in mem if _normalize_person_name(x)]
    return []


def _at_mobiles_pm_apm(config: dict, users: List[dict]) -> List[str]:
    by_id = {str(u.get('id') or ''): u for u in users if u.get('id')}
    out: List[str] = []
    seen: set = set()
    for uid in (config.get('default_pipeline_pm_user_id'), config.get('default_pipeline_apm_user_id')):
        u = by_id.get(str(uid or '').strip())
        m = _dingtalk_mobile_from_user(u)
        if m and m not in seen:
            seen.add(m)
            out.append(m)
    return out


def _at_mobiles_ops_team(config: dict, users: List[dict]) -> List[str]:
    want = {_normalize_person_name(n) for n in _ops_member_names_for_digest(config)}
    if not want:
        return []
    out: List[str] = []
    seen: set = set()
    for u in users:
        if not isinstance(u, dict):
            continue
        uname = _normalize_person_name(str(u.get('name') or ''))
        if uname not in want:
            continue
        m = _dingtalk_mobile_from_user(u)
        if m and m not in seen:
            seen.add(m)
            out.append(m)
    return out


def _build_version_digest_at_per_url(
    config: dict,
    users: List[dict],
    webhook_urls: List[str],
    wc_keys: List[Optional[str]],
    legacy_pipeline_at: List[str],
) -> List[Optional[List[str]]]:
    """每个 webhook 一份 @ 手机号列表；None 表示不圈人。wc_keys 与 webhook_config 键名对齐。"""
    n = len(webhook_urls)
    out: List[Optional[List[str]]] = []
    for i in range(n):
        k = wc_keys[i] if i < len(wc_keys) else None
        pol = _policy_for_target(config, i, k)
        if pol is None or str(pol).strip() == '':
            out.append(list(legacy_pipeline_at))
            continue
        p = str(pol).strip().lower()
        if p in ('none', 'off', 'no', '-', 'empty'):
            out.append(None)
        elif p in ('pm_apm', 'pmo', 'pm_apm_only'):
            out.append(_at_mobiles_pm_apm(config, users))
        elif p in ('ops_team', 'ops', 'operations'):
            out.append(_at_mobiles_ops_team(config, users))
        elif p in ('pipeline', 'full', 'all', 'legacy'):
            out.append(list(legacy_pipeline_at))
        else:
            out.append(list(legacy_pipeline_at))
    return out


def _send_digest_to_webhooks(
    text: str,
    webhook_urls: List[str],
    *,
    quiet: bool,
    at_mobiles: Optional[List[str]] = None,
) -> dict:
    """同一正文依次 POST（如异常通知）；全部成功才算 success。"""
    if not webhook_urls:
        return {'success': False, 'error': 'no_webhook'}
    last_err = None
    for idx, url in enumerate(webhook_urls):
        r = send_via_webhook(text, url, quiet=quiet, at_mobiles=at_mobiles)
        if not r.get('success'):
            last_err = r.get('error') or 'send failed'
            if not quiet:
                print(f'[send] webhook #{idx + 1} failed: {last_err}', flush=True)
    if last_err is None:
        return {'success': True}
    return {'success': False, 'error': last_err}


def _send_digest_body_to_webhooks(
    digest_body: str,
    webhook_urls: List[str],
    at_mobiles_per_url: List[Optional[List[str]]],
    *,
    quiet: bool,
) -> dict:
    """digest_body 不含 @ 行；按 webhook 下标附加对应 @ 后发送。"""
    if not webhook_urls:
        return {'success': False, 'error': 'no_webhook'}
    last_err = None
    for idx, url in enumerate(webhook_urls):
        raw = at_mobiles_per_url[idx] if idx < len(at_mobiles_per_url) else []
        if raw is None:
            raw = []
        full = append_dingtalk_at_line(digest_body, raw)
        r = send_via_webhook(full, url, quiet=quiet, at_mobiles=raw if raw else None)
        if not r.get('success'):
            last_err = r.get('error') or 'send failed'
            if not quiet:
                print(f'[send] webhook #{idx + 1} failed: {last_err}', flush=True)
    if last_err is None:
        return {'success': True}
    return {'success': False, 'error': last_err}


def _api_get(url, timeout=10, api_key=None):
    headers = {}
    if api_key:
        headers['X-Api-Key'] = api_key
    req = urllib.request.Request(url, headers=headers, method='GET')
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))


def fetch_checklist_blocks(pm_url, version_ids, api_key=None):
    """从 PM 内部接口拉取各版本发版检查清单 Markdown 片段（与专项推送同源）。"""
    if not version_ids:
        return {}
    try:
        qs = urllib.parse.urlencode({'version_ids': ','.join(version_ids)})
        url = f'{pm_url}/api/internal/version-checklist-blocks?{qs}'
        data = _api_get(url, api_key=api_key)
        inner = data.get('data') if isinstance(data, dict) else None
        if not isinstance(inner, dict):
            return {}
        return inner.get('blocks') or {}
    except Exception as e:
        print(f'[warn] checklist blocks: {e}', flush=True)
        return {}


def fetch_pm_users(pm_url: str, api_key=None) -> List[dict]:
    """从 GET /api/data 取 users 数组（含 externalIds），用于 Webhook @ 手机号。"""
    try:
        data = _api_get(f'{pm_url.rstrip("/")}/api/data', api_key=api_key)
        if not isinstance(data, dict):
            return []
        users = data.get('users')
        return users if isinstance(users, list) else []
    except Exception as e:
        print(f'[warn] fetch_pm_users: {e}', flush=True)
        return []


def collect_at_mobiles_for_versions(versions: List[dict], users: List[dict]) -> List[str]:
    """汇总当前摘要中各版本 PLD/PLE/PLT-F/PLT-B 对应成员的钉钉手机号（去重）。"""
    by_id = {str(u.get('id') or ''): u for u in users if u.get('id')}
    out: List[str] = []
    seen: set = set()
    for v in versions:
        for key in ('_pld', '_ple', '_plt_f', '_plt_b', '_plt'):
            uid = v.get(key) or ''
            if not uid:
                continue
            u = by_id.get(str(uid))
            if not u:
                continue
            ext = u.get('externalIds') or u.get('external_ids') or {}
            if not isinstance(ext, dict):
                ext = {}
            m = (str(ext.get('dingtalk_mobile') or '').strip()) or (str(u.get('phone') or '').strip())
            if m and m not in seen:
                seen.add(m)
                out.append(m)
    return out


def append_dingtalk_at_line(markdown: str, mobiles: List[str]) -> str:
    if not mobiles:
        return markdown
    line = ' '.join(f'@{m}' for m in mobiles)
    return markdown.rstrip() + '\n\n' + line


def append_pm_detail_footer(markdown: str, url: str = VERSION_DIGEST_PM_DETAIL_URL) -> str:
    """文末增加 PM 查看版本详情链接（钉钉 Markdown）。"""
    u = (url or '').strip()
    if not u:
        return markdown
    block = f'\n\n---\n\n请 PM 前往 [查看版本详情]({u})。'
    return markdown.rstrip() + block


def fetch_dashboard(pm_url, api_key=None):
    try:
        data = _api_get(f'{pm_url}/api/dashboard', api_key=api_key)
        versions = data.get('data', {}).get('activeVersions', [])
        if versions:
            return versions
        return []
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise FetchAuthError(f'HTTP {e.code}: Unauthorized')
        print(f'[warn] dashboard API failed: {e}', flush=True)
    except Exception as e:
        print(f'[warn] dashboard API failed: {e}', flush=True)
    return []


def _render_auth_fail_notice(pm_url, err_text):
    now_str = datetime.now().strftime('%m/%d %H:%M')
    lines = [
        f'## 版本状态拉取失败 [{now_str}]',
        '',
        f'- 数据源：`{pm_url}/api/dashboard`',
        f'- 结果：鉴权失败（{err_text}）',
        '- 处理：本次已跳过版本摘要推送，避免发送旧数据',
        '',
        '### 行动建议',
        '1. 在 PM 后端 `backend/.env` 设置 `SERVICE_API_KEY`，须与 `dingtalk-desktop/digest_config.json` 的 `pm_system_api_key` 一致',
        f'2. 确认本通知中的数据源地址 `{pm_url}` 可达，且进程已重启使 `.env` 生效',
        '3. 访问 `GET /api/health`，若 `service_api_key_configured` 为 false，说明服务端未读到密钥（常见原因：`.env` 不在 `backend/` 或启动方式导致旧版相对路径未加载）',
        '4. 本机执行 `py version_digest.py --dry-run` 复测，确认不再出现 401',
        '5. 若 key 已更新，重跑一次定时脚本或手动触发「版本咋样了」',
        '',
        '<font color="#999999">小秘书提醒</font>',
    ]
    return '\n'.join(lines)


def _notify_fetch_failed(webhook_urls, pm_url, err_text, log_to_stdout=True):
    if not webhook_urls:
        if log_to_stdout:
            print('[version-digest] no webhook configured, skip failure notice', flush=True)
        return {'success': False, 'error': 'no_webhook'}
    notice = _render_auth_fail_notice(pm_url, err_text)
    result = _send_digest_to_webhooks(notice, webhook_urls, quiet=not log_to_stdout)
    if log_to_stdout:
        if result.get('success'):
            print('[version-digest] auth-failure notice sent (all webhooks)', flush=True)
        else:
            print(f"[version-digest] auth-failure notice failed: {result.get('error')}", flush=True)
    return result


def _render_empty_data_notice(pm_url):
    now_str = datetime.now().strftime('%m/%d %H:%M')
    lines = [
        f'## 版本状态数据异常 [{now_str}]',
        '',
        f'- 数据源：`{pm_url}/api/dashboard`',
        '- 结果：接口鉴权通过，但返回 0 条活跃版本',
        '- 处理：本次已跳过正常版本摘要推送，避免误导',
        '',
        '### 行动建议',
        f'1. 核对 PM 实例 `{pm_url}` 当前连接的数据库路径（`backend/data/gamedev_pm.db`）是否为正确环境',
        '2. 直接检查 `/api/versions` 是否也为 0（若为 0，优先排查后端实例数据）',
        '3. 如刚重启/重部署，确认 `backend/.env` 与数据目录未被换到空环境',
        '4. 修复后手动重跑 `py version_digest.py` 验证推送恢复',
        '',
        '<font color="#999999">小秘书提醒</font>',
    ]
    return '\n'.join(lines)


def _notify_empty_data(webhook_urls, pm_url, log_to_stdout=True):
    if not webhook_urls:
        if log_to_stdout:
            print('[version-digest] no webhook configured, skip empty-data notice', flush=True)
        return {'success': False, 'error': 'no_webhook'}
    notice = _render_empty_data_notice(pm_url)
    result = _send_digest_to_webhooks(notice, webhook_urls, quiet=not log_to_stdout)
    if log_to_stdout:
        if result.get('success'):
            print('[version-digest] empty-data notice sent (all webhooks)', flush=True)
        else:
            print(f"[version-digest] empty-data notice failed: {result.get('error')}", flush=True)
    return result


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
        def _json_feat_done(f):
            st = (f.get('status') or '').strip()
            return f.get('stage') in ('done', 'released') or st == 'done'

        done = sum(1 for f in vf if _json_feat_done(f))
        blocked = sum(1 for f in vf if f.get('isBlocked') or f.get('stage') == 'blocked')
        in_prog = sum(
            1 for f in vf
            if (not _json_feat_done(f)) and f.get('stage') in ('dev', 'qa', 'testing', 'in_progress')
        )
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
            '_plt_f': v.get('pltFUserId', '') or v.get('pltUserId', ''),
            '_plt_b': v.get('pltBUserId', ''),
            '_plt': v.get('pltFUserId', '') or v.get('pltBUserId', '') or v.get('pltUserId', ''),
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
    """拉版本详情，解析管线超期、当前节点、时间进度与「按日程应处于」节点。"""
    vid = version.get('id')
    api_key = version.get('_api_key')
    detail: Dict[str, Any] = {}
    if vid:
        try:
            detail = fetch_version_detail(pm_url, vid, api_key=api_key) or {}
        except Exception as e:
            print(f'[warn] cannot fetch version {vid}: {e}', flush=True)

    ddls = version.get('_pipeline_ddls') or detail.get('pipeline_ddls') or {}
    status = version.get('_pipeline_status') or detail.get('pipeline_status') or {}
    version['_pipeline_ddls'] = ddls
    version['_pipeline_status'] = status
    version.setdefault('_pld', detail.get('pld_user_id') or detail.get('pldUserId', ''))
    version.setdefault('_ple', detail.get('ple_user_id') or detail.get('pleUserId', ''))
    plt_f = detail.get('plt_f_user_id') or detail.get('pltFUserId') or detail.get('plt_user_id') or detail.get('pltUserId', '')
    plt_b = detail.get('plt_b_user_id') or detail.get('pltBUserId', '')
    version.setdefault('_plt_f', plt_f)
    version.setdefault('_plt_b', plt_b)
    version.setdefault('_plt', plt_f or plt_b)

    today = date.today()
    overdue: List[str] = []
    overdue_max_days = 0
    current_node = None

    for stage_id, label in PIPELINE_STAGES:
        if stage_id == 'retro':
            continue
        done = bool(status.get(stage_id, False))
        if done:
            continue
        ddl_str = ddls.get(stage_id)
        if ddl_str:
            try:
                ddl_date = datetime.strptime(str(ddl_str)[:10], '%Y-%m-%d').date()
                if ddl_date < today:
                    days_over = (today - ddl_date).days
                    overdue_max_days = max(overdue_max_days, days_over)
                    overdue.append(f'{label} (超{days_over}天)')
                elif current_node is None:
                    days_until = (ddl_date - today).days
                    current_node = (label, str(ddl_str)[:10], days_until)
            except ValueError:
                pass
        if current_node is None and not done:
            current_node = (label, str(ddl_str)[:10] if ddl_str else '?', None)

    version['_pipeline_overdue'] = overdue
    version['_pipeline_current'] = current_node

    start_d = _parse_iso_date(detail.get('start_date')) or _parse_iso_date(
        version.get('startDate')
    )
    release_d = _parse_iso_date(version.get('releaseDate')) or _parse_iso_date(
        detail.get('release_date')
    )
    if not start_d and release_d:
        start_d = release_d - timedelta(days=90)

    eff: Dict[str, Optional[date]] = {}
    for sid, _label, base, off in STAGE_SCHEDULE_SPEC:
        raw = ddls.get(sid)
        if raw:
            eff[sid] = _parse_iso_date(raw)
        elif base == 'start' and start_d:
            eff[sid] = start_d + timedelta(days=off)
        elif base == 'release' and release_d:
            eff[sid] = release_d + timedelta(days=off)
        else:
            eff[sid] = None

    max_behind = overdue_max_days
    for sid, _label, *_ in STAGE_SCHEDULE_SPEC:
        if bool(status.get(sid, False)):
            continue
        ddl = eff.get(sid)
        if ddl and today > ddl:
            max_behind = max(max_behind, (today - ddl).days)

    expected_label = '—'
    for sid, label, *_ in STAGE_SCHEDULE_SPEC:
        if bool(status.get(sid, False)):
            continue
        ddl = eff.get(sid)
        if ddl is None:
            expected_label = label
            break
        if today <= ddl:
            expected_label = label
            break
    if expected_label == '—':
        for sid, label, *_ in STAGE_SCHEDULE_SPEC:
            if not bool(status.get(sid, False)):
                expected_label = label
                break

    actual_label = '—'
    if current_node:
        actual_label = current_node[0]

    schedule_state = 'ok'
    if max_behind > 0:
        schedule_state = 'behind'
    else:
        if current_node and current_node[2] is not None and current_node[2] >= 14:
            schedule_state = 'ahead'

    version['_schedule_max_behind_days'] = max_behind
    version['_schedule_state'] = schedule_state
    version['_expected_stage_label'] = expected_label
    version['_actual_stage_label'] = actual_label


def _render_version(v, tmpl=None, *, checklist_append=None):
    """按产品约定结构输出：### 状态emoji 版本|剩余天 → #### 建议 → #### 时间进度 → 超期 → 数据快照等。"""
    if tmpl is None:
        tmpl = _load_template()
    show = tmpl.get('show', {})
    limits = tmpl.get('limits', {})

    name = v.get('name', '?')
    days_rem = v.get('daysRemaining')
    if days_rem is None:
        sub = '发版日未定'
    elif days_rem <= 0:
        sub = '已到期或超发版日'
    else:
        sub = f'剩余{days_rem}天'

    pipeline_overdue = v.get('_pipeline_overdue') or []
    cs = v.get('capacitySummary') or {}
    risks_early = v.get('risks') or []
    al_early = cs.get('alertLevel', 'normal')
    fs = v.get('featureSummary') or {}
    tot_e = fs.get('total') or 0
    done_e = fs.get('done') or 0
    max_bd = int(v.get('_schedule_max_behind_days') or 0)

    health_bits: List[str] = []
    if pipeline_overdue:
        health_bits.append('管线超期')
    if al_early == 'critical':
        health_bits.append('容量透支')
    elif al_early == 'warning':
        health_bits.append('容量偏高')
    if risks_early:
        health_bits.append('阻塞或里程碑风险')
    if tot_e > 0 and days_rem is not None and days_rem <= 14 and done_e == 0:
        health_bits.append('Feature 完成度仍低')

    is_red = bool(pipeline_overdue or al_early == 'critical' or risks_early)
    if days_rem is not None and days_rem <= 0:
        v_emoji = '❌'
    elif pipeline_overdue or max_bd > 0 or is_red:
        v_emoji = '❌'
    elif health_bits:
        v_emoji = '⚠️'
    else:
        v_emoji = '✅'

    lines: List[str] = [f'### {v_emoji} {name}|{sub}']

    if is_red:
        action = '优先处理管线超期、解除阻塞与容量透支'
        hcolor = _DT_COLOR_RED
    elif health_bits:
        action = '跟进容量与 Feature 完成度'
        hcolor = _DT_COLOR_AMBER
    else:
        action = '维持节奏，继续按管线推进'
        hcolor = _DT_COLOR_GREEN

    overview = '、'.join(health_bits) if health_bits else '未发现上述预警项'
    lines.append(_dt_heading4(hcolor, f'[{action}]'))
    lines.append(f'{_VD_BULLET}{overview}')

    sched = v.get('_schedule_state', 'ok')
    if days_rem is not None and days_rem <= 0:
        sched_title = '发版日已过，请立即评估补救'
        scolor = _DT_COLOR_RED
    elif sched == 'behind' and max_bd > 0:
        sched_title = f'落后时间进度{max_bd}天'
        scolor = _DT_COLOR_RED
    elif pipeline_overdue and max_bd <= 0:
        sched_title = '落后时间进度（管线已超期）'
        scolor = _DT_COLOR_RED
    elif sched == 'ahead':
        sched_title = '高于时间进度'
        scolor = _DT_COLOR_GREEN
    else:
        sched_title = '符合时间进度'
        scolor = _DT_COLOR_BLUE

    lines.append(_dt_heading4(scolor, sched_title))
    exp = v.get('_expected_stage_label') or '—'
    act = v.get('_actual_stage_label') or '—'
    lines.append(f'{_VD_BULLET}当前应处于 **{exp}**')
    lines.append(f'{_VD_BULLET}系统实际处于 **{act}**')

    if show.get('overdue_nodes', True) and pipeline_overdue:
        max_od = int(limits.get('overdue_nodes', 5) or 5)
        max_od = max(1, min(max_od, 20))
        shown = pipeline_overdue[:max_od]
        lines.append(_dt_heading4(_DT_COLOR_RED, '超期节点'))
        for item in shown:
            lines.append(f'{_VD_BULLET}{item}')
        if len(pipeline_overdue) > max_od:
            lines.append(f'{_VD_BULLET}… 等 {len(pipeline_overdue) - max_od} 项')

    total = fs.get('total', 0)
    done = fs.get('done', 0)
    in_prog = fs.get('inProgress', 0)
    blocked = fs.get('blocked', 0)
    not_started = fs.get('notStarted', 0)
    parts = [f'{total}个']
    if done:
        parts.append(f'{done}完成')
    if in_prog:
        parts.append(f'{in_prog}开发中')
    if blocked:
        parts.append(f'{blocked}阻塞')
    if not_started:
        parts.append(f'{not_started}未开始')
    feat_snap = ' · '.join(parts) if parts else '0个'
    if total > 0:
        feat_snap += f' · 完成 {round(done / total * 100)}%'
    usage = cs.get('usagePct', 0)
    cap_al = cs.get('alertLevel', 'normal')
    alert = ALERT_ICONS.get(cap_al, '')
    cap_part = f'容量 {usage}%{alert}'
    snap_color = (
        _DT_COLOR_RED
        if cap_al == 'critical'
        else (_DT_COLOR_AMBER if cap_al == 'warning' else _DT_COLOR_SNAPSHOT_NAVY)
    )
    lines.append(_dt_heading4(snap_color, '数据快照'))
    lines.append(f'{_VD_BULLET}Feature：**{feat_snap}**')
    lines.append(f'{_VD_BULLET}{cap_part}')

    if show.get('milestone', True):
        ms = v.get('nextMilestone')
        if ms:
            ms_name = ms.get('name', '?')
            ms_date = ms.get('date', '?')
            ms_days = ms.get('daysUntil')
            suf = ''
            if ms_days is not None:
                suf = f'，{ms_days}天后到期' if ms_days > 0 else '，已到期'
            lines.append(f'{_VD_BULLET}下一里程碑：**{ms_name}**（{ms_date}）{suf}')

    if show.get('risks', True) and risks_early:
        max_risks = int(limits.get('risks', 3) or 3)
        lines.append(_dt_heading4(_DT_COLOR_AMBER, '其它风险'))
        for r in risks_early[:max_risks]:
            lines.append(f'{_VD_BULLET}{r}')

    body = '\n\n'.join(lines)
    if checklist_append:
        body = body + '\n\n' + checklist_append
    return body


def render_digest(versions, checklist_by_id=None):
    tmpl = _load_template()
    now_str = datetime.now().strftime('%m/%d %H:%M')
    title = tmpl.get('title', '## 版本状态 [{timestamp}]').format(timestamp=now_str)
    top_sep = tmpl.get('top_separator', '---')
    block_sep = '\n\n' + tmpl.get('separator', '---') + '\n\n'
    footer = '\n\n' + tmpl.get('separator', '---') + '\n\n' + tmpl.get(
        'footer', '<font color="#999999">小秘书提醒</font>')

    cl = checklist_by_id or {}
    blocks = [
        _render_version(v, tmpl, checklist_append=cl.get(v.get('id')))
        for v in versions
    ] or ['（无活跃版本）']
    return title + '\n\n' + top_sep + '\n\n' + block_sep.join(blocks) + footer


def send_via_webhook(text, webhook_url, *, quiet=False, at_mobiles=None):
    # title 须含自定义关键词「小秘书提醒」，与多群机器人配置一致
    payload = {
        'msgtype': 'markdown',
        'markdown': {
            'title': '小秘书提醒 · 版本状态',
            'text': text,
        },
    }
    if at_mobiles:
        payload['at'] = {'atMobiles': list(at_mobiles), 'isAtAll': False}
    body = json.dumps(payload).encode('utf-8')
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
    webhook_urls, wc_keys = _collect_version_digest_targets(config)

    if log_to_stdout:
        print(f'[version-digest] fetching from {pm_url}', flush=True)

    try:
        all_versions = fetch_dashboard(pm_url, api_key=api_key or None)
    except FetchAuthError as e:
        err = str(e)
        if log_to_stdout:
            print(f'[error] PM API auth failed: {err}', flush=True)
        notice_ok = False
        if send_webhook:
            notice_ret = _notify_fetch_failed(
                webhook_urls, pm_url, err, log_to_stdout=log_to_stdout
            )
            notice_ok = bool(notice_ret and notice_ret.get('success'))
        return {
            'ok': False,
            'versions_count': 0,
            'digest': '',
            'error': f'auth_failed: {err}',
            'sent_failure_notice': notice_ok,
        }
    except Exception as e:
        if log_to_stdout:
            print(f'[error] cannot reach PmSystem: {e}', flush=True)
        return {'ok': False, 'versions_count': 0, 'digest': '', 'error': str(e)}

    if not all_versions:
        if log_to_stdout:
            print('[error] dashboard returned 0 active versions', flush=True)
        notice_ok = False
        if send_webhook:
            notice_ret = _notify_empty_data(webhook_urls, pm_url, log_to_stdout=log_to_stdout)
            notice_ok = bool(notice_ret and notice_ret.get('success'))
        return {
            'ok': False,
            'versions_count': 0,
            'digest': '',
            'error': 'empty_active_versions',
            'sent_empty_notice': notice_ok,
        }

    versions = filter_active(all_versions, limit)
    if log_to_stdout:
        print(f'[version-digest] {len(versions)} active version(s)', flush=True)

    version_names = [
        str(v.get('name') or '').strip() for v in versions if str(v.get('name') or '').strip()
    ]
    try:
        import _push_versions_webhook_at_dm as _pvd
    except Exception as e:
        if log_to_stdout:
            print(f'[error] load progress digest module: {e}', flush=True)
        return {
            'ok': False,
            'versions_count': len(versions),
            'digest': '',
            'error': str(e),
        }

    digest, at_ms, n_built = _pvd.render_multi_version_digest_markdown(
        pm_url,
        api_key or None,
        version_names,
        config,
        log_to_stdout=log_to_stdout,
    )
    if n_built == 0:
        if log_to_stdout:
            print('[error] version digest body: no version rendered', flush=True)
        return {
            'ok': False,
            'versions_count': 0,
            'digest': '',
            'error': 'digest_body_failed',
        }

    digest = append_pm_detail_footer(digest)
    pm_users = fetch_pm_users(pm_url, api_key=api_key or None)
    at_per_url = _build_version_digest_at_per_url(
        config, pm_users, webhook_urls, wc_keys, at_ms,
    )

    if log_to_stdout:
        try:
            print(f'\n{digest}\n', flush=True)
            pairs = list(zip(wc_keys or [None] * len(webhook_urls), webhook_urls))
            print(f'[version-digest] webhooks: {pairs}', flush=True)
            at_map = config.get('version_digest_webhook_at')
            if isinstance(at_map, dict) and at_map:
                print(f'[version-digest] @ 策略: {at_map}', flush=True)
        except UnicodeEncodeError:
            enc = getattr(sys.stdout, 'encoding', None) or 'utf-8'
            safe = (digest + '\n').encode(enc, errors='replace').decode(enc, errors='replace')
            print(f'\n{safe}\n', flush=True)

    if not send_webhook:
        return {'ok': True, 'versions_count': n_built, 'digest': digest, 'error': None}

    if not webhook_urls:
        if log_to_stdout:
            print('[version-digest] no webhook configured, skipping send', flush=True)
        return {'ok': False, 'versions_count': n_built, 'digest': digest,
                'error': 'no_webhook'}

    quiet = not log_to_stdout
    result = _send_digest_body_to_webhooks(
        digest, webhook_urls, at_per_url, quiet=quiet,
    )
    ok = bool(result and result.get('success'))
    if log_to_stdout:
        if ok:
            print(f'[version-digest] sent via {len(webhook_urls)} webhook(s)', flush=True)
        else:
            print('[version-digest] send failed (one or more webhooks)', flush=True)
    err = None if ok else (result or {}).get('error', 'send failed')
    return {'ok': ok, 'versions_count': n_built, 'digest': digest, 'error': err}


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

    if r.get('error'):
        raise SystemExit(2)
    if not args.dry_run and not r.get('ok', False):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
