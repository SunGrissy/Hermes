# 策划周计划工作台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 PmSystem 内交付「策划周计划工作台」MVP：后端 `WorkItem` 持久化 + `/api/planner/*` API；前端 `#planner` 三列看板 + 弹窗编辑（**无拖拽**）；与 Feature / 需求池条目只读关联与跳转。

**Architecture:** 新增 SQLAlchemy 表 `planner_work_items`，独立 FastAPI 路由模块 `planner.py`（前缀 `/api/planner`），沿用全局 `get_current_user` 与 `ApiResponse` 包装。`version_delivery` 条目的阶段展示在列表/详情组装时 **JOIN 或二次查询** `features` 表只读取 `stage`，**永不** `UPDATE features`。`linked_pool_id` 在实现中存 **pool_items.id**（需求池**条目**），模型字段名采用 `linked_pool_item_id` 并在合并 Spec 时把 §3.1 字段名同步为该名（语义与 Spec「关联需求池条目」一致）。

**Tech Stack:** FastAPI、SQLAlchemy、SQLite（`gamedev_pm.db`）、Pydantic v2、`Base.metadata.create_all` 兜底、原生 JS（`index.html` + 独立 `planner-workbench.js`）、`pytest` + `httpx.AsyncClient`/`TestClient`（本计划新增测试依赖）。

---

## 文件结构总览（创建 / 修改）

| 路径 | 职责 |
|------|------|
| `pm-system/backend/requirements.txt` | 增加 `pytest` |
| `pm-system/backend/pytest.ini` | `testpaths=tests`，可选 `asyncio_mode=auto`（若用异步客户端） |
| `pm-system/backend/tests/conftest.py` | 内存 SQLite、`get_db` override、`get_settings` cache_clear、`dev_mode` 测试夹具 |
| `pm-system/backend/tests/test_planner_api.py` | Planner API 契约测试 |
| `pm-system/backend/app/models/__init__.py` | 追加 `WorkItem` ORM |
| `pm-system/backend/app/schemas/__init__.py`（或新建 `schemas/planner.py` 再导出） | `WorkItemCreate` / `WorkItemUpdate` / `WorkItemResponse` |
| `pm-system/backend/app/routers/planner.py` | CRUD、筛选、`from-feature`、`from-pool`、`weekly-summary`、校验 |
| `pm-system/backend/main.py` | `include_router(planner.router)`；`_KEY_FILES` 可选列入新文件供版本追踪 |
| `pm-system/index.html` | 顶栏入口 + `script` 引入 |
| `pm-system/ui/components/planner-workbench.js` | 看板 + 弹窗 + `data-service` 风格 API 调用 |
| `pm-system/core/data-service.js`（若已有统一 API 封装） | 增加 `planner*` 方法；若无则组件内 `fetch` + 与现有 `pm_config`/base URL 对齐 |

---

### Task 1: 测试基建与首个失败用例

**Files:**

- Modify: `pm-system/backend/requirements.txt`
- Create: `pm-system/backend/pytest.ini`
- Create: `pm-system/backend/tests/conftest.py`
- Create: `pm-system/backend/tests/test_planner_api.py`

- [ ] **Step 1: 在 `requirements.txt` 末尾增加一行**

```text
pytest>=8.0.0
```

- [ ] **Step 2: 写入 `pytest.ini`**

```ini
[pytest]
testpaths = tests
pythonpath = .
```

- [ ] **Step 3: 写入 `conftest.py`**（内存库 + 覆盖 `get_db`；每次测试前 `get_settings.cache_clear()`）

```python
import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.config import get_settings


@pytest.fixture()
def db_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(db_engine):
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def app_client(db_engine, db_session, monkeypatch):
    monkeypatch.setenv("DEV_MODE", "true")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.dev_mode is True

    from main import app  # noqa: WPS433 — FastAPI 实例在 backend/main.py；cwd 须为 backend/

    def _override_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_db

    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()
    get_settings.cache_clear()
```

**注意：** `pytest` 须在 **`pm-system/backend`** 为当前目录下运行（与 `pythonpath = .` 一致），以便 `from main import app` 解析到 `main.py`。

- [ ] **Step 4: 写入失败测试**（路由尚未注册时应 404）

```python
def test_planner_items_route_missing(app_client):
    r = app_client.get("/api/planner/items")
    assert r.status_code == 404
```

- [ ] **Step 5: 运行 pytest**

在 `pm-system/backend` 目录：

```powershell
cd "d:\MyAgents\pm-system\backend"
py -m pytest tests/test_planner_api.py::test_planner_items_route_missing -v
```

**期望：** `404` 时本步通过；若应用已挂载占位路由则改为断言 `200` 并调整后续任务（以当时代码为准）。

- [ ] **Step 6: Commit**（仅当用户口令要求提交时执行；下同）

```powershell
git add pm-system/backend/requirements.txt pm-system/backend/pytest.ini pm-system/backend/tests/conftest.py pm-system/backend/tests/test_planner_api.py
git commit -m "test(pm-system): add pytest scaffold for planner API"
```

---

### Task 2: `WorkItem` ORM

**Files:**

- Modify: `pm-system/backend/app/models/__init__.py`

- [ ] **Step 1: 在 `models/__init__.py` 追加模型**（与现有 `Column`/`ForeignKey` 风格一致）

```python
class WorkItem(Base):
    """制作人周计划条目（策划周计划工作台）。"""
    __tablename__ = "planner_work_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(500), nullable=False)
    category = Column(String(50), nullable=False)
    assignee = Column(String(100), nullable=True)
    stage = Column(String(100), nullable=True)
    target_week = Column(String(12), nullable=True)  # YYYY-Www
    priority = Column(String(10), nullable=False, default="P2")
    note = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="active")
    linked_feature_id = Column(String(50), ForeignKey("features.id", ondelete="SET NULL"), nullable=True)
    linked_pool_item_id = Column(String(50), ForeignKey("pool_items.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
```

- [ ] **Step 2: 语法检查**

```powershell
cd "d:\MyAgents\pm-system\backend"
py -c "import ast; ast.parse(open(r'app/models/__init__.py', encoding='utf-8').read()); print('OK')"
```

**期望：** 输出 `OK`。

- [ ] **Step 3: Commit**

```bash
git add pm-system/backend/app/models/__init__.py
git commit -m "feat(pm-system): add WorkItem model for planner workbench"
```

---

### Task 3: ISO 周校验工具（纯函数，无 FastAPI）

**Files:**

- Create: `pm-system/backend/app/services/planner_week.py`

- [ ] **Step 1: 写入模块**

```python
from __future__ import annotations

import re
from datetime import date


_ISO_WEEK_RE = re.compile(r"^(\d{4})-W(\d{2})$")


def is_valid_iso_week(value: str | None) -> bool:
    if value is None or value == "":
        return True
    m = _ISO_WEEK_RE.match(value)
    if not m:
        return False
    year, week = int(m.group(1)), int(m.group(2))
    try:
        date.fromisocalendar(year, week, 1)
    except ValueError:
        return False
    return True
```

- [ ] **Step 2: 在同文件追加测试用**（或 `tests/test_planner_week.py`）— 下面为 `tests/test_planner_week.py` 内容

```python
import pytest
from app.services.planner_week import is_valid_iso_week


@pytest.mark.parametrize(
    "s,ok",
    [
        ("2026-W17", True),
        ("2026-W00", False),
        ("2026-W54", False),
        ("bad", False),
        ("", True),
        (None, True),
    ],
)
def test_iso_week(s, ok):
    assert is_valid_iso_week(s) is ok
```

- [ ] **Step 3: 运行**

```powershell
py -m pytest tests/test_planner_week.py -v
```

**期望：** 全部 PASS。

- [ ] **Step 4: Commit**

```bash
git add pm-system/backend/app/services/planner_week.py pm-system/backend/tests/test_planner_week.py
git commit -m "feat(pm-system): ISO week validator for planner target_week"
```

---

### Task 4: Pydantic Schemas

**Files:**

- Modify: `pm-system/backend/app/schemas/__init__.py`（或新建 `schemas/planner.py` 并在 `__init__.py` import）

- [ ] **Step 1: 定义模型**（与现有 `CamelModel` / `ApiResponse` 一致）

```python
from typing import Optional, Literal
from pydantic import Field, field_validator
from app.services.planner_week import is_valid_iso_week


WorkItemCategory = Literal[
    "pre_design",
    "version_delivery",
    "data_analysis",
    "ops_maintenance",
    "tool_automation",
    "learning",
]
WorkItemStatus = Literal["active", "done", "parked", "cancelled"]
WorkItemPriority = Literal["P0", "P1", "P2"]


class WorkItemBase(CamelModel):
    title: str = Field(..., max_length=500)
    category: WorkItemCategory
    assignee: Optional[str] = None
    stage: Optional[str] = None
    target_week: Optional[str] = None
    priority: WorkItemPriority = "P2"
    note: Optional[str] = None
    status: WorkItemStatus = "active"
    linked_feature_id: Optional[str] = None
    linked_pool_item_id: Optional[str] = None

    @field_validator("target_week")
    @classmethod
    def week_ok(cls, v: Optional[str]) -> Optional[str]:
        if not is_valid_iso_week(v):
            raise ValueError("invalid target_week")
        return v


class WorkItemCreate(WorkItemBase):
    pass


class WorkItemUpdate(CamelModel):
    title: Optional[str] = Field(None, max_length=500)
    category: Optional[WorkItemCategory] = None
    assignee: Optional[str] = None
    stage: Optional[str] = None
    target_week: Optional[str] = None
    priority: Optional[WorkItemPriority] = None
    note: Optional[str] = None
    status: Optional[WorkItemStatus] = None
    linked_feature_id: Optional[str] = None
    linked_pool_item_id: Optional[str] = None

    @field_validator("target_week")
    @classmethod
    def week_ok(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v != "" and not is_valid_iso_week(v):
            raise ValueError("invalid target_week")
        return v


class WorkItemResponse(WorkItemBase):
    id: int
    display_stage: Optional[str] = None  # version_delivery 时来自 Feature.stage
    model_config = ConfigDict(from_attributes=True)
```

- [ ] **Step 2: Commit**

```bash
git add pm-system/backend/app/schemas/__init__.py
git commit -m "feat(pm-system): planner WorkItem pydantic schemas"
```

---

### Task 5: `planner.py` 路由 — 列表 / 创建 / 更新 / 取消 / 删除

**Files:**

- Create: `pm-system/backend/app/routers/planner.py`
- Modify: `pm-system/backend/main.py`

- [ ] **Step 1: 实现核心逻辑**（节选骨架；实现时补全 import 与 `_row_to_response`）

```python
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, List

from app.database import get_db
from app.models import WorkItem, Feature, PoolItem
from app.schemas import ApiResponse, WorkItemCreate, WorkItemUpdate, WorkItemResponse
from app.routers.auth import get_current_user
from app.models.user import User

router = APIRouter(prefix="/api/planner", tags=["planner"])


def _enforce_link_consistency(category: str, linked_feature_id, linked_pool_item_id):
    if category == "version_delivery" and linked_pool_item_id:
        raise HTTPException(400, "version_delivery must not link pool item")
    if category == "pre_design" and linked_feature_id:
        raise HTTPException(400, "pre_design must not link feature")
    # 允许二者皆空


@router.get("/items", response_model=ApiResponse)
async def list_items(
    week: Optional[str] = Query(None),
    assignee: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(WorkItem)
    if week is not None:
        q = q.filter(WorkItem.target_week == week) if week != "__none__" else q.filter(WorkItem.target_week.is_(None))
    if assignee is not None:
        q = q.filter(WorkItem.assignee == assignee)
    if category:
        q = q.filter(WorkItem.category == category)
    if status:
        q = q.filter(WorkItem.status == status)
    rows: List[WorkItem] = q.order_by(WorkItem.priority.asc(), WorkItem.title.asc()).all()
    out = []
    for w in rows:
        d = WorkItemResponse.model_validate(w).model_dump()
        if w.category == "version_delivery" and w.linked_feature_id:
            f = db.query(Feature).filter(Feature.id == w.linked_feature_id).first()
            d["display_stage"] = f.stage if f else None
        else:
            d["display_stage"] = w.stage
        out.append(d)
    return ApiResponse(data=out)


@router.post("/items", response_model=ApiResponse)
async def create_item(
    body: WorkItemCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    _enforce_link_consistency(body.category, body.linked_feature_id, body.linked_pool_item_id)
    row = WorkItem(**body.model_dump(exclude_unset=True))
    db.add(row)
    db.commit()
    db.refresh(row)
    return ApiResponse(data=WorkItemResponse.model_validate(row).model_dump())


@router.put("/items/{item_id}", response_model=ApiResponse)
async def update_item(
    item_id: int,
    body: WorkItemUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    row = db.query(WorkItem).filter(WorkItem.id == item_id).first()
    if not row:
        raise HTTPException(404, "not found")
    data = body.model_dump(exclude_unset=True)
    if "category" in data or "linked_feature_id" in data or "linked_pool_item_id" in data:
        cat = data.get("category", row.category)
        lf = data.get("linked_feature_id", row.linked_feature_id)
        lp = data.get("linked_pool_item_id", row.linked_pool_item_id)
        _enforce_link_consistency(cat, lf, lp)
    for k, v in data.items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return ApiResponse(data=WorkItemResponse.model_validate(row).model_dump())


@router.delete("/items/{item_id}", response_model=ApiResponse)
async def delete_item(
    item_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    row = db.query(WorkItem).filter(WorkItem.id == item_id).first()
    if not row:
        raise HTTPException(404, "not found")
    db.delete(row)
    db.commit()
    return ApiResponse(data={"deleted": item_id})
```

- [ ] **Step 2: 在 `main.py` 注册**

```python
from app.routers import planner as planner_router
# ...
app.include_router(planner_router.router)
```

- [ ] **Step 3: 更新测试** `test_planner_items_route_missing` → 期望 `200` 且 `data == []`

```python
def test_list_items_empty(app_client):
    r = app_client.get("/api/planner/items")
    assert r.status_code == 200
    body = r.json()
    assert body.get("code") == 0
    assert body.get("data") == []
```

- [ ] **Step 4: 运行**

```powershell
py -m pytest tests/test_planner_api.py -v
```

**期望：** PASS。

- [ ] **Step 5: Commit**

```bash
git add pm-system/backend/app/routers/planner.py pm-system/backend/main.py pm-system/backend/tests/test_planner_api.py
git commit -m "feat(pm-system): planner CRUD API skeleton"
```

---

### Task 6: API 测试 — 创建、非法周、关联校验

**Files:**

- Modify: `pm-system/backend/tests/test_planner_api.py`

- [ ] **Step 1: 追加用例**

```python
def test_create_and_list(app_client):
    payload = {
        "title": "锦标赛玩法",
        "category": "pre_design",
        "priority": "P0",
        "target_week": "2026-W17",
        "stage": "萌芽",
    }
    r = app_client.post("/api/planner/items", json=payload)
    assert r.status_code == 200
    wid = r.json()["data"]["id"]
    r2 = app_client.get("/api/planner/items", params={"week": "2026-W17"})
    assert len(r2.json()["data"]) == 1
    assert r2.json()["data"][0]["id"] == wid


def test_invalid_week(app_client):
    r = app_client.post(
        "/api/planner/items",
        json={"title": "x", "category": "learning", "priority": "P2", "target_week": "2026-W99"},
    )
    assert r.status_code == 422 or r.status_code == 400
```

- [ ] **Step 2: 运行 pytest**

```powershell
py -m pytest tests/test_planner_api.py -v
```

**期望：** 全部 PASS（若 Pydantic 对校验错误返回 422，接受 422）。

- [ ] **Step 3: Commit**

```bash
git add pm-system/backend/tests/test_planner_api.py
git commit -m "test(pm-system): planner create and validation cases"
```

---

### Task 7: `from-feature` / `from-pool` 与 `weekly-summary`

**Files:**

- Modify: `pm-system/backend/app/routers/planner.py`
- Modify: `pm-system/backend/tests/test_planner_api.py`

- [ ] **Step 1: 实现 `POST /items/from-feature/{feature_id}`**（查 `Feature`，不存在 404；创建 `version_delivery`，`title` 用 Feature.name，`linked_feature_id` 写入）

- [ ] **Step 2: 实现 `POST /items/from-pool/{pool_item_id}`**（查 `PoolItem`，不存在 404；创建 `pre_design`，`title` 用 `PoolItem.name`，`linked_pool_item_id` 写入）

- [ ] **Step 3: 实现 `GET /weekly-summary`**（返回结构示例）

```python
# 示例 data 形状
{
  "2026-W17": {
    "byAssignee": {"u1": 2, "unassigned": 1},
    "byCategory": {"pre_design": 2, "version_delivery": 1},
  }
}
```

- [ ] **Step 4: 测试**（在 `conftest` 的 session 里插入最小 `Version`+`Feature`+`Pool`+`PoolItem` 或使用工厂；若过于冗长，可只测 `from-feature` 在缺失时 404，存在时 200，数据在 `tests/test_planner_api.py` 用 `db_session` fixture 直接 `add` ORM 行后 `commit`，再 `app_client` 调用）

- [ ] **Step 5: Commit**

```bash
git add pm-system/backend/app/routers/planner.py pm-system/backend/tests/test_planner_api.py
git commit -m "feat(pm-system): planner from-feature/from-pool and weekly summary"
```

---

### Task 8: 前端 — 入口与看板 MVP

**Files:**

- Modify: `pm-system/index.html`
- Create: `pm-system/ui/components/planner-workbench.js`
- Modify: `pm-system/app.js`（若 hash 路由集中在此；否则在 `planner-workbench.js` 自注册 `hashchange`）

- [ ] **Step 1: `index.html` 增加导航链接**（文案示例：`策划周计划`）与 `<script src="ui/components/planner-workbench.js?v=..."></script>`（**按 `version-management.mdc` 递增查询参数**）

- [ ] **Step 2: `planner-workbench.js` 最小行为**

  - 监听 `location.hash === '#planner'` 时显示根容器（可用现有 UI 隐藏/显示模式）。
  - 三列 div：`本周` / `下周` / `未排期`；周字符串由前端用本地日期算 ISO 周（与后端一致：周一为一周之始，使用 `Temporal` 不可用时用手写 `getISOWeek` 小函数）。
  - `GET /api/planner/items` 无筛选拉全量，前端按 `target_week` 分桶；`priority` 排序同后端。
  - 点击卡片：`prompt` 或复用现有 Modal 组件编辑 `target_week`（`<select>` 生成未来 8 周 + 「未排期」空值）、`assignee`、`stage`、`priority`；保存时 `PUT /api/planner/items/{id}`。
  - 「新建」按钮：`POST /api/planner/items` 带默认 `category: pre_design`。
  - **不实现拖拽**。

- [ ] **Step 3: 手动验证**

启动 `quick_start.bat`，浏览器打开 `#planner`，创建条目、改周、刷新后仍在正确列。

- [ ] **Step 4: Commit**

```bash
git add pm-system/index.html pm-system/ui/components/planner-workbench.js pm-system/app.js
git commit -m "feat(pm-system): planner workbench UI MVP"
```

---

### Task 9: 文档与 WORK_LOG（交付闸）

**Files:**

- Modify: `d:\MyAgents\WORK_LOG.md`
- Modify: `pm-system/使用手册.md`（若存在「模块导览」节，增加策划周计划入口说明与截图占位）

- [ ] **Step 1: WORK_LOG 增加当日条目**（状态、简述、涉及路径）

- [ ] **Step 2: 使用手册** 更新「最后更新」日期与版本号（与 `agentx.mdc` 对 `使用手册.md` 要求一致）

- [ ] **Step 3: Commit**（用户明确要求时）

---

## Plan 自检（对照 Spec）

| Spec 章节 | 覆盖任务 |
|-----------|----------|
| §1 MVP 无拖拽 | Task 8 |
| §3 数据模型 + 关联 | Task 2、4、5、7 |
| §4 API 表 | Task 5–7 |
| §4.1 删除：cancelled vs DELETE | Task 5 提供 `PUT` 更新 `status`；`DELETE` 硬删；UI 默认走 `PUT`（在 Task 8 弹窗提供「从看板移除」→ `cancelled`） |
| §4.2 校验 | Task 3、6 |
| §5 前端入口与三列 | Task 8 |
| §5.4 按人/信号 | **未列入 MVP 本计划**；下一迭代单开任务或追加 Task 10 |
| §6 Feature 只读 | Task 5 `display_stage` |
| §7 测试 | Task 1、6、7 |

**占位符扫描：** 本计划未使用 `TBD`；`from-feature` 测试数据插入细节在 Task 7 由实现者用具体 ORM 行补全。

**类型一致性：** `WorkItemResponse` 与 ORM 字段 `linked_pool_item_id` 一致；API JSON camelCase 由 `CamelModel` 承担。

---

## 执行交接

Plan complete and saved to `docs/superpowers/plans/2026-04-20-planner-workbench.md`. Two execution options:

**1. Subagent-Driven (recommended)** — 每个 Task 派生子代理，任务间人工/Agent 复核，迭代快。

**2. Inline Execution** — 本会话内用 executing-plans，批量执行带检查点。

**Which approach?**

（若不需要选择：默认从 **Task 1** 开始在当前会话或新开会话执行，并遵守根目录 **git-branch-guard**：写操作前确认 `SESSION_BRANCH`。）
