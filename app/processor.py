"""
视频处理引擎
------------
整合哈希、检测、裁切模块，提供统一的处理流水线。
"""

import os
import time
import logging
from typing import List, Optional, Callable
from dataclasses import dataclass, field
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

from .hasher import FrameHasher, get_video_info
from .detector import DuplicateDetector, DetectionResult, MatchSegment
from .cutter import VideoCutter, CutResult
from .gpu_utils import get_gpu_info

logger = logging.getLogger("VideoDedup.Processor")


@dataclass
class ProcessReport:
    """单文件处理报告"""
    video_path: str
    video_name: str
    video_duration: float
    reference_path: str
    status: str = "pending"        # "pending" / "completed" / "error" / "skipped" / "no_match"
    detection: Optional[DetectionResult] = None
    cut_result: Optional[CutResult] = None
    error_message: str = ""
    processing_time: float = 0.0
    segments_found: int = 0
    total_match_duration: float = 0.0
    matched_references: List[str] = field(default_factory=list)  # 匹配到的素材库文件路径


@dataclass
class BatchReport:
    """批量处理报告"""
    reference_path: str
    total_files: int
    processed_files: int = 0
    files_with_matches: int = 0
    total_segments: int = 0
    total_match_duration: float = 0.0
    total_processing_time: float = 0.0
    file_reports: List[ProcessReport] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0


class VideoProcessor:
    """
    视频处理流水线。

    整合了帧哈希 → 重复检测 → 视频裁切的完整流程。
    """

    def __init__(
        self,
        sample_interval: float = 0.5,
        hash_threshold: int = 10,
        min_match_ratio: float = 0.10,
        min_match_duration: float = 0.5,
        merge_gap: float = 1.0,
        hash_algorithm: str = "dhash",
        auto_cut: bool = False,
        output_dir: str = "",
        max_workers: int = 4,
        use_gpu: bool = True,
        material_position: str = "anywhere",
        position_search_margin: float = 0.15,
        limit_head_tail: bool = False,
        head_tail_time: float = 60.0,
        enable_frame_filter: bool = False,
        frame_dark_threshold: float = 16.0,
        frame_bright_threshold: float = 240.0,
        enable_coarse_filter: bool = False,
        coarse_interval: float = 5.0,
        use_hash_cache: bool = True,
    ):
        self.sample_interval = sample_interval
        self.hash_threshold = hash_threshold
        self.min_match_ratio = min_match_ratio
        self.min_match_duration = min_match_duration
        self.merge_gap = merge_gap
        self.hash_algorithm = hash_algorithm
        self.auto_cut = auto_cut
        self.output_dir = output_dir
        self.max_workers = max_workers
        self.use_gpu = use_gpu
        self.material_position = material_position
        self.position_search_margin = position_search_margin
        self.limit_head_tail = limit_head_tail
        self.head_tail_time = head_tail_time
        self.enable_frame_filter = enable_frame_filter
        self.frame_dark_threshold = frame_dark_threshold
        self.frame_bright_threshold = frame_bright_threshold
        self.enable_coarse_filter = enable_coarse_filter
        self.coarse_interval = coarse_interval
        self.use_hash_cache = use_hash_cache

        # GPU 信息
        self._gpu_info = get_gpu_info()
        effective_gpu = use_gpu and self._gpu_info.available

        # 初始化子模块
        self.hasher = FrameHasher(
            sample_interval=sample_interval,
            compute_phash=(hash_algorithm == "phash" or hash_algorithm == "combined"),
            compute_ahash=(hash_algorithm == "ahash" or hash_algorithm == "combined"),
            use_gpu=effective_gpu,
            enable_frame_filter=enable_frame_filter,
            frame_dark_threshold=frame_dark_threshold,
            frame_bright_threshold=frame_bright_threshold,
            use_disk_cache=use_hash_cache,
        )
        self.detector = DuplicateDetector(
            hash_threshold=hash_threshold,
            min_match_ratio=min_match_ratio,
            min_match_duration=min_match_duration,
            merge_gap=merge_gap,
        )
        self.cutter = VideoCutter(output_dir=output_dir, use_gpu=effective_gpu)
        self._lock = threading.Lock()

        # 参照视频哈希缓存：{path: [FrameHash]}。
        # 确保参照素材在一次处理流程中只加载/哈希一次，批量处理多个目标
        # 视频时避免重复解码参照素材。
        self._ref_hash_cache: dict = {}

        # 构建 GPU 状态详情
        if effective_gpu:
            gpu_detail = f"GPU={'启用' if effective_gpu else '禁用'}"
            if self._gpu_info.available:
                gpu_detail += (
                    f" [{self._gpu_info.name}, "
                    f"{self._gpu_info.memory_mb // 1024}GB, "
                    f"CuPy={'✓' if self._gpu_info.cupy_available else '✗'}, "
                    f"NVENC={'✓' if self._gpu_info.ffmpeg_nvenc else '✗'}]"
                )
        else:
            gpu_detail = (
                f"GPU=禁用 "
                f"[{'未检测到' if not self._gpu_info.available else '用户关闭'}]"
            )

        logger.info(
            f"VideoProcessor 初始化: workers={max_workers}, "
            f"{gpu_detail}, "
            f"算法={hash_algorithm}, 素材位置={material_position}"
        )

    def _hash_references(
        self,
        reference_paths: List[str],
        progress_callback: Optional[Callable] = None,
    ) -> tuple:
        """
        一次性哈希所有参照视频（带缓存）。

        参照素材在一次处理流程中只加载/哈希一次，后续多个目标视频复用同一份
        哈希，避免每个目标文件都重新解码参照视频。

        Returns:
            (all_ref_hashes, ref_durations)
            - all_ref_hashes: 所有参照视频的 FrameHash 打平列表（含 source_path）
            - ref_durations:  每个参照视频的时长列表（与 reference_paths 对齐）
        """
        all_ref_hashes: List = []
        ref_durations: List[float] = []

        for i, ref_path in enumerate(reference_paths):
            ref_hashes = self._ref_hash_cache.get(ref_path)
            if ref_hashes is None:
                if progress_callback:
                    self._report_progress(
                        progress_callback, "hash_ref", 10,
                        f"计算参照视频哈希 ({i + 1}/{len(reference_paths)}): "
                        f"{os.path.basename(ref_path)}"
                    )
                ref_hashes = self.hasher.hash_video(ref_path)
                # 标记每帧来源，供匹配素材对应关系使用
                for h in ref_hashes:
                    h.source_path = ref_path
                self._ref_hash_cache[ref_path] = ref_hashes
            else:
                logger.debug(f"复用缓存的参照哈希: {os.path.basename(ref_path)}")

            all_ref_hashes.extend(ref_hashes)
            if ref_hashes:
                ref_durations.append(max(h.timestamp for h in ref_hashes))
            else:
                ref_durations.append(0.0)

        logger.info(
            f"参照哈希总计: {len(all_ref_hashes)} 帧 ({len(reference_paths)} 个视频)"
        )
        return all_ref_hashes, ref_durations

    def process_single(
        self,
        reference_paths: List[str],
        target_path: str,
        auto_cut: Optional[bool] = None,
        overwrite_original: bool = False,
        progress_callback: Optional[Callable] = None,
        cancel_check: Optional[Callable] = None,
        all_ref_hashes: Optional[List] = None,
        ref_durations: Optional[List] = None,
    ) -> ProcessReport:
        """
        处理单个目标视频。

        Args:
            reference_paths: 参照视频路径列表（支持多个素材）
            target_path: 目标视频路径
            auto_cut: 是否自动裁切（None 使用实例默认值）
            overwrite_original: 裁切后是否覆盖原视频
            progress_callback: 进度回调 (stage, percent) -> None
            cancel_check: 取消检查回调 () -> bool，返回 True 表示取消
            all_ref_hashes: 预计算的参照哈希（批量处理传入，跳过重复计算）
            ref_durations: 预计算的各参照时长（与 all_ref_hashes 配套传入）

        Returns:
            ProcessReport
        """
        start_time = time.time()
        video_name = os.path.basename(target_path)
        do_cut = auto_cut if auto_cut is not None else self.auto_cut

        report = ProcessReport(
            video_path=target_path,
            video_name=video_name,
            video_duration=0,
            reference_path=", ".join(reference_paths),
        )

        try:
            # 阶段 1: 获取视频信息
            if cancel_check and cancel_check():
                report.status = "skipped"
                report.error_message = "用户取消"
                return report

            self._report_progress(progress_callback, "info", 5, f"分析视频: {video_name}")
            info = get_video_info(target_path)
            report.video_duration = info.get("duration", 0)
            logger.info(f"处理视频: {video_name} ({info.get('duration', 0):.1f}s)")

            # 阶段 2: 参照视频哈希（若调用方已预计算则直接复用，避免重复加载）
            if cancel_check and cancel_check():
                report.status = "skipped"
                report.error_message = "用户取消"
                return report

            if all_ref_hashes is None:
                # 单文件处理首次调用：一次性计算参照哈希（内部带缓存）
                all_ref_hashes, ref_durations = self._hash_references(
                    reference_paths, progress_callback
                )
            else:
                # 批量处理：复用预计算好的参照哈希
                if ref_durations is None:
                    ref_durations = [0.0] * len(reference_paths)
                self._report_progress(
                    progress_callback, "hash_ref", 10,
                    f"复用已缓存的 {len(reference_paths)} 个参照视频哈希"
                )

            # 计算素材时长
            # - max_material_duration: 最长单个素材的时长 → 用于位置搜索窗口
            # - total_material_duration: 所有素材时长之和 → 仅用于日志参考
            max_material_duration = max(ref_durations) if ref_durations else 0.0
            total_material_duration = sum(ref_durations)

            # 阶段 3: 根据素材位置决定目标视频的哈希范围
            if cancel_check and cancel_check():
                report.status = "skipped"
                report.error_message = "用户取消"
                return report

            target_ranges = []  # 支持多个时间范围（用于 "both" 模式）

            if self.material_position == "both" and max_material_duration > 0:
                # 同时搜索开头和结尾，窗口 = 最长素材 × (1 + 余量)
                search_window = max_material_duration * (1 + self.position_search_margin)
                target_dur = info.get("duration", 0)

                if target_dur > 0 and target_dur > search_window * 2:
                    # 视频足够长，开头和结尾分开搜索，中间跳过
                    range_begin = (0.0, search_window)
                    start_t = target_dur - search_window
                    range_end = (start_t, target_dur)

                    # 两个范围不重叠时，中间区域完全跳过
                    target_ranges = [range_begin, range_end]
                    skipped_middle = target_dur - search_window * 2
                    self._report_progress(
                        progress_callback, "info", 15,
                        f"首尾搜索: 开头 [0.0s - {search_window:.1f}s] + "
                        f"结尾 [{start_t:.1f}s - {target_dur:.1f}s] "
                        f"| 跳过中间 {skipped_middle:.1f}s "
                        f"(最长素材{max_material_duration:.1f}s × {1 + self.position_search_margin:.0%})"
                    )
                else:
                    # 范围重叠 → 视频不够长，直接全量（此时搜索量本身就不大）
                    fallback_window = max_material_duration * (1 + self.position_search_margin)
                    self._report_progress(
                        progress_callback, "info", 15,
                        f"视频时长 {target_dur:.1f}s < 首尾窗口 {search_window * 2:.1f}s，"
                        f"回退全量搜索"
                    )

            elif self.material_position in ("beginning", "end") and max_material_duration > 0:
                # 仅搜索开头或结尾，窗口 = 最长素材 × (1 + 余量)
                search_window = max_material_duration * (1 + self.position_search_margin)
                target_dur = info.get("duration", 0)
                if self.material_position == "beginning":
                    target_ranges = [(0.0, min(search_window, target_dur))]
                    self._report_progress(
                        progress_callback, "info", 15,
                        f"仅搜索开头: [0.0s - {search_window:.1f}s] "
                        f"(最长素材{max_material_duration:.1f}s × {1 + self.position_search_margin:.0%}"
                        f", 跳过后续 {max(0, target_dur - search_window):.1f}s)"
                    )
                elif self.material_position == "end":
                    if target_dur > 0:
                        start_t = max(0.0, target_dur - search_window)
                        target_ranges = [(start_t, target_dur)]
                        self._report_progress(
                            progress_callback, "info", 15,
                            f"仅搜索结尾: [{start_t:.1f}s - {target_dur:.1f}s] "
                            f"(最长素材{max_material_duration:.1f}s × {1 + self.position_search_margin:.0%}"
                            f", 跳过前面 {max(0, start_t):.1f}s)"
                        )
                    else:
                        self._report_progress(
                            progress_callback, "info", 15,
                            "目标视频时长未知，回退到全范围搜索"
                        )

            # 阶段 3b: 首尾时间限定（可选项，覆盖素材位置的范围计算）
            # 仅在开头 [0, x] 与结尾 [时长-x, 时长] 范围内识别和裁剪，
            # 中间区域跳过；若视频时长小于指定时间则不跳过，全量识别。
            if self.limit_head_tail and self.head_tail_time > 0:
                target_dur = info.get("duration", 0)
                x = self.head_tail_time

                if target_dur <= 0:
                    target_ranges = []
                    self._report_progress(
                        progress_callback, "info", 15,
                        "目标视频时长未知，回退到全范围搜索"
                    )
                elif target_dur < x:
                    # 视频时长小于指定时间 → 不跳过，全量识别
                    target_ranges = []
                    self._report_progress(
                        progress_callback, "info", 15,
                        f"视频时长 {target_dur:.1f}s < 指定时间 {x:.1f}s，"
                        f"不跳过，全量识别"
                    )
                else:
                    tail_start = target_dur - x
                    if tail_start <= x:
                        # 首尾重叠 → 覆盖全片，直接全量
                        target_ranges = []
                        self._report_progress(
                            progress_callback, "info", 15,
                            f"视频时长 {target_dur:.1f}s，首尾时间 {x:.1f}s 重叠，"
                            f"全量识别"
                        )
                    else:
                        target_ranges = [(0.0, x), (tail_start, target_dur)]
                        self._report_progress(
                            progress_callback, "info", 15,
                            f"首尾限定: 开头 [0.0s - {x:.1f}s] + "
                            f"结尾 [{tail_start:.1f}s - {target_dur:.1f}s] "
                            f"| 跳过中间 {tail_start - x:.1f}s"
                        )

            # 阶段 3c: 整文件粗筛（可选项）——稀疏采样快速判断是否可能命中素材
            if self.enable_coarse_filter and self.coarse_interval > self.sample_interval:
                coarse_hashes = self._hash_target_ranges(
                    target_path, target_ranges, self.coarse_interval
                )
                if coarse_hashes:
                    coarse_threshold = min(64, self.hash_threshold + 5)
                    if not self.detector.has_any_match(
                        all_ref_hashes, coarse_hashes, coarse_threshold
                    ):
                        report.status = "no_match"
                        report.processing_time = time.time() - start_time
                        logger.info(f"粗筛未命中，跳过精筛: {video_name}")
                        self._report_progress(
                            progress_callback, "done", 100,
                            f"粗筛未命中，跳过: {video_name}"
                        )
                        return report
                    logger.info(f"粗筛命中，进入精筛: {video_name}")
                else:
                    self._report_progress(
                        progress_callback, "info", 20,
                        "粗筛未取得有效帧，回退精筛"
                    )

            self._report_progress(progress_callback, "hash_target", 30, "计算目标视频哈希...")

            # 支持多范围哈希（用于 "both" 模式）
            if target_ranges:
                if len(target_ranges) == 1:
                    target_hashes = self.hasher.hash_video(target_path, time_range=target_ranges[0])
                else:
                    target_hashes = []
                    for tr in target_ranges:
                        tr_hashes = self.hasher.hash_video(target_path, time_range=tr)
                        target_hashes.extend(tr_hashes)
                    # 去重 + 排序（按时间戳）
                    seen = set()
                    unique_hashes = []
                    for h in sorted(target_hashes, key=lambda x: x.timestamp):
                        if h.timestamp not in seen:
                            seen.add(h.timestamp)
                            unique_hashes.append(h)
                    target_hashes = unique_hashes
                    logger.info(
                        f"多范围哈希合并: {len(target_ranges)} 个范围, "
                        f"共 {len(target_hashes)} 帧 (去重后)"
                    )
            else:
                target_hashes = self.hasher.hash_video(target_path, time_range=None)

            # 阶段 4: 重复检测
            if cancel_check and cancel_check():
                report.status = "skipped"
                report.error_message = "用户取消"
                return report

            self._report_progress(progress_callback, "detect", 50, "向量化检测重复片段...")
            # 素材总时长 = 所有素材视频的时长之和
            material_duration = max(h.timestamp for h in all_ref_hashes) if all_ref_hashes else 0

            detection = self.detector.detect(
                all_ref_hashes, target_hashes,
                material_duration=material_duration,
                sample_interval=self.sample_interval,
            )
            detection.reference_path = ", ".join(reference_paths)
            detection.target_path = target_path
            report.detection = detection
            report.segments_found = len(detection.segments)
            report.total_match_duration = detection.total_match_duration
            report.matched_references = detection.matched_references

            if not detection.has_matches:
                report.status = "no_match"
                report.processing_time = time.time() - start_time
                logger.info(f"未找到重复片段: {video_name}")
                return report

            logger.info(
                f"找到 {len(detection.segments)} 个重复片段: {video_name}"
            )

            # 阶段 5: 裁切（可选）
            if do_cut:
                if cancel_check and cancel_check():
                    report.status = "completed"
                    report.processing_time = time.time() - start_time
                    return report

                self._report_progress(progress_callback, "cut", 75, "裁切视频...")

                def cut_progress(current, total):
                    pct = 75 + int((current / total) * 20) if total > 0 else 75
                    self._report_progress(progress_callback, "cut", pct, f"裁切中... {current}/{total}")

                cut_result = self.cutter.cut_video(
                    target_path,
                    detection.segments,
                    mode="remove_duplicates",
                    overwrite_original=overwrite_original,
                    progress_callback=cut_progress,
                )
                report.cut_result = cut_result
                if not cut_result.success:
                    report.error_message = cut_result.error_message

            report.status = "completed"
            report.processing_time = time.time() - start_time

            self._report_progress(progress_callback, "done", 100, f"完成: {video_name}")
            logger.info(
                f"处理完成: {video_name} "
                f"(找到{len(detection.segments)}段重复, 耗时{report.processing_time:.1f}s)"
            )

        except Exception as e:
            report.status = "error"
            report.error_message = str(e)
            report.processing_time = time.time() - start_time
            logger.error(f"处理失败: {video_name} - {e}", exc_info=True)
            self._report_progress(progress_callback, "error", 0, f"错误: {e}")

        return report

    def _hash_target_ranges(
        self,
        target_path: str,
        target_ranges: List[tuple],
        interval: float,
    ) -> List:
        """按给定采样间隔在（可能多个）目标时间范围内哈希目标视频（粗筛用）。"""
        if not target_ranges:
            return self.hasher.hash_video(
                target_path, time_range=None, sample_interval=interval
            )
        if len(target_ranges) == 1:
            return self.hasher.hash_video(
                target_path, time_range=target_ranges[0], sample_interval=interval
            )

        hashes = []
        for tr in target_ranges:
            hashes.extend(
                self.hasher.hash_video(
                    target_path, time_range=tr, sample_interval=interval
                )
            )
        # 去重 + 按时间戳排序
        seen = set()
        unique = []
        for h in sorted(hashes, key=lambda x: x.timestamp):
            if h.timestamp not in seen:
                seen.add(h.timestamp)
                unique.append(h)
        return unique

    def process_batch(
        self,
        reference_paths: List[str],
        target_paths: List[str],
        auto_cut: Optional[bool] = None,
        overwrite_original: bool = False,
        progress_callback: Optional[Callable] = None,
        file_progress_callback: Optional[Callable] = None,
        file_done_callback: Optional[Callable] = None,
        cancel_check: Optional[Callable] = None,
    ) -> BatchReport:
        """
        批量处理多个目标视频。

        Args:
            reference_paths: 参照视频路径列表
            target_paths: 目标视频路径列表
            auto_cut: 是否自动裁切
            overwrite_original: 裁切后是否覆盖原视频
            progress_callback: 总体进度回调 (stage, percent, message) -> None
            file_progress_callback: 单文件进度回调 (current_index, total, filename) -> None
            file_done_callback: 单文件完成回调 (ProcessReport) -> None，处理完一个即触发
            cancel_check: 取消检查回调

        Returns:
            BatchReport
        """
        batch_start = time.time()
        total = len(target_paths)

        batch_report = BatchReport(
            reference_path=", ".join(reference_paths),
            total_files=total,
            start_time=batch_start,
        )

        logger.info(f"开始批量处理: {total} 个文件, 参照={len(reference_paths)}个视频, 并发={self.max_workers}")

        # 一次性加载并哈希所有参照视频（关键优化：避免每个目标文件重复解码参照素材）
        all_ref_hashes, ref_durations = self._hash_references(
            reference_paths, progress_callback
        )

        # 使用线程池并行处理多个文件
        completed_count = 0
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {}
            for idx, target_path in enumerate(target_paths):
                if cancel_check and cancel_check():
                    break
                future = executor.submit(
                    self.process_single,
                    reference_paths,
                    target_path,
                    auto_cut,
                    overwrite_original,
                    None,  # progress_callback handled at batch level
                    cancel_check,
                    all_ref_hashes,  # 复用预计算的参照哈希
                    ref_durations,
                )
                futures[future] = (idx + 1, target_path)

            for future in as_completed(futures):
                if cancel_check and cancel_check():
                    for f in futures:
                        f.cancel()
                    break

                idx_num, tpath = futures[future]
                try:
                    report = future.result(timeout=600)
                except Exception as e:
                    report = ProcessReport(
                        video_path=tpath,
                        video_name=os.path.basename(tpath),
                        video_duration=0,
                        reference_path=",".join(reference_paths),
                        status="error",
                        error_message=str(e),
                    )

                with self._lock:
                    batch_report.file_reports.append(report)
                    batch_report.processed_files += 1
                    batch_report.total_segments += report.segments_found
                    batch_report.total_match_duration += report.total_match_duration
                    completed_count += 1

                    if report.status == "completed" and report.segments_found > 0:
                        batch_report.files_with_matches += 1

                if file_progress_callback:
                    file_progress_callback(completed_count, total, os.path.basename(tpath))

                # 单个文件完成即回调（用于界面流式显示结果）
                if file_done_callback:
                    try:
                        file_done_callback(report)
                    except Exception:
                        pass

                # 总体进度
                overall_pct = int((completed_count / total) * 100)
                if progress_callback:
                    progress_callback("batch", overall_pct,
                                      f"已完成 {completed_count}/{total}")

        batch_report.end_time = time.time()
        batch_report.total_processing_time = batch_report.end_time - batch_start

        logger.info(
            f"批量处理完成: {batch_report.processed_files}/{batch_report.total_files} 文件, "
            f"匹配={batch_report.files_with_matches}, "
            f"总重复={batch_report.total_match_duration:.1f}s, "
            f"耗时={batch_report.total_processing_time:.1f}s"
        )

        return batch_report

    @staticmethod
    def _report_progress(callback, stage, percent, message):
        """安全调用进度回调"""
        if callback:
            try:
                callback(stage, percent, message)
            except Exception:
                pass
