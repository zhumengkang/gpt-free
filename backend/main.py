"""GPT-Free Web Service - FastAPI 入口"""
import asyncio
import json
import os
from datetime import datetime

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from backend.config import PORT, HOST, STATIC_DIR, API_KEY
from backend import database as db
from backend.ws import ws_endpoint, get_log_queue, log_broadcaster, _clients
from backend.task_manager import task_manager
from backend.routers import accounts, providers, proxies, registration, settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await db.init_db()
    await db.import_default_providers()

    loop = asyncio.get_running_loop()
    queue = get_log_queue()
    task_manager.set_log_queue(queue, loop)
    task_manager.set_db_callbacks(db.create_account, db.update_account)

    broadcaster = asyncio.create_task(log_broadcaster())

    yield

    # Shutdown
    task_manager.stop()
    broadcaster.cancel()
    await db.close_db()


app = FastAPI(title="GPT-Free", lifespan=lifespan)

# API Key 认证中间件（可选）
if API_KEY:
    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        path = request.url.path
        # 静态资源、WebSocket、前端页面不需要认证
        if not path.startswith("/api/"):
            return await call_next(request)
        # 检查 header 或 query param
        key = request.headers.get("x-api-key") or request.query_params.get("api_key")
        if key != API_KEY:
            return JSONResponse({"detail": "Invalid API key"}, status_code=401)
        return await call_next(request)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API 路由
app.include_router(accounts.router)
app.include_router(providers.router)
app.include_router(proxies.router)
app.include_router(registration.router)
app.include_router(settings.router)

# WebSocket
app.websocket("/ws/logs")(ws_endpoint)


@app.get("/api/debug/ws")
async def debug_ws():
    """调试：测试 WebSocket 日志推送"""
    queue = get_log_queue()
    ts = datetime.now().strftime("%H:%M:%S")
    msg = json.dumps({"time": ts, "message": "WebSocket 测试消息"}, ensure_ascii=False)
    await queue.put(msg)
    await asyncio.sleep(0.1)
    return {
        "ws_clients": len(_clients),
        "queue_size": queue.qsize(),
    }


@app.get("/api/debug/check-mail")
async def debug_check_mail(base_url: str, jwt: str):
    """调试：手动查看邮箱里的邮件，用于排查验证码收不到的问题
    用法: /api/debug/check-mail?base_url=https://lsmail.zhiyu.cloudns.be&jwt=xxx
    """
    import httpx
    try:
        async with httpx.AsyncClient(verify=False, timeout=15) as client:
            resp = await client.get(
                f"{base_url}/api/mails?limit=20&offset=0",
                headers={
                    "accept": "application/json, text/plain, */*",
                    "authorization": f"Bearer {jwt}",
                },
            )
            return {
                "status": resp.status_code,
                "data": resp.json() if resp.status_code == 200 else resp.text[:500],
            }
    except Exception as e:
        return {"error": str(e)}


# 前端静态文件 + SPA fallback
_index_html = os.path.join(STATIC_DIR, "index.html") if os.path.isdir(STATIC_DIR) else None

if os.path.isdir(STATIC_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(STATIC_DIR, "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(request: Request, full_path: str):
        """SPA fallback: 非 API/WS 路径都返回 index.html"""
        # 尝试静态文件
        file_path = os.path.join(STATIC_DIR, full_path)
        if full_path and os.path.isfile(file_path):
            return FileResponse(file_path)
        # fallback 到 index.html
        return FileResponse(_index_html)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host=HOST, port=PORT, reload=True)
