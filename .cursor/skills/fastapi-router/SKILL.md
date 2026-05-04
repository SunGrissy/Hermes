---
name: fastapi-router
description: Build FastAPI routers with CRUD operations, authentication, and proper response models. Use when creating new API endpoints, designing FastAPI route structures, or establishing backend API patterns with Pydantic models.
---

# FastAPI Router Best Practices

## Router Template

Copy and adapt the template below. Replace placeholders:
- `{{ResourceName}}` → PascalCase (e.g., `Project`)
- `{{resource_name}}` → snake_case (e.g., `project`)
- `{{resource_plural}}` → plural form (e.g., `projects`)

```python
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/{{resource_plural}}", tags=["{{resource_plural}}"])

class {{ResourceName}}Create(BaseModel):
    name: str

class {{ResourceName}}Update(BaseModel):
    name: Optional[str] = None

class {{ResourceName}}Response(BaseModel):
    id: str
    name: str

@router.get("/", response_model=list[{{ResourceName}}Response])
async def list_{{resource_plural}}():
    ...

@router.post("/", response_model={{ResourceName}}Response, status_code=status.HTTP_201_CREATED)
async def create_{{resource_name}}(data: {{ResourceName}}Create):
    ...

@router.get("/{id}", response_model={{ResourceName}}Response)
async def get_{{resource_name}}(id: str):
    ...

@router.put("/{id}", response_model={{ResourceName}}Response)
async def update_{{resource_name}}(id: str, data: {{ResourceName}}Update):
    ...

@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_{{resource_name}}(id: str):
    ...
```

## Authentication Patterns

```python
from fastapi import Depends

async def get_current_user(token: str = Depends(oauth2_scheme)):
    """Optional auth - returns None if no token."""
    ...

async def get_current_user_required(user = Depends(get_current_user)):
    """Required auth - raises 401 if no valid user."""
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user

@router.get("/me", response_model=UserResponse)
async def get_profile(user = Depends(get_current_user_required)):
    return user
```

## Integration Steps

1. Create router file in `routers/` directory
2. Mount in `main.py`: `app.include_router(router)`
3. Create Pydantic models for request/response schemas
4. Create service layer for business logic (keep routers thin)
5. Add corresponding frontend API functions if needed

## Best Practices

- Use PascalCase for models, snake_case for route identifiers
- Annotate every endpoint with `response_model` and explicit `status_code`
- Keep routers focused on request/response; delegate logic to service layer
- Use `Depends()` for shared dependencies (auth, DB sessions, etc.)
- Return proper HTTP status codes: 201 for creates, 204 for deletes
- Use `HTTPException` with descriptive `detail` messages
- Group related endpoints under a common prefix and tag
