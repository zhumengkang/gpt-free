"""设置路由"""
from fastapi import APIRouter
from backend import database as db
from backend.models import SettingsOut, SettingsUpdate

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=SettingsOut)
async def get_settings():
    return await db.get_settings()


@router.put("", response_model=SettingsOut)
async def update_settings(body: SettingsUpdate):
    data = body.model_dump(exclude_none=True)
    if data:
        await db.update_settings(**data)
    return await db.get_settings()
