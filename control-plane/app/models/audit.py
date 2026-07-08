"""Append-only admin history log.

One row per change (create / update / delete / restore) to an admin-managed
entity. Rows are written automatically by the session listeners in
``app.services.audit`` — nothing writes here directly.
"""

from __future__ import annotations

from functools import partial
from typing import Any

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, gen_id


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=partial(gen_id, "aud"))
    # create | update | delete | restore
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    # tenant/demand table name, e.g. "publisher", "placement", "demand_partner"
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    # the acting admin subject (single admin today; real usernames once multi-user)
    actor: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    # request/device signals — hints, not identity (see CLAUDE.md)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(400), nullable=True)
    method: Mapped[str | None] = mapped_column(String(10), nullable=True)
    path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    # column snapshots (JSON-safe); before is null on create, after is null on hard delete
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # list[str] of columns that changed on an update
    changed_fields: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
