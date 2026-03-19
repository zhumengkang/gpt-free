"""注册任务路由"""
from fastapi import APIRouter, HTTPException
from backend import database as db
from backend.models import RegistrationStart, RegistrationStatus
from backend.task_manager import task_manager

router = APIRouter(prefix="/api/registration", tags=["registration"])


@router.post("/start")
async def start_registration(body: RegistrationStart):
    if body.count < 1 or body.count > 100:
        raise HTTPException(400, "注册数量需在 1-100 之间")

    settings = await db.get_settings()
    providers = await db.get_providers(enabled_only=True)
    proxies = await db.get_proxies(enabled_only=True)

    if not providers:
        raise HTTPException(400, "没有启用的邮箱提供商，请先配置")

    try:
        task_manager.start(
            count=body.count,
            thread_count=settings["thread_count"],
            password=settings["default_password"],
            default_proxy=settings.get("default_proxy", ""),
            providers=providers,
            proxies=proxies,
            email_poll_timeout=settings["email_poll_timeout"],
            delay_min=settings["registration_delay_min"],
            delay_max=settings["registration_delay_max"],
        )
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return {"ok": True, "message": f"已启动 {body.count} 个注册任务"}


@router.post("/stop")
async def stop_registration():
    task_manager.stop()
    return {"ok": True}


@router.get("/status", response_model=RegistrationStatus)
async def registration_status():
    return task_manager.status
