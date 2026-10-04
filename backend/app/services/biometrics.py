"""Where faces live, for the dashboard API.

standalone: this database / disk (services/face_store.py).
cloud:      the tenant's edge box, over the tunnel (app/edge_hub.py) -- the
            cloud keeps only ids, counts and photo references.

Routers call these functions and never care which one it is.
"""
from __future__ import annotations

import base64
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.employees import Employee
from app.models.enums import OwnerType
from app.services import face_store


def cloud() -> bool:
    return get_settings().role == "cloud"


async def _call(method: str, params: dict[str, Any], timeout: float = 30.0) -> Any:
    from app.edge_hub import edge_call

    return await edge_call(method, params, timeout)


async def _set_face_count(db: AsyncSession, employee_id: str, n: int) -> None:
    await db.execute(update(Employee).where(Employee.id == employee_id).values(face_count=int(n)))


async def enroll(db: AsyncSession, employee_id: str, images: list[tuple[str, bytes]], min_face_pixels: int) -> dict[str, Any]:
    if cloud():
        res = await _call("enroll", {"employee_id": employee_id, "min_face_pixels": min_face_pixels,
                                     "images": [{"filename": n, "b64": base64.b64encode(b).decode()} for n, b in images]},
                          timeout=120)
        await _set_face_count(db, employee_id, int(res.get("template_count", 0)))
        return dict(res)
    return await face_store.enroll_images(db, employee_id, images, min_face_pixels)


async def list_templates(db: AsyncSession, owner_type: OwnerType, owner_id: str) -> list[dict[str, Any]]:
    if cloud():
        return list(await _call("templates.list", {"owner_type": owner_type.value, "owner_id": owner_id}))
    return await face_store.list_templates(db, owner_type, owner_id)


async def delete_template(db: AsyncSession, owner_type: OwnerType, owner_id: str, template_id: str) -> bool:
    if cloud():
        res = await _call("templates.delete", {"owner_type": owner_type.value, "owner_id": owner_id, "template_id": template_id})
        if owner_type == OwnerType.EMPLOYEE:
            await _set_face_count(db, owner_id, int(res.get("template_count", 0)))
        return bool(res.get("deleted"))
    return await face_store.delete_template(db, owner_type, owner_id, template_id)


async def purge(db: AsyncSession, owner_type: OwnerType, owner_id: str) -> None:
    """Erase a person's face data (delete / consent withdrawn). In the cloud
    this needs the box online: erasure must really happen, so a failure is
    reported instead of pretending."""
    if cloud():
        await _call("templates.purge", {"owner_type": owner_type.value, "owner_id": owner_id})
        if owner_type == OwnerType.EMPLOYEE:
            await _set_face_count(db, owner_id, 0)
        return
    await face_store.purge_owner(db, owner_type, owner_id)


async def counts(db: AsyncSession, employee_ids: list[str]) -> dict[str, int]:
    if cloud():
        rows = await db.execute(select(Employee.id, Employee.face_count).where(Employee.id.in_(employee_ids)))
        return {i: int(n or 0) for i, n in rows.all()}
    return await face_store.count_templates(db, OwnerType.EMPLOYEE, employee_ids)


async def adopt_unknown(db: AsyncSession, unknown_id: str, employee_id: str, *, min_quality: float,
                        capacity: int | None, delete_rest: bool) -> None:
    """Cloud only (standalone moves the templates inside link / promote)."""
    if cloud():
        res = await _call("unknown.adopt", {"unknown_id": unknown_id, "employee_id": employee_id, "min_quality": min_quality,
                                            "capacity": capacity, "delete_rest": delete_rest})
        await _set_face_count(db, employee_id, int(res.get("template_count", 0)))


async def split_unknown(unknown_id: str, template_ids: list[str], new_unknown_id: str) -> int:
    res = await _call("unknown.split", {"unknown_id": unknown_id, "template_ids": template_ids,
                                        "new_unknown_id": new_unknown_id})
    return int(res.get("moved", 0))


async def delete_unknown(db: AsyncSession, unknown_id: str) -> None:
    if cloud():
        await _call("unknown.delete", {"unknown_id": unknown_id})


async def photo(db: AsyncSession, ref: str | None) -> bytes | None:
    """JPEG bytes for a stored photo path / reference, or None."""
    if not ref:
        return None
    if cloud():
        if not ref.startswith(("det:", "unk:", "tpl:", "emp:")):
            return None  # a pre-SaaS local path: not on this server
        res = await _call("media.get", {"ref": ref})
        return base64.b64decode(res["b64"]) if res and res.get("b64") else None
    p = await face_store.photo_path(db, ref)
    return p.read_bytes() if p else None


async def policy_search(query: str, k: int = 3) -> list[dict[str, Any]]:
    if cloud():
        try:
            return list(await _call("policy.search", {"query": query, "k": k}, timeout=15))
        except Exception:  # noqa: BLE001 - chatbot answers without policy text when the box is offline
            return []
    from app.services.chatbot.policy import get_index

    return get_index().search(query, k=k)


async def policy_status() -> dict[str, Any]:
    if cloud():
        try:
            return dict(await _call("policy.status", {}, timeout=10))
        except Exception:  # noqa: BLE001
            return {"files": [], "chunks": 0, "exists": False, "errors": ["edge box offline"], "folder": "(edge box)"}
    from app.services.chatbot.policy import get_index

    return get_index().status()


async def policy_reindex() -> dict[str, Any]:
    if cloud():
        return dict(await _call("policy.reindex", {}, timeout=60))
    from app.services.chatbot.policy import get_index

    idx = get_index()
    idx.refresh(force=True)
    return idx.status()


def config_changed() -> None:
    """Cloud: tell the tenant's edge box (settings, camera tokens or people
    changed) instead of waiting for its next poll. Fire and forget."""
    if not cloud():
        return
    import asyncio

    from app.tenancy import current_tenant

    tenant = current_tenant.get()
    if tenant is None:
        return

    async def _push() -> None:
        from app.routers.edge import push_config

        await push_config(tenant)

    try:
        asyncio.get_running_loop().create_task(_push())
    except RuntimeError:
        pass
