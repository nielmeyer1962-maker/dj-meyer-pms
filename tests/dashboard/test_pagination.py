from __future__ import annotations

import re
from datetime import date, timedelta

import pytest

from app.extensions import db
from app.models.cipc import CIPCAnnualInstance, CIPCAnnualStatus
from app.models.client import Client, EntityType
from app.models.obligation import ObligationInstance, ObligationStatus, ObligationType

# 60 obligations + 60 CIPC rows, due dates strictly alternating across 120 consecutive
# days so the two sources interleave through every page boundary. Due dates live in 2030
# (far future → use window=all to bypass bounding); period_end lives in 2020 so a
# "2030-..." regex extracts ONLY due dates, in render order.
_BASE = date(2030, 1, 1)
_N = 60  # per source
_DUE_RE = re.compile(r"2030-\d{2}-\d{2}")


@pytest.fixture
def paginated_world(app):
    c = Client(legal_name="Paginate Co", entity_type=EntityType.PTY_LTD)
    db.session.add(c)
    db.session.commit()
    rows = []
    for i in range(_N):
        rows.append(
            ObligationInstance(
                client_id=c.id,
                obligation_type=ObligationType.VAT201,
                period_start=date(2020, 1, 1) + timedelta(days=i),
                period_end=date(2020, 1, 1) + timedelta(days=i),  # unique → no idempotency clash
                submission_due_date=_BASE + timedelta(days=2 * i),  # even offsets
                payment_due_date=_BASE + timedelta(days=2 * i),
                status=ObligationStatus.PENDING,
            )
        )
        rows.append(
            CIPCAnnualInstance(
                client_id=c.id,
                anniversary_date=date(2029, 1, 1) + timedelta(days=i),  # unique
                due_date=_BASE + timedelta(days=2 * i + 1),  # odd offsets
                status=CIPCAnnualStatus.GENERATED,
            )
        )
    db.session.add_all(rows)
    db.session.commit()


def _due_dates(client, page: int) -> list[str]:
    body = client.get(f"/dashboard/?window=all&page={page}").data.decode()
    return _DUE_RE.findall(body)


def _expected_sequence() -> list[str]:
    return [(_BASE + timedelta(days=d)).isoformat() for d in range(2 * _N)]


def test_first_page_size_and_total_pages(client, paginated_world):
    body = client.get("/dashboard/?window=all").data.decode()
    assert "Showing <strong>120</strong>" in body
    assert "Page 1 of 3" in body  # 120 / 50 → 3 pages
    assert len(_DUE_RE.findall(body)) == 50


def test_pages_partition_all_rows_in_global_order(client, paginated_world):
    p1, p2, p3 = (_due_dates(client, n) for n in (1, 2, 3))
    assert (len(p1), len(p2), len(p3)) == (50, 50, 20)
    combined = p1 + p2 + p3
    # No omissions, no duplicates, and globally sorted across every page boundary.
    assert combined == _expected_sequence()
    assert len(set(combined)) == 120
    # Boundary ordering: last of a page strictly precedes first of the next.
    assert p1[-1] < p2[0] < p2[-1] < p3[0]


def test_both_kinds_interleave_across_pages(client, paginated_world):
    """Each page carries BOTH obligation rows (detail links) and CIPC rows (cipc actions),
    proving the merge interleaves the two sources rather than exhausting one first."""
    for page in (1, 2):
        body = client.get(f"/dashboard/?window=all&page={page}").data.decode()
        assert "/dashboard/obligations/" in body
        assert "/dashboard/cipc/" in body


def test_out_of_range_page_clamps_to_last(client, paginated_world):
    body = client.get("/dashboard/?window=all&page=99").data.decode()
    assert "Page 3 of 3" in body
    assert len(_DUE_RE.findall(body)) == 20
    assert _DUE_RE.findall(body) == _expected_sequence()[100:]


def test_invalid_page_defaults_to_first(client, paginated_world):
    body = client.get("/dashboard/?window=all&page=not-a-number").data.decode()
    assert "Page 1 of 3" in body
    assert _DUE_RE.findall(body) == _expected_sequence()[:50]


def test_zero_and_negative_page_default_to_first(client, paginated_world):
    for bad in ("0", "-4"):
        body = client.get(f"/dashboard/?window=all&page={bad}").data.decode()
        assert "Page 1 of 3" in body


def test_filters_preserved_in_pager_links(client, paginated_world):
    body = client.get("/dashboard/?window=all&assignee=__unassigned__").data.decode()
    # The Next link must carry both filters AND advance the page.
    assert "window=all" in body
    assert "assignee=__unassigned__" in body
    assert "page=2" in body
