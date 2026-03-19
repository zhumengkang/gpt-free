"""账号路由 + 导出 + 批量删除 + 统计 + Token刷新"""
import csv
import io
import json
import time
import urllib.parse
import urllib.request
import urllib.error
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from backend import database as db
from backend.models import ExportRequest
from backend.config import TOKEN_URL, CLIENT_ID

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


@router.get("/stats")
async def get_stats():
    return await db.get_stats()


@router.get("")
async def list_accounts(status: str | None = None, limit: int = 200, offset: int = 0):
    rows = await db.get_accounts(status=status, limit=limit, offset=offset)
    total = await db.get_accounts_count(status=status)
    return {"items": rows, "total": total}


@router.delete("/failed")
async def delete_failed_accounts():
    """一键删除所有失败的账号"""
    d = await db.get_db()
    cursor = await d.execute("SELECT COUNT(*) FROM accounts WHERE status = 'failed'")
    row = await cursor.fetchone()
    count = row[0]
    await d.execute("DELETE FROM accounts WHERE status = 'failed'")
    await d.commit()
    return {"deleted": count}


@router.post("/batch-delete")
async def batch_delete_accounts(body: dict):
    ids = body.get("ids", [])
    if not ids:
        raise HTTPException(400, "请选择至少一个账号")
    deleted = 0
    for aid in ids:
        try:
            await db.delete_account(int(aid))
            deleted += 1
        except Exception:
            pass
    return {"deleted": deleted}


@router.delete("/{account_id}")
async def delete_account(account_id: int):
    await db.delete_account(account_id)
    return {"ok": True}


@router.post("/{account_id}/refresh-token")
async def refresh_account_token(account_id: int):
    """用 refresh_token 刷新 access_token"""
    rows = await db.get_accounts(limit=100000)
    row = next((r for r in rows if r["id"] == account_id), None)
    if not row:
        raise HTTPException(404, "账号不存在")
    rt = row.get("refresh_token")
    if not rt:
        raise HTTPException(400, "该账号没有 refresh_token")

    try:
        body = urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "refresh_token": rt,
        }).encode("utf-8")
        req = urllib.request.Request(
            TOKEN_URL, data=body, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        new_at = data.get("access_token", "")
        new_rt = data.get("refresh_token", rt)
        new_id = data.get("id_token", "")
        expires_in = int(data.get("expires_in", 0))
        expired_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(time.time()) + expires_in))

        await db.update_account(account_id, access_token=new_at, refresh_token=new_rt, id_token=new_id, token_expired_at=expired_at)
        return {"ok": True, "token_expired_at": expired_at}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")[:300]
        raise HTTPException(400, f"刷新失败: {raw}")
    except Exception as e:
        raise HTTPException(400, f"刷新失败: {str(e)[:200]}")


@router.post("/batch-refresh")
async def batch_refresh_tokens():
    """批量刷新所有成功账号的 token"""
    rows = await db.get_accounts(status="success", limit=100000)
    success = 0
    failed = 0
    for row in rows:
        rt = row.get("refresh_token")
        if not rt:
            failed += 1
            continue
        try:
            body = urllib.parse.urlencode({
                "grant_type": "refresh_token",
                "client_id": CLIENT_ID,
                "refresh_token": rt,
            }).encode("utf-8")
            req = urllib.request.Request(
                TOKEN_URL, data=body, method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            new_at = data.get("access_token", "")
            new_rt = data.get("refresh_token", rt)
            new_id = data.get("id_token", "")
            expires_in = int(data.get("expires_in", 0))
            expired_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(time.time()) + expires_in))
            await db.update_account(row["id"], access_token=new_at, refresh_token=new_rt, id_token=new_id, token_expired_at=expired_at)
            success += 1
        except Exception:
            failed += 1
    return {"success": success, "failed": failed}


@router.post("/export")
async def export_accounts(body: ExportRequest):
    if body.ids:
        all_rows = await db.get_accounts(status=body.status_filter, limit=100000)
        rows = [r for r in all_rows if r["id"] in body.ids]
    else:
        rows = await db.get_accounts(status=body.status_filter, limit=100000)
    fields = body.fields

    if not fields:
        raise HTTPException(400, "请选择至少一个导出字段")

    if body.format == "json":
        filtered = [{k: r.get(k) for k in fields} for r in rows]
        content = json.dumps(filtered, ensure_ascii=False, indent=2)
        return StreamingResponse(
            io.BytesIO(content.encode("utf-8")),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=accounts.json"},
        )

    elif body.format == "csv":
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fields)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in fields})
        return StreamingResponse(
            io.BytesIO(buf.getvalue().encode("utf-8-sig")),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=accounts.csv"},
        )

    elif body.format == "txt":
        lines = []
        for r in rows:
            parts = [str(r.get(k, "")) for k in fields]
            lines.append(" | ".join(parts))
        content = "\n".join(lines)
        return StreamingResponse(
            io.BytesIO(content.encode("utf-8")),
            media_type="text/plain",
            headers={"Content-Disposition": "attachment; filename=accounts.txt"},
        )

    raise HTTPException(400, f"不支持的格式: {body.format}")
