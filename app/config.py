"""
配置管理模块
-----------
管理应用设置，支持 JSON 持久化存储到用户 AppData 目录。
"""

import json
import os
import sys
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional


def get_app_data_dir() -> Path:
    """获取应用数据目录 (Windows: %APPDATA%/VideoDedupTool)"""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path.home() / ".config"
    app_dir = base / "VideoDedupTool"
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


@dataclass
class AppConfig:
    """应用配置数据类"""
    # 配置版本（默认值变更时递增，用于迁移）
    config_version: int = 2

    # 目录设置
    reference_dir: str = ""
    target_dir: str = ""
    output_dir: str = ""
    watch_dirs: list = field(default_factory=list)

    # 哈希比对参数
    sample_interval: float = 1.0          # 采样间隔（秒），每隔多久取一帧
    hash_threshold: int = 10              # 汉明距离阈值（0-64），越小越严格
    min_match_ratio: float = 0.10         # 最小匹配比例（相对素材时长），低于此值忽略
    min_match_duration: float = 0.5       # 最短片段时长（秒）
    merge_gap: float = 1.0                # 相邻片段合并间隔（秒）

    # 处理选项
    auto_cut: bool = False                # 是否自动裁切
    keep_duplicates: bool = False         # 是否保留重复片段（否则删除）
    delete_originals: bool = False        # 处理后是否删除原文件
    use_multithread: bool = True          # 使用多线程
    max_workers: int = 4                  # 最大并发线程数
    use_gpu: bool = True                  # 使用 GPU 加速
    material_position: str = "both"       # 素材位置: "anywhere" / "beginning" / "end" / "both"
    position_search_margin: float = 0.15  # 搜索边界余量（相对素材时长的比例，0.05-0.50）

    # 首尾时间限定（可选项）
    limit_head_tail: bool = False         # 是否限定识别和裁剪到首尾指定时间内
    head_tail_time: float = 60.0          # 首尾操作时间（秒），视频时长小于此值则不跳过全量识别

    # 帧过滤（可选项）
    enable_frame_filter: bool = False     # 是否过滤过暗/过亮帧
    frame_dark_threshold: float = 16.0    # 灰度均值低于此值丢弃
    frame_bright_threshold: float = 240.0  # 灰度均值高于此值丢弃

    # 整文件粗筛 + 逐帧精筛（可选项）
    enable_coarse_filter: bool = True     # 是否启用整文件粗筛（默认开启，加速无关视频）
    coarse_interval: float = 5.0          # 粗筛采样间隔（秒）

    # 磁盘哈希缓存
    use_hash_cache: bool = True           # 是否启用磁盘哈希缓存（二次处理直接读缓存跳过解码）

    # 文件夹监控
    enable_watch: bool = False
    watch_interval: int = 5               # 扫描间隔（秒）
    watch_recursive: bool = True
    auto_process_new: bool = True

    # 界面设置
    theme: str = "dark"                   # dark / light
    language: str = "zh_CN"
    max_log_lines: int = 5000
    show_preview: bool = True

    # 哈希算法选择
    hash_algorithm: str = "dhash"         # dhash / phash / ahash / combined


class ConfigManager:
    """配置管理器：加载、保存、导出配置"""

    CONFIG_FILENAME = "config.json"

    def __init__(self):
        self._config_path = get_app_data_dir() / self.CONFIG_FILENAME
        self._config = AppConfig()
        self.load()

    @property
    def config(self) -> AppConfig:
        return self._config

    def load(self) -> AppConfig:
        """从磁盘加载配置，不存在则使用默认值"""
        data: dict = {}
        if self._config_path.exists():
            try:
                with open(self._config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for key, value in data.items():
                    if hasattr(self._config, key):
                        setattr(self._config, key, value)
            except (json.JSONDecodeError, IOError) as e:
                print(f"[Config] 加载配置失败: {e}，使用默认配置")
                data = {}
        self._migrate(data)
        return self._config

    def _migrate(self, data: dict):
        """配置迁移：默认值变更时，仅在用户沿用旧默认值的情况下更新。"""
        if data.get("config_version", 1) < 2:
            # v1 -> v2：粗筛默认开启、素材位置默认「开头和结尾」
            if data.get("material_position", "anywhere") == "anywhere":
                self._config.material_position = "both"
            if data.get("enable_coarse_filter", False) is False:
                self._config.enable_coarse_filter = True
            self._config.config_version = 2
            self.save()

    def save(self):
        """保存配置到磁盘"""
        try:
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(asdict(self._config), f, indent=2, ensure_ascii=False)
        except IOError as e:
            print(f"[Config] 保存配置失败: {e}")

    def reset(self):
        """重置为默认配置"""
        self._config = AppConfig()
        self.save()

    def export_to(self, path: str):
        """导出配置到指定路径"""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self._config), f, indent=2, ensure_ascii=False)

    def import_from(self, path: str):
        """从指定路径导入配置"""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for key, value in data.items():
            if hasattr(self._config, key):
                setattr(self._config, key, value)
        self.save()

    def get(self, key: str, default=None):
        return getattr(self._config, key, default)

    def set(self, key: str, value):
        if hasattr(self._config, key):
            setattr(self._config, key, value)
            self.save()
