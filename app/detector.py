"""
重复检测模块 (v2 - 向量化高性能版)
-----------------------------------
基于 numpy 向量化运算的帧哈希比对。
1. 对每个素材视频，在目标视频中查找匹配帧
2. 使用 numpy bit_count 向量化计算汉明距离，O(N*M) 但 C 级速度
3. 提取连续匹配片段，过滤 >= 素材时长 * match_ratio 的片段
4. 输出需要裁切的目标视频时间区间
"""

import logging
import os
import numpy as np
from typing import List, Tuple, Optional
from dataclasses import dataclass, field

from .hasher import FrameHash

logger = logging.getLogger("VideoDedup.Detector")


@dataclass
class MatchSegment:
    """匹配片段"""
    ref_start_time: float
    ref_end_time: float
    target_start_time: float
    target_end_time: float
    avg_similarity: float = 0.0
    min_similarity: float = 0.0
    matched_frames: int = 0
    total_frames: int = 0

    @property
    def duration(self) -> float:
        return self.target_end_time - self.target_start_time

    @property
    def ref_duration(self) -> float:
        return self.ref_end_time - self.ref_start_time

    def __repr__(self):
        return (
            f"MatchSegment(ref=[{self.ref_start_time:.1f}s-{self.ref_end_time:.1f}s], "
            f"target=[{self.target_start_time:.1f}s-{self.target_end_time:.1f}s], "
            f"sim={self.avg_similarity:.1f}%)"
        )


@dataclass
class DetectionResult:
    """检测结果"""
    reference_path: str
    target_path: str
    reference_duration: float
    target_duration: float
    segments: List[MatchSegment] = field(default_factory=list)
    total_match_duration: float = 0.0
    match_percentage: float = 0.0
    matched_references: List[str] = field(default_factory=list)  # 匹配到的素材库文件路径

    @property
    def has_matches(self) -> bool:
        return len(self.segments) > 0


# 预计算 0-255 每个字节的 popcount（查表法加速单次汉明距离）
_BITCOUNT_TABLE = np.array([bin(i).count('1') for i in range(256)], dtype=np.uint8)


def _hamming_distance_batch(query: np.ndarray, db: np.ndarray) -> np.ndarray:
    """
    向量化批量汉明距离计算。

    Args:
        query: shape (N,) uint64 哈希数组
        db: shape (M,) uint64 哈希数组

    Returns:
        shape (N, M) uint8 汉明距离矩阵
    """
    # XOR: shape (N, M)
    xor = np.bitwise_xor(query[:, None], db[None, :])
    # 将 uint64 拆为 8 个字节，查表求 popcount
    result = np.zeros((len(query), len(db)), dtype=np.uint8)
    for shift in range(0, 64, 8):
        byte_vals = (xor >> np.uint64(shift)).astype(np.uint8) & 0xFF
        result += _BITCOUNT_TABLE[byte_vals]
    return result


class DuplicateDetector:
    """重复片段检测器 (v2 - 向量化)"""

    def __init__(
        self,
        hash_threshold: int = 10,
        min_match_ratio: float = 0.10,   # 匹配占比阈值（相对于素材时长），默认10%
        min_match_duration: float = 0.5,  # 最短片段时长
        merge_gap: float = 1.0,           # 相邻片段合并间隔
    ):
        self.hash_threshold = hash_threshold
        self.min_match_ratio = min_match_ratio
        self.min_match_duration = min_match_duration
        self.merge_gap = merge_gap

    def detect(
        self,
        ref_hashes: List[FrameHash],
        target_hashes: List[FrameHash],
        material_duration: Optional[float] = None,
        sample_interval: float = 0.5,
    ) -> DetectionResult:
        """
        向量化检测：在目标视频中查找与素材匹配的连续片段。

        关键改进：只有匹配片段总时长 >= 素材时长 * min_match_ratio 才报告。
        """
        if not ref_hashes or not target_hashes:
            return DetectionResult(
                reference_path="", target_path="",
                reference_duration=0, target_duration=0
            )

        ref_arr = np.array([h.dhash for h in ref_hashes], dtype=np.uint64)
        tgt_arr = np.array([h.dhash for h in target_hashes], dtype=np.uint64)
        ref_ts = np.array([h.timestamp for h in ref_hashes], dtype=np.float64)
        tgt_ts = np.array([h.timestamp for h in target_hashes], dtype=np.float64)
        ref_sources = [getattr(h, 'source_path', '') or '' for h in ref_hashes]

        ref_dur = ref_ts[-1] if len(ref_ts) > 0 else 0
        tgt_dur = tgt_ts[-1] if len(tgt_ts) > 0 else 0

        if material_duration is None:
            material_duration = ref_dur

        logger.info(
            f"向量化检测: 素材={len(ref_arr)}帧({ref_dur:.1f}s), "
            f"目标={len(tgt_arr)}帧({tgt_dur:.1f}s), "
            f"阈值={self.hash_threshold}, 最小匹配比={self.min_match_ratio:.0%}"
        )

        # ---- 分块向量化比对：避免一次创建 (N*M) 的大矩阵 ----
        CHUNK = 2000  # 每次处理 2000 目标帧
        match_mask = np.zeros(len(tgt_arr), dtype=bool)
        match_best_dist = np.full(len(tgt_arr), 255, dtype=np.uint8)
        match_ref_idx = np.full(len(tgt_arr), -1, dtype=np.int64)

        for chunk_start in range(0, len(tgt_arr), CHUNK):
            chunk_end = min(chunk_start + CHUNK, len(tgt_arr))
            tgt_chunk = tgt_arr[chunk_start:chunk_end]

            # 计算汉明距离矩阵 (chunk_size, N_ref)
            dist_matrix = _hamming_distance_batch(tgt_chunk, ref_arr)

            # 每目标帧取最小距离及对应素材帧
            best_dists = dist_matrix.min(axis=1)  # shape (chunk_size,)
            best_ref_idx = dist_matrix.argmin(axis=1)
            matched = best_dists <= self.hash_threshold

            match_mask[chunk_start:chunk_end] = matched
            match_best_dist[chunk_start:chunk_end] = best_dists
            match_ref_idx[chunk_start:chunk_end] = np.where(matched, best_ref_idx, -1)

        matched_count = match_mask.sum()
        logger.info(
            f"匹配: {matched_count}/{len(tgt_arr)} 帧 "
            f"({matched_count / len(tgt_arr) * 100:.1f}%)"
        )

        # 统计匹配到的素材库文件（即本目标文件与素材库的对应关系）
        matched_references: List[str] = []
        if matched_count > 0:
            matched_references = sorted({
                ref_sources[i]
                for i in match_ref_idx[match_mask]
                if 0 <= i < len(ref_sources) and ref_sources[i]
            })
            logger.info(
                f"匹配素材: {len(matched_references)} 个 -> "
                f"{[os.path.basename(p) for p in matched_references]}"
            )

        if matched_count == 0:
            return DetectionResult(
                reference_path="", target_path="",
                reference_duration=ref_dur, target_duration=tgt_dur,
            )

        # ---- 提取连续匹配片段 ----
        segments = self._extract_contiguous_segments(
            match_mask, match_best_dist, tgt_ts, ref_ts, sample_interval
        )

        # ---- 过滤：只保留时长 >= 素材时长 * min_match_ratio 的片段 ----
        min_required = material_duration * self.min_match_ratio
        filtered = [s for s in segments if s.duration >= min_required]

        if len(filtered) < len(segments):
            logger.info(
                f"素材时长过滤: {len(segments)} -> {len(filtered)} 片段 "
                f"(阈值={min_required:.1f}s, 即素材的{self.min_match_ratio:.0%})"
            )

        # 再过滤极短片段
        filtered = [s for s in filtered if s.duration >= self.min_match_duration]

        # ---- 合并邻近片段 ----
        merged = self._merge_nearby(filtered)

        total_match = sum(s.duration for s in merged)
        result = DetectionResult(
            reference_path="",
            target_path="",
            reference_duration=ref_dur,
            target_duration=tgt_dur,
            segments=merged,
            total_match_duration=total_match,
            match_percentage=(total_match / tgt_dur * 100) if tgt_dur > 0 else 0,
            matched_references=matched_references,
        )

        logger.info(
            f"检测完成: {len(merged)} 个重复片段, 总时长={total_match:.1f}s "
            f"({result.match_percentage:.1f}% of target)"
        )
        return result

    def has_any_match(
        self,
        ref_hashes: List[FrameHash],
        target_hashes: List[FrameHash],
        threshold: Optional[int] = None,
    ) -> bool:
        """
        粗筛门控：是否存在任一帧对汉明距离 <= threshold。

        与 detect() 不同，这里不做片段提取，命中即早退，用于在精筛前
        快速判断目标视频是否可能包含素材。高召回优先，宁可漏检也不要误判。
        """
        if not ref_hashes or not target_hashes:
            return False

        thresh = self.hash_threshold if threshold is None else threshold
        ref_arr = np.array([h.dhash for h in ref_hashes], dtype=np.uint64)
        tgt_arr = np.array([h.dhash for h in target_hashes], dtype=np.uint64)

        CHUNK = 2000
        for chunk_start in range(0, len(tgt_arr), CHUNK):
            chunk_end = min(chunk_start + CHUNK, len(tgt_arr))
            tgt_chunk = tgt_arr[chunk_start:chunk_end]
            dist_matrix = _hamming_distance_batch(tgt_chunk, ref_arr)
            if int((dist_matrix <= thresh).sum()) > 0:
                return True
        return False

    def _extract_contiguous_segments(
        self,
        match_mask: np.ndarray,
        best_dists: np.ndarray,
        tgt_ts: np.ndarray,
        ref_ts: np.ndarray,
        sample_interval: float,
    ) -> List[MatchSegment]:
        """从布尔匹配掩码中提取连续 True 的片段"""
        segments = []
        in_segment = False
        seg_start = 0

        for i in range(len(match_mask)):
            if match_mask[i] and not in_segment:
                in_segment = True
                seg_start = i
            elif not match_mask[i] and in_segment:
                in_segment = False
                seg = self._make_segment(
                    seg_start, i - 1, match_mask, best_dists,
                    tgt_ts, ref_ts, sample_interval
                )
                if seg:
                    segments.append(seg)

        if in_segment:
            seg = self._make_segment(
                seg_start, len(match_mask) - 1, match_mask, best_dists,
                tgt_ts, ref_ts, sample_interval
            )
            if seg:
                segments.append(seg)

        return segments

    def _make_segment(
        self, start: int, end: int,
        match_mask: np.ndarray, best_dists: np.ndarray,
        tgt_ts: np.ndarray, ref_ts: np.ndarray,
        sample_interval: float,
    ) -> Optional[MatchSegment]:
        """构建匹配片段"""
        if end < start:
            return None

        seg_dists = best_dists[start:end + 1]
        similarities = np.maximum(0, (1 - seg_dists / 64) * 100)

        return MatchSegment(
            ref_start_time=ref_ts[0],
            ref_end_time=ref_ts[-1],
            target_start_time=float(tgt_ts[start]),
            target_end_time=float(tgt_ts[min(end, len(tgt_ts) - 1)]),
            avg_similarity=float(similarities.mean()),
            min_similarity=float(similarities.min()),
            matched_frames=int(match_mask[start:end + 1].sum()),
            total_frames=end - start + 1,
        )

    def _merge_nearby(self, segments: List[MatchSegment]) -> List[MatchSegment]:
        """合并间隔小于 merge_gap 的相邻片段"""
        if len(segments) <= 1:
            return segments

        sorted_segs = sorted(segments, key=lambda s: s.target_start_time)
        merged = [sorted_segs[0]]

        for seg in sorted_segs[1:]:
            last = merged[-1]
            gap = seg.target_start_time - last.target_end_time
            if gap <= self.merge_gap:
                last.target_end_time = seg.target_end_time
                last.matched_frames += seg.matched_frames
                last.total_frames += seg.total_frames
                last.avg_similarity = (
                    (last.avg_similarity * (last.total_frames - seg.total_frames) +
                     seg.avg_similarity * seg.total_frames) / last.total_frames
                    if last.total_frames > 0 else 0
                )
                last.min_similarity = min(last.min_similarity, seg.min_similarity)
            else:
                merged.append(seg)

        return merged
