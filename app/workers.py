"""
后台工作线程模块
----------------
基于 QThread 的后台处理线程，用于：
- 视频处理任务
- 文件夹监控任务
- 批量处理任务

通过 Qt 信号与 GUI 主线程通信，确保界面不冻结。
"""

import os
import time
import traceback
from typing import List, Optional

from PyQt6.QtCore import QThread, pyqtSignal, QMutex, QWaitCondition

from .processor import VideoProcessor, ProcessReport, BatchReport
from .watcher import create_watcher, FolderWatcher


class ProcessWorker(QThread):
    """
    视频处理工作线程。

    信号：
    - progress: 进度更新 (stage, percent, message)
    - file_progress: 单文件进度 (current, total, filename)
    - file_done: 单个文件处理完成 (ProcessReport)
    - batch_done: 批量处理完成 (BatchReport)
    - error: 处理错误 (error_message)
    - log: 日志消息 (level, message)
    """

    progress = pyqtSignal(str, int, str)       # stage, percent, message
    file_progress = pyqtSignal(int, int, str)  # current, total, filename
    file_done = pyqtSignal(object)              # ProcessReport
    batch_done = pyqtSignal(object)             # BatchReport
    error = pyqtSignal(str)
    log = pyqtSignal(str, str)                  # level, message

    def __init__(self, parent=None):
        super().__init__(parent)
        self._processor: Optional[VideoProcessor] = None
        self._reference_paths: List[str] = []
        self._target_paths: List[str] = []
        self._auto_cut = False
        self._overwrite_original = False
        self._cancelled = False
        self._mutex = QMutex()
        self._cond = QWaitCondition()

    def setup(
        self,
        reference_paths: List[str],
        target_paths: List[str],
        processor: VideoProcessor,
        auto_cut: bool = False,
        overwrite_original: bool = False,
    ):
        """配置处理参数"""
        self._reference_paths = reference_paths
        self._target_paths = target_paths
        self._processor = processor
        self._auto_cut = auto_cut
        self._overwrite_original = overwrite_original
        self._cancelled = False

    def cancel(self):
        """取消当前处理"""
        self._cancelled = True
        self.log.emit("WARNING", "正在取消处理...")

    def _check_cancelled(self) -> bool:
        return self._cancelled

    def run(self):
        """在工作线程中执行处理"""
        if not self._processor or not self._reference_paths or not self._target_paths:
            self.error.emit("处理参数未配置")
            return

        try:
            ref_names = ", ".join(os.path.basename(p) for p in self._reference_paths)
            self.log.emit("INFO", f"开始处理 {len(self._target_paths)} 个文件")
            self.log.emit("INFO", f"参照视频({len(self._reference_paths)}): {ref_names}")

            # 输出 GPU 状态信息
            from .gpu_utils import get_gpu_info
            gpu_info = get_gpu_info()
            if gpu_info.available and self._processor.use_gpu:
                self.log.emit("INFO",
                    f"GPU 加速: {gpu_info.name} ({gpu_info.memory_mb // 1024}GB) | "
                    f"CuPy={'可用' if gpu_info.cupy_available else '不可用'} | "
                    f"NVENC={'可用' if gpu_info.ffmpeg_nvenc else '不可用'}")
            elif gpu_info.available and not self._processor.use_gpu:
                self.log.emit("INFO", f"GPU 加速: 已禁用 (检测到 {gpu_info.name}，但用户关闭了 GPU 选项)")
            else:
                self.log.emit("INFO", "GPU 加速: 不可用，使用 CPU 模式")

            if len(self._target_paths) == 1:
                # 单文件处理
                self.progress.emit("start", 0, "开始处理...")
                report = self._processor.process_single(
                    self._reference_paths,
                    self._target_paths[0],
                    auto_cut=self._auto_cut,
                    overwrite_original=self._overwrite_original,
                    progress_callback=self._on_single_progress,
                    cancel_check=self._check_cancelled,
                )
                self.file_done.emit(report)

                batch = BatchReport(
                    reference_path=ref_names,
                    total_files=1,
                    processed_files=1,
                    files_with_matches=1 if report.segments_found > 0 else 0,
                    total_segments=report.segments_found,
                    total_match_duration=report.total_match_duration,
                    total_processing_time=report.processing_time,
                    file_reports=[report],
                    start_time=0,
                    end_time=time.time(),
                )
                self.batch_done.emit(batch)
            else:
                # 批量处理：每处理完一个文件立即通过 file_done_callback 流式发送结果
                batch = self._processor.process_batch(
                    self._reference_paths,
                    self._target_paths,
                    auto_cut=self._auto_cut,
                    overwrite_original=self._overwrite_original,
                    progress_callback=self._on_batch_progress,
                    file_progress_callback=self._on_file_progress,
                    file_done_callback=self.file_done.emit,
                    cancel_check=self._check_cancelled,
                )
                self.batch_done.emit(batch)

            if self._cancelled:
                self.log.emit("WARNING", "处理已被取消")
            else:
                self.log.emit("INFO", "处理完成")

        except Exception as e:
            traceback_str = traceback.format_exc()
            self.log.emit("ERROR", f"处理异常: {e}\n{traceback_str}")
            self.error.emit(str(e))

    def _on_single_progress(self, stage: str, percent: int, message: str):
        """单文件进度回调"""
        self.progress.emit(stage, percent, message)
        if stage != "info":
            self.log.emit("DEBUG", f"[{percent}%] {message}")

    def _on_batch_progress(self, stage: str, percent: int, message: str):
        """批量处理进度回调"""
        self.progress.emit(stage, percent, message)

    def _on_file_progress(self, current: int, total: int, filename: str):
        """文件进度回调"""
        self.file_progress.emit(current, total, filename)


class WatchWorker(QThread):
    """
    文件夹监控工作线程。

    信号：
    - new_file: 发现新视频文件 (file_path)
    - log: 日志消息
    - error: 错误消息
    """

    new_file = pyqtSignal(str)
    log = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._watcher: Optional[FolderWatcher] = None
        self._watch_dirs: List[str] = []
        self._interval = 5
        self._recursive = True
        self._stopped = False

    def setup(
        self,
        watch_dirs: List[str],
        interval: int = 5,
        recursive: bool = True,
    ):
        """配置监控参数"""
        self._watch_dirs = watch_dirs
        self._interval = interval
        self._recursive = recursive

    def stop(self):
        """停止监控"""
        self._stopped = True
        if self._watcher:
            self._watcher.stop()

    def run(self):
        """在工作线程中执行监控"""
        if not self._watch_dirs:
            self.log.emit("没有配置监控目录")
            return

        try:
            self.log.emit(f"开始监控 {len(self._watch_dirs)} 个目录")

            self._watcher = create_watcher(
                self._watch_dirs,
                on_new_file=self._on_new_file,
                interval=self._interval,
                recursive=self._recursive,
            )

            # 初始扫描
            existing = self._watcher.initial_scan()
            self.log.emit(f"初始扫描: 找到 {len(existing)} 个现有视频文件")

            # 开始监控（watchdog 事件驱动模式）
            if hasattr(self._watcher, 'start'):
                self._watcher.start()
                # 等待停止信号
                while not self._stopped:
                    time.sleep(0.5)
            else:
                # 轮询模式
                while not self._stopped:
                    new_files = self._watcher.scan()
                    for f in new_files:
                        self._on_new_file(f)
                    time.sleep(self._interval)

        except Exception as e:
            self.error.emit(f"监控异常: {e}")
        finally:
            if self._watcher and hasattr(self._watcher, 'stop'):
                self._watcher.stop()
            self.log.emit("监控已停止")

    def _on_new_file(self, filepath: str):
        """发现新文件"""
        self.log.emit(f"发现新视频: {os.path.basename(filepath)}")
        self.new_file.emit(filepath)
