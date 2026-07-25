"""
风调预顺 PHM 便携版启动器
嵌入式 Python 的 ._pth 会限制 sys.path, 此脚本手动注入路径后启动 uvicorn。
"""
import sys, os
BACKEND = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BACKEND)
for d in (BACKEND, ROOT):
    if d not in sys.path:
        sys.path.insert(0, d)
import uvicorn
uvicorn.run("app.main:app", host="127.0.0.1", port=8000, log_level="info")
