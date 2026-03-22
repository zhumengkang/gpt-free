import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data.sqlite3")
DEFAULT_PROVIDERS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "default_providers.json")

PORT = 12321
HOST = "0.0.0.0"

# OpenAI OAuth
AUTH_URL = "https://auth.openai.com/oauth/authorize"
TOKEN_URL = "https://auth.openai.com/oauth/token"
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
DEFAULT_REDIRECT_URI = "http://localhost:1455/auth/callback"
DEFAULT_SCOPE = "openid email profile offline_access"

# 前端静态文件
STATIC_DIR = os.path.join(BASE_DIR, "frontend", "dist")

# API 认证（可选）- 环境变量 GPT_FREE_API_KEY 或留空不启用
API_KEY = os.environ.get("GPT_FREE_API_KEY", "")

# 本地原始调试日志（仅本机文件，不走 WebSocket）- 默认开启
RAW_DEBUG_LOG_PATH = os.environ.get("GPT_FREE_RAW_DEBUG_LOG_PATH", "").strip() or os.path.join(BASE_DIR, "debug_raw.log")
