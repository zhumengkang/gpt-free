"""PyInstaller 入口 — 解决打包后路径问题"""
import os
import sys
import multiprocessing

def main():
    multiprocessing.freeze_support()

    # PyInstaller 打包后 _MEIPASS 指向临时解压目录
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))

    # 把 base 加入 sys.path，让 backend 包可以被 import
    if base not in sys.path:
        sys.path.insert(0, base)

    # 设置工作目录为可执行文件所在目录（数据库等文件放这里）
    exe_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    os.chdir(exe_dir)

    # 覆盖 config 里的路径
    import backend.config as cfg
    cfg.BASE_DIR = exe_dir
    cfg.DB_PATH = os.path.join(exe_dir, "data.sqlite3")
    cfg.STATIC_DIR = os.path.join(base, "frontend", "dist")
    cfg.DEFAULT_PROVIDERS_PATH = os.path.join(base, "backend", "default_providers.json")

    import uvicorn
    print(f"GPT-Free starting on http://0.0.0.0:{cfg.PORT}")
    print(f"Data dir: {exe_dir}")
    uvicorn.run("backend.main:app", host=cfg.HOST, port=cfg.PORT)

if __name__ == "__main__":
    main()
