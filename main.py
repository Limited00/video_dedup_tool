"""
视频去重工具 - 入口文件
======================
基于 Python + PyQt6 + OpenCV 的桌面 GUI 工具。
以标准参照视频为基准，自动识别并裁切待处理视频中的重复片段。

用法:
    python main.py              # 启动 GUI
    python main.py --cli        # 命令行模式（开发中）
"""

import sys
import os

# 确保项目目录在 Python 路径中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon

from app.main_window import MainWindow
from app.logger import setup_logging, get_logger


def main():
    """主入口"""
    # 高 DPI 支持
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("VideoDedupTool")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("VideoDedup")

    # 设置应用图标（使用 Windows 内置图标作为占位）
    try:
        from PyQt6.QtGui import QIcon
        app.setWindowIcon(QIcon())
    except Exception:
        pass

    # 初始化日志
    setup_logging()
    logger = get_logger("VideoDedup")
    logger.info("=" * 60)
    logger.info("视频去重工具 v1.0 启动")
    logger.info("=" * 60)

    # 创建并显示主窗口
    window = MainWindow()
    window.show()

    # 运行事件循环
    exit_code = app.exec()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
