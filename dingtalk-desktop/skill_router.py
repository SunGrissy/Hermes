# -*- coding: utf-8 -*-
"""
技能路由器 — 后台轮询线程

当前支持：
  - 监听招聘群内文件类消息（contentType 501/502/503/2001 等，见 _RESUME_FILE_CONTENT_TYPES）→ 触发简历 AI 初筛
  - 监听助理群 + memo_tracker.colleague_skill_cids 白名单群（及可选 topic_skill_group_cid 选题群）→ 备忘 / 许愿 / 完成 等（他人仅白名单群入队）
  - 助理通知主群 memo_tracker.group_cid：仅 memo_tracker.assistant_group_skill_uids 中的钉钉 UID 可触发技能（缺省该字段时用 DINGTALK_MY_UID / DEFAULT_MY_UID）；设为 [] 则群内所有人可触发。白名单群不受此限。
  - 手机发指令依赖桌面 /fetch：备忘轮询 JSAPI 超时默认约 95s（SKILL_MEMO_FETCH_TIMEOUT_S），须盖住 daemon _fetch_lock 排队 + beacon；POST body 带 timeout 与 fetch_history 对齐。发送者身份用 uid / is_self / sender 综合解析。
  - 文本含「许愿」「愿望」或英文 wish（整词）→ 写入 TaskReminder，负责人为配置项 wish_assignee（默认「愿望单」）
  - 文本含「愿望单」→ 列出未完成愿望（wish #N + 旧版 TR 条目）（日志 + webhook）；优先于「愿望」单独触发
  - 文本含「删除 wish N」「删除愿望 N」→ 删本地 wish 记录并移除 TR 中 wish:#N
  - 文本含「完成 wish N」「关闭愿望 N」→ 本地标 done，TR 中 wish:#N 标 processStatus=done
  - 助理通知群「上班啦」/「上班」→ 巡检并尝试拉起未就绪服务；**始终 webhook 摘要**（已在跑 / 已拉起恢复 / 仍异常）
  - 助理群「查岗」→ 只巡检不启动；**始终 webhook 摘要**（全绿也推，确认口令已执行）
  - 助理群「修复」→ **先 webhook「指令已收到」**，再同上班啦拉起并复检并推摘要；钉钉大门仍异常则分离子进程跑 daemon_health_notify（自检+可选重启），勿在本线程内关 daemon
  - digest_config.json 的 aider_runner（enabled=true 时）：助理群/白名单群内「aider 别名 任务说明」或「代码助手 别名 …」→ 后台线程调本机 aider --yes --message，开始与结束 webhook（路径白名单 + self_only 与备忘发送者策略同源）
  - 助理群「查看进程」→ desk_ops 调用仓库根 proc_manager.py --markdown-list，结果 webhook；「关进程 N」或「关进程 1,3」按快照序号关闭（与桌面运维同门禁）
  - 助理群「启动PM」「启动 PM」（中间可空格，PM 大小写不敏感）→ desk_ops 执行 quick_start_headless.bat 等，探活后 webhook 汇总（8000 若被其它服务占用会失败）
  - 助理通知主群「让涛哥更新」/「请涛哥更新」→ 从群内最近消息解析 Cursor 收工 Webhook 正文中的 `tao-update-scope:子模块`，经 daemon /send 私聊杨玉涛（正文「涛哥，{子模块}求更新~」+ 白名单则追加「需要重启」+ 结尾 `[忙疯了]`）；依赖收工推送已发助理群且含锚点
  - digest taoge_update.recipient_cid（涛哥单聊）：监测该会话，若杨玉涛在「涛哥，{模块}求更新」之后回复完成类口令（完成/done/down/好了/哦了/…更了），向助理群 webhook 推送「涛哥已经更完了{模块}」
  - 助理群发送「版本咋样了」/「版本怎么样了」→ 触发 version_digest，向 version_digest_webhook 推送版本状态摘要
  - 备忘快捷：改描述/改版本/TR 指派（例：改备忘39描述为…、备忘39版本v1、备忘39分给张三）；选题收录（【选题】/选题：→ topic_items + TR note topic:#N）；选题改描述/删除 topic（与备忘同类指令，支持多编号顿号分隔）；「选题库」从 TR 列出全部 topic:#N 并先做一次本地同步；人员筛选（配置 person_lookup_aliases，如「洋哥」「找洋哥」→ 列出含关键词的备忘+愿望）；桌面运维（检查大门/重启大门/拉今天|昨天|YYMMDD|N天日报，开始+完成 webhook）；轮询周期对齐 TR 与本地 memo/wish/topic（选题以 TR 文案/删改/完成为准）；选题专用群 cid 可由 topic_skill_group_name 在 report_cids 中按群名解析
  - 助理群「预审」：推送路径下优先用本进程缓存的「上一条钉钉文档链接」（与备忘同源 send 事件），避免依赖 /fetch 回溯

架构：
  - 启动时由 daemon.py 调用 SkillRouter.start()
  - 每 POLL_INTERVAL 秒向 daemon /fetch 查询各群的新消息
  - 文件类 contentType 且未处理过 → 交给 skills/resume_screen；消息 ts 早于 resume_monitor_max_age_hours（默认 72h）的不监测；时间窗见 _resume_time_gate_blocks（48h 本机 mtime）
  - 文本含"备忘"/"TR"/"完成"/「许愿」/「愿望」/wish/「愿望单」/「N、M推到明天」类延期 → 交给 skills/memo_tracker；触发词后可跟标点空格，解析时会剥离
  - 通过 DB + 内存 seen_ids 实现幂等
  - 备忘/wish/预审轮询与推送：仅处理 skill_router.start() 之后的消息（ts），重启不追溯历史
  - Frida 备忘推送队列开启时仍执行 _poll_memo_once：否则手机发的消息不会入队、永远无法触发技能
"""
import os
import re
import sys
import json
import time
import tempfile
import subprocess
import threading
import urllib.request
from datetime import datetime

# [AgentMemo Task] 开始时间: 2026-03-18 19:00
# [AgentMemo Task] 任务目标: MEMO-001 补齐 ct=3100 富文本处理并接入模板链路
# [AgentWish Task] 开始时间: 2026-03-19
# [AgentWish Task] 任务目标: WISH-001 群消息「许愿」/「愿望单」路由
# [AgentRsum Task] 开始时间: 2026-03-25
# [AgentRsum Task] 任务目标: RESUME-001~003 简历轮询源 cid、日志回退、排除本人/内部材料 PDF
# [AgentFilt Task] 开始时间: 2026-04-01 18:20
# [AgentFilt Task] 任务目标: RESUME-FILT-001 简历文件名第一层判定，拦截调查报告/述职总结等误触发
# [AgentAidr Task] 开始时间: 2026-04-08
# [AgentAidr Task] 任务目标: AIDR-001 digest aider_runner 接入 skill_router
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _THIS_DIR)

from db.store import (
    init_db,
    is_resume_processed,
    clear_resume_infra_read_fail,
    save_resume_result,
    is_memo_processed,
    is_doc_review_processed,
)
from skills.resume_screen import process_resume_message, _find_local_pdf
from version_digest import run_version_digest_send
from skills.memo_tracker import (
    process_memo,
    process_close,
    process_close_wish,
    process_delete,
    process_delete_topic,
    process_delete_wish,
    process_defer_memo,
    parse_defer_memo_command,
    parse_delete_memo_seqs,
    parse_delete_topic_seqs,
    process_today_focus,
    process_tomorrow_focus,
    process_week_focus,
    process_wish,
    process_wish_list,
    wish_content_key,
    strip_leading_trigger_punct,
    process_memo_edit_description,
    process_memo_edit_version,
    process_memo_assign_tr,
    process_topic_edit_description,
    process_topic_pick,
    topic_pick_content_key,
    _text_triggers_topic_pick,
    topic_library_match_text,
    process_topic_library,
    process_person_lookup,
    person_lookup_match_keyword,
    sync_tr_state_to_local_memos_wishes,
    _wish_webhook_for_cid,
)
from skills.desk_ops import process_desk_ops
from skills.aider_runner import process_aider_runner
from skills.doc_review import (
    extract_doc_url,
    extract_doc_url_from_message,
    process_doc_review,
    get_doc_review_no_link_message,
    try_user_stop_doc_review,
    send_no_active_doc_review_stop_reply,
)
from skills.status_check import run_morning_flow, run_inspection_flow, run_repair_flow
from skills.taoge_update import (
    get_taoge_recipient_cid,
    handle_taoge_dm_message,
    run_taoge_update_flow,
)
from lib.utils import get_webhook_url, DATA_DIR, DEFAULT_MY_UID, ContactsDB
from skills.check_tracker import process_check, parse_check_trigger

DAEMON_URL    = os.environ.get('DINGTALK_DAEMON_URL', 'http://127.0.0.1:19200')
POLL_INTERVAL = int(os.environ.get('SKILL_ROUTER_INTERVAL', '20'))   # 秒（推送未接入时兜底；可设 SKILL_ROUTER_INTERVAL=60 恢复）
_last_tr_sync_ms = 0
_TR_SYNC_INTERVAL_MS = int(os.environ.get('SKILL_TR_SYNC_INTERVAL_MS', '120000'))  # TR↔本地对齐周期（毫秒）
_CONFIG_PATH  = os.path.join(_THIS_DIR, 'digest_config.json')
# 与 daemon 写入的日志路径一致，否则预审回溯时读不到「刚发的文档链接」
_LOG_FILE     = os.path.join(DATA_DIR, '_msg_log.jsonl')
_TEMPLATE_PATH = os.path.join(_THIS_DIR, 'message_templates.json')
_MYAGENTS_ROOT = os.path.normpath(os.path.join(_THIS_DIR, '..'))
_PALACE_RUN_PY = os.path.join(_MYAGENTS_ROOT, 'palace', 'run.py')
_INTERVIEW_OUT_DIR = os.path.join(_MYAGENTS_ROOT, 'data', 'interview_reviews')

_INTERVIEW_PENDING_TTL_MS = 30 * 60 * 1000
_INTERVIEW_PENDING_BY_CID = {}
_INTERVIEW_PENDING_LOCK = threading.Lock()

# region agent log
_AGENT_DEBUG_LOG = os.path.normpath(os.path.join(_THIS_DIR, '..', 'debug-5a049e.log'))


def _agent_dbg(hypothesis_id: str, location: str, message: str, **data):
    try:
        rec = {
            'sessionId': '5a049e',
            'hypothesisId': hypothesis_id,
            'location': location,
            'message': message,
            'timestamp': int(time.time() * 1000),
            'data': data,
        }
        with open(_AGENT_DEBUG_LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    except Exception:
        pass
# endregion


def _memo_allowed_cids(memo_cfg: dict) -> set:
    """技能路由处理的群：助理群 group_cid + colleague_skill_cids（同事指令白名单）+ 涛哥单聊 cid。"""
    s = set()
    g = str(memo_cfg.get('group_cid') or '').strip()
    if g:
        s.add(g)
    for x in (memo_cfg.get('colleague_skill_cids') or []):
        xs = str(x).strip()
        if xs:
            s.add(xs)
    tx = get_taoge_recipient_cid()
    if tx:
        s.add(tx)
    return s


# 备忘轮询优先走 JSAPI；须 >= daemon 侧 _fetch_lock 排队 + JSAPI 等待；过短则客户端先断连 → daemon 写响应 WinError 10053
_MEMO_FETCH_JSAPI_TIMEOUT_S = int(os.environ.get('SKILL_MEMO_FETCH_TIMEOUT_S', '95'))


def _message_sender_identity(msg: dict) -> str:
    """供助理群白名单比对：优先 uid；JSAPI 标 is_self 或 sender='?'（本人）时映射为我的数字 UID；否则用 sender（常为手机端 sn）。"""
    u = str(msg.get('uid') or '').strip()
    if u:
        return u
    if msg.get('is_self') is True:
        return str(os.environ.get('DINGTALK_MY_UID', DEFAULT_MY_UID)).strip()
    s = str(msg.get('sender') or '').strip()
    if s == '?':
        return str(os.environ.get('DINGTALK_MY_UID', DEFAULT_MY_UID)).strip()
    return s


def _normalize_person_display(s: str) -> str:
    """群聊 /fetch 有时把发送者放在 uid 字段里且为「张三」或「张三（备注）」；取主名做比对。"""
    t = (s or '').strip()
    if not t:
        return ''
    for sep in ('（', '('):
        if sep in t:
            t = t.split(sep, 1)[0].strip()
    return t


def _assistant_group_allowed_sender_labels(memo_cfg: dict, allowed_ids: set) -> set:
    """数字 UID + 配置的别名 + 通讯录里这些 UID 对应的显示名（群消息里可能是名而不是数字）。"""
    lab = set(allowed_ids)
    raw = memo_cfg.get('assistant_group_skill_aliases')
    if raw is None:
        extra = []
    elif isinstance(raw, list):
        extra = raw
    else:
        extra = [raw]
    for x in extra:
        xs = str(x).strip()
        if not xs:
            continue
        lab.add(xs)
        lab.add(_normalize_person_display(xs))
    for uid in allowed_ids:
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


def _sender_matches_assistant_labels(sender: str, labels: set) -> bool:
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
        if s == L:
            return True
        ln = _normalize_person_display(L)
        if sn and ln and sn == ln:
            return True
    return False


def _assistant_group_skill_sender_allowed(memo_cfg: dict, msg_cid: str, sender_uid: str) -> bool:
    """仅助理通知主群 memo_tracker.group_cid 校验发送者；白名单 colleague 群、选题群始终放行。

    - assistant_group_skill_uids 为 []：不限制（兼容旧行为）。
    - 缺省该字段：仅允许 DINGTALK_MY_UID（未设则用 DEFAULT_MY_UID）。
    - 群聊 /fetch 可能把发送者标成显示名（如「孙懿」）而非数字 UID：用 assistant_group_skill_aliases +
      通讯录反查数字 UID 的姓名，与主名归一化后比对。
    - 发送者 uid 为空时放行：Frida 推送记录常不带 uid；环境变量 DINGTALK_ASSISTANT_DENY_EMPTY_UID=1 可拒绝。
    """
    g = str(memo_cfg.get('group_cid') or '').strip()
    if not g or str(msg_cid).strip() != g:
        return True
    raw = memo_cfg.get('assistant_group_skill_uids')
    if isinstance(raw, list) and len(raw) == 0:
        return True
    if raw is None:
        uids = [os.environ.get('DINGTALK_MY_UID', DEFAULT_MY_UID)]
    elif not isinstance(raw, list):
        uids = [raw]
    else:
        uids = raw
    allowed = {str(x).strip() for x in uids if str(x).strip()}
    if not allowed:
        return True
    labels = _assistant_group_allowed_sender_labels(memo_cfg, allowed)
    su = str(sender_uid or '').strip()
    if not su:
        if os.environ.get('DINGTALK_ASSISTANT_DENY_EMPTY_UID', '').strip().lower() in (
                '1', 'true', 'yes', 'on'):
            _log('助理群指令已忽略：发送者 uid 为空（Frida 推送常缺 uid；勿与钉钉机器人关键词混淆）')
            return False
        return True
    ok = _sender_matches_assistant_labels(su, labels)
    if not ok:
        _log(
            '助理群指令已忽略：发送者标识=%r 不在白名单（数字 UID + assistant_group_skill_aliases + 通讯录姓名）'
            % (su,)
        )
    return ok


def _log(msg: str):
    ts = datetime.now().strftime('%H:%M:%S')
    print(f'[skill_router][{ts}] {msg}', flush=True)


_RESUME_NAME_FILTER_DEFAULT = {
    # 命中任一排除词直接跳过（非候选人简历）
    'block_keywords': [
        '面试评价', '面试结论', '面试清单', '面试记录', '面试反馈',
        '述职', '二次审核', '审核意见', '入职定级', '录用审批', '背调',
        '调查报告', '调研报告', '报告', '总结', '复盘', '会议纪要', '汇报',
        '周报', '月报', '季度总结', '年度总结', '预算', '招标', '合同',
    ],
    # 命中任一关键词视为明确简历命名
    'allow_keywords': ['简历', '个人简历', 'resume', 'cv', '应聘', '求职'],
    # 未命中 allow 且未命中 block 时：
    # pass=放行；skip=全拦；skip_non_name=仅「姓名式命名」放行（推荐）
    'unknown_policy': 'skip_non_name',
}


def _resume_name_filter_cfg_from_root(cfg: dict) -> dict:
    raw = cfg.get('resume_name_filter')
    if not isinstance(raw, dict):
        raw = {}
    out = dict(_RESUME_NAME_FILTER_DEFAULT)
    _allow = raw.get('allow_keywords')
    _block = raw.get('block_keywords')
    if isinstance(_allow, list):
        out['allow_keywords'] = [str(x).strip() for x in _allow if str(x).strip()]
    if isinstance(_block, list):
        out['block_keywords'] = [str(x).strip() for x in _block if str(x).strip()]
    _policy = str(raw.get('unknown_policy') or out['unknown_policy']).strip().lower()
    if _policy not in ('pass', 'skip', 'skip_non_name'):
        _policy = 'skip_non_name'
    out['unknown_policy'] = _policy
    return out


def _load_config() -> dict:
    """从 digest_config.json 读取所有路由配置"""
    try:
        with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        recruit_cids = cfg.get('recruit_cids', [])
        cids = []
        cid_names = {}
        for c in recruit_cids:
            if not c:
                continue
            if isinstance(c, str):
                cids.append(c)
            else:
                cid = c.get('cid', '')
                name = c.get('name', '')
                if cid:
                    cids.append(cid)
                    if name:
                        cid_names[cid] = name
        notify_cid = cfg.get('notify_target', '')

        memo_cfg = cfg.get('memo_tracker', {})
        if not memo_cfg.get('group_cid'):
            memo_cfg['group_cid'] = notify_cid

        doc_review_cfg = cfg.get('doc_review', {})
        if not doc_review_cfg.get('group_cid'):
            doc_review_cfg['group_cid'] = notify_cid
        # webhook 优先从 webhook_config.json 按 key 读取
        memo_cfg['webhook_url'] = get_webhook_url(
            'memo_tracker', memo_cfg.get('webhook_url') or cfg.get('webhook_url', '')
        )
        doc_review_cfg['webhook_url'] = get_webhook_url(
            'doc_review', doc_review_cfg.get('webhook_url') or cfg.get('webhook_url', '')
        )
        # 白名单群 CID 列表（字符串），缺省为空 = 他人发言不入队
        _col = memo_cfg.get('colleague_skill_cids')
        if _col is None:
            memo_cfg['colleague_skill_cids'] = []
        elif not isinstance(_col, list):
            memo_cfg['colleague_skill_cids'] = [str(_col).strip()] if str(_col).strip() else []

        # 选题 / 选题库专用群：cid 优先；否则按 topic_skill_group_name 在 report_cids 中匹配群名
        tgc = str(memo_cfg.get('topic_skill_group_cid') or '').strip()
        tname = str(memo_cfg.get('topic_skill_group_name') or '').strip()
        if not tgc and tname:
            for c in cfg.get('report_cids', []):
                if not isinstance(c, dict):
                    continue
                nm = (c.get('name') or '').strip()
                cid = str(c.get('cid') or '').strip()
                if not cid or not nm:
                    continue
                if nm == tname or tname in nm:
                    tgc = cid
                    break
        if tgc:
            memo_cfg['topic_skill_group_cid'] = tgc
        tkey = str(memo_cfg.get('topic_skill_webhook_key') or '').strip()
        raw_tw = str(memo_cfg.get('topic_skill_webhook_url') or '').strip()
        tw = (get_webhook_url(tkey, raw_tw) if tkey else raw_tw).strip()
        if tgc:
            cols = memo_cfg['colleague_skill_cids']
            if tgc not in cols:
                cols.append(tgc)
            if tw:
                br = memo_cfg.get('wish_reply_webhook_by_cid')
                if not isinstance(br, dict):
                    br = {}
                    memo_cfg['wish_reply_webhook_by_cid'] = br
                br[tgc] = tw

        ar = cfg.get('aider_runner')
        if isinstance(ar, dict):
            memo_cfg['aider_runner'] = dict(ar)
        else:
            memo_cfg['aider_runner'] = {}

        return {
            'recruit_cids': cids,
            'cid_names': cid_names,
            'notify_cid': notify_cid,
            'memo_tracker': memo_cfg,
            'doc_review': doc_review_cfg,
            'resume_name_filter': _resume_name_filter_cfg_from_root(cfg),
            'resume_msg_max_age_ms': _resume_msg_max_age_ms_from_root(cfg),
            'resume_bypass_filename_gate_cids': _resume_bypass_filename_gate_cids_from_root(cfg),
        }
    except Exception as e:
        _log(f'load config failed: {e}')
        return {'recruit_cids': [], 'cid_names': {}, 'notify_cid': '',
                'memo_tracker': {}, 'resume_name_filter': dict(_RESUME_NAME_FILTER_DEFAULT),
                'resume_msg_max_age_ms': DEFAULT_RESUME_MSG_MAX_AGE_MS,
                'resume_bypass_filename_gate_cids': frozenset()}


def _fetch_recent_messages(cid: str, count: int = 20, timeout: int = 75) -> list:
    """调 daemon /fetch 获取群内最近消息（timeout 与 daemon fetch_history 内 beacon 等待一致，需随 POST 传入）。"""
    payload = json.dumps({
        'cid': cid, 'count': count,
        'timeout': int(timeout),
    }).encode('utf-8')
    req = urllib.request.Request(
        DAEMON_URL.rstrip('/') + '/fetch',
        data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        return data.get('messages', [])
    except Exception as e:
        _log(f'fetch {cid} 失败: {e}')
        return []


# 手机/轻量 ProcessPush 常不带 origin_text（见 _msg_log ext_keys 仅 openConversationId 等），需用 JSAPI 补正文
_HYDRATE_FETCH_MAX_DELTA_MS = 120_000
# daemon 侧 _fetch_lock 串行 + JSAPI 重扫/等待 beacon 可达数十秒，客户端过短会先断开并触发 ConnectionAbortedError
_HYDRATE_FETCH_TIMEOUT_S = 75
# 招聘群热聊时仅拉 20 条会把文件消息挤出窗口；daemon listMessage 上限 50
_RESUME_FETCH_COUNT = 50
# listMessage 的 contentType：502 常规文件、501 大文件、503 文件夹；部分桌面端为 2001（见 lib/utils CT_NAMES）
_RESUME_FILE_CONTENT_TYPES = frozenset({501, 502, 503, 2001})


def _try_hydrate_push_message_from_fetch(msg: dict) -> None:
    """push 记录 text 为空时，调 /fetch 按时间戳对齐最近一条有正文的群消息。"""
    t0 = int(time.time() * 1000)
    cid = str(msg.get('cid') or '').strip()
    push_ts = int(msg.get('ts') or 0)
    if not cid or push_ts <= 0:
        return
    rows = []
    for attempt in range(2):
        rows = _fetch_recent_messages(cid, count=35, timeout=_HYDRATE_FETCH_TIMEOUT_S)
        if rows:
            break
        if attempt == 0:
            time.sleep(2.5)
    if not rows:
        return
    best = None
    best_d = None
    for m in rows:
        t = (m.get('text') or '').strip()
        if not t:
            continue
        mts = int(m.get('ts') or 0)
        if mts <= 0:
            continue
        d = abs(mts - push_ts)
        if d > _HYDRATE_FETCH_MAX_DELTA_MS:
            continue
        if best_d is None or d < best_d:
            best_d = d
            best = m
    if not best or best_d is None:
        return
    msg['text'] = best.get('text') or ''
    rw = best.get('raw')
    if rw:
        msg['raw'] = rw
    try:
        msg['content_type'] = int(best.get('content_type') or msg.get('content_type') or 1)
    except (TypeError, ValueError):
        pass
    _log(f'push: 已用 /fetch 补全正文 (delta_ms={best_d})')


def _read_log_messages(cid: str, max_count: int = 50,
                       max_age_ms: int = 86400 * 1000) -> list:
    """从 beacon 监控日志读取指定 CID 的近期消息（JSAPI 不可用时的备选通道）。

    日志按追加顺序写入（最新在末尾），倒序扫描以快速获取最近消息。
    uid 字段可能为 null，从 md_extra.3.1 补全，确保 msg_id 能正确构造。
    返回格式与 /fetch 消息兼容（chronological 顺序）。
    """
    if not os.path.exists(_LOG_FILE):
        return []

    now_ms = int(time.time() * 1000)
    cutoff_ms = now_ms - max_age_ms
    results = []

    try:
        with open(_LOG_FILE, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
    except Exception as e:
        _log(f'read log failed: {e}')
        return []

    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            m = json.loads(line)
        except Exception:
            continue

        ts = int(m.get('ts', 0))
        if ts and ts < cutoff_ms:
            break  # 日志按时序追加，遇到过期条目即可停止

        if str(m.get('cid', '')) != str(cid):
            continue

        uid = m.get('uid') or m.get('sender') or ''
        if not uid:
            try:
                uid = (m.get('md_extra') or {}).get('3', {}).get('1', '') or ''
            except Exception:
                uid = ''

        results.append({
            'cid': m.get('cid', ''),
            'uid': uid,
            'ts': ts,
            'content_type': m.get('content_type', 0),
            'text': m.get('text', '') or '',
            'raw': m.get('raw', '') or '',
            'is_self': bool(m.get('is_self')),
            'direction': str(m.get('direction', '') or ''),
            '_from_log': True,
        })

        if len(results) >= max_count:
            break

    results.reverse()
    return results


def _fetch_memo_messages(cid: str, max_age_ms: int) -> list:
    """备忘/文档指令专用拉取：优先 JSAPI，不可用时自动降级到 beacon 日志。"""
    messages = _fetch_recent_messages(cid, count=20, timeout=_MEMO_FETCH_JSAPI_TIMEOUT_S)
    if messages:
        return messages
    msgs = _read_log_messages(cid, max_count=50, max_age_ms=max_age_ms)
    if msgs:
        _log(f'memo fetch: JSAPI 不可用，已切换到 beacon 日志 ({len(msgs)} 条)')
    return msgs


def _extract_file_info(msg: dict) -> tuple:
    """
    从 fetch 返回的消息中提取 (msg_id, file_name, file_path)。
    文件类消息的 raw 字段包含 content JSON，attachment.extension 有 f_name 和 path。
    """
    raw_str = msg.get('raw', '')
    if not raw_str:
        return None, None, None

    try:
        content = json.loads(raw_str)
    except Exception:
        return None, None, None

    attachments = content.get('attachments', [])
    if not attachments:
        return None, None, None

    att = attachments[0]
    ext = att.get('extension', {})

    file_name = ext.get('f_name', '') or att.get('filePath', '').split('/')[-1]
    file_path = att.get('filePath', '') or ext.get('path', '')

    # msg_id 不在 fetch 返回里，用 ts + uid 拼一个稳定 key
    ts  = str(msg.get('ts', ''))
    uid = str(msg.get('uid', ''))
    msg_id = f'{ts}_{uid}' if (ts and uid) else None

    return msg_id, file_name, file_path


def _normalize_resume_filename(name: str) -> str:
    n = (name or '').strip().lower()
    if not n:
        return ''
    return re.sub(r'[\s\-_().（）\[\]【】]+', '', n)


def _resume_name_keyword_hit(file_name: str, keyword: str) -> bool:
    kw = (keyword or '').strip().lower()
    if not kw:
        return False
    name_raw = (file_name or '').lower()
    name_norm = _normalize_resume_filename(file_name)
    kw_norm = _normalize_resume_filename(kw)
    return (kw in name_raw) or (kw_norm and kw_norm in name_norm)


def _resume_filename_looks_like_person_name(file_name: str) -> bool:
    """姓名式命名：张三.pdf、李先生.pdf、WangSan.pdf 等（含 5 字内纯中文，兼容部分导出文件名）。"""
    base = (file_name or '').strip()
    if not base:
        return False
    base = re.sub(r'\.[^.]+$', '', base).strip()
    if not base:
        return False
    # 去掉常见分隔符后再判定
    norm = re.sub(r'[\s\-_().（）\[\]【】·]+', '', base)
    if not norm:
        return False
    # 中文姓名（2~5字）及带称谓（先生/女士/小姐/同学）
    if re.fullmatch(r'[\u4e00-\u9fff]{2,5}', norm):
        return True
    if re.fullmatch(r'[\u4e00-\u9fff]{1,4}(先生|女士|小姐|同学)', norm):
        return True
    # 英文姓名：2~40字母（可含点与空格）
    if re.fullmatch(r"[A-Za-z][A-Za-z.\s]{1,39}", base):
        return True
    return False


def _resume_pdf_filename_gate(
    file_name: str, resume_name_filter: dict | None, *, blocks_only: bool = False,
) -> tuple:
    """第一层文件名门禁：先按文件名判断是否应进入简历预审。

    blocks_only=True：仅执行 block_keywords（面试评价/周报等），不校验 allow/unknown_policy。
    """
    cfg = resume_name_filter or _RESUME_NAME_FILTER_DEFAULT
    blocks = cfg.get('block_keywords') or []
    allows = cfg.get('allow_keywords') or []
    policy = str(cfg.get('unknown_policy') or 'pass').strip().lower()
    if policy not in ('pass', 'skip', 'skip_non_name'):
        policy = 'skip_non_name'
    if not (file_name or '').strip():
        return True, ''

    for kw in blocks:
        if _resume_name_keyword_hit(file_name, kw):
            return False, f'非候选人简历：文件名命中排除词[{kw}]'

    if blocks_only:
        return True, ''

    if allows:
        for kw in allows:
            if _resume_name_keyword_hit(file_name, kw):
                return True, ''
        if policy == 'skip':
            return False, '非候选人简历：文件名未命中简历关键词'
        if policy == 'skip_non_name':
            if _resume_filename_looks_like_person_name(file_name):
                return True, ''
            return False, '非候选人简历：文件名未命中简历关键词且非姓名式命名'

    return True, ''


def _resume_message_is_from_me(msg: dict) -> bool:
    """True = 本条文件消息为本人发出（发给 HR 的评价/清单等），非候选人投递。"""
    if msg.get('is_self') is True:
        return True
    me = str(os.environ.get('DINGTALK_MY_UID', DEFAULT_MY_UID)).strip()
    u = str(msg.get('uid') or '').strip()
    if u and me and u == me:
        return True
    d = str(msg.get('direction', '') or '')
    if '→' in d and '发送' in d:
        return True
    return False


_RESUME_WINDOW_MS = 48 * 3600 * 1000   # 与本机 PDF mtime（下载/落盘时间）比较的滑动窗长度
# 简历初筛：仅处理消息发送时间在此窗口内的文件消息（默认 72h）；更早的静默跳过，不配监测
DEFAULT_RESUME_MSG_MAX_AGE_MS = 72 * 3600 * 1000


def _resume_msg_max_age_ms_from_root(cfg: dict) -> int:
    """digest_config：resume_monitor_max_age_hours 或 resume_monitor.max_age_hours，默认 72。"""
    raw = cfg.get('resume_monitor_max_age_hours')
    if raw is None and isinstance(cfg.get('resume_monitor'), dict):
        raw = cfg['resume_monitor'].get('max_age_hours')
    try:
        h = float(raw)
        if h <= 0 or h > 8760:
            return DEFAULT_RESUME_MSG_MAX_AGE_MS
        return int(h * 3600 * 1000)
    except (TypeError, ValueError):
        return DEFAULT_RESUME_MSG_MAX_AGE_MS


def _resume_bypass_filename_gate_cids_from_root(cfg: dict) -> frozenset:
    """仅保留 block_keywords，不要求 allow/姓名式命名。根 resume_bypass_filename_gate_cids 与 resume_monitor.bypass_filename_gate_cids 合并。"""
    out: set[str] = set()
    raw = cfg.get('resume_bypass_filename_gate_cids')
    if isinstance(raw, list):
        out.update(str(x).strip() for x in raw if str(x).strip())
    if isinstance(cfg.get('resume_monitor'), dict):
        raw2 = cfg['resume_monitor'].get('bypass_filename_gate_cids')
        if isinstance(raw2, list):
            out.update(str(x).strip() for x in raw2 if str(x).strip())
    return frozenset(out)


def _resume_resolve_local_pdf_path(file_name: str, file_path_hint: str) -> str:
    """本机已落盘的简历附件路径（PDF/docx；钉钉附件路径或常见下载目录按文件名命中），无则返回空串。"""
    if file_path_hint and os.path.exists(file_path_hint):
        return file_path_hint
    if (file_name or '').strip():
        return _find_local_pdf(file_name) or ''
    return ''


def _resume_time_gate_blocks(
    file_name: str, file_path_hint: str, now_ms: int, msg_ts_ms: int = 0,
) -> bool:
    """True = 仅因「下载时间窗」应跳过本条。

    - 消息发送时间 msg_ts 在近 48h 内：**不挡**。避免本机 Downloads 里同名旧 PDF 的 mtime 误杀刚投递的新消息。
    - 尚无本机文件：不挡（等 trigger_download / 手动下载后再判）。
    - 消息过旧且无可靠 ts 时：若已能解析到本机文件，仅当其 mtime 早于「当前往前 48h」才挡（挡旧缓存/重复扫）。
    """
    if msg_ts_ms and msg_ts_ms >= (now_ms - _RESUME_WINDOW_MS):
        return False
    p = _resume_resolve_local_pdf_path(file_name, file_path_hint)
    if not p:
        return False
    try:
        mt = int(os.path.getmtime(p) * 1000)
    except OSError:
        return False
    return mt < (now_ms - _RESUME_WINDOW_MS)


def _fetch_resume_messages(cid: str, timeout: int, log_max_age_ms: int) -> list:
    """招聘群简历：优先 daemon /fetch（条数见 _RESUME_FETCH_COUNT）；超时或空列表时读 _msg_log.jsonl（依赖 Monitor 为文件类消息写入 raw）。

    log_max_age_ms：与简历监测回溯一致，避免日志里捞过久历史。
    """
    messages = _fetch_recent_messages(cid, count=_RESUME_FETCH_COUNT, timeout=timeout)
    if messages:
        return messages
    msgs = _read_log_messages(cid, max_count=80, max_age_ms=log_max_age_ms)
    if msgs:
        _log(
            'resume: /fetch 无可用数据，已改用监控日志 '
            f'({len(msgs)} 条)；若仍无初筛请确认本机已更新 monitor 且重启 daemon'
        )
    return msgs


def _poll_once(
    cid: str, seen_ids: set, source_name: str = '', resume_name_filter: dict | None = None,
    resume_msg_max_age_ms: int | None = None,
    resume_bypass_filename_gate_cids: frozenset | None = None,
):
    """轮询一个招聘群/私信，处理所有新的文件类（501/502/503/2001）简历消息。
    初筛结论经 resume_notify Webhook 推送（见 resume_screen）；本函数只负责在源会话上拉消息与触发下载。
    source_name: 来源的显示名（用于推送消息中告知来源）
    resume_msg_max_age_ms: 仅监测消息 ts 早于此窗口之前的简历（默认 72h）；None 用 DEFAULT_RESUME_MSG_MAX_AGE_MS。
    resume_bypass_filename_gate_cids: 命中的 cid 仅做 block 排除，不要求文件名含「简历」等。
    """
    _max_age = (
        resume_msg_max_age_ms
        if resume_msg_max_age_ms is not None
        else DEFAULT_RESUME_MSG_MAX_AGE_MS
    )
    _bypass_fn = resume_bypass_filename_gate_cids or frozenset()
    _blocks_only = str(cid) in _bypass_fn
    # 与 _HYDRATE_FETCH_TIMEOUT_S 一致；fetch 失败时 _fetch_resume_messages 回退监控日志
    messages = _fetch_resume_messages(
        cid, timeout=_HYDRATE_FETCH_TIMEOUT_S, log_max_age_ms=_max_age)
    processed_count = 0
    now_ms = int(time.time() * 1000)

    for msg in messages:
        if int(msg.get('content_type') or 0) not in _RESUME_FILE_CONTENT_TYPES:
            continue

        msg_id, file_name, file_path = _extract_file_info(msg)
        if not msg_id:
            continue

        _fn = (file_name or '').lower()
        if file_name and not (_fn.endswith('.pdf') or _fn.endswith('.docx')):
            continue

        _msg_ts = int(msg.get('ts') or 0)
        # 监测回溯：早于配置窗口的消息不参与初筛（静默）
        if _msg_ts and _msg_ts < (now_ms - _max_age):
            continue
        if _resume_time_gate_blocks(file_name, file_path or '', now_ms, msg_ts_ms=_msg_ts):
            # 历史简历超过 48h 窗口：静默跳过，不打日志（避免热聊群刷屏）
            continue

        if clear_resume_infra_read_fail(msg_id):
            _log(f'初筛将重试：已清除本条因读文件失败入库的记录 {file_name} ({msg_id})')

        if msg_id in seen_ids or is_resume_processed(msg_id):
            continue

        sender_uid = str(msg.get('uid', ''))
        if _resume_message_is_from_me(msg):
            _log(f'跳过简历初筛（本人发出的文件）: {file_name}')
            save_resume_result(
                msg_id, cid, sender_uid, file_name, file_path or '',
                '—', '跳过', '非候选人投递：本人发出的简历附件', reply_sent=False,
            )
            seen_ids.add(msg_id)
            continue
        _gate_ok, _gate_reason = _resume_pdf_filename_gate(
            file_name, resume_name_filter, blocks_only=_blocks_only)
        if not _gate_ok:
            _log(f'跳过简历初筛（文件名门禁）: {file_name} | {_gate_reason}')
            save_resume_result(
                msg_id, cid, sender_uid, file_name, file_path or '',
                '—', '跳过', _gate_reason, reply_sent=False,
            )
            seen_ids.add(msg_id)
            continue

        # process_resume_message.group_cid 用于本地路径缺失时的 /trigger_download，必须在简历所在群/私信 cid；
        # 初筛结论仅经 resume_notify Webhook 推送，与 notify_cid 无绑定。
        _log(f'发现新简历: {file_name} (uid={sender_uid}, 来源={source_name or cid})')

        try:
            result = process_resume_message(
                msg_id=msg_id,
                group_cid=cid,
                sender_uid=sender_uid,
                file_name=file_name,
                file_path=file_path,
                source_name=source_name,
            )
            if result is None:
                # 文件未下载，不加 seen_ids，下次 poll 继续重试
                _log(f'等待下载: {file_name}')
            elif result is True:
                processed_count += 1
                seen_ids.add(msg_id)
                _log(f'处理完成: {file_name}')
            else:
                # False: 结论为待定/不通过，已发通知，加 seen_ids 避免重复调 LLM
                seen_ids.add(msg_id)
                _log(f'已通知（非通过）: {file_name}')
        except Exception as e:
            _log(f'处理失败 {file_name}: {e}')

    return processed_count


def _make_msg_id(msg: dict) -> str | None:
    ts = str(msg.get('ts', ''))
    uid = str(msg.get('uid', ''))
    if ts and uid:
        return f'{ts}_{uid}'
    dm = msg.get('ding_mid')
    if dm is not None and str(dm).strip() not in ('', '0'):
        sdm = str(dm).strip()
        if ts:
            return f'{ts}_mid{sdm}'
        return f'mid_{sdm}'
    if ts:
        return f'{ts}_nouid'
    return None


def _extract_message_text(msg: dict) -> str:
    """统一提取消息文本：纯文本、富文本(3100)，以及带 text 字段的 Markdown 等类型。"""
    ct = int(msg.get('content_type') or 0)
    if ct == 1:
        return (msg.get('text') or '').strip()

    if ct == 3100:
        text = (msg.get('text') or '').strip()
        raw = msg.get('raw', '') or ''
        if raw:
            try:
                raw_data = json.loads(raw) if isinstance(raw, str) else raw
                descs = []
                for att in (raw_data.get('attachments') or []):
                    ext = att.get('extension') or {}
                    desc = (ext.get('desc') or '').strip()
                    if desc and desc not in descs:
                        descs.append(desc)
                if descs:
                    merged = '\n'.join(descs).strip()
                    if not text or len(merged) > len(text):
                        text = merged
            except Exception:
                pass
        return text

    return (msg.get('text') or '').strip()


def _normalize_command_text(text: str) -> str:
    """指令关键词归一：零宽字符、繁体「許願」等。"""
    if not text:
        return text
    t = text.replace('\u200b', '').replace('\ufeff', '')
    t = t.replace('許願', '许愿')
    return t


_RE_MEMO   = re.compile(r'[\uff3b【\[]*(?:备忘|提醒我|TR)[\uff3d】\]]*')
_RE_CLOSE  = re.compile(r'(?:完成|关闭)\s*#?\d+')
_RE_CLOSE_WISH = re.compile(r'(?:完成|关闭)\s*(?:wish|愿望)\s*#?\s*\d+', re.IGNORECASE)
_RE_DELETE_WISH = re.compile(r'删除\s*(?:wish|愿望)\s*#?\s*\d+', re.IGNORECASE)
_RE_TODAY_FOCUS = re.compile(
    r'今天\s*(?:我要?)?\s*关注\s*啥|今天\s*有啥\s*(?:要做的|要关注)|今天\s*关注\s*啥'
)
_RE_TOMORROW_FOCUS = re.compile(
    r'明天\s*(?:我\s*)?(?:要\s*)?\s*关注\s*啥|明天\s*有啥'
)
_RE_WEEK_FOCUS = re.compile(
    r'本周\s*(?:我要?)?\s*关注\s*啥|本周\s*有啥|本周\s*关注\s*啥'
)
_RE_PRECHECK = re.compile(r'^\s*预审[!！。.\s]*$')
# 同一文档在 doc_review_window 内被去重后，发下列句式可跳过时间窗再跑一轮
_RE_PRECHECK_FORCE_PREFIX = re.compile(
    r'^\s*(?:强制|再|重跑|坚持|必须|再来|依旧|还要)\s*预审[!！。.\s]*$'
)
_RE_PRECHECK_FORCE_SUFFIX = re.compile(
    r'^\s*预审\s*(?:再来|重试|重跑)(?:[!！。.\s]*)?$'
)
# 停止 Palace 子进程：停止预审 / 中断预审 / 叫停预审 / 预审停止 …
_RE_PRECHECK_STOP = re.compile(
    r'^\s*(?:(?:停止|中断|叫停)\s*预审|预审\s*(?:停止|中断|叫停))(?:[!！。.,，\s]*)?$'
)
# 支持「上班啦」「上班」「上班啦！」等，整条以上班啦/上班开头且无其它实质内容即可
_RE_MORNING = re.compile(r'^\s*(?:上班啦|上班)\s*[!！。.~\s]*$')
_RE_INSPECTION = re.compile(r'^\s*查岗\s*[!！。.~\s]*$')
_RE_REPAIR = re.compile(r'^\s*修复\s*[!！。.~\s]*$')
# 版本状态摘要（与 py version_digest.py 同源，发向 digest 里 version_digest_webhook）
_RE_VERSION_DIGEST = re.compile(
    r'^\s*版本\s*(?:咋样|怎么样)了\s*[!！。.?？~\s]*$')


def _text_triggers_taoge_update(text: str) -> bool:
    """助理群口令：让涛哥更新 / 请涛哥更新（子串匹配，可前后带其它字）。"""
    t = text or ''
    return ('让涛哥更新' in t) or ('请涛哥更新' in t)


def _precheck_command_flags(text: str) -> tuple:
    """预审指令：(是否匹配, 是否跳过同一文档的短时去重窗口)。"""
    if not text:
        return (False, False)
    if _RE_PRECHECK_FORCE_PREFIX.match(text) or _RE_PRECHECK_FORCE_SUFFIX.match(text):
        return (True, True)
    if _RE_PRECHECK.match(text):
        return (True, False)
    return (False, False)

_MEMO_MAX_AGE_MS       = 24 * 3600 * 1000   # 处理 24 小时内的备忘（beacon 日志兜底，seen_ids 保幂等）
_DOC_REVIEW_MAX_AGE_MS = 30 * 60 * 1000    # 预审：回溯文档链接时只看近 30 分钟消息
# 推送链路上缓存助理群最近一条文档 URL（send Hook 先到、免等 JSAPI /fetch）
_doc_push_url_lock = threading.Lock()
_last_push_doc_url_by_cid: dict = {}


def _remember_push_doc_url_if_any(msg_cid: str, msg: dict, doc_group_cid: str) -> None:
    """本人/群内任一条发送里若带钉钉文档链接，写入缓存，供下一条「预审」免 fetch。"""
    if not doc_group_cid or str(msg_cid) != str(doc_group_cid).strip():
        return
    u = extract_doc_url_from_message(msg)
    if not u:
        return
    now_ms = int(time.time() * 1000)
    with _doc_push_url_lock:
        _last_push_doc_url_by_cid[str(msg_cid)] = (u, now_ms)


def _cached_push_doc_url(msg_cid: str, doc_group_cid: str, now_ms: int, max_age_ms: int):
    """返回推送缓存中仍有效的文档链接；过期或未命中返回 None。"""
    if not doc_group_cid or str(msg_cid) != str(doc_group_cid).strip():
        return None
    with _doc_push_url_lock:
        t = _last_push_doc_url_by_cid.get(str(msg_cid))
    if not t:
        return None
    url, ts_ms = t
    if not url or (now_ms - int(ts_ms or 0)) > max_age_ms:
        return None
    return url


# 即时类指令：仅当消息带有效 ts 且在下列时间窗内才执行（钉钉/ daemon 重启后轮询到历史消息时不误触发）
_MORNING_CMD_MAX_AGE_MS = int(os.environ.get('SKILL_MORNING_MAX_AGE_MS', str(15 * 60 * 1000)))   # 默认 15 分钟
_PRECHECK_CMD_MAX_AGE_MS = int(os.environ.get('SKILL_PRECHECK_MAX_AGE_MS', str(30 * 60 * 1000)))  # 默认 30 分钟
_RECENT_CMD_MS = 15000   # 同一指令 15 秒内只响应一次，避免重复推送
# 今日/明日/本周关注：Hook 推送与 /fetch 轮询对同一条消息可能生成不同 msg_id，15s 挡不住「下一轮 poll」；窗口须盖住 POLL_INTERVAL
_RECENT_FOCUS_CMD_MS = max(
    _RECENT_CMD_MS,
    int(os.environ.get('SKILL_FOCUS_THROTTLE_MS', str(POLL_INTERVAL * 1000 + 5000))),
)
_recent_cmd_ts = {}      # (group_cid, cmd_key) -> last_run_ts_ms
_recent_memo_ts = {}     # (group_cid, content_key) -> last_run_ts_ms，备忘按内容短时去重
# 人员筛选等 throttle 的读改写与 push/poll 并发时加锁，避免双线程同时通过 15s 窗
_MEMO_THROTTLE_LOCK = threading.Lock()
# 备忘「内容键 + 短时窗」登记与 push/poll 并发时加锁，避免双线程同时通过去重导致双收录
_MEMO_INGEST_LOCK = threading.Lock()
# msg_id 去重需要原子“查+写”，否则并发 push 可能同一 msg_id 双处理
_MEMO_SEEN_LOCK = threading.Lock()


def _reserve_msg_id_once(seen_set: set, msg_id: str) -> bool:
    """原子预占 msg_id。True=本次首次占用，可继续处理；False=已处理过。"""
    with _MEMO_SEEN_LOCK:
        if msg_id in seen_set:
            return False
        seen_set.add(msg_id)
        return True


def _is_stale_command_msg(msg: dict, now_ms: int, max_age_ms: int) -> bool:
    """即时类指令（上班啦、预审等）：True 表示消息过旧或时间戳不可靠，应忽略。

    - ts<=0：常见于 beacon 日志兜底写入的发送记录，无真实消息时间，轮询时不应触发。
    - now_ms - ts > max_age_ms：历史消息（如重启后 JSAPI 拉回群历史）。
    """
    ts = int(msg.get('ts') or 0)
    if ts <= 0:
        return True
    return (now_ms - ts) > max_age_ms


def _skip_msg_before_router_start(msg: dict, router_start_ms: int) -> bool:
    """True：本条消息早于 skill_router 本次 start()，应跳过（重启后不追溯）。

    router_start_ms<=0 时不启用。ts<=0 且无 ding_mid 时视为不可靠；有 ding_mid 的实时 push 仍处理（手机端常见）。
    """
    if not router_start_ms or router_start_ms <= 0:
        return False
    ts = int(msg.get('ts') or 0)
    if ts <= 0:
        return msg.get('ding_mid') is None
    return ts < router_start_ms


def _memo_content_key(text: str) -> str:
    """备忘内容归一化，用于短时去重（同一条备忘不重复收录）。"""
    if not text:
        return ''
    t = re.sub(r'[\uff3b【\[]*(?:备忘|提醒我|TR)[\uff3d】\]]*', '', text).strip()
    t = strip_leading_trigger_punct(t)
    t = ' '.join(t.split())  # 合并中间空白，避免同一句因空格差异被处理两次
    return (t[:80] or '').strip()


def _text_triggers_new_wish(text: str, memo_cfg: dict | None = None) -> bool:
    """与「许愿」等效的新愿望触发：含愿望单时只走列表，不收录。"""
    if not text:
        return False
    # 选题优先：标题里常带「愿望/wish」等词，勿误进愿望单
    if _text_triggers_topic_pick(text, memo_cfg):
        return False
    if '愿望单' in text:
        return False
    if '许愿' in text:
        return True
    if re.search(r'愿望(?!单)', text):
        return True
    if re.search(r'(?i)\bwish\b', text):
        return True
    return False


def _normalize_push_record(record: dict) -> dict:
    """把 monitor 推送的 record 转成与 _read_log_messages 一致的 msg 结构（含 uid）。"""
    uid = record.get('uid', '') or ''
    if not uid:
        try:
            me = record.get('md_extra') or {}
            inner = me.get(3) or me.get('3') or {}
            uid = str(inner.get(1) or inner.get('1') or '')
        except Exception:
            uid = ''
    dm = record.get('msg_id')
    ding_mid = None
    if dm is not None and str(dm).strip() not in ('', '0'):
        ding_mid = dm
    return {
        'cid': record.get('cid', ''),
        'uid': uid,
        'ts': record.get('ts', 0),
        'content_type': record.get('content_type', 0),
        'text': record.get('text', '') or '',
        'raw': '',
        'ding_mid': ding_mid,
    }


def _dispatch_one_message(record: dict, memo_cfg: dict,
                          memo_seen_ids: set, doc_review_cfg: dict = None,
                          doc_seen_ids: set = None, router_start_ms: int = 0):
    """推送到达时立刻处理单条：消息 cid 须在 memo 助理群或 colleague_skill_cids 白名单内。

    router_start_ms：本次 router 启动时刻（毫秒）；早于该时刻的记录不处理（与轮询一致）。
    """
    msg = _normalize_push_record(record)
    if _skip_msg_before_router_start(msg, router_start_ms):
        return
    msg_cid = str(msg.get('cid', '') or '')
    tcid = get_taoge_recipient_cid()
    if tcid and msg_cid == tcid:
        try:
            _ct_t = int(msg.get('content_type') or 0)
        except (TypeError, ValueError):
            _ct_t = 0
        if _ct_t == 1 and not (msg.get('text') or '').strip():
            _try_hydrate_push_message_from_fetch(msg)
        msg_id_t = _make_msg_id(msg)
        if msg_id_t:
            handle_taoge_dm_message(
                msg, memo_cfg, memo_seen_ids,
                msg_id=msg_id_t, router_start_ms=router_start_ms, source='push',
            )
        return
    if msg_cid not in _memo_allowed_cids(memo_cfg):
        return
    _sender_uid = _message_sender_identity(msg)
    if not _assistant_group_skill_sender_allowed(memo_cfg, msg_cid, _sender_uid):
        return
    _doc_g = str((doc_review_cfg or {}).get('group_cid') or '').strip()
    if _doc_g:
        _remember_push_doc_url_if_any(msg_cid, msg, _doc_g)

    try:
        _ct_h = int(msg.get('content_type') or 0)
    except (TypeError, ValueError):
        _ct_h = 0
    # 仅文本类 push 补水；文件/卡片等空正文不应误配邻近文字
    if _ct_h == 1 and not (msg.get('text') or '').strip():
        _try_hydrate_push_message_from_fetch(msg)

    text = _normalize_command_text(_extract_message_text(msg))
    if not text:
        return
    msg_id = _make_msg_id(msg)
    if not msg_id:
        # send 钩子捕获的自发消息在上传前 msg_id=0，由 poll 路径负责处理
        if msg.get('is_self') is True and text:
            _log(f'push: self-send captured (no msg_id yet, poll will handle) cid={msg_cid} text={text[:40]}')
        return

    # 预审所在群：用户叫停（终止 Palace + 停进度推送）
    if (
        doc_review_cfg
        and str(doc_review_cfg.get('group_cid') or '').strip()
        and msg_cid == str(doc_review_cfg.get('group_cid')).strip()
        and _RE_PRECHECK_STOP.match(text)
    ):
        wh = doc_review_cfg.get('webhook_url', '')
        if try_user_stop_doc_review(wh):
            _log('push: 预审已按用户指令叫停')
        else:
            send_no_active_doc_review_stop_reply(wh)
        if doc_seen_ids is not None:
            doc_seen_ids.add(msg_id)
        return

    # 预审：即时拉取近期消息、回溯文档链接后执行（推送即刚发生，不做时间窗判断；轮询侧再做过期过滤）
    _is_precheck, _force_precheck = _precheck_command_flags(text)
    if _is_precheck and doc_review_cfg and doc_review_cfg.get('group_cid') and msg_cid == str(doc_review_cfg.get('group_cid')):
        if doc_seen_ids is not None and msg_id in doc_seen_ids:
            return
        try:
            now_precheck = int(time.time() * 1000)
            doc_url = _cached_push_doc_url(
                msg_cid, _doc_g, now_precheck, _DOC_REVIEW_MAX_AGE_MS,
            )
            if doc_url:
                _log('push: 预审 -> 使用前序 send 缓存的文档链接（不调用 fetch）')

            if not doc_url:
                messages = list(_fetch_memo_messages(msg_cid, max_age_ms=_DOC_REVIEW_MAX_AGE_MS))
                # 当前这条「预审」可能尚未出现在 fetch 结果中，并入列表以便正确回溯前序文档
                messages.append(msg)
                msgs_by_ts = sorted(messages, key=lambda m: int(m.get('ts', 0)))
                for i, m in enumerate(msgs_by_ts):
                    if _make_msg_id(m) != msg_id:
                        continue
                    for j in range(i - 1, -1, -1):
                        u = extract_doc_url_from_message(msgs_by_ts[j])
                        if u:
                            doc_url = u
                            break
                    break
                # 首次未找到时延迟 2 秒再拉一次（刚发的文档链接可能尚未入历史）
                if not doc_url and messages:
                    time.sleep(2)
                    messages2 = list(_fetch_memo_messages(msg_cid, max_age_ms=_DOC_REVIEW_MAX_AGE_MS))
                    messages2.append(msg)
                    msgs_by_ts = sorted(messages2, key=lambda m: int(m.get('ts', 0)))
                    for i, m in enumerate(msgs_by_ts):
                        if _make_msg_id(m) != msg_id:
                            continue
                        for j in range(i - 1, -1, -1):
                            u = extract_doc_url_from_message(msgs_by_ts[j])
                            if u:
                                doc_url = u
                                break
                        break
            if doc_url:
                sender_uid = str(msg.get('uid', ''))
                result = process_doc_review(
                    msg_id=msg_id, url=doc_url, sender_uid=sender_uid,
                    msg_text=text, config=doc_review_cfg,
                    force_bypass_recent_window=_force_precheck,
                )
                if doc_seen_ids is not None:
                    doc_seen_ids.add(msg_id)
                _log('push: 预审 -> 已触发')
            else:
                _send_notify(get_doc_review_no_link_message(), doc_review_cfg.get('webhook_url', ''))
                if doc_seen_ids is not None:
                    doc_seen_ids.add(msg_id)
                _log('push: 预审 -> 未找到前序文档链接')
        except Exception as e:
            _log(f'push doc_review error: {e}')
        return

    reserved = _reserve_msg_id_once(memo_seen_ids, msg_id)
    _agent_dbg(
        'H2', 'skill_router._dispatch', 'after_reserve',
        reserved=reserved, msg_id=msg_id, cid=msg_cid,
        text_preview=(text or '')[:120],
    )
    if not reserved:
        return

    now_ms = int(time.time() * 1000)

    if _RE_MORNING.match(text):
        key = (msg_cid, 'morning')
        if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_CMD_MS:
            memo_seen_ids.add(msg_id)
            return
        _recent_cmd_ts[key] = now_ms
        try:
            webhook_url = _wish_webhook_for_cid(memo_cfg, msg_cid)
            if not webhook_url:
                _log('push: 上班啦 -> 未配置 webhook')
            else:
                r = run_morning_flow(webhook_url)
                if r.get('notified'):
                    _log('push: 上班啦 -> 已推送%s' % ('（全部就绪）' if r.get('all_ok') else '（含仍异常）'))
                else:
                    _log('push: 上班啦 -> 发送失败')
            memo_seen_ids.add(msg_id)
        except Exception as e:
            _log(f'morning status_check error: {e}')
        return

    if _RE_INSPECTION.match(text):
        key = (msg_cid, 'inspection')
        if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_CMD_MS:
            memo_seen_ids.add(msg_id)
            return
        _recent_cmd_ts[key] = now_ms
        try:
            webhook_url = _wish_webhook_for_cid(memo_cfg, msg_cid)
            if not webhook_url:
                _log('push: 查岗 -> 未配置 webhook')
            else:
                r = run_inspection_flow(webhook_url)
                if r.get('notified'):
                    _log('push: 查岗 -> 已推送%s' % ('（全绿）' if r.get('all_ok') else '（含异常）'))
                else:
                    _log('push: 查岗 -> 发送失败')
            memo_seen_ids.add(msg_id)
        except Exception as e:
            _log(f'inspection status_check error: {e}')
        return

    if _RE_REPAIR.match(text):
        key = (msg_cid, 'repair')
        if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_CMD_MS:
            memo_seen_ids.add(msg_id)
            return
        _recent_cmd_ts[key] = now_ms
        try:
            webhook_url = _wish_webhook_for_cid(memo_cfg, msg_cid)
            if not webhook_url:
                _log('push: 修复 -> 未配置 webhook')
            else:
                r = run_repair_flow(webhook_url)
                if r.get('ack_notified'):
                    _log('push: 修复 -> 已推送收到确认')
                if r.get('notified'):
                    _log('push: 修复 -> 已推送复检摘要')
                else:
                    _log('push: 修复 -> 复检摘要发送失败')
                if r.get('gate_repair_spawned'):
                    _log('push: 修复 -> 已分离启动 daemon_health_notify')
            memo_seen_ids.add(msg_id)
        except Exception as e:
            _log(f'repair status_check error: {e}')
        return

    if _text_triggers_taoge_update(text):
        if _is_stale_command_msg(msg, now_ms, _MORNING_CMD_MAX_AGE_MS):
            memo_seen_ids.add(msg_id)
            _log('push: 涛哥更新 -> 跳过（超出有效时间窗或时间戳无效）')
            return
        key = (msg_cid, 'taoge_update')
        if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_CMD_MS:
            memo_seen_ids.add(msg_id)
            return
        _recent_cmd_ts[key] = now_ms
        try:
            run_taoge_update_flow(group_cid=msg_cid, memo_cfg=memo_cfg)
            memo_seen_ids.add(msg_id)
            _log('push: 涛哥更新 -> 已处理')
        except Exception as e:
            memo_seen_ids.add(msg_id)
            _log(f'taoge_update error: {e}')
        return

    if _RE_VERSION_DIGEST.match(text):
        key = (msg_cid, 'version_digest')
        if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_CMD_MS:
            memo_seen_ids.add(msg_id)
            return
        _recent_cmd_ts[key] = now_ms
        try:
            r = run_version_digest_send(send_webhook=True, log_to_stdout=False)
            memo_seen_ids.add(msg_id)
            if r.get('ok'):
                _log('push: 版本咋样了 -> version_digest 已推送')
            else:
                _log(f'push: 版本咋样了 -> 未成功 ({r.get("error")})')
        except Exception as e:
            memo_seen_ids.add(msg_id)
            _log(f'version_digest error: {e}')
        return

    if _RE_TODAY_FOCUS.search(text):
        key = (msg_cid, 'today_focus')
        if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_FOCUS_CMD_MS:
            memo_seen_ids.add(msg_id)
            return
        _recent_cmd_ts[key] = now_ms
        try:
            process_today_focus(memo_cfg, group_cid=msg_cid)
            memo_seen_ids.add(msg_id)
            _log('push: 今日关注已回复')
        except Exception as e:
            _log(f'today_focus error: {e}')
        return

    if _RE_TOMORROW_FOCUS.search(text):
        key = (msg_cid, 'tomorrow_focus')
        if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_FOCUS_CMD_MS:
            memo_seen_ids.add(msg_id)
            return
        _recent_cmd_ts[key] = now_ms
        try:
            process_tomorrow_focus(memo_cfg, group_cid=msg_cid)
            memo_seen_ids.add(msg_id)
            _log('push: 明日关注已回复')
        except Exception as e:
            _log(f'tomorrow_focus error: {e}')
        return

    if _RE_WEEK_FOCUS.search(text):
        key = (msg_cid, 'week_focus')
        if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_FOCUS_CMD_MS:
            memo_seen_ids.add(msg_id)
            return
        _recent_cmd_ts[key] = now_ms
        try:
            process_week_focus(memo_cfg, group_cid=msg_cid)
            memo_seen_ids.add(msg_id)
            _log('push: 本周关注已回复')
        except Exception as e:
            _log(f'week_focus error: {e}')
        return

    pdef = parse_defer_memo_command(text)
    if pdef is not None:
        seqs, due_d = pdef
        defer_dedup_id = f'def:{msg_cid}:{due_d or "nodate"}:{"|".join(sorted(map(str, seqs)))}'
        if defer_dedup_id in memo_seen_ids:
            memo_seen_ids.add(msg_id)
            return
        memo_seen_ids.add(defer_dedup_id)
        key = (msg_cid, 'defer', tuple(seqs), due_d or '')
        if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_CMD_MS:
            memo_seen_ids.add(msg_id)
            return
        _recent_cmd_ts[key] = now_ms
        try:
            process_defer_memo(msg_id=msg_id, text=text, group_cid=msg_cid, config=memo_cfg)
            memo_seen_ids.add(msg_id)
            _log('push: 备忘延期已处理')
        except Exception as e:
            _log(f'defer_memo error: {e}')
        return

    for _edit_fn in (
        process_topic_edit_description,
        process_memo_edit_description,
        process_memo_edit_version,
        process_memo_assign_tr,
    ):
        try:
            if _edit_fn(msg_id=msg_id, text=text, group_cid=msg_cid, config=memo_cfg):
                memo_seen_ids.add(msg_id)
                _log('push: 备忘/选题快捷指令已处理')
                return
        except Exception as e:
            _log(f'memo quick-edit {_edit_fn.__name__} error: {e}')

    try:
        if process_aider_runner(
                msg_id=msg_id, text=text, group_cid=msg_cid, config=memo_cfg,
                sender_uid=_message_sender_identity(msg)):
            memo_seen_ids.add(msg_id)
            _log('push: Aider 指令')
            return
    except Exception as e:
        _log(f'aider_runner error: {e}')

    try:
        if process_desk_ops(msg_id=msg_id, text=text, group_cid=msg_cid, config=memo_cfg):
            memo_seen_ids.add(msg_id)
            _log('push: 桌面运维指令')
            return
    except Exception as e:
        _log(f'desk_ops error: {e}')

    with _MEMO_THROTTLE_LOCK:
        kw_pl = person_lookup_match_keyword(text, memo_cfg)
        if kw_pl is not None:
            pl_key = (str(msg_cid).strip(), 'person_lookup', kw_pl)
            if now_ms - _recent_cmd_ts.get(pl_key, 0) < _RECENT_CMD_MS:
                memo_seen_ids.add(msg_id)
                return
            _recent_cmd_ts[pl_key] = now_ms
    try:
        if process_person_lookup(msg_id=msg_id, text=text, group_cid=msg_cid, config=memo_cfg):
            memo_seen_ids.add(msg_id)
            _log('push: 人员关键词筛选（备忘+愿望）')
            return
    except Exception as e:
        _log(f'person_lookup error: {e}')

    if _RE_DELETE_WISH.search(text):
        m_seq = re.search(r'删除\s*(?:wish|愿望)\s*#?\s*(\d+)', text, re.IGNORECASE)
        if m_seq:
            seq = m_seq.group(1)
            delete_dedup_id = f'delwish:{msg_cid}:{seq}'
            if delete_dedup_id in memo_seen_ids:
                memo_seen_ids.add(msg_id)
                return
            memo_seen_ids.add(delete_dedup_id)
            key = (msg_cid, 'delete_wish', seq)
            if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_CMD_MS:
                memo_seen_ids.add(msg_id)
                return
            _recent_cmd_ts[key] = now_ms
        try:
            if process_delete_wish(msg_id=msg_id, text=text, group_cid=msg_cid, config=memo_cfg):
                memo_seen_ids.add(msg_id)
                _log('push: 删除 wish 指令已处理')
        except Exception as e:
            _log(f'delete_wish error: {e}')
        return

        pk_topic = parse_delete_topic_seqs(text)
        if pk_topic is not None:
            _agent_dbg(
                'H4', 'skill_router.push', 'delete_topic_branch',
                msg_id=msg_id, cid=msg_cid, seqs=pk_topic, text_preview=(text or '')[:80],
            )
            seq_key = '|'.join(sorted(map(str, pk_topic))) if pk_topic else ''
        delete_dedup_id = f'deltopic:{msg_cid}:{seq_key}'
        if delete_dedup_id in memo_seen_ids:
            memo_seen_ids.add(msg_id)
            return
        memo_seen_ids.add(delete_dedup_id)
        key = (msg_cid, 'delete_topic', seq_key)
        if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_CMD_MS:
            memo_seen_ids.add(msg_id)
            return
        _recent_cmd_ts[key] = now_ms
        try:
            if process_delete_topic(msg_id=msg_id, text=text, group_cid=msg_cid, config=memo_cfg):
                memo_seen_ids.add(msg_id)
                _log('push: 删除选题指令已处理')
        except Exception as e:
            _log(f'delete_topic error: {e}')
        return

    pk_memo = parse_delete_memo_seqs(text)
    if pk_memo is not None:
        _agent_dbg(
            'H4', 'skill_router.push', 'delete_memo_branch',
            msg_id=msg_id, cid=msg_cid, seqs=pk_memo, text_preview=(text or '')[:80],
        )
        seq_key = '|'.join(sorted(map(str, pk_memo))) if pk_memo else ''
        delete_dedup_id = f'del:{msg_cid}:{seq_key}'
        if delete_dedup_id in memo_seen_ids:
            memo_seen_ids.add(msg_id)
            return
        memo_seen_ids.add(delete_dedup_id)
        key = (msg_cid, 'delete', seq_key)
        if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_CMD_MS:
            memo_seen_ids.add(msg_id)
            return
        _recent_cmd_ts[key] = now_ms
        try:
            if process_delete(msg_id=msg_id, text=text, group_cid=msg_cid, config=memo_cfg):
                memo_seen_ids.add(msg_id)
                _log('push: 删除备忘指令已处理')
        except Exception as e:
            _log(f'delete error: {e}')
        return

    if _RE_CLOSE_WISH.search(text):
        m_seq = re.search(r'(?:完成|关闭)\s*(?:wish|愿望)\s*#?\s*(\d+)', text, re.IGNORECASE)
        if m_seq:
            seq = m_seq.group(1)
            dedup = f'closewish:{msg_cid}:{seq}'
            if dedup in memo_seen_ids:
                memo_seen_ids.add(msg_id)
                return
            memo_seen_ids.add(dedup)
            key = (msg_cid, 'close_wish', seq)
            if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_CMD_MS:
                memo_seen_ids.add(msg_id)
                return
            _recent_cmd_ts[key] = now_ms
        try:
            if process_close_wish(msg_id=msg_id, text=text, group_cid=msg_cid, config=memo_cfg):
                memo_seen_ids.add(msg_id)
                _log('push: 完成 wish 指令已处理')
        except Exception as e:
            _log(f'close_wish error: {e}')
        return

    if _RE_CLOSE.search(text):
        try:
            process_close(msg_id=msg_id, text=text, group_cid=msg_cid, config=memo_cfg)
            memo_seen_ids.add(msg_id)
            _log('push: 完成指令已处理')
        except Exception as e:
            _log(f'close error: {e}')
        return

    # 「愿望单」优先于「愿望」单字触发，避免误收录
    if '愿望单' in text:
        key = (msg_cid, 'wish_list')
        if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_CMD_MS:
            memo_seen_ids.add(msg_id)
            return
        _recent_cmd_ts[key] = now_ms
        try:
            process_wish_list(memo_cfg, group_cid=msg_cid)
            memo_seen_ids.add(msg_id)
            _log('push: 愿望单列表已打印并推送')
        except Exception as e:
            _log(f'wish_list error: {e}')
        return

    if _text_triggers_new_wish(text, memo_cfg):
        ck = wish_content_key(text)
        if ck:
            wish_dedup = 'wish_c:' + ck
            if wish_dedup in memo_seen_ids:
                memo_seen_ids.add(msg_id)
                return
            wkey = (msg_cid, ck)
            if now_ms - _recent_memo_ts.get(wkey, 0) < _RECENT_CMD_MS:
                memo_seen_ids.add(msg_id)
                return
        try:
            result = process_wish(msg_id=msg_id, text=text, group_cid=msg_cid, config=memo_cfg)
            if result is not None:
                memo_seen_ids.add(msg_id)
                if ck:
                    memo_seen_ids.add('wish_c:' + ck)
                    _recent_memo_ts[(msg_cid, ck)] = now_ms
                _log('push: 愿望已收录 TaskReminder')
        except Exception as e:
            _log(f'wish error: {e}')
        return

    if topic_library_match_text(text, memo_cfg):
        key = (msg_cid, 'topic_library')
        if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_CMD_MS:
            memo_seen_ids.add(msg_id)
            return
        _recent_cmd_ts[key] = now_ms
        try:
            process_topic_library(memo_cfg, group_cid=msg_cid)
            memo_seen_ids.add(msg_id)
            _log('push: 选题库已推送')
        except Exception as e:
            _log(f'topic_library error: {e}')
        return

    try:
        if _text_triggers_topic_pick(text, memo_cfg):
            _tck_dbg = topic_pick_content_key(text)
            _tid_dbg = ('topic_c:' + _tck_dbg) if _tck_dbg else ''
            _agent_dbg(
                'H1', 'skill_router.push', 'before_process_topic_pick',
                msg_id=msg_id, cid=msg_cid, tck=_tck_dbg,
                topic_c_in_seen=(_tid_dbg in memo_seen_ids) if _tid_dbg else None,
            )
        memo_ts_push = int(msg.get('ts', 0) or 0)
        tp = process_topic_pick(
            msg_id=msg_id, text=text, context_msgs=[msg],
            memo_ts=memo_ts_push, group_cid=msg_cid, config=memo_cfg)
        if tp is not False:
            if tp is None:
                _log('push: 选题收录 TR 暂不可写')
            else:
                tck = topic_pick_content_key(text)
                if tck:
                    tid = 'topic_c:' + tck
                    if tid in memo_seen_ids:
                        memo_seen_ids.add(msg_id)
                        return
                    memo_seen_ids.add(tid)
                    _recent_memo_ts[(msg_cid, tck)] = now_ms
                memo_seen_ids.add(msg_id)
                _log('push: 选题已收录')
            return
    except Exception as e:
        _log(f'topic_pick error: {e}')

    # check_tracker: 本人发出的引用回复 TR → 跟进任务（push 路径）
    _check_cfg_p = memo_cfg.get('check_tracker', {})
    _check_allowed_p = set(
        str(c).strip() for c in (_check_cfg_p.get('allowed_cids') or []) if str(c).strip()
    )
    _check_my_uids_p = (
        set(str(u).strip() for u in (memo_cfg.get('assistant_group_skill_uids') or []) if str(u).strip())
        | set(str(a).strip() for a in (memo_cfg.get('assistant_group_skill_aliases') or []) if str(a).strip())
        | {str(os.environ.get('DINGTALK_MY_UID', DEFAULT_MY_UID)).strip()}
    )
    # P2P 私聊（CID 含 ':'）依赖 CID 白名单已足够，JSAPI 路径 is_self 不可靠；群聊仍要验证发送者
    _check_is_p2p_p = ':' in msg_cid
    _check_is_self_p = (
        _check_is_p2p_p
        or msg.get('is_self') is True
        or _message_sender_identity(msg) in _check_my_uids_p
    )
    if (
        _check_allowed_p
        and msg_cid in _check_allowed_p
        and _check_is_self_p
        and parse_check_trigger(text)
    ):
        # 内容去重：防止 push+poll 双路径对同一消息重复创建
        _check_content_key_p = text[:200]
        _check_dedup_id_p = 'check_c:' + msg_cid + ':' + _check_content_key_p
        if _check_dedup_id_p in memo_seen_ids:
            memo_seen_ids.add(msg_id)
            return
        memo_seen_ids.add(_check_dedup_id_p)
        try:
            r = process_check(msg_id=msg_id, text=text, group_cid=msg_cid, config=memo_cfg)
            memo_seen_ids.add(msg_id)
            if r is True:
                _log('push: check TR -> 已创建')
            else:
                _log('push: check TR -> TaskReminder 不可用')
        except Exception as e:
            memo_seen_ids.add(msg_id)
            _log(f'check error: {e}')
        return

    if _RE_MEMO.search(text):
        if is_memo_processed(msg_id):
            memo_seen_ids.add(msg_id)
            return
        with _MEMO_INGEST_LOCK:
            content_key = _memo_content_key(text)
            if content_key:
                # 按内容去重：同一条备忘若被 Hook/轮询各触发一次（不同 msg_id），只处理一次
                content_dedup_id = 'memo_c:' + content_key
                if content_dedup_id in memo_seen_ids:
                    memo_seen_ids.add(msg_id)
                    return
                memo_seen_ids.add(content_dedup_id)
                key = (msg_cid, content_key)
                if now_ms - _recent_memo_ts.get(key, 0) < _RECENT_CMD_MS:
                    memo_seen_ids.add(msg_id)
                    return
                _recent_memo_ts[key] = now_ms
        try:
            memo_ts = int(msg.get('ts', 0))
            result = process_memo(
                msg_id=msg_id, text=text,
                context_msgs=[msg], memo_ts=memo_ts,
                group_cid=msg_cid, config=memo_cfg,
            )
            if result is not None:
                memo_seen_ids.add(msg_id)
                _log('push: 备忘已收录')
        except Exception as e:
            _log(f'memo error: {e}')


def _poll_memo_once(group_cid: str, memo_cfg: dict, seen_ids: set,
                    router_start_ms: int = 0):
    """轮询助理通知群, 处理备忘/完成指令（JSAPI 不可用时自动降级到 beacon 日志）。

    router_start_ms：仅处理不早于本次 router 启动的消息（重启后不追溯）。
    """
    messages = _fetch_memo_messages(group_cid, max_age_ms=_MEMO_MAX_AGE_MS)
    _cleanup_pending_interview_bind()
    if os.environ.get('SKILL_ROUTER_MEMO_POLL_TRACE', '').strip() == '1':
        _log(f'memo poll trace cid={group_cid} fetched_messages={len(messages)}')
    now_ms = int(time.time() * 1000)

    for msg in messages:
        if _handle_interview_file_message(msg, group_cid, seen_ids, router_start_ms=router_start_ms):
            continue
        text = _normalize_command_text(_extract_message_text(msg))
        if not text:
            continue

        msg_ts = int(msg.get('ts') or 0)
        if _skip_msg_before_router_start(msg, router_start_ms):
            continue
        if msg_ts and (now_ms - msg_ts) > _MEMO_MAX_AGE_MS:
            continue

        msg_id = _make_msg_id(msg)
        if not msg_id or msg_id in seen_ids:
            continue

        tcid = get_taoge_recipient_cid()
        if tcid and str(group_cid).strip() == tcid:
            handle_taoge_dm_message(
                msg, memo_cfg, seen_ids,
                msg_id=msg_id, router_start_ms=router_start_ms, now_ms=now_ms, source='poll',
            )
            continue

        if not _assistant_group_skill_sender_allowed(memo_cfg, group_cid, _message_sender_identity(msg)):
            seen_ids.add(msg_id)
            continue

        if _try_bind_candidate_command(text, group_cid, seen_ids, msg_id):
            continue

        if _RE_MORNING.match(text):
            if _is_stale_command_msg(msg, now_ms, _MORNING_CMD_MAX_AGE_MS):
                seen_ids.add(msg_id)
                _log('poll: 上班啦 -> 跳过（超出有效时间窗或时间戳无效）')
                continue
            try:
                webhook_url = _wish_webhook_for_cid(memo_cfg, group_cid)
                if not webhook_url:
                    _log('poll: 上班啦 -> 未配置 webhook')
                else:
                    r = run_morning_flow(webhook_url)
                    if r.get('notified'):
                        _log('poll: 上班啦 -> 已推送%s' % ('（全部就绪）' if r.get('all_ok') else '（含仍异常）'))
                    else:
                        _log('poll: 上班啦 -> 发送失败')
                seen_ids.add(msg_id)
            except Exception as e:
                _log(f'morning status_check error: {e}')
            continue

        if _RE_INSPECTION.match(text):
            if _is_stale_command_msg(msg, now_ms, _MORNING_CMD_MAX_AGE_MS):
                seen_ids.add(msg_id)
                _log('poll: 查岗 -> 跳过（超出有效时间窗或时间戳无效）')
                continue
            try:
                webhook_url = _wish_webhook_for_cid(memo_cfg, group_cid)
                if not webhook_url:
                    _log('poll: 查岗 -> 未配置 webhook')
                else:
                    r = run_inspection_flow(webhook_url)
                    if r.get('notified'):
                        _log('poll: 查岗 -> 已推送%s' % ('（全绿）' if r.get('all_ok') else '（含异常）'))
                    else:
                        _log('poll: 查岗 -> 发送失败')
                seen_ids.add(msg_id)
            except Exception as e:
                _log(f'inspection status_check error: {e}')
            continue

        if _RE_REPAIR.match(text):
            if _is_stale_command_msg(msg, now_ms, _MORNING_CMD_MAX_AGE_MS):
                seen_ids.add(msg_id)
                _log('poll: 修复 -> 跳过（超出有效时间窗或时间戳无效）')
                continue
            try:
                webhook_url = _wish_webhook_for_cid(memo_cfg, group_cid)
                if not webhook_url:
                    _log('poll: 修复 -> 未配置 webhook')
                else:
                    r = run_repair_flow(webhook_url)
                    if r.get('ack_notified'):
                        _log('poll: 修复 -> 已推送收到确认')
                    if r.get('notified'):
                        _log('poll: 修复 -> 已推送复检摘要')
                    else:
                        _log('poll: 修复 -> 复检摘要发送失败')
                    if r.get('gate_repair_spawned'):
                        _log('poll: 修复 -> 已分离启动 daemon_health_notify')
                seen_ids.add(msg_id)
            except Exception as e:
                _log(f'repair status_check error: {e}')
            continue

        if _text_triggers_taoge_update(text):
            if _is_stale_command_msg(msg, now_ms, _MORNING_CMD_MAX_AGE_MS):
                seen_ids.add(msg_id)
                _log('poll: 涛哥更新 -> 跳过（超出有效时间窗或时间戳无效）')
                continue
            key = (str(group_cid), 'taoge_update')
            if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_CMD_MS:
                seen_ids.add(msg_id)
                continue
            _recent_cmd_ts[key] = now_ms
            try:
                run_taoge_update_flow(group_cid=group_cid, memo_cfg=memo_cfg)
                seen_ids.add(msg_id)
                _log('poll: 涛哥更新 -> 已处理')
            except Exception as e:
                seen_ids.add(msg_id)
                _log(f'taoge_update error: {e}')
            continue

        if _RE_VERSION_DIGEST.match(text):
            if _is_stale_command_msg(msg, now_ms, _MORNING_CMD_MAX_AGE_MS):
                seen_ids.add(msg_id)
                _log('poll: 版本咋样了 -> 跳过（超出有效时间窗或时间戳无效）')
                continue
            key = (str(group_cid), 'version_digest')
            if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_CMD_MS:
                seen_ids.add(msg_id)
                continue
            _recent_cmd_ts[key] = now_ms
            try:
                r = run_version_digest_send(send_webhook=True, log_to_stdout=False)
                seen_ids.add(msg_id)
                if r.get('ok'):
                    _log('poll: 版本咋样了 -> version_digest 已推送')
                else:
                    _log(f'poll: 版本咋样了 -> 未成功 ({r.get("error")})')
            except Exception as e:
                seen_ids.add(msg_id)
                _log(f'version_digest error: {e}')
            continue

        if _RE_DELETE_WISH.search(text):
            m_seq = re.search(r'删除\s*(?:wish|愿望)\s*#?\s*(\d+)', text, re.IGNORECASE)
            if m_seq:
                seq = m_seq.group(1)
                delete_dedup_id = f'delwish:{str(group_cid).strip()}:{seq}'
                if delete_dedup_id in seen_ids:
                    seen_ids.add(msg_id)
                    continue
                seen_ids.add(delete_dedup_id)
                key = (str(group_cid), 'delete_wish', seq)
                if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_CMD_MS:
                    seen_ids.add(msg_id)
                    continue
                _recent_cmd_ts[key] = now_ms
            try:
                if process_delete_wish(msg_id=msg_id, text=text, group_cid=group_cid, config=memo_cfg):
                    seen_ids.add(msg_id)
            except Exception as e:
                _log(f'delete_wish error: {e}')
            continue

        pk_topic = parse_delete_topic_seqs(text)
        if pk_topic is not None:
            _agent_dbg(
                'H4', 'skill_router.poll', 'delete_topic_branch',
                msg_id=msg_id, cid=str(group_cid), seqs=pk_topic, text_preview=(text or '')[:80],
            )
            gc = str(group_cid).strip()
            seq_key = '|'.join(sorted(map(str, pk_topic))) if pk_topic else ''
            delete_dedup_id = f'deltopic:{gc}:{seq_key}'
            if delete_dedup_id in seen_ids:
                seen_ids.add(msg_id)
                continue
            seen_ids.add(delete_dedup_id)
            key = (gc, 'delete_topic', seq_key)
            if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_CMD_MS:
                seen_ids.add(msg_id)
                continue
            _recent_cmd_ts[key] = now_ms
            try:
                if process_delete_topic(msg_id=msg_id, text=text, group_cid=group_cid, config=memo_cfg):
                    seen_ids.add(msg_id)
            except Exception as e:
                _log(f'delete_topic error: {e}')
            continue

        pk_memo = parse_delete_memo_seqs(text)
        if pk_memo is not None:
            _agent_dbg(
                'H4', 'skill_router.poll', 'delete_memo_branch',
                msg_id=msg_id, cid=str(group_cid), seqs=pk_memo, text_preview=(text or '')[:80],
            )
            gc = str(group_cid).strip()
            seq_key = '|'.join(sorted(map(str, pk_memo))) if pk_memo else ''
            delete_dedup_id = f'del:{gc}:{seq_key}'
            if delete_dedup_id in seen_ids:
                seen_ids.add(msg_id)
                continue
            seen_ids.add(delete_dedup_id)
            key = (gc, 'delete', seq_key)
            if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_CMD_MS:
                seen_ids.add(msg_id)
                continue
            _recent_cmd_ts[key] = now_ms
            try:
                if process_delete(msg_id=msg_id, text=text, group_cid=group_cid, config=memo_cfg):
                    seen_ids.add(msg_id)
            except Exception as e:
                _log(f'delete error: {e}')
            continue

        if _RE_TODAY_FOCUS.search(text):
            gc = str(group_cid).strip()
            key = (gc, 'today_focus')
            if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_FOCUS_CMD_MS:
                seen_ids.add(msg_id)
                continue
            _recent_cmd_ts[key] = now_ms
            try:
                process_today_focus(memo_cfg, group_cid=group_cid)
                seen_ids.add(msg_id)
            except Exception as e:
                _log(f'today_focus error: {e}')
            continue

        if _RE_TOMORROW_FOCUS.search(text):
            gc = str(group_cid).strip()
            key = (gc, 'tomorrow_focus')
            if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_FOCUS_CMD_MS:
                seen_ids.add(msg_id)
                continue
            _recent_cmd_ts[key] = now_ms
            try:
                process_tomorrow_focus(memo_cfg, group_cid=group_cid)
                seen_ids.add(msg_id)
            except Exception as e:
                _log(f'tomorrow_focus error: {e}')
            continue

        if _RE_WEEK_FOCUS.search(text):
            gc = str(group_cid).strip()
            key = (gc, 'week_focus')
            if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_FOCUS_CMD_MS:
                seen_ids.add(msg_id)
                continue
            _recent_cmd_ts[key] = now_ms
            try:
                process_week_focus(memo_cfg, group_cid=group_cid)
                seen_ids.add(msg_id)
            except Exception as e:
                _log(f'week_focus error: {e}')
            continue

        pdef = parse_defer_memo_command(text)
        if pdef is not None:
            seqs, due_d = pdef
            defer_dedup_id = f'def:{str(group_cid).strip()}:{due_d or "nodate"}:{"|".join(sorted(map(str, seqs)))}'
            if defer_dedup_id in seen_ids:
                seen_ids.add(msg_id)
                continue
            seen_ids.add(defer_dedup_id)
            key = (str(group_cid), 'defer', tuple(seqs), due_d or '')
            if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_CMD_MS:
                seen_ids.add(msg_id)
                continue
            _recent_cmd_ts[key] = now_ms
            try:
                process_defer_memo(msg_id=msg_id, text=text, group_cid=group_cid, config=memo_cfg)
                seen_ids.add(msg_id)
            except Exception as e:
                _log(f'defer_memo error: {e}')
            continue

        _poll_edit_handled = False
        for _edit_fn in (
            process_topic_edit_description,
            process_memo_edit_description,
            process_memo_edit_version,
            process_memo_assign_tr,
        ):
            try:
                if _edit_fn(msg_id=msg_id, text=text, group_cid=group_cid, config=memo_cfg):
                    seen_ids.add(msg_id)
                    _log('poll: 备忘/选题快捷指令已处理')
                    _poll_edit_handled = True
                    break
            except Exception as e:
                _log(f'memo quick-edit {_edit_fn.__name__} error: {e}')
        if _poll_edit_handled:
            continue

        try:
            if process_aider_runner(
                    msg_id=msg_id, text=text, group_cid=group_cid, config=memo_cfg,
                    sender_uid=_message_sender_identity(msg)):
                seen_ids.add(msg_id)
                _log('poll: Aider 指令')
                continue
        except Exception as e:
            _log(f'aider_runner error: {e}')

        try:
            if process_desk_ops(msg_id=msg_id, text=text, group_cid=group_cid, config=memo_cfg):
                seen_ids.add(msg_id)
                _log('poll: 桌面运维指令')
                continue
        except Exception as e:
            _log(f'desk_ops error: {e}')

        with _MEMO_THROTTLE_LOCK:
            kw_pl = person_lookup_match_keyword(text, memo_cfg)
            if kw_pl is not None:
                pl_key = (str(group_cid).strip(), 'person_lookup', kw_pl)
                if now_ms - _recent_cmd_ts.get(pl_key, 0) < _RECENT_CMD_MS:
                    seen_ids.add(msg_id)
                    continue
                _recent_cmd_ts[pl_key] = now_ms
        try:
            if process_person_lookup(msg_id=msg_id, text=text, group_cid=group_cid, config=memo_cfg):
                seen_ids.add(msg_id)
                _log('poll: 人员关键词筛选（备忘+愿望）')
                continue
        except Exception as e:
            _log(f'person_lookup error: {e}')

        if _RE_CLOSE_WISH.search(text):
            m_seq = re.search(r'(?:完成|关闭)\s*(?:wish|愿望)\s*#?\s*(\d+)', text, re.IGNORECASE)
            if m_seq:
                key = (str(group_cid), 'close_wish', m_seq.group(1))
                if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_CMD_MS:
                    seen_ids.add(msg_id)
                    continue
                _recent_cmd_ts[key] = now_ms
            try:
                if process_close_wish(msg_id=msg_id, text=text, group_cid=group_cid, config=memo_cfg):
                    seen_ids.add(msg_id)
            except Exception as e:
                _log(f'close_wish error: {e}')
            continue

        if _RE_CLOSE.search(text):
            try:
                process_close(msg_id=msg_id, text=text,
                              group_cid=group_cid, config=memo_cfg)
                seen_ids.add(msg_id)
            except Exception as e:
                _log(f'close error: {e}')
            continue

        if '愿望单' in text:
            key = (str(group_cid), 'wish_list')
            if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_CMD_MS:
                seen_ids.add(msg_id)
                continue
            _recent_cmd_ts[key] = now_ms
            try:
                process_wish_list(memo_cfg, group_cid=group_cid)
                seen_ids.add(msg_id)
            except Exception as e:
                _log(f'wish_list error: {e}')
            continue

        if _text_triggers_new_wish(text, memo_cfg):
            ck = wish_content_key(text)
            if ck:
                wish_dedup = 'wish_c:' + ck
                if wish_dedup in seen_ids:
                    seen_ids.add(msg_id)
                    continue
                seen_ids.add(wish_dedup)
                wkey = (str(group_cid), ck)
                if now_ms - _recent_memo_ts.get(wkey, 0) < _RECENT_CMD_MS:
                    seen_ids.add(msg_id)
                    continue
                _recent_memo_ts[wkey] = now_ms
            try:
                result = process_wish(msg_id=msg_id, text=text, group_cid=group_cid, config=memo_cfg)
                if result is not None:
                    seen_ids.add(msg_id)
            except Exception as e:
                _log(f'wish error: {e}')
            continue

        if topic_library_match_text(text, memo_cfg):
            key = (str(group_cid), 'topic_library')
            if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_CMD_MS:
                seen_ids.add(msg_id)
                continue
            _recent_cmd_ts[key] = now_ms
            try:
                process_topic_library(memo_cfg, group_cid=group_cid)
                seen_ids.add(msg_id)
                _log('poll: 选题库已推送')
            except Exception as e:
                _log(f'topic_library error: {e}')
            continue

        try:
            if _text_triggers_topic_pick(text, memo_cfg):
                _tck_p = topic_pick_content_key(text)
                _tid_p = ('topic_c:' + _tck_p) if _tck_p else ''
                _agent_dbg(
                    'H1', 'skill_router.poll', 'before_process_topic_pick',
                    msg_id=msg_id, cid=str(group_cid), tck=_tck_p,
                    topic_c_in_seen=(_tid_p in seen_ids) if _tid_p else None,
                )
            memo_ts_poll = int(msg.get('ts', 0) or 0)
            tp = process_topic_pick(
                msg_id=msg_id, text=text, context_msgs=messages,
                memo_ts=memo_ts_poll, group_cid=group_cid, config=memo_cfg)
            if tp is not False:
                if tp is None:
                    _log('poll: 选题收录 TR 暂不可写')
                else:
                    tck = topic_pick_content_key(text)
                    if tck:
                        tid = 'topic_c:' + tck
                        if tid in seen_ids:
                            seen_ids.add(msg_id)
                            continue
                        seen_ids.add(tid)
                        _recent_memo_ts[(str(group_cid), tck)] = now_ms
                    seen_ids.add(msg_id)
                    _log('poll: 选题已收录')
                continue
        except Exception as e:
            _log(f'topic_pick error: {e}')

        # check_tracker: 本人发出的引用回复 TR → 跟进任务
        _check_cfg = memo_cfg.get('check_tracker', {})
        _check_allowed = set(
            str(c).strip() for c in (_check_cfg.get('allowed_cids') or []) if str(c).strip()
        )
        _check_my_uids = (
            set(str(u).strip() for u in (memo_cfg.get('assistant_group_skill_uids') or []) if str(u).strip())
            | set(str(a).strip() for a in (memo_cfg.get('assistant_group_skill_aliases') or []) if str(a).strip())
            | {str(os.environ.get('DINGTALK_MY_UID', DEFAULT_MY_UID)).strip()}
        )
        # P2P 私聊（CID 含 ':'）依赖 CID 白名单已足够，JSAPI 路径 is_self 不可靠；群聊仍要验证发送者
        _check_cid_str = str(group_cid).strip()
        _check_is_p2p = ':' in _check_cid_str
        _check_is_self = (
            _check_is_p2p
            or msg.get('is_self') is True
            or _message_sender_identity(msg) in _check_my_uids
        )
        if (
            _check_allowed
            and _check_cid_str in _check_allowed
            and _check_is_self
            and parse_check_trigger(text)
        ):
            # 内容去重：防止 push+poll 双路径对同一消息重复创建（与 memo content_dedup_id 同源）
            _check_content_key = text[:200]
            _check_dedup_id = 'check_c:' + str(group_cid) + ':' + _check_content_key
            if _check_dedup_id in seen_ids:
                seen_ids.add(msg_id)
                continue
            seen_ids.add(_check_dedup_id)
            try:
                r = process_check(msg_id=msg_id, text=text, group_cid=group_cid, config=memo_cfg)
                seen_ids.add(msg_id)
                if r is True:
                    _log('poll: check TR -> 已创建')
                else:
                    _log('poll: check TR -> TaskReminder 不可用')
            except Exception as e:
                seen_ids.add(msg_id)
                _log(f'check error: {e}')
            continue

        if _RE_MEMO.search(text):
            if is_memo_processed(msg_id):
                seen_ids.add(msg_id)
                continue
            with _MEMO_INGEST_LOCK:
                content_key = _memo_content_key(text)
                if content_key:
                    content_dedup_id = 'memo_c:' + content_key
                    if content_dedup_id in seen_ids:
                        seen_ids.add(msg_id)
                        continue
                    seen_ids.add(content_dedup_id)
                    key = (str(group_cid), content_key)
                    if now_ms - _recent_memo_ts.get(key, 0) < _RECENT_CMD_MS:
                        seen_ids.add(msg_id)
                        continue
                    _recent_memo_ts[key] = now_ms
            try:
                memo_ts = int(msg.get('ts', 0))
                result = process_memo(
                    msg_id=msg_id, text=text,
                    context_msgs=messages, memo_ts=memo_ts,
                    group_cid=group_cid, config=memo_cfg,
                )
                if result is not None:
                    seen_ids.add(msg_id)
            except Exception as e:
                _log(f'memo error: {e}')
            continue


def _maybe_sync_tr_local(memo_cfg: dict) -> None:
    global _last_tr_sync_ms
    if not (memo_cfg or {}).get('task_reminder_base', '').strip():
        return
    now_ms = int(time.time() * 1000)
    if now_ms - _last_tr_sync_ms < _TR_SYNC_INTERVAL_MS:
        return
    _last_tr_sync_ms = now_ms
    try:
        stats = sync_tr_state_to_local_memos_wishes(memo_cfg)
        n = sum(stats.values())
        if n:
            _log(f'TR<->local sync {stats}')
    except Exception as e:
        _log(f'TR sync error: {e}')


def _resume_notify_webhook() -> str:
    """面试评价通知统一走 resume_notify。"""
    fallback = ''
    try:
        with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        fallback = str(cfg.get('resume_notify_webhook') or '').strip()
    except Exception:
        pass
    return get_webhook_url('resume_notify', fallback)


def _load_msg_templates() -> dict:
    try:
        with open(_TEMPLATE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _interview_tpl() -> dict:
    data = _load_msg_templates().get('interview_review', {})
    if isinstance(data, dict):
        return data
    return {}


def _send_notify_markdown(title: str, text: str, webhook_url: str):
    if not webhook_url:
        return
    payload = json.dumps({
        'msgtype': 'markdown',
        'markdown': {'title': title, 'text': text},
    }, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(
        webhook_url, data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=15):
            pass
    except Exception as e:
        _log(f'notify markdown webhook failed: {e}')


def _looks_like_interview_file(file_name: str) -> bool:
    n = (file_name or '').strip().lower()
    if not n or not n.endswith('.pdf'):
        return False
    return ('招聘面试' in n) or ('面试纪要' in n)


def _extract_candidate_from_filename(file_name: str) -> str:
    base = re.sub(r'\.[^.]+$', '', (file_name or '').strip())
    # 常见命名：招聘面试-张三-xxx
    m = re.search(r'招聘面试[\s\-_—]*([\u4e00-\u9fa5]{2,8})', base)
    if m:
        return m.group(1)
    m2 = re.search(r'([\u4e00-\u9fa5]{2,8})[\s\-_—]*招聘面试', base)
    if m2:
        return m2.group(1)
    return ''


def _guess_role_from_interview(file_name: str, text: str) -> str:
    s = ((file_name or '') + '\n' + (text or '')[:800]).lower()
    if '主策' in s or '主策划' in s:
        return '主策划'
    if '战斗' in s:
        return '战斗策划'
    if '系统策划' in s or ('系统' in s and '策划' in s):
        return '系统策划'
    if '应届' in s:
        return 'fresh'
    return '运营策划'


def _extract_mobile_tail(file_name: str, text: str) -> str:
    s = ((file_name or '') + '\n' + (text or '')[:1200])
    m = re.search(r'1\d{10}', s)
    if m:
        return m.group(0)[-4:]
    m2 = re.search(r'手机号[:：]?\s*(\d{4})', s)
    if m2:
        return m2.group(1)
    return ''


def _read_pdf_text(path: str) -> str:
    """面试纪要等 PDF：优先 pdfplumber，缺省时 pypdf。"""
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            return '\n'.join((p.extract_text() or '') for p in pdf.pages).strip()
    except ImportError:
        pass
    except Exception as e:
        _log(f'interview pdf read failed (pdfplumber): {e}')
        return ''
    try:
        from pypdf import PdfReader
        reader = PdfReader(path)
        return '\n'.join((p.extract_text() or '') for p in reader.pages).strip()
    except ImportError as e:
        _log(f'interview pdf read failed: no pdfplumber/pypdf ({e})')
        return ''
    except Exception as e:
        _log(f'interview pdf read failed (pypdf): {e}')
        return ''


def _build_interview_out_path(candidate: str, role: str, suffix: str = '面试评价') -> str:
    day = datetime.now().strftime('%Y-%m-%d')
    safe_candidate = re.sub(r'[\\/:*?"<>|]+', '_', (candidate or '候选人')).strip() or '候选人'
    safe_role = re.sub(r'[\\/:*?"<>|]+', '_', (role or '岗位')).strip() or '岗位'
    out_dir = os.path.join(_INTERVIEW_OUT_DIR, f'{day}_{safe_role}')
    os.makedirs(out_dir, exist_ok=True)
    return os.path.join(out_dir, f'{safe_candidate}-{suffix}.md')


def _run_palace_interview_eval(note_text: str, role: str, candidate: str, mobile_tail: str) -> tuple:
    if not os.path.isfile(_PALACE_RUN_PY):
        return False, f'Palace run.py 不存在: {_PALACE_RUN_PY}', ''
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', encoding='utf-8', delete=False) as tmp:
        tmp.write(note_text or '')
        tmp_path = tmp.name
    output_path = _build_interview_out_path(candidate, role, suffix='面试评价')
    doc_type = f'role:{role};mode:evaluation;candidate:{candidate};mobile_tail:{mobile_tail}'
    cmd = [
        'py', _PALACE_RUN_PY,
        '--scenario', 'interview_checklist',
        '--input-file', tmp_path,
        '--doc-type', doc_type,
        '--format', 'markdown',
        '--output', output_path,
    ]
    try:
        p = subprocess.run(
            cmd,
            cwd=os.path.dirname(_PALACE_RUN_PY),
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=180,
        )
        if p.returncode != 0:
            return False, (p.stderr or p.stdout or 'Palace 调用失败').strip(), output_path
        if not os.path.exists(output_path):
            return False, 'Palace 未产出评价文件', output_path
        return True, 'ok', output_path
    except Exception as e:
        return False, str(e), output_path
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def _set_pending_interview_bind(group_cid: str, payload: dict):
    with _INTERVIEW_PENDING_LOCK:
        _INTERVIEW_PENDING_BY_CID[str(group_cid)] = payload


def _pop_pending_interview_bind(group_cid: str) -> dict | None:
    with _INTERVIEW_PENDING_LOCK:
        item = _INTERVIEW_PENDING_BY_CID.pop(str(group_cid), None)
    if not item:
        return None
    now_ms = int(time.time() * 1000)
    if now_ms - int(item.get('created_ms', 0)) > _INTERVIEW_PENDING_TTL_MS:
        return None
    return item


def _cleanup_pending_interview_bind():
    now_ms = int(time.time() * 1000)
    with _INTERVIEW_PENDING_LOCK:
        dead = [
            k for k, v in _INTERVIEW_PENDING_BY_CID.items()
            if now_ms - int(v.get('created_ms', 0)) > _INTERVIEW_PENDING_TTL_MS
        ]
        for k in dead:
            _INTERVIEW_PENDING_BY_CID.pop(k, None)


def _notify_interview_bind_needed(file_name: str):
    tpl = _interview_tpl()
    title = tpl.get('ask_bind_title') or '❓ 面试纪要待绑定候选人'
    text_tpl = tpl.get('ask_bind_text') or (
        "检测到招聘面试纪要：{file_name}\n\n"
        "未识别到候选人姓名，请回复：**绑定候选人 张三**\n\n"
        "###### ※ 小秘书提醒"
    )
    text = text_tpl.format(file_name=file_name)
    _send_notify_markdown(title, text, _resume_notify_webhook())


def _notify_interview_bound(candidate: str):
    tpl = _interview_tpl()
    title = tpl.get('bind_ok_title') or '✅ 候选人已绑定'
    text_tpl = tpl.get('bind_ok_text') or (
        "已绑定候选人：**{candidate}**，开始生成面试评价。\n\n"
        "###### ※ 小秘书提醒"
    )
    _send_notify_markdown(title, text_tpl.format(candidate=candidate), _resume_notify_webhook())


def _notify_interview_no_pending():
    tpl = _interview_tpl()
    title = tpl.get('bind_fail_title') or '⚠️ 绑定失败'
    text = tpl.get('bind_fail_text') or (
        "当前没有待绑定的招聘面试任务，请先下载“招聘面试”文件。\n\n"
        "###### ※ 小秘书提醒"
    )
    _send_notify_markdown(title, text, _resume_notify_webhook())


def _notify_interview_result(candidate: str, ok: bool, detail: str, output_path: str):
    tpl = _interview_tpl()
    if ok:
        title = tpl.get('result_ok_title') or '✅ 面试评价已生成'
        text_tpl = tpl.get('result_ok_text') or (
            "候选人：**{candidate}**\n"
            "评价文件：`{output_path}`\n\n"
            "###### ※ 小秘书提醒"
        )
        text = text_tpl.format(candidate=candidate, output_path=output_path)
    else:
        title = tpl.get('result_fail_title') or '❌ 面试评价生成失败'
        text_tpl = tpl.get('result_fail_text') or (
            "候选人：**{candidate}**\n"
            "原因：{detail}\n\n"
            "###### ※ 小秘书提醒"
        )
        text = text_tpl.format(candidate=candidate, detail=detail)
    _send_notify_markdown(title, text, _resume_notify_webhook())


def _handle_interview_file_message(msg: dict, group_cid: str, seen_ids: set, router_start_ms: int = 0) -> bool:
    """返回 True 表示该消息已处理（会入 seen_ids），False 表示继续走普通流程。"""
    if int(msg.get('content_type') or 0) not in _RESUME_FILE_CONTENT_TYPES:
        return False
    if _skip_msg_before_router_start(msg, router_start_ms):
        return True
    msg_id, file_name, file_path_hint = _extract_file_info(msg)
    if not msg_id:
        msg_id = _make_msg_id(msg)
    if not msg_id or msg_id in seen_ids:
        return True
    if not _looks_like_interview_file(file_name):
        return False
    local_path = _resume_resolve_local_pdf_path(file_name or '', file_path_hint or '')
    if not local_path:
        # 手动下载前不标记 seen，允许后续轮询继续命中
        return True
    note_text = _read_pdf_text(local_path)
    if len(note_text) < 30:
        _notify_interview_result('候选人', False, '面试纪要解析失败或内容过短', '')
        seen_ids.add(msg_id)
        return True
    candidate = _extract_candidate_from_filename(file_name)
    role = _guess_role_from_interview(file_name, note_text)
    mobile_tail = _extract_mobile_tail(file_name, note_text)
    if not candidate:
        _set_pending_interview_bind(str(group_cid), {
            'msg_id': msg_id,
            'file_name': file_name,
            'note_text': note_text,
            'role': role,
            'mobile_tail': mobile_tail,
            'created_ms': int(time.time() * 1000),
        })
        _notify_interview_bind_needed(file_name or '招聘面试文件')
        seen_ids.add(msg_id)
        return True
    ok, detail, output_path = _run_palace_interview_eval(note_text, role, candidate, mobile_tail)
    _notify_interview_result(candidate, ok, detail, output_path)
    seen_ids.add(msg_id)
    return True


def _try_bind_candidate_command(text: str, group_cid: str, seen_ids: set, msg_id: str) -> bool:
    m = re.match(r'^\s*绑定候选人\s+(.+?)\s*$', text or '')
    if not m:
        return False
    candidate = m.group(1).strip()
    if not re.fullmatch(r'[\u4e00-\u9fa5]{2,8}', candidate):
        _notify_interview_result('候选人', False, '姓名格式不合法，请用2-8位中文姓名', '')
        seen_ids.add(msg_id)
        return True
    item = _pop_pending_interview_bind(str(group_cid))
    if not item:
        _notify_interview_no_pending()
        seen_ids.add(msg_id)
        return True
    _notify_interview_bound(candidate)
    ok, detail, output_path = _run_palace_interview_eval(
        item.get('note_text', ''),
        item.get('role', '运营策划'),
        candidate,
        item.get('mobile_tail', ''),
    )
    _notify_interview_result(candidate, ok, detail, output_path)
    seen_ids.add(msg_id)
    return True


def _send_notify(text: str, webhook_url: str):
    """轻量 webhook 通知（用于路由层的边界情况提示）"""
    if not webhook_url:
        return
    payload = json.dumps({
        'msgtype': 'text',
        'text': {'content': text},
    }).encode('utf-8')
    req = urllib.request.Request(
        webhook_url, data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=15):
            pass
    except Exception as e:
        _log(f'notify webhook failed: {e}')


def _poll_doc_review_once(group_cid: str, doc_cfg: dict, seen_ids: set,
                          router_start_ms: int = 0, memo_cfg: dict = None):
    """轮询助理通知群，检测'预审'指令，回溯找最近的文档链接后启动预审。

    触发条件：用户先发文档链接（消息A），再发'预审'（消息B）。
    以消息B的 msg_id 做去重 key。
    router_start_ms：仅处理不早于本次 router 启动的预审指令（重启后不追溯）。
    """
    messages = _fetch_memo_messages(group_cid, max_age_ms=_DOC_REVIEW_MAX_AGE_MS)
    now_ms = int(time.time() * 1000)
    webhook_url = doc_cfg.get('webhook_url', '')

    msgs_by_ts = sorted(messages, key=lambda m: int(m.get('ts', 0)))

    for i, msg in enumerate(msgs_by_ts):
        text = _normalize_command_text(_extract_message_text(msg))
        if not text:
            continue

        if _skip_msg_before_router_start(msg, router_start_ms):
            continue

        if _is_stale_command_msg(msg, now_ms, _PRECHECK_CMD_MAX_AGE_MS):
            continue

        msg_id = _make_msg_id(msg)
        if not msg_id or msg_id in seen_ids:
            continue

        _mc = memo_cfg if memo_cfg is not None else {}
        if not _assistant_group_skill_sender_allowed(_mc, group_cid, _message_sender_identity(msg)):
            seen_ids.add(msg_id)
            continue

        if _RE_PRECHECK_STOP.match(text):
            if try_user_stop_doc_review(webhook_url):
                _log('poll: 预审已按用户指令叫停')
            else:
                send_no_active_doc_review_stop_reply(webhook_url)
            seen_ids.add(msg_id)
            continue

        _poll_is_precheck, _poll_force_precheck = _precheck_command_flags(text)
        if not _poll_is_precheck:
            continue

        if is_doc_review_processed(msg_id):
            seen_ids.add(msg_id)
            continue

        doc_url = None
        for j in range(i - 1, -1, -1):
            prev_msg = msgs_by_ts[j]
            url = extract_doc_url_from_message(prev_msg)
            if url:
                doc_url = url
                break

        if not doc_url:
            _log('收到预审指令，但未找到前序文档链接')
            _send_notify(get_doc_review_no_link_message(), webhook_url)
            seen_ids.add(msg_id)
            continue

        sender_uid = str(msg.get('uid', ''))
        _log(f'预审指令触发: {doc_url[:60]}... (uid={sender_uid})')

        try:
            result = process_doc_review(
                msg_id=msg_id,
                url=doc_url,
                sender_uid=sender_uid,
                msg_text=text,
                config=doc_cfg,
                force_bypass_recent_window=_poll_force_precheck,
            )
            seen_ids.add(msg_id)
            if result:
                _log(f'文档预审完成: {doc_url[:40]}...')
            else:
                _log(f'文档预审失败，已通知: {doc_url[:40]}...')
        except Exception as e:
            _log(f'doc_review error: {e}')
            seen_ids.add(msg_id)


class SkillRouter:
    def __init__(self):
        self._thread = None
        self._running = False
        self._seen_ids: set = set()
        self._memo_seen_ids: set = set()
        self._doc_seen_ids: set = set()
        # 在 start() 首行赋值；轮询与推送均不处理早于此时刻的消息
        self._start_ts: int = 0
        self._memo_poll_heartbeat_ms: int = 0

    def start(self, memo_event_queue=None):
        """启动后台轮询线程（由 daemon.py 调用）。

        memo_event_queue 非空时额外消费 Frida 推送（桌面会话内消息可立刻处理）。
        手机发的消息通常不会进该队列，仍依赖下方周期性的 _poll_memo_once(/fetch)，故**有队列时也继续轮询**。
        """
        self._start_ts = int(time.time() * 1000)
        init_db()
        _log('DB initialized')

        cfg = _load_config()
        recruit_cids = cfg['recruit_cids']
        cid_names    = cfg.get('cid_names', {})
        notify_cid   = cfg['notify_cid']
        memo_cfg     = cfg.get('memo_tracker', {})
        doc_review_cfg = cfg.get('doc_review', {})
        resume_name_filter = cfg.get('resume_name_filter', {})
        resume_msg_max_age_ms = int(
            cfg.get('resume_msg_max_age_ms') or DEFAULT_RESUME_MSG_MAX_AGE_MS)
        resume_bypass_fn = cfg.get('resume_bypass_filename_gate_cids') or frozenset()

        has_resume     = bool(recruit_cids)
        _allowed = _memo_allowed_cids(memo_cfg)
        has_memo       = bool(_allowed)
        has_doc_review = bool(doc_review_cfg.get('group_cid'))

        if has_resume:
            _h = resume_msg_max_age_ms / (3600 * 1000)
            _log(
                f'resume watch: {recruit_cids}, notify: {notify_cid or "source group"}, '
                f'msg max age: {_h:g}h'
            )
            if resume_bypass_fn:
                _log(
                    'resume filename gate bypass (blocks_only): '
                    f'{sorted(resume_bypass_fn)}'
                )
        if has_memo:
            _col = [x for x in (memo_cfg.get('colleague_skill_cids') or []) if str(x).strip()]
            _log(
                f'memo watch: assistant={memo_cfg.get("group_cid") or "?"} '
                f'colleague_whitelist={_col or "(empty)"}'
                + (' (push+poll)' if memo_event_queue else '')
            )
            _log(
                '说明: daemon 里「群聊←/→接收」是 Monitor 日志；备忘是否处理要看本线程每 '
                f'{POLL_INTERVAL}s 的 POST /fetch，无新指令时通常不再打日志。'
            )
            _log(
                '可选: 环境变量 SKILL_ROUTER_MEMO_POLL_TRACE=1 每次备忘拉取后打一行条数。'
            )
        if has_doc_review:
            _log(f'doc_review watch: {doc_review_cfg["group_cid"]}')
        if not has_resume and not has_memo and not has_doc_review:
            _log('no skills configured, router idle')
            return

        _log(f'poll interval: {POLL_INTERVAL}s')
        self._running = True
        self._memo_queue = memo_event_queue

        self._thread = threading.Thread(
            target=self._loop,
            args=(
                recruit_cids, cid_names, notify_cid, memo_cfg, doc_review_cfg,
                resume_name_filter, resume_msg_max_age_ms, resume_bypass_fn,
            ),
            daemon=True,
        )
        self._thread.start()

        if memo_event_queue and _allowed:
            push_thread = threading.Thread(
                target=self._memo_push_loop,
                args=(memo_cfg, doc_review_cfg),
                daemon=True,
            )
            push_thread.start()
            _log('memo push consumer started')

    def stop(self):
        self._running = False

    def _memo_push_loop(self, memo_cfg: dict, doc_review_cfg: dict = None):
        """消费 daemon 推送的消息；cid 须在助理群或 colleague_skill_cids 白名单内。"""
        import queue as queue_module
        q = getattr(self, '_memo_queue', None)
        if not q:
            return
        while self._running:
            try:
                record = q.get(timeout=1.0)
            except queue_module.Empty:
                continue
            except Exception:
                break
            try:
                _dispatch_one_message(
                    record, memo_cfg, self._memo_seen_ids,
                    doc_review_cfg=doc_review_cfg, doc_seen_ids=self._doc_seen_ids,
                    router_start_ms=self._start_ts,
                )
            except Exception as e:
                _log(f'memo push dispatch error: {e}')

    def _loop(self, recruit_cids: list, cid_names: dict,
              notify_cid: str, memo_cfg: dict, doc_review_cfg: dict = None,
              resume_name_filter: dict | None = None,
              resume_msg_max_age_ms: int | None = None,
              resume_bypass_filename_gate_cids: frozenset | None = None):
        while self._running:
            for cid in recruit_cids:
                source_name = cid_names.get(cid, '')
                try:
                    n = _poll_once(
                        cid, self._seen_ids, source_name=source_name,
                        resume_name_filter=resume_name_filter,
                        resume_msg_max_age_ms=resume_msg_max_age_ms,
                        resume_bypass_filename_gate_cids=resume_bypass_filename_gate_cids,
                    )
                    if n:
                        _log(f'[{source_name or cid}] processed {n} resumes')
                except Exception as e:
                    _log(f'resume poll [{source_name or cid}] error: {e}')

            # 有 Frida 推送队列时也必须轮询：手机/其他端发的消息往往只经 JSAPI 历史出现，不会入队
            _memo_cids = sorted(_memo_allowed_cids(memo_cfg))
            for _poll_cid in _memo_cids:
                try:
                    _poll_memo_once(
                        _poll_cid, memo_cfg, self._memo_seen_ids,
                        router_start_ms=self._start_ts,
                    )
                except Exception as e:
                    _log(f'memo poll [{_poll_cid}] error: {e}')
            if _memo_cids:
                try:
                    _hb_ms = int(os.environ.get('SKILL_ROUTER_POLL_HEARTBEAT_MS', '45000'))
                except ValueError:
                    _hb_ms = 45000
                if _hb_ms > 0:
                    _now_ms = int(time.time() * 1000)
                    if _now_ms - self._memo_poll_heartbeat_ms >= _hb_ms:
                        self._memo_poll_heartbeat_ms = _now_ms
                        _log(
                            'memo /fetch poll alive: cids=%s (每 %ds 一轮；'
                            '仅心跳日志；设 SKILL_ROUTER_POLL_HEARTBEAT_MS=0 可关闭)'
                            % (_memo_cids, POLL_INTERVAL)
                        )
            if _memo_cids:
                _maybe_sync_tr_local(memo_cfg)

            if doc_review_cfg and doc_review_cfg.get('group_cid'):
                try:
                    _poll_doc_review_once(
                        doc_review_cfg['group_cid'],
                        doc_review_cfg, self._doc_seen_ids,
                        router_start_ms=self._start_ts,
                        memo_cfg=memo_cfg,
                    )
                except Exception as e:
                    _log(f'doc_review poll error: {e}')

            time.sleep(POLL_INTERVAL)


# 单例
_router = SkillRouter()


def start_router(memo_event_queue=None):
    """供 daemon.py 调用的入口。memo_event_queue 非空时增加推送消费；备忘仍周期 /fetch 轮询（含手机消息）。"""
    _router.start(memo_event_queue)


if __name__ == '__main__':
    # 直接运行做单次测试
    init_db()
    _cfg = _load_config()
    recruit_cids = _cfg['recruit_cids']
    _ram = int(_cfg.get('resume_msg_max_age_ms') or DEFAULT_RESUME_MSG_MAX_AGE_MS)
    _bypass = _cfg.get('resume_bypass_filename_gate_cids') or frozenset()
    print('招聘群:', recruit_cids)
    seen: set = set()
    _rf = _cfg.get('resume_name_filter', {})
    for cid in recruit_cids:
        n = _poll_once(
            cid, seen, resume_name_filter=_rf, resume_msg_max_age_ms=_ram,
            resume_bypass_filename_gate_cids=_bypass,
        )
        print(f'群 {cid} 处理 {n} 份')
