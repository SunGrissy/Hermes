# -*- coding: utf-8 -*-
"""一次性触发文档预审，结果推送到 digest_config doc_review.webhook（助理通知群）。

用法（在 dingtalk-desktop 目录）:
  py run_doc_review_once.py <钉钉文档 URL>

依赖: 本机 daemon 已 attach 钉钉；Palace Web 可发布（默认 127.0.0.1:8300）。
"""
from __future__ import annotations

import json
import os
import sys
import time

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from lib.utils import get_webhook_url  # noqa: E402
from skills.doc_review import process_doc_review  # noqa: E402


def _load_doc_review_cfg() -> dict:
    path = os.path.join(_ROOT, 'digest_config.json')
    with open(path, encoding='utf-8') as f:
        cfg = json.load(f)
    doc = dict(cfg.get('doc_review') or {})
    if not doc.get('group_cid'):
        doc['group_cid'] = cfg.get('notify_target') or ''
    doc['webhook_url'] = get_webhook_url(
        'doc_review', doc.get('webhook_url') or cfg.get('webhook_url') or ''
    )
    return doc


def main() -> int:
    url = (sys.argv[1] if len(sys.argv) > 1 else '').strip()
    if not url:
        print('usage: py run_doc_review_once.py <document url>')
        return 2
    doc = _load_doc_review_cfg()
    if not doc.get('webhook_url'):
        print('error: doc_review webhook_url empty')
        return 1
    msg_id = f'manual_{int(time.time() * 1000)}'
    print(f'start doc_review msg_id={msg_id}', flush=True)
    ok = process_doc_review(
        msg_id,
        url,
        sender_uid='agent_manual',
        msg_text='预审',
        config=doc,
        force_bypass_recent_window=True,
    )
    print(f'finished ok={ok}', flush=True)
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
