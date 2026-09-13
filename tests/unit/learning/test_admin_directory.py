from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ac_platform.community.models import CohorvaPublicProfile
from ac_platform.db.models import model_metadata
from ac_platform.identity.models import Person
from ac_platform.learning.admin_diagnosis import DiagnosisLookupInvalid
from ac_platform.learning.admin_directory import list_members
from ac_platform.tenancy.models import Membership, Tenant

NOW = datetime(2026, 9, 13, tzinfo=UTC)


@pytest.fixture
def directory_db():
    engine = create_engine("sqlite:///:memory:")
    model_metadata().create_all(engine)
    with Session(engine) as db:
        tenant, other = uuid4(), uuid4()
        db.add_all(
            [
                Tenant(id=tenant, slug="academy", name="Academy"),
                Tenant(id=other, slug="other", name="Other"),
            ]
        )
        for index, (name, role, membership, account, verified, target) in enumerate(
            [
                ("Dipak Owner", "owner", "active", "active", True, tenant),
                ("Suyash Learner", "learner", "active", "active", True, tenant),
                ("Pending Email", "learner", "active", "active", False, tenant),
                ("Inactive Person", "learner", "inactive", "active", True, tenant),
                ("Suspended Person", "admin", "active", "suspended", True, tenant),
                ("Deleted Person", "learner", "active", "deleted", True, tenant),
                ("Other Academy", "learner", "active", "active", True, other),
            ]
        ):
            person = uuid4()
            db.add(
                Person(
                    id=person,
                    display_name=name,
                    email=f"person{index}@example.test",
                    status=account,
                    email_verified_at=NOW if verified else None,
                )
            )
            db.add(
                Membership(
                    tenant_id=target,
                    person_id=person,
                    role=role,
                    status=membership,
                    created_at=NOW,
                    ended_at=NOW if membership == "inactive" else None,
                )
            )
            db.add(
                CohorvaPublicProfile(
                    person_id=person,
                    username=f"user_{index}",
                    claim_source="legacy_0027",
                    legacy_profile_count=1,
                )
            )
        db.commit()
        yield db, tenant, other
    engine.dispose()


def test_first_load_lists_all_roles_and_keeps_account_scope(directory_db):
    db, tenant, _other = directory_db
    result = list_members(db, tenant_id=tenant)
    assert {m.display_name for m in result.members} == {
        "Dipak Owner",
        "Suyash Learner",
        "Pending Email",
        "Inactive Person",
        "Suspended Person",
    }
    assert result.summary.total == result.matching_count == 5
    assert result.summary.active_learners == 2
    assert result.summary.team == 1
    assert result.summary.unverified == 1
    assert all(m.masked_email == "p***@example.test" for m in result.members)
    assert all(m.active_enrollments == 0 for m in result.members)
    assert list_members(db, tenant_id=tenant, query="Other Academy").members == ()


@pytest.mark.parametrize(
    ("query", "names"),
    [
        ("  SUY  ", {"Suyash Learner"}),
        ("person0@", {"Dipak Owner"}),
        ("user_1", {"Suyash Learner"}),
        ("%", set()),
        (
            "_",
            {
                "Dipak Owner",
                "Suyash Learner",
                "Pending Email",
                "Inactive Person",
                "Suspended Person",
            },
        ),
        (
            "user_",
            {
                "Dipak Owner",
                "Suyash Learner",
                "Pending Email",
                "Inactive Person",
                "Suspended Person",
            },
        ),
    ],
)
def test_search_is_partial_case_insensitive_and_escapes_wildcards(directory_db, query, names):
    db, tenant, _other = directory_db
    assert {
        m.display_name for m in list_members(db, tenant_id=tenant, query=query).members
    } == names


def test_filters_and_stable_pages_have_scoped_counts(directory_db):
    db, tenant, _other = directory_db
    pages = [list_members(db, tenant_id=tenant, page=page, page_size=2) for page in (1, 2, 3)]
    assert len({m.person_id for page in pages for m in page.members}) == 5
    assert [len(page.members) for page in pages] == [2, 2, 1]
    for status, name in [
        ("suspended", "Suspended Person"),
        ("inactive", "Inactive Person"),
        ("unverified", "Pending Email"),
    ]:
        result = list_members(db, tenant_id=tenant, status=status)
        assert [m.display_name for m in result.members] == [name]
        assert result.summary.total == 5 and result.matching_count == 1
    assert list_members(db, tenant_id=tenant, role="owner").matching_count == 1
    assert list_members(db, tenant_id=tenant, status="active").matching_count == 3


@pytest.mark.parametrize(
    "kwargs",
    [
        {"page": 0},
        {"page_size": 51},
        {"query": "x" * 321},
        {"status": "deleted"},
        {"role": "superuser"},
    ],
)
def test_invalid_filters_fail_before_directory_read(directory_db, kwargs):
    db, tenant, _other = directory_db
    with pytest.raises(DiagnosisLookupInvalid):
        list_members(db, tenant_id=tenant, **kwargs)


def test_suspended_academy_returns_no_directory(directory_db):
    db, tenant, _other = directory_db
    db.get(Tenant, tenant).status = "suspended"
    db.commit()
    with pytest.raises(DiagnosisLookupInvalid):
        list_members(db, tenant_id=tenant)
