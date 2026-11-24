"""Pulls tenant/user identity out of the request headers or query params."""

import uuid
from dataclasses import dataclass

from fastapi import Header, HTTPException, Query


@dataclass
class Identity:
    tenant_id: uuid.UUID
    user_id: uuid.UUID


def get_current_identity(
    x_tenant_id: str | None = Header(None),
    x_user_id: str | None = Header(None),
    # query-param fallback for SSE routes, which can't set custom headers
    tenant_id: str | None = Query(None),
    user_id: str | None = Query(None),
) -> Identity:
    raw_tenant_id = x_tenant_id or tenant_id
    raw_user_id = x_user_id or user_id
    if not raw_tenant_id or not raw_user_id:
        raise HTTPException(status_code=400, detail="missing tenant/user identity")
    try:
        return Identity(tenant_id=uuid.UUID(raw_tenant_id), user_id=uuid.UUID(raw_user_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid tenant/user identity")
