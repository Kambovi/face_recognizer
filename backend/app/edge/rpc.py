"""What the cloud may ask the edge box to do (over the tunnel).

Each handler gets the params dict and returns JSON. Everything touching a
face template or a photo happens here, on the box.
"""
from __future__ import annotations

import base64
from collections.abc import Awaitable, Callable
from typing import Any

from app.db import AsyncSessionLocal
from app.models.enums import OwnerType
from app.services import face_store

Handler = Callable[[dict[str, Any]], Awaitable[Any]]
MAX_PHOTO_BYTES = 2 * 1024 * 1024


def _owner(p: dict[str, Any]) -> tuple[OwnerType, str]:
    return OwnerType(str(p["owner_type"])), str(p["owner_id"])


async def enroll(p: dict[str, Any]) -> Any:
    images = [(str(i.get("filename") or "image"), base64.b64decode(i["b64"])) for i in (p.get("images") or [])[:5]]
    async with AsyncSessionLocal() as db:
        res = await face_store.enroll_images(db, str(p["employee_id"]), images, int(p.get("min_face_pixels") or 80))
        await db.commit()
    return res


async def templates_list(p: dict[str, Any]) -> Any:
    ot, oid = _owner(p)
    async with AsyncSessionLocal() as db:
        return await face_store.list_templates(db, ot, oid)


async def templates_delete(p: dict[str, Any]) -> Any:
    ot, oid = _owner(p)
    async with AsyncSessionLocal() as db:
        ok = await face_store.delete_template(db, ot, oid, str(p["template_id"]))
        await db.commit()
        n = (await face_store.count_templates(db, ot, [oid])).get(oid, 0)
    return {"deleted": ok, "template_count": n}


async def templates_purge(p: dict[str, Any]) -> Any:
    ot, oid = _owner(p)
    async with AsyncSessionLocal() as db:
        n = await face_store.purge_owner(db, ot, oid)
        await db.commit()
    return {"deleted": n}


async def templates_counts(p: dict[str, Any]) -> Any:
    async with AsyncSessionLocal() as db:
        return await face_store.count_templates(db, OwnerType.EMPLOYEE, p.get("owner_ids"))


async def unknown_adopt(p: dict[str, Any]) -> Any:
    eid = str(p["employee_id"])
    async with AsyncSessionLocal() as db:
        moved = await face_store.adopt_unknown_templates(
            db, str(p["unknown_id"]), eid, min_quality=float(p.get("min_quality") or 0.5),
            capacity=p.get("capacity"), delete_rest=bool(p.get("delete_rest")))
        await db.commit()
        n = (await face_store.count_templates(db, OwnerType.EMPLOYEE, [eid])).get(eid, 0)
    return {"moved": moved, "template_count": n}


async def unknown_split(p: dict[str, Any]) -> Any:
    async with AsyncSessionLocal() as db:
        moved = await face_store.split_unknown_templates(db, str(p["unknown_id"]), [str(x) for x in p.get("template_ids") or []],
                                                         str(p["new_unknown_id"]))
        await db.commit()
    return {"moved": moved}


async def unknown_delete(p: dict[str, Any]) -> Any:
    async with AsyncSessionLocal() as db:
        n = await face_store.delete_unknown(db, str(p["unknown_id"]))
        await db.commit()
    return {"deleted": n}


async def media_get(p: dict[str, Any]) -> Any:
    ref = str(p.get("ref") or "")
    if not ref.startswith(("det:", "unk:", "tpl:", "emp:")):
        return None  # only references -- never an arbitrary path from the network
    async with AsyncSessionLocal() as db:
        path = await face_store.photo_path(db, ref)
    if path is None:
        return None
    data = path.read_bytes()
    if len(data) > MAX_PHOTO_BYTES:
        return None
    return {"b64": base64.b64encode(data).decode(), "content_type": "image/jpeg"}


async def policy_search(p: dict[str, Any]) -> Any:
    from app.services.chatbot.policy import get_index

    return get_index().search(str(p.get("query") or "")[:500], k=min(int(p.get("k") or 3), 8))


async def policy_status(_p: dict[str, Any]) -> Any:
    from app.services.chatbot.policy import get_index

    st = get_index().status()
    st["folder"] = "(edge box) " + st.get("folder", "")
    return st


async def policy_reindex(_p: dict[str, Any]) -> Any:
    from app.services.chatbot.policy import get_index

    idx = get_index()
    idx.refresh(force=True)
    return idx.status()


async def ping(_p: dict[str, Any]) -> Any:
    from app.edge.state import state

    return {"pong": True, "licence": state.licence_state().reason}


HANDLERS: dict[str, Handler] = {
    "enroll": enroll,
    "templates.list": templates_list,
    "templates.delete": templates_delete,
    "templates.purge": templates_purge,
    "templates.counts": templates_counts,
    "unknown.adopt": unknown_adopt,
    "unknown.split": unknown_split,
    "unknown.delete": unknown_delete,
    "media.get": media_get,
    "policy.search": policy_search,
    "policy.status": policy_status,
    "policy.reindex": policy_reindex,
    "ping": ping,
}


async def handle(method: str, params: dict[str, Any]) -> Any:
    fn = HANDLERS.get(method)
    if fn is None:
        raise ValueError(f"unknown method {method}")
    return await fn(params)
