"""无头命令行入口（薄封装）。

等价于 ``python main.py --cli`` 或 ``python -m app.cli``。
Docker 镜像以此文件作为 ENTRYPOINT。
"""

import sys

from app.cli import main as cli_main

if __name__ == "__main__":
    sys.exit(cli_main())
