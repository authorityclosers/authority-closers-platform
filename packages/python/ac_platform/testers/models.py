"""The Sales X-Ray tester list (owner, 13 Nov 2026; migration 0151).

``sales_xray_tester_events`` is the append-only history of each Play tester, one Google
account (email) each: who applied and with what phone, who was already in the Play group
when the list began, the team's approvals and declines, when they were added to the
Google Group and when the welcome email went. Every step is a new row, written once; where
a tester stands is folded from their rows (``store.fold``), and installs and activity come
from their app sessions at read time, never stored here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKeyConstraint, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.db.base import Base

#: applied: the person, from /testers; listed: already in the Play group when the list began;
#: approved, declined: the team; added_to_group: the Google Group has them (by the team in
#: Admin, or "seed" for the group's members at the start); emailed: the welcome email went
#: (by the app's mail, or "gmail" for one sent by hand before the list).
KINDS = ("applied", "listed", "approved", "declined", "added_to_group", "emailed")
VIAS = ("admin", "seed", "app", "gmail")
ROLES = ("owner", "manager", "seller", "other")


class SalesXrayTesterEvent(Base):
    """One step in a tester's history; the folded rows say where they stand."""

    __tablename__ = "sales_xray_tester_events"
    __table_args__ = (
        ForeignKeyConstraint(["person_id"], ["persons.id"], name="fk_sx_tester_person"),
        ForeignKeyConstraint(["actor_person_id"], ["persons.id"], name="fk_sx_tester_actor"),
        CheckConstraint(
            "kind IN ('applied', 'listed', 'approved', 'declined', 'added_to_group', 'emailed')",
            name="sx_tester_kind",
        ),
        CheckConstraint(
            "email = lower(email) AND length(email) BETWEEN 3 AND 320 AND email LIKE '_%@_%'",
            name="sx_tester_email",
        ),
        # A person applies for themself, signed in with that Google account; nothing else
        # names a person (activity is read from sessions by email).
        CheckConstraint(
            "(kind = 'applied') = (person_id IS NOT NULL)"
            " AND (kind <> 'applied' OR actor_person_id = person_id)",
            name="sx_tester_applicant",
        ),
        CheckConstraint(
            "(kind IN ('added_to_group', 'emailed')) = (via IS NOT NULL)"
            " AND (via IS NULL OR via IN ('admin', 'seed', 'app', 'gmail'))",
            name="sx_tester_via",
        ),
        CheckConstraint(
            "role IS NULL OR role IN ('owner', 'manager', 'seller', 'other')",
            name="sx_tester_role",
        ),
        CheckConstraint("kind = 'listed' OR facts IS NULL", name="sx_tester_facts"),
        Index("ix_sx_tester_email", "email", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    email: Mapped[str] = mapped_column(String(320))
    kind: Mapped[str] = mapped_column(String(16))
    person_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    actor_person_id: Mapped[UUID] = mapped_column(Uuid)
    via: Mapped[str | None] = mapped_column(String(16), nullable=True)
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    phone_model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    role: Mapped[str | None] = mapped_column(String(16), nullable=True)
    business: Mapped[str | None] = mapped_column(String(120), nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # listed only: what production showed for this account when the list began (counts and
    # dates, no content), so dev and staging show the same starting stages.
    facts: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


__all__ = ["KINDS", "ROLES", "VIAS", "SalesXrayTesterEvent"]
