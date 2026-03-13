#!/bin/bash
cd "$(dirname "$0")"
echo "Starting MD Reader..."
echo "http://localhost:8899"
echo ""
python3 -m uvicorn server:app --host 127.0.0.1 --port 8899
