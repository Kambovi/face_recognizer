"""Multi-site: register a site at HQ, the site pushes a snapshot, HQ lists it."""
from __future__ import annotations

import httpx

from app.main import app as fastapi_app
from app.services.multisite import build_snapshot, get_link, push_once, save_link


async def test_register_push_and_list(client, admin_headers, db_session):
    r = await client.post("/api/v1/hq/sites", headers=admin_headers, json={"name": "Plant 2 - Chakan"})
    assert r.status_code == 201
    token = r.json()["token"]
    assert len(token) > 30

    snap = await build_snapshot(db_session)
    assert {"roster", "present", "cameras_online", "open_alerts", "inside_now"} <= snap.keys()

    bad = await client.post("/api/v1/hq/ingest", json=snap, headers={"X-Site-Token": "nope"})
    assert bad.status_code == 401
    ok = await client.post("/api/v1/hq/ingest", json={**snap, "evil": {"nested": 1}}, headers={"X-Site-Token": token})
    assert ok.status_code == 200

    sites = (await client.get("/api/v1/hq/sites", headers=admin_headers)).json()
    assert sites[0]["name"] == "Plant 2 - Chakan"
    assert sites[0]["snapshot"]["roster"] == snap["roster"]
    assert "evil" not in sites[0]["snapshot"]  # only flat values are stored


async def test_site_side_push_through_the_link(client, admin_headers, db_session):
    token = (await client.post("/api/v1/hq/sites", headers=admin_headers, json={"name": "Self"})).json()["token"]
    # this install reports to itself (ASGI transport stands in for the network)
    await save_link(db_session, {"url": "http://hq.test", "token": token})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=fastapi_app), base_url="http://hq.test") as hq:
        result = await push_once(db_session, client=hq)
    assert result == {"pushed": True}
    assert (await get_link(db_session))["last_push_at"]

    link = (await client.get("/api/v1/hq/link", headers=admin_headers)).json()
    assert link["url"] == "http://hq.test" and link["token_set"] is True and "token" not in link
    # the token never shows up among the ordinary settings
    settings = (await client.get("/api/v1/settings", headers=admin_headers)).json()["settings"]
    assert not any("hq" in k for k in settings)
