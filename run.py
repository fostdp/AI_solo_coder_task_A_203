"""
启动脚本 - 古代筒车轴承水润滑流场仿真与摩擦功耗分析系统
快速启动后端服务器
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import uvicorn

if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))

    print("=" * 60)
    print("  古代筒车轴承水润滑流场仿真与摩擦功耗分析系统")
    print("=" * 60)
    print(f"  服务器地址: http://{host}:{port}")
    print(f"  API文档: http://{host}:{port}/docs")
    print(f"  前端页面: http://{host}:{port}/app")
    print("=" * 60)
    print()

    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=True,
    )
