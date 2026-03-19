# GPT-Free

OpenAI 全自动注册 Web 服务。

## 快速启动

```bash
# 安装依赖
pip3 install -r requirements.txt
cd frontend && npm install && npx vite build && cd ..

# 启动服务（端口 12321）
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 12321
```

访问 http://localhost:12321

## 开发模式

```bash
# 后端
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 12321 --reload

# 前端（另一个终端）
cd frontend && npm run dev
```

## 技术栈

- 后端: FastAPI + aiosqlite + curl_cffi + httpx
- 前端: React + TypeScript + Vite + Tailwind CSS
- 数据库: SQLite3 (data.sqlite3)

## 项目结构

- `backend/` — FastAPI 后端
- `frontend/` — React 前端
- `Chick.py` — 原始注册脚本（保留）
- `data.sqlite3` — 运行时生成的数据库
