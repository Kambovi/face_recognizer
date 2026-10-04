#!/usr/bin/env python
"""VENDOR CONSOLE for the SaaS cloud (APP_ROLE=cloud). Run on the cloud
server from the backend folder (same .env as the API):

  python scripts/tenants.py create --slug acme --name "Acme Industries" \\
      --type business --admin-email hr@acme.in --departments Production Stores Office \\
      --max-cameras 2 --max-people 200
        -> creates the client's own database, migrates it, sets the profile,
           creates the first admin (temporary password) and an edge-box token

  python scripts/tenants.py list
  python scripts/tenants.py edge-token --slug acme [--name "Plant 1"]   new / extra box token
  python scripts/tenants.py suspend --slug acme --reason "Invoice 2026-11 unpaid"
  python scripts/tenants.py resume  --slug acme
  python scripts/tenants.py set --slug acme --max-cameras 4 --allowed-cidrs 203.0.113.10/32
  python scripts/tenants.py profile --slug acme --add-department Packing
  python scripts/tenants.py migrate                  all tenant databases to the latest version
  python scripts/tenants.py delete --slug acme --yes  mark deleted (database kept until you drop it)

Tenant databases: TENANT_DATABASE_URL_TEMPLATE with {db} -> fa_<slug>, e.g.
postgresql+asyncpg://fa_app:<pw>@127.0.0.1:5432/{db}. The Postgres user
needs CREATEDB (create) -- or create the database by hand and pass --db-url.
"""
from __future__ import annotations

import argparse
import asyncio
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.security import encrypt_text, hash_password  # noqa: E402
from app.tenancy import (  # noqa: E402
    RESERVED_SLUGS,
    SLUG_RE,
    EdgeSite,
    Tenant,
    control_sessions,
    dispose_engines,
    hash_token,
    init_control_db,
    migrate_tenant_db,
    sessions_for,
    tenant_by_slug,
)


def _db_name(slug: str) -> str:
    return "fa_" + slug.replace("-", "_")


async def _create_database(url: str) -> None:
    """CREATE DATABASE for a Postgres URL (SQLite files appear on their own)."""
    from sqlalchemy.engine import make_url

    u = make_url(url)
    if not u.drivername.startswith("postgresql"):
        return
    import asyncpg

    conn = await asyncpg.connect(user=u.username, password=u.password, host=u.host or "127.0.0.1",
                                 port=u.port or 5432, database="postgres")
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", u.database)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{u.database}"')
    finally:
        await conn.close()


async def _new_site(db, tenant: Tenant, name: str) -> str:  # type: ignore[no-untyped-def]
    token = "es_" + secrets.token_urlsafe(32)
    db.add(EdgeSite(tenant_id=tenant.id, name=name, token_hash=hash_token(token)))
    await db.flush()
    return token


async def cmd_create(a: argparse.Namespace) -> None:
    from app.models.enums import UserRole
    from app.models.users import User
    from app.routers.users import temp_password
    from app.services.client_profile import PRESETS, save_raw

    slug = a.slug.strip().lower()
    if not SLUG_RE.match(slug) or slug in RESERVED_SLUGS:
        sys.exit("ERROR: slug = 3-32 chars, a-z 0-9 and -, starts with a letter (it becomes <slug>.<domain>)")
    if a.type not in PRESETS:
        sys.exit(f"ERROR: --type one of {sorted(PRESETS)}")
    s = get_settings()
    url = a.db_url or s.tenant_database_url_template.replace("{db}", _db_name(slug))
    async with control_sessions()() as db:
        if (await db.execute(select(Tenant).where(Tenant.slug == slug))).scalar_one_or_none():
            sys.exit(f"ERROR: tenant {slug} already exists")
    await _create_database(url)
    await asyncio.to_thread(migrate_tenant_db, url)

    async with control_sessions()() as db:
        t = Tenant(slug=slug, name=a.name.strip(), db_url_enc=encrypt_text(url), max_cameras=a.max_cameras,
                   max_people=a.max_people, plan=a.plan)
        db.add(t)
        await db.flush()
        site_token = await _new_site(db, t, a.site_name)
        await db.commit()

    info = await tenant_by_slug(slug)
    assert info is not None
    pw = temp_password()
    async with sessions_for(info)() as tdb:
        from datetime import datetime, timezone

        await save_raw(tdb, {"org_type": a.type, "org_name": a.name.strip(), "departments": a.departments or [],
                             "max_enrolled_per_camera": a.max_people, "vendor_pin_hash": hash_password(secrets.token_hex(16)),
                             "setup_at": datetime.now(timezone.utc).isoformat()})
        # the migration's demo admin must not exist on a client
        for u in (await tdb.execute(select(User))).scalars().all():
            await tdb.delete(u)
        tdb.add(User(email=a.admin_email.strip().lower(), password_hash=hash_password(pw), role=UserRole.ADMIN,
                     must_change_password=True, name=a.admin_name))
        await tdb.commit()

    print(f"OK: tenant {slug} created")
    print(f"  Dashboard     : https://{slug}.{s.base_domain}")
    print(f"  Admin login   : {a.admin_email}  temporary password: {pw}   (must be changed at first login)")
    print(f"  Edge box      : CLOUD_URL=https://{s.base_domain if s.base_domain != 'localhost' else 'localhost:8000'}")
    print(f"                  EDGE_SITE_TOKEN={site_token}")
    from app.licence import public_from_private

    if s.licence_private_key:
        print(f"                  LICENCE_PUBLIC_KEY={public_from_private(s.licence_private_key)}")
    print("  Keep these safe -- the token and password are shown only now.")


async def cmd_list(_a: argparse.Namespace) -> None:
    async with control_sessions()() as db:
        rows = (await db.execute(select(Tenant).order_by(Tenant.slug))).scalars().all()
        sites = (await db.execute(select(EdgeSite))).scalars().all()
    by_t: dict[str, list[EdgeSite]] = {}
    for st in sites:
        by_t.setdefault(st.tenant_id, []).append(st)
    print(f"{'SLUG':20} {'STATUS':10} {'CAMS':>4} {'PEOPLE':>6}  NAME / EDGE BOXES")
    for t in rows:
        print(f"{t.slug:20} {t.status:10} {t.max_cameras:>4} {t.max_people:>6}  {t.name}")
        for st in by_t.get(t.id, []):
            seen = st.last_seen_at.strftime("%Y-%m-%d %H:%M") if st.last_seen_at else "never"
            print(f"{'':44}- {st.name}: last seen {seen} from {st.last_ip or '?'} {'' if st.enabled else '(disabled)'}")


async def _tenant(db, slug: str) -> Tenant:  # type: ignore[no-untyped-def]
    t = (await db.execute(select(Tenant).where(Tenant.slug == slug))).scalar_one_or_none()
    if t is None:
        sys.exit(f"ERROR: no tenant {slug}")
    return t


async def cmd_edge_token(a: argparse.Namespace) -> None:
    async with control_sessions()() as db:
        t = await _tenant(db, a.slug)
        if a.replace:
            for st in (await db.execute(select(EdgeSite).where(EdgeSite.tenant_id == t.id))).scalars().all():
                st.enabled = False
        token = await _new_site(db, t, a.name)
        await db.commit()
    print(f"EDGE_SITE_TOKEN={token}" + ("   (old box tokens disabled)" if a.replace else ""))


async def _status(slug: str, status: str, reason: str | None) -> None:
    from app.tenancy import forget_tenant

    async with control_sessions()() as db:
        t = await _tenant(db, slug)
        t.status, t.status_reason = status, reason
        await db.commit()
    forget_tenant(slug)
    print(f"OK: {slug} -> {status}" + (f" ({reason})" if reason else "") + "  (takes effect within 30 s)")


async def cmd_suspend(a: argparse.Namespace) -> None:
    await _status(a.slug, "suspended", a.reason)


async def cmd_resume(a: argparse.Namespace) -> None:
    await _status(a.slug, "active", None)


async def cmd_delete(a: argparse.Namespace) -> None:
    if not a.yes:
        sys.exit("Add --yes. The tenant is marked deleted; drop its database yourself after the retention period.")
    await _status(a.slug, "deleted", "deleted by vendor")


async def cmd_set(a: argparse.Namespace) -> None:
    async with control_sessions()() as db:
        t = await _tenant(db, a.slug)
        if a.max_cameras is not None:
            t.max_cameras = a.max_cameras
        if a.max_people is not None:
            t.max_people = a.max_people
        if a.allowed_cidrs is not None:
            import ipaddress

            for c in a.allowed_cidrs:
                ipaddress.ip_network(c, strict=False)
            t.allowed_cidrs = a.allowed_cidrs or None
        if a.name:
            t.name = a.name
        await db.commit()
    print("OK")


async def cmd_profile(a: argparse.Namespace) -> None:
    from app.services.client_profile import load_raw, public_view, save_raw

    info = await tenant_by_slug(a.slug)
    if info is None:
        sys.exit("ERROR: no such tenant")
    async with sessions_for(info)() as db:
        p = await load_raw(db) or {}
        deps = list(p.get("departments") or [])
        for d in a.add_department or []:
            if d not in deps:
                deps.append(d)
        for d in a.remove_department or []:
            if d in deps:
                deps.remove(d)
        p["departments"] = deps
        if a.type:
            p["org_type"] = a.type
        if a.name:
            p["org_name"] = a.name
        if a.camera_cap is not None:
            p["max_enrolled_per_camera"] = a.camera_cap
        await save_raw(db, p)
        await db.commit()
    print(public_view(p))


async def cmd_migrate(_a: argparse.Namespace) -> None:
    from app.tenancy import all_tenants

    for t in await all_tenants(active_only=False):
        print(f"migrating {t.slug} ...", end=" ", flush=True)
        await asyncio.to_thread(migrate_tenant_db, t.db_url)
        print("ok")


def main() -> None:
    if get_settings().role != "cloud":
        sys.exit("ERROR: set APP_ROLE=cloud in backend/.env (this console manages the SaaS cloud)")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create")
    c.add_argument("--slug", required=True)
    c.add_argument("--name", required=True)
    c.add_argument("--type", default="business", help="business | school | hospital")
    c.add_argument("--departments", nargs="*")
    c.add_argument("--admin-email", required=True)
    c.add_argument("--admin-name")
    c.add_argument("--max-cameras", type=int, default=2)
    c.add_argument("--max-people", type=int, default=200)
    c.add_argument("--plan", default="standard")
    c.add_argument("--site-name", default="Main site")
    c.add_argument("--db-url", help="use this database instead of the template")
    sub.add_parser("list")
    e = sub.add_parser("edge-token")
    e.add_argument("--slug", required=True)
    e.add_argument("--name", default="Edge box")
    e.add_argument("--replace", action="store_true", help="disable the old box tokens")
    for name in ("suspend", "resume", "delete"):
        x = sub.add_parser(name)
        x.add_argument("--slug", required=True)
        if name == "suspend":
            x.add_argument("--reason", default="Subscription inactive")
        if name == "delete":
            x.add_argument("--yes", action="store_true")
    st = sub.add_parser("set")
    st.add_argument("--slug", required=True)
    st.add_argument("--name")
    st.add_argument("--max-cameras", type=int)
    st.add_argument("--max-people", type=int)
    st.add_argument("--allowed-cidrs", nargs="*", help="office IPs / ranges allowed to open the dashboard; none = anywhere")
    pr = sub.add_parser("profile")
    pr.add_argument("--slug", required=True)
    pr.add_argument("--type")
    pr.add_argument("--name")
    pr.add_argument("--add-department", nargs="*")
    pr.add_argument("--remove-department", nargs="*")
    pr.add_argument("--camera-cap", type=int)
    sub.add_parser("migrate")
    a = p.parse_args()
    handler = {"create": cmd_create, "list": cmd_list, "edge-token": cmd_edge_token, "suspend": cmd_suspend,
               "resume": cmd_resume, "delete": cmd_delete, "set": cmd_set, "profile": cmd_profile,
               "migrate": cmd_migrate}[a.cmd]

    async def run() -> None:
        await init_control_db()
        try:
            await handler(a)
        finally:
            await dispose_engines()

    asyncio.run(run())


if __name__ == "__main__":
    main()
