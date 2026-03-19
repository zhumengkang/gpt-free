"""代理池路由"""
import time
import asyncio
import httpx
from fastapi import APIRouter, HTTPException, BackgroundTasks
from backend import database as db
from backend.models import ProxyOut, ProxyCreate, ProxyBatchCreate, ProxyUpdate

router = APIRouter(prefix="/api/proxies", tags=["proxies"])


async def _test_one_proxy(row: dict) -> dict:
    """测试单个代理，返回结果并写入数据库"""
    start = time.time()
    ok = False
    ms = 0
    info = ""
    err = ""
    try:
        async with httpx.AsyncClient(proxy=row["url"], timeout=10, verify=False) as client:
            resp = await client.get("https://cloudflare.com/cdn-cgi/trace")
            ms = int((time.time() - start) * 1000)
            if resp.status_code == 200:
                ok = True
                info = resp.text[:200]
            else:
                err = f"HTTP {resp.status_code}"
    except Exception as e:
        ms = int((time.time() - start) * 1000)
        err = str(e)[:200]

    # 写入数据库，失败不影响返回结果
    try:
        await db.update_proxy(
            row["id"],
            last_test_ok=1 if ok else 0,
            last_test_ms=ms,
            last_test_info=info if ok else err,
            last_test_at="datetime('now')",
        )
    except Exception:
        pass

    if ok:
        return {"id": row["id"], "ok": True, "ms": ms, "info": info}
    return {"id": row["id"], "ok": False, "ms": ms, "error": err}


@router.get("")
async def list_proxies():
    rows = await db.get_proxies()
    return [_fix(r) for r in rows]


@router.post("")
async def add_proxy(body: ProxyCreate):
    try:
        pid = await db.create_proxy(body.url, body.proxy_type, body.enabled)
    except Exception as e:
        raise HTTPException(400, f"添加失败: {e}")
    rows = await db.get_proxies()
    row = next((r for r in rows if r["id"] == pid), None)
    if not row:
        raise HTTPException(500, "创建后未找到记录")
    return _fix(row)


@router.post("/batch")
async def batch_add_proxies(body: ProxyBatchCreate):
    added = 0
    for url in body.proxies:
        url = url.strip()
        if not url:
            continue
        try:
            await db.create_proxy(url, body.proxy_type)
            added += 1
        except Exception:
            pass
    return {"added": added}


@router.put("/{proxy_id}")
async def update_proxy(proxy_id: int, body: ProxyUpdate):
    data = body.model_dump(exclude_none=True)
    if data:
        await db.update_proxy(proxy_id, **data)
    rows = await db.get_proxies()
    row = next((r for r in rows if r["id"] == proxy_id), None)
    if not row:
        raise HTTPException(404, "Proxy not found")
    return _fix(row)


@router.post("/batch-delete")
async def batch_delete_proxies(body: dict):
    ids = body.get("ids", [])
    if not ids:
        raise HTTPException(400, "请选择至少一个代理")
    deleted = 0
    for pid in ids:
        try:
            await db.delete_proxy(int(pid))
            deleted += 1
        except Exception:
            pass
    return {"deleted": deleted}


@router.post("/batch-test")
async def batch_test_proxies(background_tasks: BackgroundTasks):
    """批量测试所有启用的代理（后台执行）"""
    rows = await db.get_proxies(enabled_only=True)
    if not rows:
        return {"message": "没有启用的代理", "testing": 0}

    async def _run():
        for row in rows:
            await _test_one_proxy(row)

    background_tasks.add_task(_run)
    return {"message": f"开始测试 {len(rows)} 个代理", "testing": len(rows)}


@router.delete("/{proxy_id}")
async def delete_proxy(proxy_id: int):
    await db.delete_proxy(proxy_id)
    return {"ok": True}


@router.post("/{proxy_id}/test")
async def test_proxy(proxy_id: int):
    rows = await db.get_proxies()
    row = next((r for r in rows if r["id"] == proxy_id), None)
    if not row:
        raise HTTPException(404, "Proxy not found")
    return await _test_one_proxy(row)


def _fix(row: dict) -> dict:
    row = dict(row)
    row["enabled"] = bool(row.get("enabled"))
    row["last_test_ok"] = bool(row["last_test_ok"]) if row.get("last_test_ok") is not None else None
    return row
