"""
视频裁切模块 (v2)
------------------
基于 FFmpeg 的高速裁切，无需重新编码（stream copy）。
移除检测到的重复片段，保留原创部分。
"""

import os
import sys
import subprocess
import logging
import tempfile
from typing import List, Optional
from dataclasses import dataclass
from pathlib import Path

from .detector import MatchSegment
from . import subprocess_no_window_kwargs

logger = logging.getLogger("VideoDedup.Cutter")


@dataclass
class CutResult:
    """裁切结果"""
    input_path: str
    output_path: str
    mode: str
    original_duration: float
    output_duration: float
    removed_segments: List[MatchSegment]
    removed_duration: float
    success: bool
    error_message: str = ""


def _run_ffmpeg(cmd: list, timeout: int = 600) -> bool:
    """运行 FFmpeg 命令，返回是否成功"""
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            **subprocess_no_window_kwargs(),
        )
        if result.returncode != 0:
            # FFmpeg 有时返回非0但文件正常，检查文件是否存在
            logger.warning(f"FFmpeg 返回码 {result.returncode}: {result.stderr[-300:]}")
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.error("FFmpeg 命令超时")
        return False
    except FileNotFoundError:
        logger.error("FFmpeg 未安装或不在 PATH 中")
        return False


def _check_ffmpeg() -> bool:
    """检查 FFmpeg 是否可用"""
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=10,
            **subprocess_no_window_kwargs(),
        )
        return True
    except Exception:
        return False


class VideoCutter:
    """视频裁切器 (v2 - FFmpeg stream copy)"""

    def __init__(self, output_dir: str = "", use_gpu: bool = True):
        self.output_dir = output_dir
        self.use_gpu = use_gpu
        self._has_ffmpeg = _check_ffmpeg()
        if not self._has_ffmpeg:
            logger.warning("FFmpeg 不可用！裁切功能将无法使用。请安装 FFmpeg。")

    def cut_video(
        self,
        video_path: str,
        segments: List[MatchSegment],
        mode: str = "remove_duplicates",
        output_path: Optional[str] = None,
        overwrite_original: bool = False,
        progress_callback=None,
    ) -> CutResult:
        """
        裁切视频：使用 FFmpeg stream copy 快速移除重复片段。

        方法：将保留区间分别切出为独立片段，再用 concat 拼接。
        使用 -c copy 避免重新编码，速度极快。
        """
        if not segments:
            return CutResult(
                input_path=video_path, output_path="", mode=mode,
                original_duration=0, output_duration=0,
                removed_segments=[], removed_duration=0,
                success=False, error_message="没有可处理的片段"
            )

        if not self._has_ffmpeg:
            return CutResult(
                input_path=video_path, output_path="", mode=mode,
                original_duration=0, output_duration=0,
                removed_segments=[], removed_duration=0,
                success=False, error_message="FFmpeg 未安装，无法裁切"
            )

        # 获取视频时长
        original_duration = self._get_duration(video_path)
        if original_duration is None:
            original_duration = 0

        # 生成输出路径
        if output_path is None:
            input_stem = Path(video_path).stem
            suffix = "_dedup" if mode == "remove_duplicates" else "_duplicates"
            output_path = os.path.join(
                self.output_dir or os.path.dirname(video_path),
                f"{input_stem}{suffix}.mp4"
            )

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        # 构建保留区间
        keep_ranges = self._build_keep_ranges(segments, original_duration, mode)

        if not keep_ranges:
            return CutResult(
                input_path=video_path, output_path=output_path, mode=mode,
                original_duration=original_duration, output_duration=0,
                removed_segments=segments,
                removed_duration=original_duration,
                success=False, error_message="处理后没有可保留的内容"
            )

        logger.info(
            f"FFmpeg 裁切: {os.path.basename(video_path)}, "
            f"保留 {len(keep_ranges)} 个区间, 移除 {len(segments)} 段重复"
        )

        # 使用临时目录存放分段
        with tempfile.TemporaryDirectory(prefix="videodedup_") as tmpdir:
            segment_files = []

            for i, (start_t, end_t) in enumerate(keep_ranges):
                seg_path = os.path.join(tmpdir, f"seg_{i:04d}.ts")
                segment_files.append(seg_path)

                # FFmpeg: 精确切出保留区间（使用 stream copy，极快）
                cmd = [
                    "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-ss", f"{start_t:.3f}",
                    "-to", f"{end_t:.3f}",
                    "-i", video_path,
                    "-c", "copy",
                    "-avoid_negative_ts", "make_zero",
                    "-f", "mpegts",  # 使用 mpegts 容器便于拼接
                    seg_path,
                ]
                success = _run_ffmpeg(cmd, timeout=120)
                if not success or not os.path.exists(seg_path) or os.path.getsize(seg_path) < 100:
                    logger.warning(f"分段 {i} 切出失败，尝试重编码...")
                    # 回退：重编码
                    cmd_rec = [
                        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                        "-ss", f"{start_t:.3f}",
                        "-to", f"{end_t:.3f}",
                        "-i", video_path,
                        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                        "-c:a", "aac", "-b:a", "128k",
                        "-f", "mpegts",
                        seg_path,
                    ]
                    _run_ffmpeg(cmd_rec, timeout=180)

                if progress_callback:
                    progress_callback(i + 1, len(keep_ranges))

            # 检查哪些分段文件有效
            valid_segs = [s for s in segment_files if os.path.exists(s) and os.path.getsize(s) > 100]
            if not valid_segs:
                return CutResult(
                    input_path=video_path, output_path=output_path, mode=mode,
                    original_duration=original_duration, output_duration=0,
                    removed_segments=segments, removed_duration=0,
                    success=False, error_message="所有分段切出均失败"
                )

            # 写入 concat 列表
            concat_file = os.path.join(tmpdir, "concat.txt")
            with open(concat_file, "w", encoding="utf-8") as f:
                for sp in valid_segs:
                    f.write(f"file '{sp}'\n")

            # 拼接所有保留分段
            final_tmp = os.path.join(tmpdir, "output.mp4")
            concat_cmd = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "concat", "-safe", "0",
                "-i", concat_file,
                "-c", "copy",
                final_tmp,
            ]
            success = _run_ffmpeg(concat_cmd, timeout=120)

            if not success or not os.path.exists(final_tmp):
                # 回退：重编码拼接
                logger.warning("Stream copy concat 失败，尝试重编码拼接...")
                concat_rec = [
                    "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "concat", "-safe", "0",
                    "-i", concat_file,
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                    "-c:a", "aac", "-b:a", "128k",
                    final_tmp,
                ]
                _run_ffmpeg(concat_rec, timeout=300)

            if not os.path.exists(final_tmp) or os.path.getsize(final_tmp) < 1000:
                return CutResult(
                    input_path=video_path, output_path=output_path, mode=mode,
                    original_duration=original_duration, output_duration=0,
                    removed_segments=segments, removed_duration=0,
                    success=False, error_message="拼接失败，输出文件无效"
                )

            # 移动到最终位置
            import shutil
            if overwrite_original:
                try:
                    # 直接用新文件替换原文件（不保留 bak）
                    shutil.move(final_tmp, video_path)
                    actual_output = video_path
                    logger.info(f"已覆盖原视频: {video_path}")
                except Exception as e:
                    logger.error(f"覆盖失败: {e}，输出到: {output_path}")
                    if os.path.exists(final_tmp):
                        shutil.move(final_tmp, output_path)
                    actual_output = output_path
            else:
                shutil.move(final_tmp, output_path)
                actual_output = output_path

        # 计算输出时长
        output_duration = sum(e - s for s, e in keep_ranges)
        removed_duration = original_duration - output_duration if original_duration > 0 else 0

        logger.info(
            f"裁切完成: {os.path.basename(video_path)} -> {os.path.basename(actual_output)}, "
            f"原={original_duration:.1f}s, 输出={output_duration:.1f}s, "
            f"移除={removed_duration:.1f}s"
        )

        return CutResult(
            input_path=video_path,
            output_path=actual_output,
            mode=mode,
            original_duration=original_duration,
            output_duration=output_duration,
            removed_segments=segments,
            removed_duration=removed_duration,
            success=True,
        )

    def _build_keep_ranges(
        self,
        segments: List[MatchSegment],
        total_duration: float,
        mode: str,
    ) -> List[tuple]:
        """构建保留的时间区间"""
        if mode == "keep_duplicates":
            return [(s.target_start_time, s.target_end_time) for s in segments]

        sorted_segs = sorted(segments, key=lambda s: s.target_start_time)
        keep_ranges = []
        current_pos = 0.0

        for seg in sorted_segs:
            if seg.target_start_time > current_pos + 0.05:
                keep_ranges.append((current_pos, seg.target_start_time))
            current_pos = max(current_pos, seg.target_end_time)

        if current_pos < total_duration - 0.05:
            keep_ranges.append((current_pos, total_duration))

        return keep_ranges

    @staticmethod
    def _get_duration(video_path: str) -> Optional[float]:
        """用 FFprobe 获取视频时长"""
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", video_path],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, timeout=30,
                **subprocess_no_window_kwargs(),
            )
            return float(result.stdout.strip())
        except Exception:
            # 回退到 OpenCV
            try:
                import cv2
                cap = cv2.VideoCapture(video_path)
                fps = cap.get(cv2.CAP_PROP_FPS)
                frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                cap.release()
                return frames / fps if fps > 0 else None
            except Exception:
                return None
