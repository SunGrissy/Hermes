---
name: multi-service-orchestration
description: Service registry and orchestration guide for MyAgents workspace. Covers port assignments, startup commands, dependencies, health checks, and troubleshooting for all projects. Use when starting services, debugging cross-service issues, or setting up development environments.
---

# MyAgents 多服务编排

MyAgents 工作空间包含多个独立服务。本 Skill 记录各项目的端口、入口、依赖和健康检查，用于启动、调试和跨服务问题排查。

## 服务清单

| 项目 | 端口 | 入口 | 技术栈 | 启动脚本 |
|------|------|------|--------|----------|
| **PmSystemApp** | 后端 8000 | `backend/main.py` + `index.html` | FastAPI + 原生 JS | `quick_start.bat` |
| **PerformEval** | 8112 | `backend/main.py` + `index.html` | FastAPI + 原生 JS | `run.bat` |
| **CCI-ScoreSystem（Streamlit）** | 8501 (默认) | `app.py` | Streamlit | `启动.bat` |
| **CCI-ScoreSystem（TD 报表 API）** | 8502 (默认) | `api.app:app` | FastAPI | `run_api.bat` |
| **TaskReminderApp** | 8000 | `server.py` + `TaskReminder.html` | FastAPI | `python server.py` |
| **FileCleanerTool** | 无（GUI） | `gui.py` | Python + customtkinter | `run.bat` |
| **TeamScore** | 无（脚本） | 各子目录 `.py` | Python 脚本集 | 手动运行 |
| **dingtalk-desktop** | 19200 (daemon) + 18899 (beacon) | `daemon.py` | Python + Frida + msgpack | `py daemon.py` |

## 端口冲突警告

PmSystemApp (8000) 与 TaskReminderApp (8000) 端口冲突，不能同时启动。解决方案：
- TaskReminderApp 改用其他端口（如 8001）
- 或在 `server.py` 的 uvicorn.run 中指定不同端口

## 健康检查

| 项目 | 端点 | 预期响应 |
|------|------|----------|
| PmSystemApp | `GET /api/health` | 200 |
| PmSystemApp | `GET /api/version` | 版本信息 |
| PerformEval | `GET /api/health` | 200 |
| PerformEval | `GET /api/version` | 版本信息 |
| CCI-ScoreSystem（Streamlit） | 无 | 访问首页 200 |
| CCI-ScoreSystem（TD 报表 API） | `GET /api/health` | `{"status":"ok","app":"cci-td-report-api",...}` |
| CCI-ScoreSystem（TD 报表 API） | `GET /api/version` | 版本信息 + 关键文件 mtime |
| TaskReminderApp | 无 | 访问首页 200 |
| dingtalk-desktop | `GET /api/health` | `{"status":"ok","app":"dingtalk-daemon"}` |
| dingtalk-desktop | `GET /api/version` | 版本信息 + 文件修改时间 |

## 依赖清单

### PmSystemApp (`pm-system/backend/requirements.txt`)
fastapi, uvicorn[standard], sqlalchemy, pydantic, pydantic-settings, email-validator, httpx, python-dotenv, python-jose[cryptography], passlib[bcrypt]>=1.7.4, python-multipart, bcrypt<4.0.0

### PerformEval (`performeval/requirements.txt`)
fastapi>=0.104.0, uvicorn[standard]>=0.24.0, sqlalchemy>=2.0.0, pydantic>=2.5.0, pydantic-settings>=2.1.0, aiosqlite>=0.19.0, python-multipart>=0.0.6, openpyxl>=3.1.0

### CCI-ScoreSystem (`cci_system/requirements.txt`)
streamlit, pandas, matplotlib, openpyxl, xlsxwriter, fastapi, uvicorn, httpx（与 TestClient 兼容见文件内 httpx 上限）

### FileCleanerTool (`FileCleanerTool/requirements.txt`)
customtkinter, packaging

### dingtalk-desktop (`dingtalk-desktop/requirements.txt`)
frida, msgpack, winotify

## 启动单个服务

```bash
# PmSystemApp
cd pm-system && quick_start.bat
# 或手动：cd backend && python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# PerformEval
cd performeval && run.bat
# 或手动：cd backend && python -m uvicorn main:app --host 0.0.0.0 --port 8112 --reload

# CCI-ScoreSystem（Streamlit 工具）
cd cci_system && streamlit run app.py --server.headless=true

# CCI-ScoreSystem（TD 报表 API，契约见 cci_system/TD_CCI_REPORT_API.md）
cd cci_system && py -m uvicorn api.app:app --host 0.0.0.0 --port 8502

# TaskReminderApp
cd task_reminder && python server.py

# dingtalk-desktop (Frida daemon, requires DingTalk running)
cd dingtalk-desktop && py daemon.py
```

## 全局启动脚本

`start_army.bat` 位于工作空间根目录。当前配置可能引用了不存在的子模块目录（llm-plotter, align-flow, central-console），启动前需确认。

## 新 Worktree 环境搭建

在 Git Worktree 中创建新工作目录后，依赖不会自动复制。需要：

```bash
# Python 项目
cd <worktree>/backend
pip install -r requirements.txt

# Streamlit 项目
cd <worktree>
pip install -r requirements.txt
```

## 排障清单

1. **端口占用** → `netstat -ano | findstr :<port>` 查找占用进程
2. **后端崩溃** → 检查 Windows GBK 编码问题（print 含 emoji 会崩溃）
3. **前端连不上后端** → 检查 CORS 配置和 `location.hostname` 动态地址
4. **数据不同步** → 检查 `localStorage` 中 `pm-sync-base` 和 `pm-sync-meta` 状态
5. **服务启动后无响应** → 确认 `--host 0.0.0.0`（非 127.0.0.1）以支持局域网访问
