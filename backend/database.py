import json
import aiosqlite
from backend.config import DB_PATH, DEFAULT_PROVIDERS_PATH

_db: aiosqlite.Connection | None = None


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        _db = await aiosqlite.connect(DB_PATH)
        _db.row_factory = aiosqlite.Row
        await _db.execute("PRAGMA journal_mode=WAL")
        await _db.execute("PRAGMA foreign_keys=ON")
    return _db


async def close_db():
    global _db
    if _db:
        await _db.close()
        _db = None


async def init_db():
    db = await get_db()
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            password TEXT NOT NULL,
            access_token TEXT,
            refresh_token TEXT,
            id_token TEXT,
            account_id TEXT,
            token_expired_at TEXT,
            temp_email_provider TEXT,
            proxy_used TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            error_message TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS email_providers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            base_url TEXT NOT NULL,
            origin TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            fail_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS proxies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL UNIQUE,
            proxy_type TEXT NOT NULL DEFAULT 'http',
            enabled INTEGER NOT NULL DEFAULT 1,
            fail_count INTEGER NOT NULL DEFAULT 0,
            last_test_ok INTEGER,
            last_test_ms INTEGER,
            last_test_info TEXT,
            last_test_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            thread_count INTEGER NOT NULL DEFAULT 5,
            default_password TEXT NOT NULL DEFAULT '',
            default_proxy TEXT NOT NULL DEFAULT 'http://127.0.0.1:7897',
            registration_delay_min INTEGER NOT NULL DEFAULT 5,
            registration_delay_max INTEGER NOT NULL DEFAULT 30,
            email_poll_timeout INTEGER NOT NULL DEFAULT 120,
            auto_switch_provider INTEGER NOT NULL DEFAULT 1
        );

        INSERT OR IGNORE INTO settings (id) VALUES (1);
    """)
    await db.commit()
    # 兼容旧数据库：补齐 proxies 表缺失的列
    await _migrate_proxies_columns(db)
    # 修正旧数据库中过短的 email_poll_timeout
    await _migrate_email_poll_timeout(db)


async def _migrate_proxies_columns(db: aiosqlite.Connection):
    """为旧数据库补齐 proxies 表的 last_test_* 列"""
    cursor = await db.execute("PRAGMA table_info(proxies)")
    existing = {row[1] for row in await cursor.fetchall()}
    migrations = [
        ("last_test_ok", "INTEGER"),
        ("last_test_ms", "INTEGER"),
        ("last_test_info", "TEXT"),
        ("last_test_at", "TEXT"),
    ]
    for col, col_type in migrations:
        if col not in existing:
            await db.execute(f"ALTER TABLE proxies ADD COLUMN {col} {col_type}")
    await db.commit()


async def _migrate_email_poll_timeout(db: aiosqlite.Connection):
    """旧数据库 email_poll_timeout 太短(35s)，自动升到 120s"""
    cursor = await db.execute("SELECT email_poll_timeout FROM settings WHERE id = 1")
    row = await cursor.fetchone()
    if row and row[0] < 60:
        await db.execute("UPDATE settings SET email_poll_timeout = 120 WHERE id = 1")
        await db.commit()


async def import_default_providers():
    """导入默认邮箱提供商（跳过已存在的）"""
    db = await get_db()
    try:
        with open(DEFAULT_PROVIDERS_PATH, "r", encoding="utf-8") as f:
            providers = json.load(f)
    except FileNotFoundError:
        return 0

    count = 0
    for p in providers:
        try:
            await db.execute(
                "INSERT OR IGNORE INTO email_providers (name, base_url, origin) VALUES (?, ?, ?)",
                (p["name"], p["base_url"], p["origin"]),
            )
            count += 1
        except Exception:
            pass
    await db.commit()
    return count


# ── Account CRUD ──

async def get_accounts(status: str | None = None, limit: int = 200, offset: int = 0):
    db = await get_db()
    if status:
        cursor = await db.execute(
            "SELECT * FROM accounts WHERE status = ? ORDER BY id DESC LIMIT ? OFFSET ?",
            (status, limit, offset),
        )
    else:
        cursor = await db.execute(
            "SELECT * FROM accounts ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
    return [dict(r) for r in await cursor.fetchall()]


async def get_accounts_count(status: str | None = None) -> int:
    db = await get_db()
    if status:
        cursor = await db.execute("SELECT COUNT(*) FROM accounts WHERE status = ?", (status,))
    else:
        cursor = await db.execute("SELECT COUNT(*) FROM accounts")
    row = await cursor.fetchone()
    return row[0]


async def create_account(email: str, password: str, **kwargs) -> int:
    db = await get_db()
    cols = ["email", "password"] + list(kwargs.keys())
    vals = [email, password] + list(kwargs.values())
    placeholders = ", ".join(["?"] * len(vals))
    col_names = ", ".join(cols)
    cursor = await db.execute(
        f"INSERT INTO accounts ({col_names}) VALUES ({placeholders})", vals
    )
    await db.commit()
    return cursor.lastrowid


async def update_account(row_id: int, **kwargs):
    if not kwargs:
        return
    db = await get_db()
    _allowed = {
        "email", "password", "access_token", "refresh_token", "id_token",
        "account_id", "token_expired_at", "temp_email_provider", "proxy_used",
        "status", "error_message",
    }
    sets = []
    vals = []
    for k, v in kwargs.items():
        if k not in _allowed:
            continue
        sets.append(f"{k} = ?")
        vals.append(v)
    if not sets:
        return
    sets.append("updated_at = datetime('now')")
    vals.append(row_id)
    await db.execute(f"UPDATE accounts SET {', '.join(sets)} WHERE id = ?", vals)
    await db.commit()


async def delete_account(account_id: int):
    db = await get_db()
    await db.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
    await db.commit()


# ── Provider CRUD ──

async def get_providers(enabled_only: bool = False):
    db = await get_db()
    if enabled_only:
        cursor = await db.execute(
            "SELECT * FROM email_providers WHERE enabled = 1 ORDER BY fail_count ASC"
        )
    else:
        cursor = await db.execute("SELECT * FROM email_providers ORDER BY id")
    return [dict(r) for r in await cursor.fetchall()]


async def create_provider(name: str, base_url: str, origin: str, enabled: bool = True) -> int:
    db = await get_db()
    cursor = await db.execute(
        "INSERT INTO email_providers (name, base_url, origin, enabled) VALUES (?, ?, ?, ?)",
        (name, base_url, origin, int(enabled)),
    )
    await db.commit()
    return cursor.lastrowid


async def update_provider(provider_id: int, **kwargs):
    if not kwargs:
        return
    db = await get_db()
    sets = []
    vals = []
    for k, v in kwargs.items():
        if k == "enabled":
            v = int(v)
        sets.append(f"{k} = ?")
        vals.append(v)
    vals.append(provider_id)
    await db.execute(f"UPDATE email_providers SET {', '.join(sets)} WHERE id = ?", vals)
    await db.commit()


async def delete_provider(provider_id: int):
    db = await get_db()
    await db.execute("DELETE FROM email_providers WHERE id = ?", (provider_id,))
    await db.commit()


async def increment_provider_fail(provider_id: int):
    db = await get_db()
    await db.execute(
        "UPDATE email_providers SET fail_count = fail_count + 1 WHERE id = ?",
        (provider_id,),
    )
    await db.commit()


# ── Proxy CRUD ──

async def get_proxies(enabled_only: bool = False):
    db = await get_db()
    if enabled_only:
        cursor = await db.execute(
            "SELECT * FROM proxies WHERE enabled = 1 ORDER BY fail_count ASC"
        )
    else:
        cursor = await db.execute("SELECT * FROM proxies ORDER BY id")
    return [dict(r) for r in await cursor.fetchall()]


async def create_proxy(url: str, proxy_type: str = "http", enabled: bool = True) -> int:
    db = await get_db()
    cursor = await db.execute(
        "INSERT INTO proxies (url, proxy_type, enabled) VALUES (?, ?, ?)",
        (url, proxy_type, int(enabled)),
    )
    await db.commit()
    return cursor.lastrowid


async def update_proxy(proxy_id: int, **kwargs):
    if not kwargs:
        return
    db = await get_db()
    sets = []
    vals = []
    for k, v in kwargs.items():
        if k == "enabled":
            v = int(v)
        if v == "datetime('now')":
            sets.append(f"{k} = datetime('now')")
        else:
            sets.append(f"{k} = ?")
            vals.append(v)
    vals.append(proxy_id)
    await db.execute(f"UPDATE proxies SET {', '.join(sets)} WHERE id = ?", vals)
    await db.commit()


async def delete_proxy(proxy_id: int):
    db = await get_db()
    await db.execute("DELETE FROM proxies WHERE id = ?", (proxy_id,))
    await db.commit()


async def increment_proxy_fail(proxy_id: int):
    db = await get_db()
    await db.execute(
        "UPDATE proxies SET fail_count = fail_count + 1 WHERE id = ?",
        (proxy_id,),
    )
    await db.commit()


# ── Statistics ──

async def get_stats() -> dict:
    db = await get_db()
    cursor = await db.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success,
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
            SUM(CASE WHEN status = 'registering' THEN 1 ELSE 0 END) as registering,
            SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending
        FROM accounts
    """)
    row = await cursor.fetchone()
    total = row[0] or 0
    success = row[1] or 0
    failed = row[2] or 0
    registering = row[3] or 0
    pending = row[4] or 0
    return {
        "total": total,
        "success": success,
        "failed": failed,
        "registering": registering,
        "pending": pending,
        "success_rate": round(success / (success + failed) * 100, 1) if (success + failed) > 0 else 0,
    }


# ── Settings ──

async def get_settings() -> dict:
    db = await get_db()
    cursor = await db.execute("SELECT * FROM settings WHERE id = 1")
    row = await cursor.fetchone()
    if row:
        d = dict(row)
        d["auto_switch_provider"] = bool(d["auto_switch_provider"])
        return d
    return {}


async def update_settings(**kwargs):
    if not kwargs:
        return
    db = await get_db()
    sets = []
    vals = []
    for k, v in kwargs.items():
        if k == "auto_switch_provider":
            v = int(v)
        sets.append(f"{k} = ?")
        vals.append(v)
    await db.execute(f"UPDATE settings SET {', '.join(sets)} WHERE id = 1", vals)
    await db.commit()
