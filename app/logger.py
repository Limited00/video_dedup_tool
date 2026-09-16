"""
日志管理模块
-----------
提供文件日志和内存日志（供 GUI 显示）双通道。
"""

import logging
import logging.handlers
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Callable

from .config import get_app_data_dir


# 内存日志记录（供 GUI Log Viewer 使用）
class MemoryLogHandler(logging.Handler):
    """将日志记录保存在内存列表中，供 GUI 显示"""

    def __init__(self, max_records: int = 5000):
        super().__init__()
        self.max_records = max_records
        self.records: List[logging.LogRecord] = []
        self._callbacks: List[Callable] = []

    def emit(self, record: logging.LogRecord):
        self.records.append(record)
        if len(self.records) > self.max_records:
            self.records = self.records[-self.max_records:]
        for cb in self._callbacks:
            try:
                cb(record)
            except Exception:
                pass

    def add_callback(self, callback: Callable):
        """添加新日志记录回调"""
        self._callbacks.append(callback)

    def remove_callback(self, callback: Callable):
        """移除回调"""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def get_records(self, level: Optional[int] = None, count: int = 500) -> List[logging.LogRecord]:
        """获取最近的日志记录，可按级别过滤"""
        if level is not None:
            filtered = [r for r in self.records if r.levelno >= level]
        else:
            filtered = list(self.records)
        return filtered[-count:]

    def clear(self):
        self.records.clear()


# 全局单例
_memory_handler: Optional[MemoryLogHandler] = None
_logger_initialized = False


def get_memory_handler() -> MemoryLogHandler:
    """获取内存日志处理器"""
    global _memory_handler
    if _memory_handler is None:
        _memory_handler = MemoryLogHandler()
    return _memory_handler


def setup_logging(
    log_level: int = logging.INFO,
    max_records: int = 5000,
    log_to_file: bool = True
) -> logging.Logger:
    """
    初始化日志系统。
    返回根 logger，同时配置：
    - 控制台输出（StreamHandler）
    - 文件输出（RotatingFileHandler，10MB x 5）
    - 内存输出（MemoryLogHandler，供 GUI）
    """
    global _logger_initialized, _memory_handler

    root_logger = logging.getLogger("VideoDedup")
    root_logger.setLevel(log_level)

    # 避免重复初始化
    if _logger_initialized:
        return root_logger

    # 格式
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S"
    )
    file_formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(filename)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 控制台
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # 内存
    _memory_handler = MemoryLogHandler(max_records=max_records)
    _memory_handler.setLevel(logging.DEBUG)
    _memory_handler.setFormatter(formatter)
    root_logger.addHandler(_memory_handler)

    # 文件
    if log_to_file:
        log_dir = get_app_data_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"video_dedup_{datetime.now().strftime('%Y%m%d')}.log"
        file_handler = logging.handlers.RotatingFileHandler(
            str(log_file), maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)

    _logger_initialized = True
    root_logger.info(f"日志系统初始化完成，日志文件: {log_file}")
    return root_logger


def get_logger(name: str = "VideoDedup") -> logging.Logger:
    """获取指定名称的 logger"""
    return logging.getLogger(name)
