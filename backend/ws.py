"""WebSocket 日志推送"""
import asyncio
import traceback
from fastapi import WebSocket, WebSocketDisconnect

_clients: set[WebSocket] = set()
_log_queue: asyncio.Queue | None = None


def get_log_queue() -> asyncio.Queue:
    global _log_queue
    if _log_queue is None:
        _log_queue = asyncio.Queue(maxsize=5000)
    return _log_queue


async def ws_endpoint(ws: WebSocket):
    global _clients
    await ws.accept()
    _clients.add(ws)
    try:
        while True:
            try:
                msg = await ws.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
            except Exception:
                break
    except WebSocketDisconnect:
        pass
    finally:
        _clients.discard(ws)


async def broadcast(message: str):
    global _clients
    if not _clients:
        return
    dead = set()
    for ws in list(_clients):
        try:
            await ws.send_text(message)
        except Exception:
            dead.add(ws)
    if dead:
        _clients -= dead


async def log_broadcaster():
    """后台任务：从队列读取日志并广播"""
    queue = get_log_queue()
    while True:
        try:
            msg = await queue.get()
            await broadcast(msg)
        except asyncio.CancelledError:
            break
        except Exception:
            traceback.print_exc()
