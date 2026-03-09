#!/bin/bash
cd "$(dirname "$0")"
echo "Starting MD Reader..."
echo "http://localhost:8899"
echo ""
python3 server.py
