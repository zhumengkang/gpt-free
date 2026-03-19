"""邮箱提供商路由"""
import httpx
from fastapi import APIRouter, HTTPException
from backend import database as db
from backend.models import ProviderOut, ProviderCreate, ProviderUpdate

router = APIRouter(prefix="/api/providers", tags=["providers"])


@router.get("", response_model=list[ProviderOut])
async def list_providers():
    rows = await db.get_providers()
    return [_fix_bool(r) for r in rows]


@router.post("", response_model=ProviderOut)
async def add_provider(body: ProviderCreate):
    try:
        pid = await db.create_provider(body.name, body.base_url, body.origin, body.enabled)
    except Exception as e:
        raise HTTPException(400, f"添加失败: {e}")
    rows = await db.get_providers()
    row = next((r for r in rows if r["id"] == pid), None)
    if not row:
        raise HTTPException(500, "创建后未找到记录")
    return _fix_bool(row)


@router.put("/{provider_id}", response_model=ProviderOut)
async def update_provider(provider_id: int, body: ProviderUpdate):
    data = body.model_dump(exclude_none=True)
    if data:
        await db.update_provider(provider_id, **data)
    rows = await db.get_providers()
    row = next((r for r in rows if r["id"] == provider_id), None)
    if not row:
        raise HTTPException(404, "Provider not found")
    return _fix_bool(row)


@router.delete("/{provider_id}")
async def delete_provider(provider_id: int):
    await db.delete_provider(provider_id)
    return {"ok": True}


@router.post("/{provider_id}/test")
async def test_provider(provider_id: int):
    rows = await db.get_providers()
    row = next((r for r in rows if r["id"] == provider_id), None)
    if not row:
        raise HTTPException(404, "Provider not found")

    try:
        async with httpx.AsyncClient(verify=False, timeout=10) as client:
            url = f"{row['base_url']}/open_api/settings"
            resp = await client.get(
                url,
                headers={
                    "accept": "application/json",
                    "origin": row["origin"],
                    "referer": f"{row['origin']}/",
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                domains = data.get("defaultDomains") or data.get("default_domains") or []
                return {"ok": True, "domains": domains}
            return {"ok": False, "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


@router.post("/import-defaults")
async def import_defaults():
    count = await db.import_default_providers()
    return {"imported": count}


def _fix_bool(row: dict) -> dict:
    row = dict(row)
    row["enabled"] = bool(row.get("enabled"))
    return row
