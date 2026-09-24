"""Dimensional report: day-wise per publisher/site, filters, sorting, derived money."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from tests.helpers import build_chain

R = "/v1/admin/analytics/report"


async def _seeded(client: AsyncClient, headers: dict[str, str], n: int = 120) -> dict[str, str]:
    ids = await build_chain(client, headers)
    r = await client.post(
        "/v1/admin/analytics/dev/seed",
        headers=headers,
        json={"placement_id": ids["placement_id"], "sessions": n, "days": 5},
    )
    assert r.status_code == 200, r.text
    return ids


async def test_day_wise_per_publisher(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    a = await _seeded(client, auth_headers)
    b = await _seeded(client, auth_headers)  # same publisher NAME, different publisher
    rep = (
        await client.get(f"{R}?dimensions=publisher,day&sort=day&order=asc", headers=auth_headers)
    ).json()
    assert rep["dimensions"] == ["publisher", "day"]
    rows = rep["rows"]
    # Same-named publishers stay separate rows, told apart by id.
    assert {r["publisher_id"] for r in rows} == {a["publisher_id"], b["publisher_id"]}
    days = [r["day"] for r in rows]
    assert days == sorted(days)
    date.fromisoformat(days[0])  # ISO calendar date
    # Rows add up to the grand total, which matches summary().
    s = (await client.get("/v1/admin/analytics/summary", headers=auth_headers)).json()
    assert sum(r["loads"] for r in rows) == rep["totals"]["loads"] == s["loads"]
    assert sum(r["impressions"] for r in rows) == rep["totals"]["impressions"]
    assert rep["totals"]["fillRate"] == s["fillRate"]


async def test_filters_scope_every_endpoint(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    a = await _seeded(client, auth_headers)
    await _seeded(client, auth_headers)
    q = f"publisher_id={a['publisher_id']}"
    only_a = (
        await client.get(
            f"/v1/admin/analytics/summary?placement_id={a['placement_id']}", headers=auth_headers
        )
    ).json()
    for path in ("summary", f"report?dimensions=site&{q}"):
        sep = "&" if "?" in path else "?"
        body = (
            await client.get(f"/v1/admin/analytics/{path}{sep}{q}", headers=auth_headers)
        ).json()
        loads = body["loads"] if "loads" in body else body["totals"]["loads"]
        assert loads == only_a["loads"], path
    rep = (
        await client.get(f"{R}?dimensions=site&site_id={a['site_id']}", headers=auth_headers)
    ).json()
    assert [r["site_id"] for r in rep["rows"]] == [a["site_id"]]
    # Filters that match nothing give an empty report and zero totals, not an error.
    none = (await client.get(f"{R}?dimensions=day&format=banner", headers=auth_headers)).json()
    assert none["rows"] == [] and none["totals"]["loads"] == 0


async def test_device_country_and_refresh_dimensions(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _seeded(client, auth_headers, 200)
    dev = (await client.get(f"{R}?dimensions=device", headers=auth_headers)).json()["rows"]
    assert {r["device"] for r in dev} == {"desktop", "mobile", "tablet", "ctv"}
    cz = (await client.get(f"{R}?dimensions=country&country=cz", headers=auth_headers)).json()
    assert [r["country"] for r in cz["rows"]] == ["CZ"]
    ref = (await client.get(f"{R}?dimensions=refresh", headers=auth_headers)).json()["rows"]
    kinds = {r["refresh"]: r for r in ref}
    assert set(kinds) == {"initial", "refresh"}
    # Page loads only ever happen on the initial opportunity.
    assert kinds["refresh"]["loads"] == 0 and kinds["initial"]["loads"] > 0


async def test_sorting_and_limit(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    await _seeded(client, auth_headers)
    rep = (
        await client.get(f"{R}?dimensions=day&sort=impressions&order=desc", headers=auth_headers)
    ).json()
    imps = [r["impressions"] for r in rep["rows"]]
    assert imps == sorted(imps, reverse=True)
    # Default for a time-led report: newest day first.
    default = (await client.get(f"{R}?dimensions=day", headers=auth_headers)).json()
    days = [r["day"] for r in default["rows"]]
    assert default["sort"] == "day" and days == sorted(days, reverse=True)
    # Multi-dimension default: grouped by the leading dimension, days newest first.
    grp = (await client.get(f"{R}?dimensions=site,day", headers=auth_headers)).json()
    assert grp["sort"] == "site" and grp["order"] == "asc"
    gdays = [r["day"] for r in grp["rows"]]
    assert gdays == sorted(gdays, reverse=True)
    capped = (await client.get(f"{R}?dimensions=day&limit=2", headers=auth_headers)).json()
    assert len(capped["rows"]) == 2 and capped["truncated"] and capped["total"] > 2


async def test_derived_ecpm_and_revenue(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    await _seeded(client, auth_headers, 150)
    t = (await client.get(f"{R}?dimensions=day", headers=auth_headers)).json()["totals"]
    assert t["revenue"] > 0
    assert t["ecpm"] == pytest.approx(t["revenue"] / t["impressions"] * 1000, abs=1e-3)
    assert t["rpm"] == pytest.approx(t["revenue"] / t["loads"] * 1000, abs=1e-3)
    # Revenue counts only wins that rendered and uses RAW cpm, so derived eCPM
    # can never exceed the average winning bid.
    assert t["ecpm"] <= t["avgCpmRaw"]
    s = (await client.get("/v1/admin/analytics/summary", headers=auth_headers)).json()
    assert s["ecpm"] == t["ecpm"] and s["revenue"] == t["revenue"]


async def test_date_range_in_timezone(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    await _seeded(client, auth_headers)
    today = date.today()
    q = f"dimensions=day&tz=Asia/Kolkata&date_from={today - timedelta(days=1)}&date_to={today}"
    rep = (await client.get(f"{R}?{q}", headers=auth_headers)).json()
    assert rep["tz"] == "Asia/Kolkata"
    assert all(r["day"] >= str(today - timedelta(days=1)) for r in rep["rows"])
    bad = await client.get(f"{R}?dimensions=day&tz=Mars/Base", headers=auth_headers)
    assert bad.status_code == 422


async def test_csv_export(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    await _seeded(client, auth_headers)
    r = await client.get(f"{R}.csv?dimensions=site,day", headers=auth_headers)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    header = r.text.splitlines()[0].split(",")
    assert header[:3] == ["site", "day", "site_id"] and "ecpm" in header


async def test_report_validation_and_filters_endpoint(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    ids = await _seeded(client, auth_headers)
    for q in (
        "dimensions=",
        "dimensions=day,day",
        "dimensions=nope",
        "dimensions=a,b,c,d",
        "dimensions=day&device=fridge",
        "dimensions=day&player_type=banner",
    ):
        assert (await client.get(f"{R}?{q}", headers=auth_headers)).status_code == 422, q
    f = (await client.get("/v1/admin/analytics/filters", headers=auth_headers)).json()
    assert ids["publisher_id"] in {p["id"] for p in f["publishers"]}
    assert any(s["publisher_id"] == ids["publisher_id"] for s in f["sites"])
    assert "CZ" in f["countries"] and "day" in f["dimensions"]
    assert (await client.get(R)).status_code in (401, 403)
