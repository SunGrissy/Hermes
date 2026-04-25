@echo off
cd /d D:\MyAgents\silicon-legion
py -m uvicorn main:app --host 0.0.0.0 --port 8299 --reload
