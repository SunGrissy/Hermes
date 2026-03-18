# -*- coding: utf-8 -*-
"""CLI wrapper for DingTalkSender — called by MCP tool"""
import argparse
import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from lib.sender import DingTalkSender


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cid', required=True, help='会话 CID')
    parser.add_argument('--msg', required=True, help='消息文本')
    parser.add_argument('--port', type=int, default=18899, help='Beacon 端口')
    args = parser.parse_args()

    sender = DingTalkSender(beacon_port=args.port)
    try:
        cid = args.cid
        if ':' in cid:
            parts = cid.split(':')
            result = sender.send_text(parts[1], args.msg)
        else:
            result = sender.send_to_group(cid, args.msg)

        print(json.dumps(result, ensure_ascii=False))
        sys.exit(0 if result.get('success') else 1)
    finally:
        sender.close()


if __name__ == '__main__':
    main()
