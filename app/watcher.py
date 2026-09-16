"""
文件夹监控模块
--------------
基于 watchdog 库实现文件夹变化监控。
当监控目录中出现新视频文件时，自动触发处理流程。
"""

import os
import time
import logging
from typing import List, Callable, Optional, Set
from pathlib import Path

logger = logging.getLogger("VideoDedup.Watcher")

# 支持的视频文件扩展名
VIDEO_EXTENSIONS = {
    ".mp4", ".avi", ".mov", ".mkv", ".wmv", ".flv", ".webm",
    ".m4v", ".mpg", ".mpeg", ".3gp", ".ts", ".mts", ".m2ts",
    ".rmvb", ".asf", ".divx", ".xvid",
}


def is_video_file(filepath: str) -> bool:
    """判断是否为支持的视频文件"""
    ext = os.path.splitext(filepath)[1].lower()
    return ext in VIDEO_EXTENSIONS


class FolderWatcher:
    """
    文件夹监控器。

    使用轮询方式监控文件夹变化（兼容性更好，无需 watchdog 的事件系统依赖）。
    支持 watchdog 可选依赖作为更高效的替代。
    """

    def __init__(
        self,
        watch_dirs: List[str],
        on_new_file: Callable[[str], None],
        interval: int = 5,
        recursive: bool = True,
    ):
        """
        初始化监控器。

        Args:
            watch_dirs: 要监控的目录列表
            on_new_file: 发现新文件时的回调 (file_path) -> None
            interval: 扫描间隔（秒）
            recursive: 是否递归扫描子目录
        """
        self.watch_dirs = [os.path.abspath(d) for d in watch_dirs if os.path.isdir(d)]
        self.on_new_file = on_new_file
        self.interval = interval
        self.recursive = recursive
        self._known_files: Set[str] = set()
        self._running = False
        self._stop_flag = False

    def initial_scan(self) -> List[str]:
        """初始扫描，返回所有已存在的视频文件"""
        existing = []
        for watch_dir in self.watch_dirs:
            if not os.path.isdir(watch_dir):
                continue
            for root, dirs, files in os.walk(watch_dir):
                for f in files:
                    filepath = os.path.join(root, f)
                    if is_video_file(filepath):
                        existing.append(filepath)
                        self._known_files.add(filepath)
                if not self.recursive:
                    break
        logger.info(f"初始扫描完成: {len(existing)} 个已知视频文件")
        return existing

    def scan(self) -> List[str]:
        """扫描新文件，返回新增的视频文件列表"""
        new_files = []
        for watch_dir in self.watch_dirs:
            if not os.path.isdir(watch_dir):
                continue
            for root, dirs, files in os.walk(watch_dir):
                for f in files:
                    filepath = os.path.join(root, f)
                    if is_video_file(filepath) and filepath not in self._known_files:
                        new_files.append(filepath)
                        self._known_files.add(filepath)
                if not self.recursive:
                    break
        return new_files

    def add_watch_dir(self, directory: str):
        """添加监控目录"""
        abs_dir = os.path.abspath(directory)
        if os.path.isdir(abs_dir) and abs_dir not in self.watch_dirs:
            self.watch_dirs.append(abs_dir)
            logger.info(f"添加监控目录: {abs_dir}")

    def remove_watch_dir(self, directory: str):
        """移除监控目录"""
        abs_dir = os.path.abspath(directory)
        if abs_dir in self.watch_dirs:
            self.watch_dirs.remove(abs_dir)
            logger.info(f"移除监控目录: {abs_dir}")

    def stop(self):
        """停止监控"""
        self._stop_flag = True
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running


# 尝试导入 watchdog 以获得更高效的事件驱动监控
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler

    class WatchdogEventHandler(FileSystemEventHandler):
        """watchdog 事件处理器"""

        def __init__(self, callback: Callable[[str], None], known_files: Set[str]):
            super().__init__()
            self.callback = callback
            self.known_files = known_files

        def on_created(self, event):
            if not event.is_directory:
                filepath = event.src_path
                if is_video_file(filepath) and filepath not in self.known_files:
                    self.known_files.add(filepath)
                    # 等待文件写入完成
                    time.sleep(1)
                    if os.path.exists(filepath):
                        logger.info(f"发现新视频: {filepath}")
                        self.callback(filepath)

    class WatchdogWatcher:
        """基于 watchdog 的高效文件夹监控器"""

        def __init__(
            self,
            watch_dirs: List[str],
            on_new_file: Callable[[str], None],
            recursive: bool = True,
        ):
            self.watch_dirs = [os.path.abspath(d) for d in watch_dirs if os.path.isdir(d)]
            self.on_new_file = on_new_file
            self.recursive = recursive
            self._known_files: Set[str] = set()
            self._observer: Optional[Observer] = None
            self._running = False

        def initial_scan(self) -> List[str]:
            existing = []
            for watch_dir in self.watch_dirs:
                for root, dirs, files in os.walk(watch_dir):
                    for f in files:
                        filepath = os.path.join(root, f)
                        if is_video_file(filepath):
                            existing.append(filepath)
                            self._known_files.add(filepath)
                    if not self.recursive:
                        break
            return existing

        def start(self):
            if self._running:
                return
            self._observer = Observer()
            handler = WatchdogEventHandler(self.on_new_file, self._known_files)
            for watch_dir in self.watch_dirs:
                self._observer.schedule(handler, watch_dir, recursive=self.recursive)
            self._observer.start()
            self._running = True
            logger.info(f"Watchdog 监控已启动: {self.watch_dirs}")

        def stop(self):
            if self._observer:
                self._observer.stop()
                self._observer.join(timeout=5)
                self._running = False
                logger.info("Watchdog 监控已停止")

        @property
        def is_running(self) -> bool:
            return self._running

        def add_watch_dir(self, directory: str):
            abs_dir = os.path.abspath(directory)
            if os.path.isdir(abs_dir) and abs_dir not in self.watch_dirs:
                self.watch_dirs.append(abs_dir)
                if self._observer and self._running:
                    self._observer.schedule(
                        WatchdogEventHandler(self.on_new_file, self._known_files),
                        abs_dir, recursive=self.recursive
                    )

        def remove_watch_dir(self, directory: str):
            abs_dir = os.path.abspath(directory)
            if abs_dir in self.watch_dirs:
                self.watch_dirs.remove(abs_dir)

    HAS_WATCHDOG = True

except ImportError:
    HAS_WATCHDOG = False
    WatchdogWatcher = None


def create_watcher(
    watch_dirs: List[str],
    on_new_file: Callable[[str], None],
    interval: int = 5,
    recursive: bool = True,
    use_watchdog: bool = True,
):
    """
    创建文件夹监控器。

    优先使用 watchdog（事件驱动），不可用时回退到轮询方式。
    """
    if use_watchdog and HAS_WATCHDOG:
        logger.info("使用 Watchdog 事件驱动监控")
        return WatchdogWatcher(watch_dirs, on_new_file, recursive)
    else:
        logger.info("使用轮询方式监控（watchdog 不可用）")
        return FolderWatcher(watch_dirs, on_new_file, interval, recursive)
