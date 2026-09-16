"""
帧哈希算法模块
--------------
实现多种感知哈希算法用于视频帧相似度比对：
- dHash: 差异哈希（默认，速度与精度平衡最佳）
- pHash: 感知哈希（基于 DCT，对缩放/压缩更鲁棒）
- aHash: 均值哈希（最快，但对细节不敏感）
- 颜色直方图: 辅助判断色彩相似度
"""

import os
import json
import hashlib
import cv2
import numpy as np
from typing import List, Tuple, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger("VideoDedup.Hasher")


def _get_hash_cache_dir() -> str:
    """返回磁盘哈希缓存目录（LOCALAPPDATA/VideoDedupTool/hash_cache）。"""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "VideoDedupTool", "hash_cache")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


# 磁盘缓存上限（默认 2GB），超出后按最久未用（mtime）淘汰最旧文件
CACHE_MAX_BYTES = 2 * 1024 ** 3


def clear_hash_cache() -> int:
    """清空磁盘哈希缓存，返回删除的文件数。"""
    d = _get_hash_cache_dir()
    removed = 0
    try:
        for f in os.listdir(d):
            if f.endswith(".json"):
                try:
                    os.remove(os.path.join(d, f))
                    removed += 1
                except OSError:
                    pass
    except OSError:
        pass
    return removed


def _enforce_cache_limit():
    """缓存目录超过上限时，按最久未用顺序删除最旧的缓存文件。"""
    d = _get_hash_cache_dir()
    try:
        entries = [os.path.join(d, f) for f in os.listdir(d) if f.endswith(".json")]
        total = sum(os.path.getsize(e) for e in entries)
        if total <= CACHE_MAX_BYTES:
            return
        entries.sort(key=os.path.getmtime)  # 旧 -> 新
        target = int(CACHE_MAX_BYTES * 0.8)
        for e in entries:
            if total <= target:
                break
            try:
                total -= os.path.getsize(e)
                os.remove(e)
            except OSError:
                continue
        logger.info(f"磁盘哈希缓存已清理，降至 {total / (1024 ** 2):.0f}MB")
    except OSError:
        pass


@dataclass
class FrameHash:
    """单帧哈希数据"""
    timestamp: float       # 帧在视频中的时间（秒）
    frame_index: int       # 帧序号
    dhash: int             # 64位 dHash
    phash: Optional[int] = None   # 64位 pHash
    ahash: Optional[int] = None   # 64位 aHash
    histogram: Optional[np.ndarray] = None  # 颜色直方图（可选）
    source_path: str = ""  # 来源视频路径（用于标记素材对应关系）


class FrameHasher:
    """视频帧哈希计算器"""

    def __init__(
        self,
        sample_interval: float = 0.5,
        hash_size: int = 8,
        compute_phash: bool = False,
        compute_ahash: bool = False,
        compute_histogram: bool = False,
        use_gpu: bool = True,
        batch_size: int = 32,
        enable_frame_filter: bool = False,
        frame_dark_threshold: float = 16.0,
        frame_bright_threshold: float = 240.0,
        use_disk_cache: bool = True,
    ):
        """
        初始化帧哈希计算器。

        Args:
            sample_interval: 采样间隔（秒）
            hash_size: 哈希尺寸（默认 8，产生 64 位哈希）
            compute_phash: 是否同时计算 pHash
            compute_ahash: 是否同时计算 aHash
            compute_histogram: 是否同时计算颜色直方图
            use_gpu: 是否使用 GPU 加速
            batch_size: 批量处理帧数（越大 GPU 利用率越高）
            enable_frame_filter: 是否过滤过暗/过亮帧
            frame_dark_threshold: 灰度均值低于此值丢弃
            frame_bright_threshold: 灰度均值高于此值丢弃
        """
        self.sample_interval = sample_interval
        self.hash_size = hash_size
        self.compute_phash = compute_phash
        self.compute_ahash = compute_ahash
        self.compute_histogram = compute_histogram
        self.batch_size = batch_size
        self.enable_frame_filter = enable_frame_filter
        self.frame_dark_threshold = frame_dark_threshold
        self.frame_bright_threshold = frame_bright_threshold
        self._use_disk_cache = use_disk_cache

        # GPU 加速器
        from .gpu_utils import GPUFrameProcessor
        self._gpu_proc = GPUFrameProcessor(use_gpu=use_gpu)
        self._use_gpu = use_gpu and self._gpu_proc.gpu_enabled

    def hash_video(
        self, video_path: str,
        time_range: Optional[Tuple[float, float]] = None,
        sample_interval: Optional[float] = None,
    ) -> List[FrameHash]:
        """
        对视频文件进行采样哈希。
        使用批量处理 + GPU 加速提升性能。

        Args:
            video_path: 视频文件路径
            time_range: 可选的时间范围 (start_seconds, end_seconds)，
                       仅采样此范围内的帧。None 表示采样整个视频。
            sample_interval: 可选，覆盖实例默认采样间隔（用于粗筛更粗采样）。

        Returns:
            FrameHash 列表，按时间戳排序
        """
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            logger.warning(f"无法打开视频文件: {video_path}")
            return []

        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps if fps > 0 else 0

        # 计算采样间隔对应的帧间隔（允许单次调用覆盖实例默认间隔）
        effective_interval = self.sample_interval if sample_interval is None else sample_interval
        frame_interval = max(1, int(fps * effective_interval))

        # 处理 time_range：计算起始/结束帧号
        start_frame = 0
        end_frame = total_frames
        if time_range is not None and fps > 0:
            start_time, end_time = time_range
            start_frame = max(0, int(start_time * fps))
            end_frame = min(total_frames, int(end_time * fps) + 1)
            # 对齐 start_frame 到采样间隔的整数倍，保持采样模式一致
            if frame_interval > 0:
                start_frame = (start_frame // frame_interval) * frame_interval

        # 磁盘哈希缓存：命中则直接返回，跳过解码
        cache_key: Optional[str] = None
        if self._use_disk_cache:
            cache_key = self._cache_key(
                video_path, effective_interval, start_frame, end_frame, frame_interval
            )
            if cache_key:
                cached = self._load_cache(cache_key)
                if cached is not None:
                    logger.info(
                        f"命中磁盘哈希缓存: {os.path.basename(video_path)} "
                        f"({len(cached)} 帧)"
                    )
                    cap.release()
                    return cached

        gpu_tag = "(GPU)" if self._use_gpu else "(CPU)"
        range_info = ""
        if time_range is not None:
            range_info = (
                f", 范围=[{start_frame / fps:.1f}s-{end_frame / fps:.1f}s]"
            )

        # 构建 GPU 详细信息
        gpu_detail = ""
        if self._use_gpu:
            from .gpu_utils import get_gpu_info
            gpu_info = get_gpu_info()
            if gpu_info.available:
                gpu_detail = f", GPU={gpu_info.name}({gpu_info.memory_mb // 1024}GB)"
            else:
                gpu_detail = ", GPU=CuPy(软件加速)"

        logger.info(
            f"开始哈希视频 {gpu_tag}: {os.path.basename(video_path)} "
            f"(FPS={fps:.1f}, 总帧数={total_frames}, "
            f"时长={duration:.1f}s, 帧间隔={frame_interval}, batch={self.batch_size}{range_info}{gpu_detail})"
        )

        frame_hashes: List[FrameHash] = []
        processed = 0

        # 批量读取：用 grab() 跳帧（不解码），retrieve() 仅解码需要的帧
        batch_frames = []  # [(frame, timestamp, frame_index), ...]

        frame_idx = 0
        while True:
            # 超过结束帧：立即退出
            if frame_idx >= end_frame:
                break

            # 在起始帧之前：仅 grab 跳帧（不解码），快速跳过
            if frame_idx < start_frame:
                if not cap.grab():
                    break
                frame_idx += 1
                continue

            # grab() 仅读取不解码，比 read() 快 5-10x
            if frame_idx % frame_interval == 0:
                # 需要这一帧：先 grab 再 retrieve（等同于 read 但可控）
                grabbed = cap.grab()
                if not grabbed:
                    break
                ret, frame = cap.retrieve()
                if not ret:
                    break

                timestamp = frame_idx / fps
                batch_frames.append((frame, timestamp, frame_idx))

                if len(batch_frames) >= self.batch_size:
                    hashes = self._process_batch(batch_frames)
                    frame_hashes.extend(hashes)
                    processed += len(batch_frames)
                    batch_frames.clear()
            else:
                # 跳过此帧：只用 grab()，不解码
                if not cap.grab():
                    break

            frame_idx += 1

        # 处理剩余帧
        if batch_frames:
            hashes = self._process_batch(batch_frames)
            frame_hashes.extend(hashes)
            processed += len(batch_frames)

        cap.release()

        gpu_detail = ""
        if self._use_gpu:
            from .gpu_utils import get_gpu_info
            gpu_info = get_gpu_info()
            if gpu_info.available:
                gpu_detail = f", GPU={gpu_info.name.split()[0]}"  # 只取型号简称

        logger.info(
            f"哈希完成 {gpu_tag}: 共处理 {processed} 帧, "
            f"生成 {len(frame_hashes)} 个哈希 (间隔={self.sample_interval}s{gpu_detail})"
        )

        # 写入磁盘哈希缓存（供后续重复处理直接复用）
        if cache_key:
            self._save_cache(cache_key, frame_hashes)

        return frame_hashes

    def _cache_key(
        self, video_path: str, effective_interval: float,
        start_frame: int, end_frame: int, frame_interval: int,
    ) -> Optional[str]:
        """生成磁盘缓存键：涵盖所有影响哈希结果的因素。"""
        try:
            st = os.stat(video_path)
            mtime_ns = st.st_mtime_ns
            size = st.st_size
        except OSError:
            return None

        identity = (
            os.path.abspath(video_path),
            mtime_ns,
            size,
            self.hash_size,
            effective_interval,
            frame_interval,
            start_frame,
            end_frame,
            self.compute_phash,
            self.compute_ahash,
            self.enable_frame_filter,
            self.frame_dark_threshold,
            self.frame_bright_threshold,
        )
        return hashlib.sha256(repr(identity).encode("utf-8")).hexdigest()

    def _load_cache(self, key: str) -> Optional[List[FrameHash]]:
        """从磁盘读取哈希缓存，失败或不存在返回 None。"""
        if not key:
            return None
        path = os.path.join(_get_hash_cache_dir(), key + ".json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return None

        rows = data.get("hashes")
        if not isinstance(rows, list):
            return None

        hashes: List[FrameHash] = []
        for row in rows:
            try:
                t, i, d, p, a = row[0], row[1], row[2], row[3], row[4]
            except (IndexError, TypeError):
                continue
            hashes.append(FrameHash(
                timestamp=float(t), frame_index=int(i), dhash=int(d),
                phash=None if p is None else int(p),
                ahash=None if a is None else int(a),
                histogram=None, source_path="",
            ))
        return hashes

    def _save_cache(self, key: str, frame_hashes: List[FrameHash]) -> None:
        """把哈希结果写入磁盘缓存（原子替换，避免写坏）。"""
        if not key:
            return
        rows = [
            [h.timestamp, h.frame_index, h.dhash, h.phash, h.ahash]
            for h in frame_hashes
        ]
        path = os.path.join(_get_hash_cache_dir(), key + ".json")
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"hashes": rows}, f)
            os.replace(tmp, path)
            _enforce_cache_limit()
        except OSError as e:
            logger.debug(f"写入哈希缓存失败: {e}")

    def _is_valid_gray(self, gray: np.ndarray) -> bool:
        """判断灰度小图是否有效（过暗/过亮帧过滤）。

        过滤关闭时恒为 True。否则检查灰度均值是否落在
        [frame_dark_threshold, frame_bright_threshold] 区间内。
        """
        if not self.enable_frame_filter:
            return True
        mean = float(gray.mean())
        return self.frame_dark_threshold <= mean <= self.frame_bright_threshold

    def _process_batch(self, batch_frames: list) -> List[FrameHash]:
        """批量处理帧：GPU 加速缩放 + 灰度化 + 批量 dHash 计算"""
        size = self.hash_size

        if self._use_gpu and len(batch_frames) >= 32:
            # GPU 路径：批量灰度+缩放 → 过滤 → 批量 dHash
            gray_frames = self._gpu_proc.batch_resize_gray(
                batch_frames, (size + 1, size)
            )
            gray_frames = [
                (g, ts, idx) for g, ts, idx in gray_frames
                if self._is_valid_gray(g)
            ]
            dhash_results = self._gpu_proc.batch_compute_dhash(gray_frames, size)

            results = []
            for dhash_val, ts, idx in dhash_results:
                results.append(FrameHash(
                    timestamp=ts,
                    frame_index=idx,
                    dhash=dhash_val,
                    phash=None,
                    ahash=None,
                ))
            return results

        # CPU 路径：逐帧处理
        results = []
        for frame, ts, idx in batch_frames:
            gray = self._gpu_proc.resize_gray(frame, (size + 1, size))
            if not self._is_valid_gray(gray):
                continue
            dhash_val = self._compute_dhash_from_gray(gray)
            phash_val = None
            ahash_val = None
            if self.compute_phash:
                phash_gray = self._gpu_proc.resize_gray(frame, (32, 32))
                phash_val = self._compute_phash_from_gray(phash_gray)
            if self.compute_ahash:
                ahash_gray = self._gpu_proc.resize_gray(frame, (size, size))
                ahash_val = self._compute_ahash_from_gray(ahash_gray)

            results.append(FrameHash(
                timestamp=ts,
                frame_index=idx,
                dhash=dhash_val,
                phash=phash_val,
                ahash=ahash_val,
            ))
        return results

    def _compute_dhash_from_gray(self, gray: np.ndarray) -> int:
        """从已缩放的灰度图计算 dHash"""
        diff = gray[:, 1:] > gray[:, :-1]
        return self._bits_to_int(diff.flatten())

    def _compute_phash_from_gray(self, gray: np.ndarray) -> int:
        """从已缩放的灰度图计算 pHash"""
        size = self.hash_size
        dct = cv2.dct(gray.astype(np.float32))
        dct_low = dct[:size, :size]
        mean = dct_low.mean()
        bits = dct_low > mean
        return self._bits_to_int(bits.flatten())

    def _compute_ahash_from_gray(self, gray: np.ndarray) -> int:
        """从已缩放的灰度图计算 aHash"""
        mean = gray.mean()
        bits = gray > mean
        return self._bits_to_int(bits.flatten())

    def _compute_frame_hash(
        self, frame: np.ndarray, timestamp: float, frame_index: int
    ) -> FrameHash:
        """计算单帧的所有哈希值"""
        # 转为灰度图
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # dHash（始终计算，速度最快）
        dhash_val = self._compute_dhash(gray)

        # 可选哈希
        phash_val = self._compute_phash(gray) if self.compute_phash else None
        ahash_val = self._compute_ahash(gray) if self.compute_ahash else None
        hist = self._compute_histogram(frame) if self.compute_histogram else None

        return FrameHash(
            timestamp=timestamp,
            frame_index=frame_index,
            dhash=dhash_val,
            phash=phash_val,
            ahash=ahash_val,
            histogram=hist
        )

    def _compute_dhash(self, gray: np.ndarray) -> int:
        """
        计算差异哈希 (Difference Hash)。

        算法：
        1. 缩放图像到 (hash_size+1) x hash_size
        2. 比较相邻水平像素，左边 > 右边则为 1
        3. 生成 64 位哈希值
        """
        size = self.hash_size
        resized = cv2.resize(gray, (size + 1, size), interpolation=cv2.INTER_AREA)
        diff = resized[:, 1:] > resized[:, :-1]
        return self._bits_to_int(diff.flatten())

    def _compute_phash(self, gray: np.ndarray) -> int:
        """
        计算感知哈希 (Perceptual Hash)。

        算法：
        1. 缩放图像到 32x32
        2. 应用 DCT 变换
        3. 取左上角 hash_size x hash_size 低频系数
        4. 比较每个系数与均值
        """
        size = self.hash_size
        # 缩放并转为浮点
        resized = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
        # DCT
        dct = cv2.dct(resized)
        # 取左上角低频部分
        dct_low = dct[:size, :size]
        # 与均值比较
        mean = dct_low.mean()
        bits = dct_low > mean
        return self._bits_to_int(bits.flatten())

    def _compute_ahash(self, gray: np.ndarray) -> int:
        """
        计算均值哈希 (Average Hash)。

        算法：
        1. 缩放图像到 hash_size x hash_size
        2. 比较每个像素与均值
        """
        size = self.hash_size
        resized = cv2.resize(gray, (size, size), interpolation=cv2.INTER_AREA)
        mean = resized.mean()
        bits = resized > mean
        return self._bits_to_int(bits.flatten())

    def _compute_histogram(self, frame: np.ndarray, bins: int = 64) -> np.ndarray:
        """计算颜色直方图（HSV 空间）"""
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [bins, bins], [0, 180, 0, 256])
        cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)
        return hist

    @staticmethod
    def _bits_to_int(bits: np.ndarray) -> int:
        """将布尔数组转为 64 位整数哈希"""
        val = 0
        for bit in bits:
            val = (val << 1) | (1 if bit else 0)
        return val


def hamming_distance(hash1: int, hash2: int) -> int:
    """计算两个哈希值的汉明距离（不同位的数量）"""
    xor = hash1 ^ hash2
    return xor.bit_count()


def histogram_similarity(hist1: np.ndarray, hist2: np.ndarray) -> float:
    """
    计算两个直方图的相似度（使用相关性比较）。
    返回值范围 [-1, 1]，1 表示完全相同。
    """
    if hist1 is None or hist2 is None:
        return 0.0
    return float(cv2.compareHist(hist1, hist2, cv2.HISTCMP_CORREL))


def get_video_info(video_path: str) -> dict:
    """获取视频基本信息"""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return {}

    info = {
        "path": video_path,
        "fps": cap.get(cv2.CAP_PROP_FPS),
        "frame_count": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
        "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        "codec": int(cap.get(cv2.CAP_PROP_FOURCC)),
        "duration": 0.0,
    }
    if info["fps"] > 0:
        info["duration"] = info["frame_count"] / info["fps"]

    cap.release()
    return info
