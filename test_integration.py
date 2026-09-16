"""快速集成测试 - 验证所有模块导入和基本功能"""
import sys
sys.path.insert(0, '.')

# Test all core imports
from app.config import ConfigManager, AppConfig, get_app_data_dir
from app.logger import setup_logging, get_logger, get_memory_handler
from app.hasher import FrameHasher, FrameHash, hamming_distance, get_video_info
from app.detector import DuplicateDetector, DetectionResult, MatchSegment
from app.cutter import VideoCutter, CutResult, _check_ffmpeg
from app.processor import VideoProcessor, ProcessReport, BatchReport
from app.report import ReportExporter
from app.watcher import create_watcher, is_video_file, VIDEO_EXTENSIONS

# Test basic functionality
print('Testing config...')
mgr = ConfigManager()
print(f'  Config path: {mgr._config_path}')
print(f'  Theme: {mgr.config.theme}')
print(f'  Hash threshold: {mgr.config.hash_threshold}')

print('Testing hasher...')
hasher = FrameHasher(sample_interval=0.5)
print(f'  Sample interval: {hasher.sample_interval}')

print('Testing detector...')
detector = DuplicateDetector(hash_threshold=10, min_match_duration=1.0)
print(f'  Threshold: {detector.hash_threshold}')

print('Testing hash functions...')
h1 = 0b1111000011110000111100001111000011110000111100001111000011110000
h2 = 0b1111000011110000111100001111000011110000111100001111000011111111
dist = hamming_distance(h1, h2)
print(f'  Hamming distance: {dist}')
assert dist == 4, f"Expected 4, got {dist}"

print('Testing video file detection...')
print(f'  mp4 is video: {is_video_file("test.mp4")}')
print(f'  txt is NOT video: {is_video_file("test.txt")}')
print(f'  Supported extensions: {len(VIDEO_EXTENSIONS)}')
assert is_video_file("test.mp4") == True
assert is_video_file("test.txt") == False

print('Testing report exporter...')
exporter = ReportExporter()
print(f'  Output dir: {exporter.output_dir}')

print()
print('✅ All tests passed! System is operational.')
