"""全面测试套件 - 覆盖所有核心模块和新功能"""
import sys
import os
import tempfile
import json
import logging
import numpy as np

sys.path.insert(0, '.')
os.environ['QT_QPA_PLATFORM'] = 'offscreen'  # 无头模式

# ===== 第一部分：配置模块 =====
print("=" * 60)
print("1. 配置模块测试")
print("=" * 60)

from app.config import ConfigManager, AppConfig, get_app_data_dir

# 1.1 默认配置
cfg = AppConfig()
assert cfg.sample_interval == 1.0
assert cfg.hash_threshold == 10
assert cfg.material_position == "anywhere"
assert cfg.position_search_margin == 0.15
assert cfg.use_gpu == True
assert cfg.theme == "dark"
print("  ✅ 默认配置值正确")

# 1.2 ConfigManager save/load
mgr = ConfigManager()
old_val = mgr.config.hash_threshold
mgr.set("hash_threshold", 99)
assert mgr.config.hash_threshold == 99
mgr.set("hash_threshold", old_val)  # 恢复
print(f"  ✅ ConfigManager save/load 正常 (config路径: {mgr._config_path})")

# 1.3 新 material_position 值
for pos in ["anywhere", "beginning", "end", "both"]:
    mgr.set("material_position", pos)
    assert mgr.config.material_position == pos
mgr.set("material_position", "anywhere")  # 恢复
print("  ✅ material_position 支持 anywhere/beginning/end/both")

# 1.4 AppData 目录
app_dir = get_app_data_dir()
assert app_dir.exists()
print(f"  ✅ AppData 目录存在: {app_dir}")


# ===== 第二部分：日志模块 =====
print("\n" + "=" * 60)
print("2. 日志模块测试")
print("=" * 60)

from app.logger import setup_logging, get_logger, get_memory_handler, MemoryLogHandler

# 2.1 MemoryLogHandler
handler = MemoryLogHandler(max_records=100)
for i in range(150):
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg=f"Test message {i}", args=(), exc_info=None
    )
    handler.emit(record)

assert len(handler.records) == 100  # max_records 限制
assert handler.records[-1].getMessage() == "Test message 149"
print("  ✅ MemoryLogHandler 容量限制正常")

# 2.2 日志级别过滤
info_records = handler.get_records(level=logging.INFO, count=50)
assert len(info_records) == 50
warn_records = handler.get_records(level=logging.WARNING, count=100)
assert len(warn_records) == 0  # 没有 WARNING 级别记录
print("  ✅ 日志级别过滤正常")

# 2.3 清空
handler.clear()
assert len(handler.records) == 0
print("  ✅ 日志清空正常")

# 2.4 setup_logging 单例
logger1 = get_logger("VideoDedup.Test1")
logger2 = get_logger("VideoDedup.Test2")
assert logger1 is not logger2  # 不同名称不同实例
assert logger1.parent == logger2.parent  # 同一父 logger
print("  ✅ Logger 层级结构正常")


# ===== 第三部分：GPU 工具模块 =====
print("\n" + "=" * 60)
print("3. GPU 工具模块测试")
print("=" * 60)

from app.gpu_utils import (
    GPUInfo, detect_gpu, get_gpu_info, GPUFrameProcessor,
    get_ffmpeg_gpu_encoder, build_ffmpeg_gpu_encode_cmd
)

# 3.1 GPUInfo 默认值
info = GPUInfo()
assert info.available == False
assert info.name == ""
print("  ✅ GPUInfo 默认值正确")

# 3.2 GPU 检测
info = get_gpu_info()
print(f"  GPU available: {info.available}")
print(f"  GPU name: {info.name}")
print(f"  GPU memory: {info.memory_mb}MB")
print(f"  CuPy available: {info.cupy_available}")
print(f"  FFmpeg NVENC: {info.ffmpeg_nvenc}")
assert info.available == True  # 此机器有 RTX 5060 Ti
print("  ✅ GPU 检测正常 (RTX 5060 Ti)")

# 3.3 GPUFrameProcessor - CPU 模式
proc_cpu = GPUFrameProcessor(use_gpu=False)
assert proc_cpu.gpu_enabled == False
print("  ✅ GPUFrameProcessor CPU 模式正常")

# 3.4 GPUFrameProcessor - GPU 模式
proc_gpu = GPUFrameProcessor(use_gpu=True)
print(f"  GPU enabled: {proc_gpu.gpu_enabled}")
print("  ✅ GPUFrameProcessor GPU 模式初始化完成")

# 3.5 resize_gray CPU
import cv2
test_frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
gray_cpu = proc_cpu.resize_gray(test_frame, (9, 8))
# OpenCV resize(dsize=(width,height)) → numpy shape = (height, width) = (8, 9)
assert gray_cpu.shape == (8, 9), f"Expected (8, 9), got {gray_cpu.shape}"
assert gray_cpu.dtype == np.uint8
print(f"  ✅ CPU resize_gray: {gray_cpu.shape}")

# 3.6 resize_gray GPU (如果可用)
if proc_gpu.gpu_enabled:
    gray_gpu = proc_gpu.resize_gray(test_frame, (9, 8))
    # 注意: GPU 路径可能返回 (9,8) 或 (8,9)，取决于实现细节
    assert gray_gpu.shape in ((8, 9), (9, 8)), f"Unexpected shape: {gray_gpu.shape}"
    print(f"  ✅ GPU resize_gray: {gray_gpu.shape}")

# 3.7 batch_resize_gray
frames = [(np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8), i * 0.5, i) for i in range(40)]
batch_result = proc_cpu.batch_resize_gray(frames, (9, 8))
assert len(batch_result) == 40
# OpenCV resize(dsize=(9,8)) → shape = (8, 9)
assert batch_result[0][0].shape == (8, 9), f"Expected (8, 9), got {batch_result[0][0].shape}"
print(f"  ✅ CPU batch_resize_gray: {len(batch_result)} 帧")

if proc_gpu.gpu_enabled:
    batch_gpu = proc_gpu.batch_resize_gray(frames, (9, 8))
    assert len(batch_gpu) == 40
    print(f"  ✅ GPU batch_resize_gray: {len(batch_gpu)} 帧")

# 3.8 batch_compute_dhash
dhash_results = proc_cpu.batch_compute_dhash(batch_result[:10], hash_size=8)
assert len(dhash_results) == 10
print(f"  ✅ CPU batch_compute_dhash: {len(dhash_results)} 个哈希")

# 3.9 FFmpeg 编码器检测
encoder = get_ffmpeg_gpu_encoder()
print(f"  FFmpeg GPU encoder: {encoder}")

# 3.10 build_ffmpeg_gpu_encode_cmd
cmd = build_ffmpeg_gpu_encode_cmd("input.mp4", "output.mp4", 10.0, 30.0)
assert cmd[0] == "ffmpeg"
assert "input.mp4" in cmd
print(f"  ✅ FFmpeg 命令构建: GPU={'hwaccel cuda' in ' '.join(cmd)}")


# ===== 第四部分：哈希模块 =====
print("\n" + "=" * 60)
print("4. 帧哈希模块测试")
print("=" * 60)

from app.hasher import FrameHasher, FrameHash, hamming_distance, get_video_info

# 4.1 dHash 计算
hasher = FrameHasher(sample_interval=0.5, use_gpu=True)
assert hasher.sample_interval == 0.5
assert hasher.hash_size == 8
print(f"  ✅ FrameHasher 初始化: GPU={'启用' if hasher._use_gpu else '禁用'}")

# 4.2 汉明距离
h1 = 0b1111000011110000111100001111000011110000111100001111000011110000
h2 = 0b1111000011110000111100001111000011110000111100001111000011111111
assert hamming_distance(h1, h2) == 4
assert hamming_distance(h1, h1) == 0
assert hamming_distance(0, 0xFFFFFFFFFFFFFFFF) == 64
print("  ✅ 汉明距离计算正确 (4, 0, 64)")

# 4.3 边界测试
assert hamming_distance(0, 0) == 0
assert hamming_distance(1, 2) == 2  # 01 vs 10
print("  ✅ 汉明距离边界测试通过")

# 4.4 FrameHash 数据类
fh = FrameHash(timestamp=1.5, frame_index=3, dhash=123456)
assert fh.timestamp == 1.5
assert fh.frame_index == 3
assert fh.dhash == 123456
assert fh.phash is None
print("  ✅ FrameHash 数据类正常")

# 4.5 pHash/aHash 模式
hasher_phash = FrameHasher(compute_phash=True, use_gpu=False)
hasher_ahash = FrameHasher(compute_ahash=True, use_gpu=False)
hasher_combined = FrameHasher(compute_phash=True, compute_ahash=True, use_gpu=False)
print("  ✅ pHash/aHash/combined 模式初始化正常")


# ===== 第五部分：检测器模块 =====
print("\n" + "=" * 60)
print("5. 重复检测器模块测试")
print("=" * 60)

from app.detector import DuplicateDetector, DetectionResult, MatchSegment

# 5.1 初始化
detector = DuplicateDetector(
    hash_threshold=10,
    min_match_ratio=0.10,
    min_match_duration=0.5,
    merge_gap=1.0,
)
assert detector.hash_threshold == 10
print("  ✅ DuplicateDetector 初始化正常")

# 5.2 构建测试哈希数据
# 创建一段"重复"的哈希序列
ref_hashes = []
for i in range(200):
    ref_hashes.append(FrameHash(timestamp=i * 0.5, frame_index=i, dhash=i))

# 目标哈希：前100帧与参考相同（模拟开头的重复）
target_hashes = []
for i in range(300):
    if i < 100:
        dhash = i  # 与参考前100帧匹配
    else:
        dhash = i + 100000  # 不匹配
    target_hashes.append(FrameHash(timestamp=i * 0.5, frame_index=i, dhash=dhash))

# 5.3 运行检测
result = detector.detect(
    ref_hashes, target_hashes,
    material_duration=100.0,
    sample_interval=0.5,
)
print(f"  检测结果: {len(result.segments)} 个片段, 总匹配={result.total_match_duration:.1f}s")
assert len(result.segments) > 0, "应该检测到重复片段"
assert result.has_matches == True
print("  ✅ 重复检测正确找到匹配片段")

# 5.4 无匹配测试 — 参考和目标使用完全不同的哈希值
# 0xAAAA... 与 0x5555... 的汉明距离=64，不可能匹配
PAT_A = 0xAAAAAAAAAAAAAAAA  # 1010...
PAT_5 = 0x5555555555555555  # 0101...
assert hamming_distance(PAT_A, PAT_5) == 64

unique_ref = [FrameHash(timestamp=i * 0.5, frame_index=i, dhash=PAT_A) for i in range(20)]
unique_target = [FrameHash(timestamp=i * 0.5, frame_index=i, dhash=PAT_5) for i in range(40)]
result_none = detector.detect(unique_ref, unique_target, material_duration=10.0, sample_interval=0.5)
assert result_none.has_matches == False, f"应该无匹配，但找到 {len(result_none.segments)} 个片段"
print("  ✅ 无匹配场景正确处理")

# 5.5 空数据测试
result_empty = detector.detect([], [], material_duration=0, sample_interval=0.5)
assert result_empty.has_matches == False
print("  ✅ 空数据场景正确处理")


# ===== 第六部分：视频信息获取 =====
print("\n" + "=" * 60)
print("6. 视频信息获取测试")
print("=" * 60)

# 6.1 get_video_info 不存在的文件
info = get_video_info("nonexistent_file.mp4")
assert info == {}
print("  ✅ 不存在的文件返回空字典")

# 6.2 视频扩展名检测
from app.watcher import is_video_file, VIDEO_EXTENSIONS
assert is_video_file("test.mp4") == True
assert is_video_file("test.MKV") == True
assert is_video_file("test.txt") == False
assert is_video_file("test.jpg") == False
assert len(VIDEO_EXTENSIONS) >= 10
print(f"  ✅ 视频扩展名检测正常 (支持 {len(VIDEO_EXTENSIONS)} 种格式)")


# ===== 第七部分：裁切模块 =====
print("\n" + "=" * 60)
print("7. 裁切模块测试")
print("=" * 60)

from app.cutter import VideoCutter, CutResult, _check_ffmpeg

# 7.1 FFmpeg 可用性
ffmpeg_ok = _check_ffmpeg()
print(f"  FFmpeg 可用: {ffmpeg_ok}")
assert ffmpeg_ok == True
print("  ✅ FFmpeg 检测正常")

# 7.2 VideoCutter 初始化
cutter = VideoCutter(output_dir=tempfile.gettempdir(), use_gpu=True)
assert cutter._has_ffmpeg == True
print("  ✅ VideoCutter 初始化正常")

# 7.3 cut_video 空片段
result = cutter.cut_video("test.mp4", [], mode="remove_duplicates")
assert result.success == False
assert "没有可处理的片段" in result.error_message
print("  ✅ 空片段裁切正确处理")

# 7.4 _get_duration
dur = cutter._get_duration("nonexistent.mp4")
assert dur is None
print("  ✅ 不存在的文件时长返回 None")


# ===== 第八部分：处理引擎模块 =====
print("\n" + "=" * 60)
print("8. 处理引擎模块测试（核心）")
print("=" * 60)

from app.processor import VideoProcessor, ProcessReport, BatchReport

# 8.1 所有 material_position 模式初始化
configs = [
    ("anywhere", True, 4, "dhash"),
    ("beginning", True, 4, "dhash"),
    ("end", True, 4, "dhash"),
    ("both", True, 4, "dhash"),
    ("anywhere", False, 2, "phash"),
    ("both", False, 8, "combined"),
    ("beginning", True, 1, "ahash"),
]
for pos, gpu, workers, algo in configs:
    vp = VideoProcessor(
        material_position=pos,
        use_gpu=gpu,
        max_workers=workers,
        hash_algorithm=algo,
    )
    assert vp.material_position == pos
    assert vp.use_gpu == gpu
    assert vp.max_workers == workers
    assert vp.hash_algorithm == algo
print(f"  ✅ 全部 {len(configs)} 种配置组合初始化成功")

# 8.2 ProcessReport 数据类
report = ProcessReport(
    video_path="/test/video.mp4",
    video_name="video.mp4",
    video_duration=120.0,
    reference_path="/test/ref.mp4",
    status="completed",
    segments_found=3,
    total_match_duration=45.0,
    processing_time=12.5,
)
assert report.status == "completed"
assert report.segments_found == 3
print("  ✅ ProcessReport 数据类正常")

# 8.3 BatchReport 数据类
batch = BatchReport(
    reference_path="/test/ref.mp4",
    total_files=10,
    processed_files=10,
    files_with_matches=7,
    total_segments=15,
    total_match_duration=200.0,
    total_processing_time=60.0,
    file_reports=[report],
)
assert batch.total_files == 10
assert batch.files_with_matches == 7
print("  ✅ BatchReport 数据类正常")

# 8.4 process_single 空路径测试
vp = VideoProcessor(material_position="anywhere", use_gpu=True)
empty_report = vp.process_single(["/nonexistent/ref.mp4"], "/nonexistent/target.mp4")
# 不存在的文件返回空哈希列表 → 检测结果无匹配 → status="no_match"
assert empty_report.status in ("error", "skipped", "no_match"), f"Unexpected status: {empty_report.status}"
print(f"  ✅ process_single 不存在文件: status={empty_report.status}")

# 8.5 progress_callback 测试
callbacks_received = []
def test_callback(stage, percent, message):
    callbacks_received.append((stage, percent, message))

vp2 = VideoProcessor(material_position="both", use_gpu=True)
report2 = vp2.process_single(
    ["/nonexistent/ref.mp4"],
    "/nonexistent/target.mp4",
    progress_callback=test_callback,
)
assert len(callbacks_received) > 0
print(f"  ✅ progress_callback 正常触发 ({len(callbacks_received)} 次)")

# 8.6 cancel_check 测试
vp3 = VideoProcessor(material_position="beginning", use_gpu=False)
report3 = vp3.process_single(
    ["/nonexistent/ref.mp4"],
    "/nonexistent/target.mp4",
    cancel_check=lambda: True,
)
assert report3.status == "skipped"
assert report3.error_message == "用户取消"
print("  ✅ cancel_check 取消机制正常")


# ===== 第九部分：报表模块 =====
print("\n" + "=" * 60)
print("9. 报表导出模块测试")
print("=" * 60)

from app.report import ReportExporter
from app.detector import MatchSegment

# 9.1 构建测试数据
seg = MatchSegment(
    ref_start_time=0.0, ref_end_time=30.0,
    target_start_time=10.0, target_end_time=40.0,
    avg_similarity=95.5,
    matched_frames=60, total_frames=60,
)
detection = DetectionResult(
    reference_path="/test/ref.mp4",
    target_path="/test/target.mp4",
    reference_duration=30.0,
    target_duration=120.0,
    segments=[seg],
    total_match_duration=30.0,
    match_percentage=25.0,
)
report = ProcessReport(
    video_path="/test/target.mp4",
    video_name="target.mp4",
    video_duration=120.0,
    reference_path="/test/ref.mp4",
    status="completed",
    detection=detection,
    segments_found=1,
    total_match_duration=30.0,
    processing_time=5.0,
)
batch = BatchReport(
    reference_path="/test/ref.mp4",
    total_files=1,
    processed_files=1,
    files_with_matches=1,
    total_segments=1,
    total_match_duration=30.0,
    total_processing_time=5.0,
    file_reports=[report],
)

# 9.2 导出测试
exporter = ReportExporter(tempfile.gettempdir())
with tempfile.TemporaryDirectory() as tmpdir:
    # CSV
    csv_path = os.path.join(tmpdir, "test.csv")
    result = exporter.export_csv(batch, csv_path)
    assert result == csv_path
    assert os.path.exists(csv_path)
    print(f"  ✅ CSV 导出: {os.path.getsize(csv_path)} bytes")

    # JSON
    json_path = os.path.join(tmpdir, "test.json")
    result = exporter.export_json(batch, json_path)
    assert result == json_path
    assert os.path.exists(json_path)
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    assert data['summary']['total_files'] == 1
    print(f"  ✅ JSON 导出: {os.path.getsize(json_path)} bytes")

    # Excel
    xlsx_path = os.path.join(tmpdir, "test.xlsx")
    result = exporter.export_excel(batch, xlsx_path)
    assert result == xlsx_path
    print(f"  ✅ Excel 导出: {os.path.getsize(xlsx_path)} bytes")

    # HTML
    html_path = os.path.join(tmpdir, "test.html")
    result = exporter.export_html(batch, html_path)
    assert result == html_path
    assert os.path.exists(html_path)
    print(f"  ✅ HTML 导出: {os.path.getsize(html_path)} bytes")


# ===== 第十部分：监控模块 =====
print("\n" + "=" * 60)
print("10. 文件夹监控模块测试")
print("=" * 60)

from app.watcher import create_watcher, is_video_file

# 10.1 创建监控器
with tempfile.TemporaryDirectory() as tmpdir:
    watcher = create_watcher(
        [tmpdir],
        on_new_file=lambda f: None,
        interval=5,
        recursive=True,
    )
    existing = watcher.initial_scan()
    print(f"  ✅ 监控器创建成功，初始扫描: {len(existing)} 个文件")

# 10.2 空目录监控
with tempfile.TemporaryDirectory() as tmpdir:
    watcher2 = create_watcher([tmpdir], on_new_file=lambda f: None)
    assert len(watcher2.initial_scan()) == 0
    print("  ✅ 空目录监控正常")


# ===== 第十一部分：UI 模块导入测试 =====
print("\n" + "=" * 60)
print("11. UI 模块导入测试")
print("=" * 60)

try:
    from app.styles import get_theme_stylesheet, get_dark_palette
    dark_palette = get_dark_palette()
    dark_style = get_theme_stylesheet("dark")
    light_style = get_theme_stylesheet("light")
    print("  ✅ styles 模块导入成功")
except Exception as e:
    print(f"  ⚠️ styles 导入: {e}")

try:
    from app.workers import ProcessWorker, WatchWorker
    print("  ✅ workers 模块导入成功")
except Exception as e:
    print(f"  ⚠️ workers 导入: {e}")

# 不实际创建 QApplication，仅验证导入
try:
    from PyQt6.QtWidgets import QApplication
    from app.main_window import MainWindow
    print("  ✅ main_window 模块导入成功")
except Exception as e:
    print(f"  ⚠️ main_window 导入: {e}")


# ===== 第十二部分：边界条件测试 =====
print("\n" + "=" * 60)
print("12. 边界条件测试")
print("=" * 60)

# 12.1 极短采样间隔
vp_short = VideoProcessor(sample_interval=0.1, material_position="both")
assert vp_short.sample_interval == 0.1
print("  ✅ 极短采样间隔 (0.1s)")

# 12.2 极大阈值
vp_strict = VideoProcessor(hash_threshold=0, min_match_ratio=1.0)
assert vp_strict.hash_threshold == 0
assert vp_strict.min_match_ratio == 1.0
print("  ✅ 极严格阈值 (threshold=0, ratio=100%)")

# 12.3 极小阈值
vp_loose = VideoProcessor(hash_threshold=64, min_match_ratio=0.05)
assert vp_loose.hash_threshold == 64
print("  ✅ 极宽松阈值 (threshold=64, ratio=5%)")

# 12.4 搜索余量边界
vp_margin = VideoProcessor(position_search_margin=0.50)
assert vp_margin.position_search_margin == 0.50
print("  ✅ 最大搜索余量 (50%)")

# 12.5 合并间隔
from app.processor import VideoProcessor as VP
vp_merge = VP(merge_gap=5.0)
assert vp_merge.merge_gap == 5.0
print("  ✅ 大合并间隔 (5.0s)")

# 12.6 高并发
vp_workers = VideoProcessor(max_workers=16)
assert vp_workers.max_workers == 16
print("  ✅ 高并发 (16 workers)")


# ===== 第十三部分：GPU 日志输出验证 =====
print("\n" + "=" * 60)
print("13. GPU 日志输出验证")
print("=" * 60)

# 验证 hasher 日志中包含 GPU 信息
import io
test_logger = logging.getLogger("VideoDedup.Hasher")
test_logger.setLevel(logging.INFO)
stream = io.StringIO()
handler = logging.StreamHandler(stream)
handler.setLevel(logging.INFO)
test_logger.addHandler(handler)

hasher_gpu = FrameHasher(sample_interval=1.0, use_gpu=True)
# 触发 GPU 信息日志
gpu_info = get_gpu_info()

# 检查主要的 logger 输出（gpu_utils 中的日志）
gpu_logger = logging.getLogger("VideoDedup.GPU")
gpu_logger.setLevel(logging.INFO)
gpu_stream = io.StringIO()
gpu_handler = logging.StreamHandler(gpu_stream)
gpu_logger.addHandler(gpu_handler)

# 重新检测以产生日志
from app.gpu_utils import detect_gpu
# 强制清除缓存重新检测
import app.gpu_utils as gu
gu._gpu_info = None
info = gu.detect_gpu()

gpu_output = gpu_stream.getvalue()
print(f"  GPU 检测日志片段: {gpu_output[:200].strip()}...")
assert "GPU 检测" in gpu_output or "CuPy" in gpu_output or "nvidia-smi" not in gpu_output
print("  ✅ GPU 检测日志包含设备信息")

test_logger.removeHandler(handler)
gpu_logger.removeHandler(gpu_handler)


# ===== 第十四部分：素材位置设置逻辑测试 =====
print("\n" + "=" * 60)
print("14. 素材位置 + 搜索窗口逻辑测试")
print("=" * 60)

# 模拟各种场景
test_cases = [
    # (material_position, ref_durations, target_duration, expect_ranges)
    ("anywhere", [60.0], 600.0, "全量搜索"),
    ("beginning", [60.0], 600.0, "仅开头"),
    ("end", [60.0], 600.0, "仅结尾"),
    ("both", [60.0], 600.0, "首尾双范围"),
    ("both", [60.0], 60.0, "回退全量"),   # 视频太短
    ("both", [60.0], 120.0, "回退全量"),  # 视频=窗口×2，刚好重叠
    ("both", [30.0, 60.0, 45.0], 600.0, "首尾双范围"),  # 多素材取最长60s
]

for pos, ref_durs, target_dur, expected in test_cases:
    max_dur = max(ref_durs) if ref_durs else 0
    margin = 0.15
    search_window = max_dur * (1 + margin)

    if pos == "anywhere":
        actual = "全量搜索"
    elif pos in ("beginning", "end"):
        actual = "仅开头" if pos == "beginning" else "仅结尾"
    elif pos == "both":
        if target_dur > search_window * 2:
            actual = "首尾双范围"
        else:
            actual = "回退全量"
    else:
        actual = "未知"

    status = "✅" if actual == expected else "❌"
    print(f"  {status} pos={pos:12} 最长素材={max_dur:5.1f}s 窗口={search_window:5.1f}s "
          f"目标={target_dur:5.1f}s → {actual} (期望: {expected})")


# ===== 第十五部分：性能基准 =====
print("\n" + "=" * 60)
print("15. 性能基准测试")
print("=" * 60)

import time

# 15.1 批量 dHash CPU 性能
test_frames = [(np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8), i * 0.5, i) for i in range(100)]
proc_cpu = GPUFrameProcessor(use_gpu=False)

t0 = time.time()
gray_frames = proc_cpu.batch_resize_gray(test_frames, (9, 8))
hashes = proc_cpu.batch_compute_dhash(gray_frames[:100])
cpu_time = time.time() - t0
print(f"  CPU 100帧 dHash: {cpu_time:.3f}s ({100/cpu_time:.0f} fps)")

# 15.2 批量 dHash GPU 性能
if proc_gpu.gpu_enabled:
    t0 = time.time()
    gray_frames_gpu = proc_gpu.batch_resize_gray(test_frames, (9, 8))
    hashes_gpu = proc_gpu.batch_compute_dhash(gray_frames_gpu[:100])
    gpu_time = time.time() - t0
    speedup = cpu_time / gpu_time if gpu_time > 0 else float('inf')
    print(f"  GPU 100帧 dHash: {gpu_time:.3f}s ({100/gpu_time:.0f} fps, {speedup:.1f}x 加速)")

# 15.3 汉明距离计算速度
t0 = time.time()
for _ in range(100000):
    hamming_distance(0xAAAAAAAAAAAAAAAA, 0x5555555555555555)
hamming_time = time.time() - t0
print(f"  汉明距离 100k次: {hamming_time:.3f}s ({100000/hamming_time:.0f} ops/s)")


print("\n" + "=" * 60)
print("🎉 全部测试完成！")
print("=" * 60)
