# -*- coding: utf-8 -*-
# [AgentAidr Task] 开始时间: 2026-04-08
# [AgentAidr Task] 任务目标: 钉钉「aider 别名 任务」异步调本机 Aider，结果 webhook
"""
钉钉指令触发本机 Aider：群内发送「aider 仓库别名 任务说明」异步执行，结果经 memo 同款 webhook 推送。

与 Palace 共用网关：palace/.env 的 PALACE_API_BASE + PALACE_API_KEY（OpenAI 兼容接口）可映射为 Aider 的
AIDER_OPENAI_API_BASE / AIDER_OPENAI_API_KEY；inherit_palace_llm 为 true（默认）时从 palace/.env 读取并注入子进程
（PALACE_PROVIDER=mock 时不注入密钥）。digest 的 aider_model 可单独指定钉钉 Aider 用的模型名，不修改 palace/.env 的
PALACE_MODEL。详见 digest_config.json 的 aider_runner 段。

安全：默认 self_only，发送者须与 memo_tracker.assistant_group_skill_uids / aliases 及通讯录扩展标签一致；仓库路径须在
repo_roots_allow 下且为别名表映射结果。配置见根 digest_config.json 的 aider_runner 段（enabled 默认 false）。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading

from skills.memo_tracker import _send_webhook
from lib.utils import DEFAULT_MY_UID, ContactsDB

_MYAGENTS = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..'))
_DEFAULT_PALACE_ENV = os.path.join(_MYAGENTS, 'palace', '.env')


def _parse_simple_env_file(path: str) -> dict[str, str]:
    """解析 KEY=VALUE 行（无 python-dotenv 依赖）；忽略空行与 # 注释。"""
    out: dict[str, str] = {}
    if not path or not os.path.isfile(path):
        return out
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if line.lower().startswith('export '):
                    line = line[7:].strip()
                if '=' not in line:
                    continue
                k, _, v = line.partition('=')
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k:
                    out[k] = v
    except OSError:
        pass
    return out


def _aider_model_for_argv(
    pv: dict[str, str],
    extra_argv: list,
    litellm_prefix: str,
    model_override: str | None,
) -> str | None:
    """确定传给 aider 的 --model。

    - digest 的 aider_model 非空时优先（仅影响钉钉 Aider，不改 palace/.env 的 PALACE_MODEL）。
    - 否则用 palace/.env 的 PALACE_MODEL。
    - extra 已含 --model 时不覆盖。
    - OpenAI 兼容网关 + LiteLLM 需要 provider/model；裸名会加 litellm_model_prefix。
    """
    flat = []
    if isinstance(extra_argv, list):
        for x in extra_argv:
            xs = str(x).strip()
            if xs:
                flat.append(xs)
    if '--model' in flat:
        return None
    m = (model_override or '').strip() or (pv.get('PALACE_MODEL') or '').strip()
    if not m:
        return None
    if '/' in m:
        return m
    p = (litellm_prefix or 'openai').strip().strip('/')
    if not p:
        return m
    return '%s/%s' % (p, m)


def _merge_palace_openai_into_env(env: dict, pv: dict[str, str]) -> None:
    """把 Palace 网关配置写入 Aider 识别的环境变量（不覆盖进程里已有值）。"""
    prov = (pv.get('PALACE_PROVIDER') or '').strip().lower()
    if prov == 'mock':
        return
    key = (pv.get('PALACE_API_KEY') or '').strip()
    base = (pv.get('PALACE_API_BASE') or '').strip()
    if key:
        env.setdefault('AIDER_OPENAI_API_KEY', key)
        env.setdefault('OPENAI_API_KEY', key)
    if base:
        env.setdefault('AIDER_OPENAI_API_BASE', base)
        env.setdefault('OPENAI_API_BASE', base)


def _pipx_local_aider_paths() -> list[str]:
    """pipx 默认把入口放在 ~/.local/bin；Windows 服务/守护进程常未带该目录 PATH。"""
    home = os.environ.get('USERPROFILE') or os.environ.get('HOME') or ''
    if not home:
        return []
    if sys.platform == 'win32':
        return [os.path.join(home, '.local', 'bin', 'aider.exe')]
    return [os.path.join(home, '.local', 'bin', 'aider')]


def _resolve_aider_executable(bin_name: str) -> str | None:
    bn = (bin_name or 'aider').strip() or 'aider'
    w = shutil.which(bn)
    if w:
        return w
    if os.path.isabs(bn) and os.path.isfile(bn):
        return bn
    for p in _pipx_local_aider_paths():
        if p and os.path.isfile(p):
            return p
    return None


def _normalize_person_display(s: str) -> str:
    t = (s or '').strip()
    if not t:
        return ''
    for sep in ('（', '('):
        if sep in t:
            t = t.split(sep, 1)[0].strip()
    return t


def _allowed_sender_labels(memo_cfg: dict, explicit_uids: list | None) -> set:
    if isinstance(explicit_uids, list) and explicit_uids:
        uids = [str(x).strip() for x in explicit_uids if str(x).strip()]
    else:
        raw = memo_cfg.get('assistant_group_skill_uids')
        if isinstance(raw, list) and len(raw) == 0:
            uids = []
        elif raw is None:
            uids = [str(os.environ.get('DINGTALK_MY_UID', DEFAULT_MY_UID)).strip()]
        elif not isinstance(raw, list):
            uids = [str(raw).strip()]
        else:
            uids = [str(x).strip() for x in raw if str(x).strip()]
    lab = set(uids)
    raw_a = memo_cfg.get('assistant_group_skill_aliases')
    if raw_a is None:
        extra = []
    elif isinstance(raw_a, list):
        extra = raw_a
    else:
        extra = [raw_a]
    for x in extra:
        xs = str(x).strip()
        if not xs:
            continue
        lab.add(xs)
        lab.add(_normalize_person_display(xs))
    for uid in list(uids):
        if not uid.isdigit():
            continue
        try:
            nm = ContactsDB._resolve_name(uid)
            if nm:
                lab.add(nm)
                lab.add(_normalize_person_display(nm))
        except Exception:
            pass
        try:
            for ent in ContactsDB.get_all():
                eu = str(ent.get('uid') or '')
                if eu == uid and ent.get('name'):
                    lab.add(ent['name'])
                    lab.add(_normalize_person_display(ent['name']))
        except Exception:
            pass
    lab.discard('')
    return lab


def _sender_matches_aider(sender: str, labels: set) -> bool:
    s = (sender or '').strip()
    if not s:
        return False
    if s in labels:
        return True
    sn = _normalize_person_display(s)
    if sn and sn in labels:
        return True
    for L in labels:
        if not L:
            continue
        ln = _normalize_person_display(L)
        if sn and ln and sn == ln:
            return True
    return False


def _parse_aider_command(text: str, trigger_main: str, trigger_alt: str):
    t = (text or '').strip()
    if not t:
        return None, None
    main = (trigger_main or 'aider').strip()
    alt = (trigger_alt or '').strip()
    lower = t.lower()
    body = None
    if main and lower.startswith(main.lower()):
        body = t[len(main):].lstrip()
    elif alt and t.startswith(alt):
        body = t[len(alt):].lstrip()
    if body is None:
        return None, None
    m = re.match(r'^(\S+)\s+(.+)$', body, re.DOTALL)
    if not m:
        return None, None
    alias = m.group(1).strip()
    instruction = m.group(2).strip()
    if not alias or not instruction:
        return None, None
    return alias, instruction


def _resolve_repo_path(alias: str, repos: dict) -> str | None:
    if not isinstance(repos, dict):
        return None
    k = (alias or '').strip()
    path = repos.get(k) or repos.get(k.lower())
    if path is None:
        return None
    return os.path.normpath(os.path.expandvars(str(path).strip()))


def _path_under_allowed_roots(repo: str, roots: list) -> bool:
    try:
        rp = os.path.normcase(os.path.realpath(repo))
    except OSError:
        return False
    for root in roots or []:
        try:
            rr = os.path.normcase(os.path.realpath(os.path.expandvars(str(root).strip())))
        except OSError:
            continue
        if rp == rr or rp.startswith(rr + os.sep):
            return True
    return False


def _is_git_work_tree(path: str) -> bool:
    """判定 path 是否位于某个 Git 工作树内。

    父仓子目录（如 dingtalk-desktop）本身可能没有 .git，需沿目录向上找到工作树根。
    """
    try:
        p = os.path.realpath(path)
    except OSError:
        return False
    if not os.path.isdir(p):
        return False
    cur = p
    drive, _ = os.path.splitdrive(cur)
    root = drive + os.sep if drive else os.sep
    while True:
        git_dir = os.path.join(cur, '.git')
        if os.path.isdir(git_dir) or os.path.isfile(git_dir):
            return True
        parent = os.path.dirname(cur)
        if parent == cur or cur == root:
            break
        cur = parent
    return False


def _truncate(s: str, n: int) -> str:
    s = s or ''
    if len(s) <= n:
        return s
    return s[: max(0, n - 1)] + '…'


_HUMANIZE_SKIP_PREFIXES = (
    'Detected dumb terminal',
    'You can skip this check',
    'Added .aider',
    'Aider v',
    'Model:',
    'Git repo:',
    'Repo-map:',
    'Note: in-chat filenames',
    'Cur working dir:',
    'Git working dir:',
    'Initial repo scan can be slow',
)


def _humanize_aider_terminal_output(raw: str, returncode: int) -> str:
    """把 Aider 原始终端日志压成钉钉可读：中文状态 + 简要原因 + 短摘录。"""
    raw = raw or ''
    lines = raw.splitlines()
    out_lines: list[str] = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if s.startswith(_HUMANIZE_SKIP_PREFIXES):
            continue
        if s.startswith("Repo-map can't include") or s.startswith('Has it been deleted'):
            continue
        if 'Scanning repo:' in s and 'it/s' in s:
            continue
        if re.match(r'^\s*\d+%\|', s):
            continue
        out_lines.append(s)

    filtered = '\n'.join(out_lines).strip()
    rl = raw.lower()

    if returncode == 0:
        status = '**状态**：已完成。'
    else:
        status = '**状态**：未正常结束（退出码 %s）。' % returncode

    hints: list[str] = []
    if 'authenticationerror' in rl or (
        'api key' in rl and 'check your api key' in rl
    ) or ('authenticate' in rl and 'provider' in rl):
        hints.append('模型接口**鉴权失败**（密钥无效、过期，或网关返回令牌不可用）。')
    elif '令牌' in raw and '不可用' in raw:
        hints.append('网关提示**令牌状态不可用**，请核对密钥与控制台额度。')
    if 'rate' in rl and 'limit' in rl:
        hints.append('可能被**限流**，可稍后再试。')
    if re.search(r'\b429\b', raw):
        hints.append('出现 **HTTP 429**（请求过频或额度不足）。')
    if 'context length' in rl or ('token' in rl and 'exceed' in rl):
        hints.append('**上下文或 Token 超限**，可缩小任务或换模型。')

    parts: list[str] = [status]
    if hints:
        parts.append('')
        parts.append('**说明**：' + ' '.join(hints))
    elif returncode != 0 and not filtered:
        parts.append('')
        parts.append('**说明**：未留下可读输出，可在本机查看 Aider 窗口或日志。')
    if filtered:
        parts.append('')
        parts.append('**摘录**（已去掉进度条与索引噪音）：')
        parts.append('')
        parts.append('```')
        parts.append(_truncate(filtered, 2800))
        parts.append('```')
    elif not hints and returncode == 0:
        parts.append('')
        parts.append('**说明**：无额外终端输出。')

    return '\n'.join(parts)


def _run_aider_worker(
    *,
    repo: str,
    instruction: str,
    aider_bin: str,
    max_seconds: int,
    max_chars: int,
    extra_argv: list,
    memo_cfg: dict,
    group_cid: str,
    alias: str,
    inherit_palace_llm: bool,
    palace_env_path: str | None,
    litellm_model_prefix: str,
    aider_model_override: str | None,
):
    env = os.environ.copy()
    env.setdefault('PYTHONUTF8', '1')
    env.setdefault('PYTHONIOENCODING', 'utf-8')
    env.setdefault('CI', '1')
    env.setdefault('TERM', 'dumb')
    flat_extra: list[str] = []
    if isinstance(extra_argv, list):
        for x in extra_argv:
            xs = str(x).strip()
            if xs:
                flat_extra.append(xs)

    pv: dict[str, str] = {}
    if inherit_palace_llm:
        p = (palace_env_path or '').strip() or _DEFAULT_PALACE_ENV
        pv = _parse_simple_env_file(p)
        _merge_palace_openai_into_env(env, pv)
    palace_model = _aider_model_for_argv(
        pv, flat_extra, litellm_model_prefix, aider_model_override)

    argv = [aider_bin, '--yes', '--no-show-model-warnings']
    if palace_model:
        argv.extend(['--model', palace_model])
    argv.extend(flat_extra)
    argv.extend(['--message', instruction])
    try:
        r = subprocess.run(
            argv,
            cwd=repo,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=max_seconds,
        )
        out = (r.stdout or '') + ('\n' + r.stderr if r.stderr else '')
        out = _truncate(out.strip(), max_chars)
        friendly = _humanize_aider_terminal_output(out, r.returncode)
        body = (
            '### Aider 结果\n\n'
            '- 仓库：`%s`\n'
            '- 别名：`%s`\n\n'
            '%s\n\n----'
            % (repo, alias, friendly)
        )
    except subprocess.TimeoutExpired:
        body = (
            '### Aider 结果\n\n'
            '- 仓库：`%s`\n'
            '- 别名：`%s`\n\n'
            '**状态**：超时（已按 %s 秒终止）。若任务较大，可在 digest 里调大 `aider_runner.max_seconds`。\n\n----'
            % (repo, alias, max_seconds)
        )
    except Exception as e:
        body = (
            '### Aider 结果\n\n'
            '**状态**：本机调度异常。\n\n'
            '**说明**：`%s`\n\n----'
            % _truncate(str(e), 500)
        )
    _send_webhook(body, memo_cfg, group_cid=group_cid)


def process_aider_runner(
    msg_id,
    text: str,
    group_cid: str,
    config: dict,
    sender_uid: str,
) -> bool:
    """
    若文本匹配 aider 指令则调度后台线程并返回 True（立即占用本条消息，避免重复触发）。
    """
    del msg_id
    ac = config.get('aider_runner')
    if not isinstance(ac, dict):
        return False
    if ac.get('enabled') is not True:
        return False

    trigger = str(ac.get('trigger_prefix') or 'aider').strip() or 'aider'
    trigger_alt = str(ac.get('alternate_trigger') or '代码助手').strip()
    alias, instruction = _parse_aider_command(text, trigger, trigger_alt)
    if not alias:
        return False

    if ac.get('self_only', True) is not False:
        explicit = ac.get('allowed_sender_uids')
        if isinstance(explicit, list) and not explicit:
            labels = _allowed_sender_labels(config, None)
        else:
            labels = _allowed_sender_labels(
                config, explicit if isinstance(explicit, list) else None)
        deny_empty = os.environ.get('DINGTALK_ASSISTANT_DENY_EMPTY_UID', '').strip().lower() in (
            '1', 'true', 'yes', 'on')
        su = str(sender_uid or '').strip()
        if not su:
            if deny_empty:
                _send_webhook(
                    '### **Aider 已忽略**\n\n发送者为空（与助理群门禁一致可设 DINGTALK_ASSISTANT_DENY_EMPTY_UID）。\n\n----',
                    config,
                    group_cid=group_cid,
                )
                return True
        elif not _sender_matches_aider(su, labels):
            _send_webhook(
                '### **Aider 已忽略**\n\n当前配置仅允许指定发送者触发。\n\n----',
                config,
                group_cid=group_cid,
            )
            return True

    repos = ac.get('repos') or {}
    repo = _resolve_repo_path(alias, repos)
    if not repo or not os.path.isdir(repo):
        _send_webhook(
            '### **Aider 未执行**\n\n未知仓库别名或目录不存在：`%s`。\n\n----' % _truncate(alias, 80),
            config,
            group_cid=group_cid,
        )
        return True

    roots = ac.get('repo_roots_allow') or ac.get('workspace_roots_allow')
    if isinstance(roots, str):
        roots = [roots]
    if not isinstance(roots, list) or not roots:
        roots = [_MYAGENTS]
    roots_n = [os.path.normpath(os.path.expandvars(str(x).strip())) for x in roots if str(x).strip()]
    if not _path_under_allowed_roots(repo, roots_n):
        _send_webhook(
            '### **Aider 拒绝**\n\n路径不在 repo_roots_allow 内。\n\n----',
            config,
            group_cid=group_cid,
        )
        return True

    if ac.get('require_git', True) is not False and not _is_git_work_tree(repo):
        _send_webhook(
            '### **Aider 未执行**\n\n`%s` 不是 Git 工作副本。\n\n----' % repo,
            config,
            group_cid=group_cid,
        )
        return True

    bin_name = str(ac.get('aider_bin') or 'aider').strip() or 'aider'
    aider_path = _resolve_aider_executable(bin_name)
    if not aider_path:
        _send_webhook(
            '### **Aider 未执行**\n\n未找到可执行文件：`%s`（可 `pipx install aider-chat`，或配置 aider_bin 为绝对路径）。\n\n----'
            % bin_name,
            config,
            group_cid=group_cid,
        )
        return True

    max_sec = int(ac.get('max_seconds') or 600)
    max_sec = max(30, min(max_sec, 3600))
    max_chars = int(ac.get('max_output_chars') or 10000)
    max_chars = max(500, min(max_chars, 50000))
    extra = ac.get('aider_extra_args')
    if not isinstance(extra, list):
        extra = []
    inherit_palace = ac.get('inherit_palace_llm', True) is not False
    palace_env_path = str(ac.get('palace_env_path') or '').strip() or None
    litellm_prefix = str(ac.get('litellm_model_prefix') or 'openai').strip() or 'openai'
    aider_model_ov = str(ac.get('aider_model') or '').strip() or None

    _send_webhook(
        '### Aider 已排队\n\n'
        '- 仓库：`%s`\n'
        '- 别名：`%s`\n'
        '- 最长等待：%s 秒\n\n'
        '后台执行中，结束后会再发一条结果摘要。\n\n----'
        % (repo, alias, max_sec),
        config,
        group_cid=group_cid,
    )

    th = threading.Thread(
        target=_run_aider_worker,
        kwargs={
            'repo': repo,
            'instruction': instruction,
            'aider_bin': aider_path,
            'max_seconds': max_sec,
            'max_chars': max_chars,
            'extra_argv': extra,
            'memo_cfg': config,
            'group_cid': group_cid,
            'alias': alias,
            'inherit_palace_llm': inherit_palace,
            'palace_env_path': palace_env_path,
            'litellm_model_prefix': litellm_prefix,
            'aider_model_override': aider_model_ov,
        },
        daemon=True,
        name='aider-runner',
    )
    th.start()
    return True
