# -*- coding: utf-8 -*-
"""
从 data/dingtalk/contacts.json 查找联系人 CID

Usage:
    python lookup_contact.py <name>    → 搜索联系人，输出 JSON
    python lookup_contact.py --list    → 列出所有联系人
"""
import os
import sys
import json

sys.stdout.reconfigure(encoding='utf-8')

def _find_data_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):
        if os.path.isdir(os.path.join(here, 'src')):
            return os.path.join(here, 'data', 'dingtalk')
        here = os.path.dirname(here)
    return os.path.join(os.getcwd(), 'data', 'dingtalk')

DATA_DIR = _find_data_dir()
CONTACTS_FILE = os.path.join(DATA_DIR, 'contacts.json')


def _load_contacts():
    if not os.path.exists(CONTACTS_FILE):
        return {}
    with open(CONTACTS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def lookup(name):
    contacts = _load_contacts()
    kw = name.lower()
    return [
        {'cid': c['cid'], 'name': c.get('name', ''), 'type': c.get('type', ''),
         'uid': c.get('uid', '')}
        for c in contacts.values()
        if kw in (c.get('name') or '').lower()
           or kw in c.get('cid', '').lower()
           or kw in (c.get('uid') or '').lower()
    ]


def list_all():
    contacts = _load_contacts()
    return [
        {'cid': c['cid'], 'name': c.get('name', ''), 'type': c.get('type', ''),
         'uid': c.get('uid', '')}
        for c in contacts.values()
    ]


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(json.dumps({'error': 'Usage: lookup_contact.py <name|--list>'}, ensure_ascii=False))
        sys.exit(1)

    if sys.argv[1] == '--list':
        print(json.dumps(list_all(), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(lookup(sys.argv[1]), ensure_ascii=False, indent=2))
