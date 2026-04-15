# -*- coding: utf-8 -*-
"""
助理通知主群：口令「让涛哥更新」→ 从群内最近消息里解析 Cursor 收工推送里的锚点 `tao-update-scope:子模块`，
再以用户本人身份经 daemon POST /send 单聊杨玉涛（需本机钉钉 + daemon）。

锚点由 Cursor 发助理群 Webhook 时在正文中写入（见 .cursor/skills/dingtalk-actions）。

涛哥单聊（digest taoge_update.recipient_cid）：监测 Frida 推送 + /fetch 轮询；
若涛哥在「涛哥，{模块}求更新」之后回复完成类口令，向助理群 webhook 推送「涛哥已经更完了{模块}」。
"""
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime

from skills.memo_tracker import _send_wish_webhook, _wish_webhook_for_cid
from lib.utils import ContactsDB, DEFAULT_MY_UID, extract_markdown_body_from_ct1200_raw

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_THIS)
_DIGEST_PATH = os.path.join(_ROOT, 'digest_config.json')

TAO_SCOPE_RE = re.compile(r"tao-update-scope:\s*(\S+)", re.IGNORECASE)
TAO_REQUEST_LINE_RE = re.compile(r"涛哥，(.+?)求更新")

# POST /send 会等 B1 就绪 + exec_js + beacon；过短易在客户端先超时，daemon 仍可能已发出，误报失败
try:
    _SEND_HTTP_TIMEOUT_S = int(float(os.environ.get("DINGTALK_SEND_TIMEOUT_S", "120")))
except (TypeError, ValueError):
    _SEND_HTTP_TIMEOUT_S = 120
_SEND_HTTP_TIMEOUT_S = max(30, min(_SEND_HTTP_TIMEOUT_S, 300))

_DEFAULT_RESTART_MODULES = frozenset(
    x.strip().lower()
    for x in (
        "pm-system",
        "performeval",
        "task_reminder",
        "dingtalk-desktop",
        "cci_system",
        "cci-scoresystem",
        "taskreminderapp",
    )
    if x.strip()
)


def _load_taoge_cfg() -> dict:
    try:
        with open(_DIGEST_PATH, "r", encoding="utf-8") as f:
            root = json.load(f)
        t = root.get("taoge_update")
        return t if isinstance(t, dict) else {}
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def get_taoge_recipient_cid() -> str:
    return str(_load_taoge_cfg().get("recipient_cid") or "").strip()


def _normalize_person_display(s: str) -> str:
    t = (s or "").strip()
    if not t:
        return ""
    for sep in ("（", "("):
        if sep in t:
            t = t.split(sep, 1)[0].strip()
    return t


def _msg_is_self(msg: dict) -> bool:
    if msg.get("is_self") is True:
        return True
    uid = str(msg.get("uid") or "").strip()
    my_uid = str(os.environ.get("DINGTALK_MY_UID", DEFAULT_MY_UID)).strip()
    return bool(uid and my_uid and uid == my_uid)


def _identity_matches_tao(msg: dict, tcfg: dict) -> bool:
    target = str(tcfg.get("recipient_display_name") or "杨玉涛").strip()
    uid = str(msg.get("uid") or "").strip()
    sender = str(msg.get("sender") or "").strip()
    for part in (uid, sender):
        if not part or part == "?":
            continue
        if part == target:
            return True
        if _normalize_person_display(part) == target:
            return True
    if uid.isdigit():
        try:
            nm = ContactsDB._resolve_name(uid)
            if nm and _normalize_person_display(nm) == target:
                return True
        except Exception:
            pass
    return False


def _text_looks_like_tao_done(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if any(x in t for x in ("完成", "好了", "哦了")):
        return True
    if "更了" in t:
        return True
    tl = t.lower()
    if re.search(r"(?i)\bdone\b", tl):
        return True
    if re.search(r"(?i)\bdown\b", tl):
        return True
    return False


def _parse_scope_from_our_request_line(text: str) -> str | None:
    m = TAO_REQUEST_LINE_RE.search((text or "").replace("\n", " "))
    if not m:
        return None
    scope = m.group(1).strip().rstrip("~").strip()
    if scope.endswith("需要重启"):
        scope = scope[: -4].strip()
    scope = re.sub(r"\s*\[忙疯了\]\s*$", "", scope).strip()
    return scope or None


def _skip_msg_before_router_start(msg: dict, router_start_ms: int) -> bool:
    if not router_start_ms or router_start_ms <= 0:
        return False
    ts = int(msg.get("ts") or 0)
    if ts <= 0:
        return msg.get("ding_mid") is None
    return ts < router_start_ms


def _taoge_notify_log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[skill_router][{ts}] {msg}", flush=True)


def _find_scope_for_tao_done_reply(tcfg: dict, dm_cid: str, tao_ts: int) -> str | None:
    count = int(tcfg.get("done_fetch_message_count") or 40)
    timeout = int(tcfg.get("done_fetch_timeout_s") or 95)
    max_gap_ms = int(float(tcfg.get("done_reply_max_gap_hours") or 72) * 3600 * 1000)
    rows = _fetch_recent_messages(dm_cid, count=count, timeout=timeout)
    if not rows:
        return None
    best_ts = -1
    best_scope = None
    for m in rows:
        if not m.get("is_self"):
            continue
        ts = int(m.get("ts") or 0)
        if ts <= 0 or ts >= tao_ts:
            continue
        if max_gap_ms > 0 and (tao_ts - ts) > max_gap_ms:
            continue
        scope = _parse_scope_from_our_request_line(m.get("text") or "")
        if not scope:
            continue
        if ts > best_ts:
            best_ts = ts
            best_scope = scope
    return best_scope


def handle_taoge_dm_message(
    msg: dict,
    memo_cfg: dict,
    seen_ids: set,
    *,
    msg_id: str,
    router_start_ms: int = 0,
    now_ms: int | None = None,
    source: str = "poll",
) -> None:
    """涛哥单聊会话：完成回执 → 助理群 webhook。幂等依赖 seen_ids。"""
    tcfg = _load_taoge_cfg()
    if tcfg.get("done_notify_enabled") is False:
        return
    if msg_id in seen_ids:
        return
    if _skip_msg_before_router_start(msg, router_start_ms):
        seen_ids.add(msg_id)
        return
    if _msg_is_self(msg):
        seen_ids.add(msg_id)
        return
    if not _identity_matches_tao(msg, tcfg):
        seen_ids.add(msg_id)
        return
    import skill_router as _sr

    text = _sr._normalize_command_text(_sr._extract_message_text(msg)).strip()
    if not _text_looks_like_tao_done(text):
        seen_ids.add(msg_id)
        return
    dm_cid = get_taoge_recipient_cid()
    tao_ts = int(msg.get("ts") or 0)
    if tao_ts <= 0:
        tao_ts = int((now_ms or int(time.time() * 1000)))
    scope = _find_scope_for_tao_done_reply(tcfg, dm_cid, tao_ts)
    if not scope:
        _taoge_notify_log(
            f"taoge_done_notify ({source}): 未在单聊历史中找到前置「涛哥，…求更新」或超出时间窗"
        )
        seen_ids.add(msg_id)
        return
    group_cid = str(memo_cfg.get("group_cid") or "").strip()
    body = f"涛哥已经更完了{scope}"
    wh = _wish_webhook_for_cid(memo_cfg, group_cid)
    if not wh:
        _taoge_notify_log(f"taoge_done_notify ({source}): 无助理群 webhook，跳过")
        seen_ids.add(msg_id)
        return
    try:
        _send_wish_webhook(body, memo_cfg, group_cid=group_cid)
        _taoge_notify_log(f"taoge_done_notify ({source}): 已推送 -> {scope!r}")
    except Exception as e:
        _taoge_notify_log(f"taoge_done_notify ({source}): webhook 异常 {e}")
    seen_ids.add(msg_id)


def _restart_modules(cfg: dict) -> frozenset:
    raw = cfg.get("restart_modules")
    if isinstance(raw, list) and raw:
        return frozenset(str(x).strip().lower() for x in raw if str(x).strip())
    return _DEFAULT_RESTART_MODULES


def _scope_tail(scope: str) -> str:
    s = (scope or "").replace("\\", "/").strip().strip("/")
    if not s:
        return ""
    return s.split("/")[-1].lower()


def _scope_search_text(m: dict) -> str:
    """与 daemon /fetch 一致：ct=1200 时正文可能在 raw，不能只看 text。"""
    t = (m.get("text") or "").strip()
    try:
        ct = int(m.get("content_type") or 0)
    except (TypeError, ValueError):
        ct = 0
    raw = m.get("raw") or ""
    if ct == 1200 and raw:
        full = extract_markdown_body_from_ct1200_raw(raw)
        if full:
            low_t, low_f = t.lower(), full.lower()
            if "tao-update-scope" in low_f or len(full) > len(t):
                return full
    return t


def _find_latest_scope(messages, max_age_ms: int):
    now_ms = int(time.time() * 1000)
    best_ts = -1
    best_scope = None
    for m in messages:
        ts = int(m.get("ts") or 0)
        if not ts or (now_ms - ts) > max_age_ms:
            continue
        body = _scope_search_text(m)
        mo = TAO_SCOPE_RE.search(body)
        if not mo:
            continue
        scope = mo.group(1).strip().strip("`").strip("*")
        if not scope:
            continue
        if ts >= best_ts:
            best_ts = ts
            best_scope = scope
    return best_scope


def _fetch_recent_messages(cid: str, count: int, timeout: int) -> list:
    daemon = os.environ.get("DINGTALK_DAEMON_URL", "http://127.0.0.1:19200").rstrip("/")
    payload = json.dumps({"cid": cid, "count": count, "timeout": int(timeout)}, ensure_ascii=False).encode(
        "utf-8"
    )
    req = urllib.request.Request(
        daemon + "/fetch",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("messages") or []
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TypeError):
        return []


def _daemon_send_message(*, message: str, cid: str = "", name: str = "") -> tuple[bool, str]:
    daemon = os.environ.get("DINGTALK_DAEMON_URL", "http://127.0.0.1:19200").rstrip("/")
    cid = (cid or "").strip()
    name = (name or "").strip()
    if cid:
        body = {"cid": cid, "message": message}
    elif name:
        body = {"name": name, "message": message}
    else:
        return False, "cid or name required"
    body = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        daemon + "/send",
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_SEND_HTTP_TIMEOUT_S) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw) if raw else {}
        if data.get("error"):
            return False, str(data.get("error"))
        return True, "ok"
    except urllib.error.HTTPError as e:
        try:
            err = e.read().decode("utf-8", errors="replace")
        except Exception:
            err = str(e)
        return False, err or str(e)
    except Exception as e:
        return False, str(e)


def _build_dm_text(scope: str, restart_set: frozenset) -> str:
    tail = _scope_tail(scope)
    line = f"涛哥，{scope}求更新~"
    if tail and tail in restart_set:
        line += "需要重启"
    # 尾标用方括号词；钉钉里常显示为表情/贴图，属正常。勿改回裸 Unicode emoji（Frida 注入路径易乱码）。
    line += " [忙疯了]"
    return line


def run_taoge_update_flow(*, group_cid: str, memo_cfg: dict, reply_webhook_on_miss: bool = True) -> None:
    """仅在助理通知主群 memo_tracker.group_cid 上调用。

    reply_webhook_on_miss：未解析到 tao-update-scope 时是否向助理群发机器人说明；群内口令建议 True。
    """
    main = str(memo_cfg.get("group_cid") or "").strip()
    if not main or str(group_cid).strip() != main:
        return

    tcfg = _load_taoge_cfg()
    recipient = str(tcfg.get("recipient_display_name") or "杨玉涛").strip() or "杨玉涛"
    recipient_cid = str(tcfg.get("recipient_cid") or "").strip()
    max_age_ms = int(float(tcfg.get("scope_max_age_hours") or 6) * 3600 * 1000)
    fetch_count = int(tcfg.get("fetch_message_count") or 40)
    fetch_timeout = int(tcfg.get("fetch_timeout_s") or 95)
    restart_set = _restart_modules(tcfg)

    rows = _fetch_recent_messages(main, count=fetch_count, timeout=fetch_timeout)
    scope = _find_latest_scope(rows, max_age_ms=max_age_ms)

    wh = _wish_webhook_for_cid(memo_cfg, group_cid)

    if not scope:
        hint = (
            "未在最近群内消息里找到 **tao-update-scope:子模块名**（请确认 Cursor 收工已用 Webhook 发助理群，"
            "且正文含独立一行锚点）。"
        )
        if reply_webhook_on_miss and wh:
            _send_wish_webhook(hint, memo_cfg, group_cid=group_cid)
        return

    body = _build_dm_text(scope, restart_set)
    if recipient_cid:
        ok, detail = _daemon_send_message(message=body, cid=recipient_cid)
    else:
        ok, detail = _daemon_send_message(message=body, name=recipient)
    if ok:
        msg = f"已通过桌面钉钉私聊发给 **{recipient}**：\n\n{body}"
        if wh:
            _send_wish_webhook(msg, memo_cfg, group_cid=group_cid)
        return

    if recipient_cid:
        fail = (
            f"私聊 **{recipient}** 失败：{detail}\n\n"
            "已使用固定 CID，与姓名解析无关。若含 **B1 / advancedSearch**：请钉钉窗口在前台，"
            "或重启钉钉后再启 daemon；必要时在钉钉内打开一次「搜索/高级搜索」相关页。"
        )
    else:
        fail = (
            f"私聊 **{recipient}** 失败：{detail}\n\n"
            "请确认本机 daemon 已启动且通讯录可唯一解析该姓名。"
        )
    if wh:
        _send_wish_webhook(fail, memo_cfg, group_cid=group_cid)
