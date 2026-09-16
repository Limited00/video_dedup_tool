"""
主窗口模块
----------
视频去重工具的主 GUI 窗口。
提供文件管理、参数设置、处理控制、结果展示、日志查看等功能。
采用 Windows 11 Fluent Design 深色风格。
"""

import os
import sys
import json
import html
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QPushButton, QLabel, QLineEdit, QSpinBox, QDoubleSpinBox,
    QComboBox, QCheckBox, QGroupBox, QTableWidget, QTableWidgetItem,
    QTextEdit, QProgressBar, QStatusBar, QMenuBar, QMenu,
    QToolBar, QFileDialog, QMessageBox, QTabWidget, QListWidget,
    QListWidgetItem, QHeaderView, QAbstractItemView, QApplication,
    QFrame, QStyle, QTreeWidget, QTreeWidgetItem, QGridLayout,
    QSlider, QSizePolicy, QScrollArea,
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QSize, QSettings,
)
from PyQt6.QtGui import (
    QAction, QIcon, QFont, QColor, QPalette, QDragEnterEvent,
    QDropEvent, QTextCursor, QKeySequence,
)

from .config import ConfigManager
from .logger import (
    setup_logging, get_logger, get_memory_handler, MemoryLogHandler
)
from .styles import get_theme_stylesheet, get_dark_palette
from .processor import VideoProcessor, ProcessReport, BatchReport
from .workers import ProcessWorker, WatchWorker
from .report import ReportExporter
from .watcher import is_video_file

logger = get_logger("VideoDedup.GUI")


class MainWindow(QMainWindow):
    """主窗口"""

    # 常量
    WINDOW_TITLE = "视频去重工具 - Video Dedup Tool"
    WINDOW_MIN_WIDTH = 1200
    WINDOW_MIN_HEIGHT = 800
    WINDOW_DEFAULT_WIDTH = 1400
    WINDOW_DEFAULT_HEIGHT = 900

    def __init__(self):
        super().__init__()
        self.setWindowTitle(self.WINDOW_TITLE)
        self.setMinimumSize(self.WINDOW_MIN_WIDTH, self.WINDOW_MIN_HEIGHT)
        self.resize(self.WINDOW_DEFAULT_WIDTH, self.WINDOW_DEFAULT_HEIGHT)

        # 初始化配置和日志
        self.config_mgr = ConfigManager()
        self.config = self.config_mgr.config

        setup_logging(
            log_level=20,  # INFO
            max_records=self.config.max_log_lines,
        )

        # 状态变量
        self._reference_path = ""
        self._target_paths: List[str] = []
        self._is_processing = False
        self._reference_paths: List[str] = []
        self._last_batch_report: Optional[BatchReport] = None

        # 工作线程
        self._process_worker: Optional[ProcessWorker] = None
        self._watch_worker: Optional[WatchWorker] = None

        # 初始化界面
        self._init_theme()
        self._setup_menu_bar()
        self._setup_toolbar()
        self._setup_central_widget()
        self._setup_status_bar()
        self._connect_signals()

        # 设置拖放
        self.setAcceptDrops(True)

        # 定时更新日志显示
        self._log_timer = QTimer(self)
        self._log_timer.timeout.connect(self._refresh_log_view)
        self._log_timer.start(2000)  # 每 2 秒刷新，降低 GUI 文本渲染压力

        # 恢复上次会话的目录
        self._restore_directories()

        logger.info("应用启动完成")

        self.statusBar().showMessage("就绪", 3000)

    # ===== 主题 =====
    def _init_theme(self):
        """初始化主题"""
        app = QApplication.instance()
        app.setStyle("Fusion")
        if self.config.theme == "dark":
            app.setPalette(get_dark_palette())
        app.setStyleSheet(get_theme_stylesheet(self.config.theme))

    # ===== 菜单栏 =====
    def _setup_menu_bar(self):
        """设置菜单栏"""
        menubar = self.menuBar()

        # 文件菜单
        file_menu = menubar.addMenu("文件(&F)")

        add_ref_action = QAction("添加参照视频...", self)
        add_ref_action.setShortcut(QKeySequence("Ctrl+R"))
        add_ref_action.triggered.connect(self._select_reference)
        file_menu.addAction(add_ref_action)

        add_target_action = QAction("添加目标视频...", self)
        add_target_action.setShortcut(QKeySequence("Ctrl+O"))
        add_target_action.triggered.connect(self._select_targets)
        file_menu.addAction(add_target_action)

        add_folder_action = QAction("添加目标文件夹...", self)
        add_folder_action.setShortcut(QKeySequence("Ctrl+D"))
        add_folder_action.triggered.connect(self._select_target_folder)
        file_menu.addAction(add_folder_action)

        file_menu.addSeparator()

        clear_action = QAction("清空列表", self)
        clear_action.triggered.connect(self._clear_all)
        file_menu.addAction(clear_action)

        file_menu.addSeparator()

        export_menu = file_menu.addMenu("导出报表")
        export_csv_action = QAction("导出 CSV...", self)
        export_csv_action.triggered.connect(lambda: self._export_report("csv"))
        export_menu.addAction(export_csv_action)

        export_json_action = QAction("导出 JSON...", self)
        export_json_action.triggered.connect(lambda: self._export_report("json"))
        export_menu.addAction(export_json_action)

        export_excel_action = QAction("导出 Excel...", self)
        export_excel_action.triggered.connect(lambda: self._export_report("excel"))
        export_menu.addAction(export_excel_action)

        export_html_action = QAction("导出 HTML...", self)
        export_html_action.triggered.connect(lambda: self._export_report("html"))
        export_menu.addAction(export_html_action)

        file_menu.addSeparator()

        exit_action = QAction("退出(&X)", self)
        exit_action.setShortcut(QKeySequence("Alt+F4"))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # 设置菜单
        settings_menu = menubar.addMenu("设置(&S)")

        theme_action = QAction("切换主题", self)
        theme_action.triggered.connect(self._toggle_theme)
        settings_menu.addAction(theme_action)

        settings_menu.addSeparator()

        open_output_action = QAction("打开输出目录...", self)
        open_output_action.triggered.connect(self._select_output_dir)
        settings_menu.addAction(open_output_action)

        # 帮助菜单
        help_menu = menubar.addMenu("帮助(&H)")

        about_action = QAction("关于...", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    # ===== 工具栏 =====
    def _setup_toolbar(self):
        """设置工具栏"""
        toolbar = QToolBar("主工具栏")
        toolbar.setObjectName("mainToolbar")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        # 参照视频
        btn_ref = QPushButton("📁 参照视频")
        btn_ref.setObjectName("secondaryBtn")
        btn_ref.clicked.connect(self._select_reference)
        toolbar.addWidget(btn_ref)

        # 目标视频
        btn_target = QPushButton("➕ 添加目标")
        btn_target.setObjectName("secondaryBtn")
        btn_target.clicked.connect(self._select_targets)
        toolbar.addWidget(btn_target)

        # 目标文件夹
        btn_folder = QPushButton("📂 添加文件夹")
        btn_folder.setObjectName("secondaryBtn")
        btn_folder.clicked.connect(self._select_target_folder)
        toolbar.addWidget(btn_folder)

        toolbar.addSeparator()

        # 开始处理
        self._btn_start = QPushButton("▶ 开始处理")
        self._btn_start.clicked.connect(self._start_processing)
        toolbar.addWidget(self._btn_start)

        # 停止
        self._btn_stop = QPushButton("⏹ 停止")
        self._btn_stop.setObjectName("dangerBtn")
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._stop_processing)
        toolbar.addWidget(self._btn_stop)

        toolbar.addSeparator()

        # 清空
        btn_clear = QPushButton("🗑 清空")
        btn_clear.setObjectName("secondaryBtn")
        btn_clear.clicked.connect(self._clear_all)
        toolbar.addWidget(btn_clear)

        # 导出
        self._btn_export = QPushButton("📊 导出报表")
        self._btn_export.setObjectName("secondaryBtn")
        self._btn_export.setEnabled(False)
        self._btn_export.clicked.connect(lambda: self._export_report("excel"))
        toolbar.addWidget(self._btn_export)

        # 右侧弹簧
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)

        # 版本标签
        version_label = QLabel("v1.0")
        version_label.setObjectName("subtitleLabel")
        toolbar.addWidget(version_label)

    # ===== 中央组件 =====
    def _setup_central_widget(self):
        """设置中央组件布局"""
        central = QWidget()
        self.setCentralWidget(central)

        # 主垂直布局
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 8, 12, 8)
        main_layout.setSpacing(8)

        # 顶部：文件列表 + 参数设置（水平分割）
        top_splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左侧：文件列表面板
        self._file_panel = self._create_file_panel()
        top_splitter.addWidget(self._file_panel)

        # 右侧：参数设置 + 结果预览
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        self._settings_panel = self._create_settings_panel()
        right_layout.addWidget(self._settings_panel)

        top_splitter.addWidget(right_panel)
        top_splitter.setStretchFactor(0, 3)
        top_splitter.setStretchFactor(1, 2)
        top_splitter.setCollapsible(0, False)
        top_splitter.setCollapsible(1, False)

        main_layout.addWidget(top_splitter, stretch=3)

        # 中部：进度条
        self._progress_bar = QProgressBar()
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setFormat("就绪")
        main_layout.addWidget(self._progress_bar)

        # 底部：标签页（结果 + 监控 + 日志）
        bottom_tabs = QTabWidget()

        # 结果表格
        self._result_table = self._create_result_table()
        bottom_tabs.addTab(self._result_table, "📋 检测结果")

        # 文件夹监控
        self._monitor_panel = self._create_monitor_panel()
        bottom_tabs.addTab(self._monitor_panel, "👁 文件夹监控")

        # 日志查看器
        self._log_viewer = self._create_log_viewer()
        bottom_tabs.addTab(self._log_viewer, "📝 运行日志")

        main_layout.addWidget(bottom_tabs, stretch=2)

    def _create_file_panel(self) -> QWidget:
        """创建文件列表面板"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # 标题
        title = QLabel("视频文件列表")
        title.setObjectName("titleLabel")
        layout.addWidget(title)

        # 参照视频显示
        ref_group = QGroupBox("素材库（参照视频）")
        ref_layout = QVBoxLayout(ref_group)
        self._ref_label = QLabel("未选择参照视频")
        self._ref_label.setWordWrap(True)
        self._ref_label.setStyleSheet("color: #0078d4; font-weight: 600; padding: 4px;")
        ref_layout.addWidget(self._ref_label)

        ref_btn_layout = QHBoxLayout()
        btn_add_ref = QPushButton("➕ 添加视频")
        btn_add_ref.setObjectName("secondaryBtn")
        btn_add_ref.clicked.connect(self._select_reference)
        btn_add_ref.setMaximumWidth(120)
        ref_btn_layout.addWidget(btn_add_ref)

        btn_add_ref_folder = QPushButton("📂 导入文件夹")
        btn_add_ref_folder.setObjectName("secondaryBtn")
        btn_add_ref_folder.clicked.connect(self._select_reference_folder)
        btn_add_ref_folder.setMaximumWidth(120)
        ref_btn_layout.addWidget(btn_add_ref_folder)

        btn_clear_ref = QPushButton("清空")
        btn_clear_ref.setObjectName("secondaryBtn")
        btn_clear_ref.clicked.connect(self._clear_references)
        btn_clear_ref.setMaximumWidth(80)
        ref_btn_layout.addWidget(btn_clear_ref)
        ref_btn_layout.addStretch()

        ref_layout.addLayout(ref_btn_layout)
        layout.addWidget(ref_group)

        # 目标视频列表
        target_group = QGroupBox("目标视频（待检测）")
        target_layout = QVBoxLayout(target_group)
        self._target_list = QListWidget()
        self._target_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._target_list.setAlternatingRowColors(True)
        target_layout.addWidget(self._target_list)

        # 列表操作按钮
        btn_layout = QHBoxLayout()
        btn_remove = QPushButton("移除选中")
        btn_remove.setObjectName("secondaryBtn")
        btn_remove.clicked.connect(self._remove_selected_targets)
        btn_remove.setMaximumWidth(100)
        btn_layout.addWidget(btn_remove)

        btn_clear = QPushButton("清空列表")
        btn_clear.setObjectName("secondaryBtn")
        btn_clear.clicked.connect(self._clear_targets)
        btn_clear.setMaximumWidth(100)
        btn_layout.addWidget(btn_clear)

        btn_layout.addStretch()
        self._target_count_label = QLabel("共 0 个文件")
        self._target_count_label.setObjectName("subtitleLabel")
        btn_layout.addWidget(self._target_count_label)

        target_layout.addLayout(btn_layout)
        layout.addWidget(target_group)

        return panel

    def _create_settings_panel(self) -> QWidget:
        """创建设置面板（包裹在滚动区域中，窗口过小时可滚动而非裁剪）"""
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # 标题
        title = QLabel("处理参数")
        title.setObjectName("titleLabel")
        layout.addWidget(title)

        # 哈希参数
        hash_group = QGroupBox("哈希比对参数")
        hash_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        hash_layout = QGridLayout(hash_group)
        hash_layout.setSpacing(8)

        hash_layout.addWidget(QLabel("采样间隔(秒):"), 0, 0)
        self._sample_interval_spin = QDoubleSpinBox()
        self._sample_interval_spin.setRange(0.5, 10.0)
        self._sample_interval_spin.setSingleStep(0.5)
        self._sample_interval_spin.setValue(self.config.sample_interval)
        self._sample_interval_spin.setToolTip("每隔多少秒采样一帧。1.0s 推荐；值越小越精确但越慢。")
        hash_layout.addWidget(self._sample_interval_spin, 0, 1)

        hash_layout.addWidget(QLabel("相似度阈值:"), 1, 0)
        self._threshold_spin = QSpinBox()
        self._threshold_spin.setRange(0, 64)
        self._threshold_spin.setValue(self.config.hash_threshold)
        self._threshold_spin.setToolTip("汉明距离阈值(0-64)。值越小匹配越严格，10=推荐值。")
        hash_layout.addWidget(self._threshold_spin, 1, 1)

        hash_layout.addWidget(QLabel("匹配比例(%):"), 2, 0)
        self._match_ratio_spin = QSpinBox()
        self._match_ratio_spin.setRange(5, 100)
        self._match_ratio_spin.setValue(int(self.config.min_match_ratio * 100))
        self._match_ratio_spin.setSuffix(" %")
        self._match_ratio_spin.setToolTip(
            "匹配片段需 >= 素材时长 * 此比例才处理。\n"
            "例如素材60秒，比例10%=匹配需>=6秒。值越大越严格。"
        )
        hash_layout.addWidget(self._match_ratio_spin, 2, 1)

        hash_layout.addWidget(QLabel("最短片段(秒):"), 3, 0)
        self._min_duration_spin = QDoubleSpinBox()
        self._min_duration_spin.setRange(0.3, 60.0)
        self._min_duration_spin.setSingleStep(0.5)
        self._min_duration_spin.setValue(self.config.min_match_duration)
        self._min_duration_spin.setToolTip("低于此时长的匹配片段将被忽略。")
        hash_layout.addWidget(self._min_duration_spin, 3, 1)

        hash_layout.addWidget(QLabel("哈希算法:"), 4, 0)
        self._algorithm_combo = QComboBox()
        self._algorithm_combo.addItems(["dHash (差异哈希)", "pHash (感知哈希)", "aHash (均值哈希)", "综合比较"])
        self._algorithm_combo.setCurrentIndex(0)
        hash_layout.addWidget(self._algorithm_combo, 4, 1)

        layout.addWidget(hash_group)

        # 处理选项（网格布局，紧凑排版）
        proc_group = QGroupBox("处理选项")
        proc_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        proc_layout = QGridLayout(proc_group)
        proc_layout.setHorizontalSpacing(12)
        proc_layout.setVerticalSpacing(8)

        self._auto_cut_check = QCheckBox("自动裁切重复片段")
        self._auto_cut_check.setChecked(self.config.auto_cut)
        self._auto_cut_check.setToolTip("检测到重复后自动进行视频裁切。")
        proc_layout.addWidget(self._auto_cut_check, 0, 0)

        self._keep_dup_check = QCheckBox("保留重复片段（不勾选则删除重复）")
        self._keep_dup_check.setChecked(self.config.keep_duplicates)
        proc_layout.addWidget(self._keep_dup_check, 0, 1)

        self._overwrite_check = QCheckBox("裁切后覆盖原视频（直接替换，不留备份）")
        self._overwrite_check.setChecked(True)
        self._overwrite_check.setToolTip("勾选：裁切后直接替换原文件。\n不勾选：生成 *_dedup.mp4 新文件。")
        self._overwrite_check.setStyleSheet("color: #f0c040; font-weight: 600;")
        proc_layout.addWidget(self._overwrite_check, 1, 0, 1, 2)

        # FFmpeg 状态
        from .cutter import _check_ffmpeg
        ffmpeg_ok = _check_ffmpeg()
        ffmpeg_label = QLabel("🟢 FFmpeg 可用" if ffmpeg_ok else "🔴 FFmpeg 未安装！裁切功能不可用")
        ffmpeg_label.setObjectName("statusError" if not ffmpeg_ok else "statusGood")
        proc_layout.addWidget(ffmpeg_label, 2, 0, 1, 2)

        # GPU 加速
        self._gpu_check = QCheckBox("启用 GPU 加速")
        self._gpu_check.setChecked(self.config.use_gpu)
        self._gpu_check.setToolTip("使用 NVIDIA GPU 加速帧处理和视频编码。")
        proc_layout.addWidget(self._gpu_check, 3, 0)

        from .gpu_utils import get_gpu_info
        gpu_info = get_gpu_info()
        gpu_status = "🟢 GPU 可用" if gpu_info.available else "⚪ 未检测到 GPU"
        if gpu_info.available:
            gpu_status = f"🟢 {gpu_info.name} ({gpu_info.memory_mb // 1024}GB)"
        gpu_label = QLabel(gpu_status)
        gpu_label.setObjectName("subtitleLabel")
        proc_layout.addWidget(gpu_label, 3, 1, Qt.AlignmentFlag.AlignLeft)

        # 并发线程数（下拉选择）
        proc_layout.addWidget(QLabel("并发线程数:"), 4, 0)
        self._worker_combo = QComboBox()
        self._worker_combo.addItems(["1", "2", "4", "6", "8", "12", "16"])
        worker_default = str(self.config.max_workers)
        worker_items = [self._worker_combo.itemText(i) for i in range(self._worker_combo.count())]
        self._worker_combo.setCurrentText(worker_default if worker_default in worker_items else "4")
        self._worker_combo.setToolTip("并行处理的文件数量。RTX 5060 Ti 建议 4-8。")
        proc_layout.addWidget(self._worker_combo, 4, 1)

        # 素材位置选项
        proc_layout.addWidget(QLabel("素材位置:"), 5, 0)
        self._material_position_combo = QComboBox()
        self._material_position_combo.addItems([
            "任意位置 (Anywhere)",
            "视频开头 (Beginning)",
            "视频结尾 (End)",
            "开头和结尾 (Both)"
        ])
        idx_map = {"anywhere": 0, "beginning": 1, "end": 2, "both": 3}
        self._material_position_combo.setCurrentIndex(
            idx_map.get(self.config.material_position, 0)
        )
        self._material_position_combo.setToolTip(
            "素材在目标视频中的位置。\n"
            "指定位置可大幅减少搜索范围，提升处理速度。\n"
            "任意位置: 搜索整个视频（最慢但最安全）\n"
            "视频开头/结尾: 仅搜索对应区域（快 50-80%）\n"
            "开头和结尾: 同时搜索首尾区域（适合片头片尾素材）"
        )
        proc_layout.addWidget(self._material_position_combo, 5, 1)

        # 搜索余量
        proc_layout.addWidget(QLabel("搜索余量:"), 6, 0)
        self._position_margin_spin = QDoubleSpinBox()
        self._position_margin_spin.setRange(0.05, 0.50)
        self._position_margin_spin.setSingleStep(0.05)
        self._position_margin_spin.setValue(self.config.position_search_margin)
        self._position_margin_spin.setDecimals(2)
        self._position_margin_spin.setSuffix(" (x)")
        self._position_margin_spin.setToolTip(
            "在素材估算时长基础上额外搜索的缓冲比例。\n"
            "例如 0.15 表示素材 60 秒 → 搜索 69 秒范围。\n"
            "值越大越安全，但速度提升越小。建议 0.10-0.20。"
        )
        proc_layout.addWidget(self._position_margin_spin, 6, 1)

        # 首尾时间限定（可选项）
        self._limit_head_tail_check = QCheckBox("限定识别和裁剪到首尾指定时间")
        self._limit_head_tail_check.setChecked(self.config.limit_head_tail)
        self._limit_head_tail_check.setToolTip(
            "勾选后，仅在视频开头和结尾的指定时间内进行识别和裁剪，"
            "中间区域跳过以提升速度。\n"
            "若视频时长小于指定时间，则不跳过，全量识别。\n"
            "开启后覆盖上方「素材位置 / 搜索余量」的范围计算。"
        )
        proc_layout.addWidget(self._limit_head_tail_check, 7, 0)

        self._head_tail_time_spin = QDoubleSpinBox()
        self._head_tail_time_spin.setRange(1.0, 3600.0)
        self._head_tail_time_spin.setSingleStep(5.0)
        self._head_tail_time_spin.setValue(self.config.head_tail_time)
        self._head_tail_time_spin.setDecimals(1)
        self._head_tail_time_spin.setSuffix(" 秒")
        self._head_tail_time_spin.setToolTip(
            "开头和结尾各自操作的时间长度（秒）。\n"
            "例如 60 秒表示开头 [0-60s] 和结尾 [时长-60s ~ 时长] 内识别和裁剪。"
        )
        proc_layout.addWidget(self._head_tail_time_spin, 7, 1)

        # 帧过滤（可选项）
        self._enable_frame_filter_check = QCheckBox("过滤过暗/过亮帧")
        self._enable_frame_filter_check.setChecked(self.config.enable_frame_filter)
        self._enable_frame_filter_check.setToolTip(
            "勾选后丢弃过暗/过亮的帧（黑屏、过曝、纯色画面），减少噪声哈希。\n"
            "丢弃帧会形成采样空隙，连续片段可能被分割，由合并间隔兜底。"
        )
        proc_layout.addWidget(self._enable_frame_filter_check, 8, 0)

        frame_filter_layout = QHBoxLayout()
        frame_filter_layout.setSpacing(6)
        self._frame_dark_spin = QDoubleSpinBox()
        self._frame_dark_spin.setRange(0.0, 128.0)
        self._frame_dark_spin.setValue(self.config.frame_dark_threshold)
        self._frame_dark_spin.setDecimals(1)
        self._frame_dark_spin.setToolTip("灰度均值低于此值的帧被丢弃（暗阈值）。")
        frame_filter_layout.addWidget(QLabel("暗:"))
        frame_filter_layout.addWidget(self._frame_dark_spin)
        self._frame_bright_spin = QDoubleSpinBox()
        self._frame_bright_spin.setRange(128.0, 255.0)
        self._frame_bright_spin.setValue(self.config.frame_bright_threshold)
        self._frame_bright_spin.setDecimals(1)
        self._frame_bright_spin.setToolTip("灰度均值高于此值的帧被丢弃（亮阈值）。")
        frame_filter_layout.addWidget(QLabel("亮:"))
        frame_filter_layout.addWidget(self._frame_bright_spin)
        frame_filter_layout.addStretch()
        proc_layout.addLayout(frame_filter_layout, 8, 1)

        # 整文件粗筛（可选项）
        self._enable_coarse_filter_check = QCheckBox("整文件粗筛（加速无关视频）")
        self._enable_coarse_filter_check.setChecked(self.config.enable_coarse_filter)
        self._enable_coarse_filter_check.setToolTip(
            "勾选后先用稀疏采样快速判断目标是否可能包含素材，\n"
            "不命中则跳过逐帧精筛。对「多数目标不含素材」的场景提速明显。\n"
            "注意：短于粗筛间隔的素材可能被漏检，默认关闭。"
        )
        proc_layout.addWidget(self._enable_coarse_filter_check, 9, 0)

        self._coarse_interval_spin = QDoubleSpinBox()
        self._coarse_interval_spin.setRange(1.0, 60.0)
        self._coarse_interval_spin.setSingleStep(1.0)
        self._coarse_interval_spin.setValue(self.config.coarse_interval)
        self._coarse_interval_spin.setDecimals(1)
        self._coarse_interval_spin.setSuffix(" 秒")
        self._coarse_interval_spin.setToolTip("粗筛采样间隔（秒），越大约快但漏检风险越高。")
        proc_layout.addWidget(self._coarse_interval_spin, 9, 1)

        # 磁盘哈希缓存（可选项）
        self._use_hash_cache_check = QCheckBox("启用磁盘哈希缓存（二次处理直接读缓存）")
        self._use_hash_cache_check.setChecked(self.config.use_hash_cache)
        self._use_hash_cache_check.setToolTip(
            "把视频帧哈希缓存到本地磁盘，二次处理同一视频时直接读缓存、跳过解码，\n"
            "大幅缩短重复处理时间。缓存按文件修改时间/大小自动失效。"
        )
        proc_layout.addWidget(self._use_hash_cache_check, 10, 0, 1, 2)

        proc_layout.setColumnStretch(1, 1)

        layout.addWidget(proc_group)

        # 输出目录
        out_group = QGroupBox("输出设置")
        out_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        out_layout = QHBoxLayout(out_group)
        self._output_dir_edit = QLineEdit(self.config.output_dir)
        self._output_dir_edit.setPlaceholderText("选择输出目录...")
        self._output_dir_edit.setReadOnly(True)
        out_layout.addWidget(self._output_dir_edit)

        btn_out = QPushButton("浏览...")
        btn_out.setObjectName("secondaryBtn")
        btn_out.clicked.connect(self._select_output_dir)
        btn_out.setMaximumWidth(80)
        out_layout.addWidget(btn_out)

        layout.addWidget(out_group)

        # 弹性空间
        layout.addStretch()

        # 保存设置按钮
        btn_save = QPushButton("💾 保存设置")
        btn_save.clicked.connect(self._save_settings)
        layout.addWidget(btn_save)

        # 清空磁盘哈希缓存
        btn_clear_cache = QPushButton("🧹 清空哈希缓存")
        btn_clear_cache.setObjectName("secondaryBtn")
        btn_clear_cache.clicked.connect(self._clear_hash_cache)
        layout.addWidget(btn_clear_cache)

        # 包裹在滚动区域中，窗口变小时可滚动查看完整参数
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        return scroll

    def _create_result_table(self) -> QWidget:
        """创建结果表格"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # 表头操作栏
        header_layout = QHBoxLayout()
        self._result_summary = QLabel("待处理...")
        self._result_summary.setObjectName("subtitleLabel")
        header_layout.addWidget(self._result_summary)
        header_layout.addStretch()

        btn_clear_results = QPushButton("清空结果")
        btn_clear_results.setObjectName("secondaryBtn")
        btn_clear_results.clicked.connect(self._clear_results)
        btn_clear_results.setMaximumWidth(100)
        header_layout.addWidget(btn_clear_results)

        layout.addLayout(header_layout)

        # 表格
        self._table = QTableWidget()
        self._table.setColumnCount(9)
        self._table.setHorizontalHeaderLabels([
            "文件名", "状态", "时长", "片段数", "匹配素材",
            "重复时长", "重复占比", "处理耗时", "详情"
        ])
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        # 列宽自适应：文件名列随窗口拉伸，其余列可交互调整
        header = self._table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.setColumnWidth(0, 220)
        self._table.setColumnWidth(1, 70)
        self._table.setColumnWidth(2, 70)
        self._table.setColumnWidth(3, 60)
        self._table.setColumnWidth(4, 180)   # 匹配素材
        self._table.setColumnWidth(5, 80)
        self._table.setColumnWidth(6, 80)
        self._table.setColumnWidth(7, 80)
        self._table.setColumnWidth(8, 90)    # 详情
        self._table.doubleClicked.connect(self._show_segment_details)

        layout.addWidget(self._table)
        return panel

    def _create_log_viewer(self) -> QWidget:
        """创建日志查看器"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # 控制栏
        ctrl_layout = QHBoxLayout()
        self._log_filter_combo = QComboBox()
        self._log_filter_combo.addItems(["全部", "INFO", "WARNING", "ERROR", "DEBUG"])
        self._log_filter_combo.currentTextChanged.connect(self._refresh_log_view)
        ctrl_layout.addWidget(QLabel("级别过滤:"))
        ctrl_layout.addWidget(self._log_filter_combo)
        ctrl_layout.addStretch()

        btn_clear_log = QPushButton("清空日志")
        btn_clear_log.setObjectName("secondaryBtn")
        btn_clear_log.clicked.connect(self._clear_log)
        btn_clear_log.setMaximumWidth(100)
        ctrl_layout.addWidget(btn_clear_log)

        layout.addLayout(ctrl_layout)

        # 日志文本框
        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self._log_text)

        return panel

    def _create_monitor_panel(self) -> QWidget:
        """创建文件夹监控面板"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        ctrl_layout = QHBoxLayout()
        self._monitor_dir_edit = QLineEdit()
        self._monitor_dir_edit.setPlaceholderText("选择要监控的文件夹...")
        self._monitor_dir_edit.setReadOnly(True)
        ctrl_layout.addWidget(self._monitor_dir_edit)

        btn_add_monitor = QPushButton("添加目录")
        btn_add_monitor.setObjectName("secondaryBtn")
        btn_add_monitor.clicked.connect(self._add_monitor_dir)
        btn_add_monitor.setMaximumWidth(100)
        ctrl_layout.addWidget(btn_add_monitor)

        self._btn_start_monitor = QPushButton("▶ 开始监控")
        self._btn_start_monitor.setObjectName("successBtn")
        self._btn_start_monitor.clicked.connect(self._toggle_monitoring)
        self._btn_start_monitor.setMaximumWidth(120)
        ctrl_layout.addWidget(self._btn_start_monitor)
        layout.addLayout(ctrl_layout)

        self._monitor_dir_list = QListWidget()
        layout.addWidget(self._monitor_dir_list)

        monitor_log_label = QLabel("监控日志:")
        monitor_log_label.setObjectName("subtitleLabel")
        layout.addWidget(monitor_log_label)

        self._monitor_log = QTextEdit()
        self._monitor_log.setReadOnly(True)
        self._monitor_log.setMaximumHeight(150)
        self._monitor_log.setPlaceholderText("监控事件将在此显示...")
        layout.addWidget(self._monitor_log)
        return panel

    def _add_monitor_dir(self):
        """添加监控目录"""
        folder = QFileDialog.getExistingDirectory(
            self, "选择要监控的文件夹", os.path.expanduser("~")
        )
        if folder:
            if not hasattr(self, '_monitor_dirs'):
                self._monitor_dirs = []
            if folder not in self._monitor_dirs:
                self._monitor_dirs.append(folder)
                self._monitor_dir_list.addItem(f"📁 {folder}")
                self.config_mgr.set("watch_dirs", self._monitor_dirs)
                self._append_monitor_log(f"添加监控目录: {folder}")

    def _toggle_monitoring(self):
        """开始/停止文件夹监控"""
        if not hasattr(self, '_monitor_dirs') or not self._monitor_dirs:
            QMessageBox.warning(self, "提示", "请先添加要监控的文件夹！")
            return
        if self._watch_worker and self._watch_worker.isRunning():
            self._watch_worker.stop()
            self._watch_worker.wait(3000)
            self._watch_worker = None
            self._btn_start_monitor.setText("▶ 开始监控")
            self._btn_start_monitor.setObjectName("successBtn")
            self._append_monitor_log("监控已停止")
            self.statusBar().showMessage("监控已停止", 2000)
        else:
            self._watch_worker = WatchWorker()
            self._watch_worker.setup(
                watch_dirs=self._monitor_dirs,
                interval=self.config.watch_interval,
                recursive=self.config.watch_recursive,
            )
            self._watch_worker.new_file.connect(self._on_monitor_new_file)
            self._watch_worker.log.connect(lambda msg: self._append_monitor_log(msg))
            self._watch_worker.error.connect(lambda msg: self._append_monitor_log(f"[错误] {msg}"))
            self._watch_worker.start()
            self._btn_start_monitor.setText("⏹ 停止监控")
            self._btn_start_monitor.setObjectName("dangerBtn")
            self._append_monitor_log(f"开始监控 {len(self._monitor_dirs)} 个目录...")
            self.statusBar().showMessage("文件夹监控已启动", 2000)

    def _on_monitor_new_file(self, filepath: str):
        """监控发现新文件"""
        self._append_monitor_log(f"发现新视频: {os.path.basename(filepath)}")
        if not self._is_processing and self._reference_paths:
            if filepath not in self._target_paths:
                self._target_paths.append(filepath)
                item = QListWidgetItem(f"🎬 {os.path.basename(filepath)}")
                item.setToolTip(filepath)
                self._target_list.addItem(item)
                self._update_target_count()
                self._append_monitor_log(f"已自动添加: {os.path.basename(filepath)}")

    def _append_monitor_log(self, message: str):
        """追加监控日志"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._monitor_log.append(f"[{timestamp}] {message}")
        if self._monitor_log.document().blockCount() > 500:
            self._monitor_log.clear()

    # ===== 状态栏 =====
    def _setup_status_bar(self):
        """设置状态栏"""
        self._status_label = QLabel("就绪")
        self._status_label.setObjectName("subtitleLabel")
        self.statusBar().addWidget(self._status_label, stretch=1)

        self._status_count = QLabel("")
        self.statusBar().addPermanentWidget(self._status_count)

    # ===== 信号连接 =====
    def _connect_signals(self):
        """连接信号"""
        # 配置参数变更时自动保存
        self._sample_interval_spin.valueChanged.connect(
            lambda v: self.config_mgr.set("sample_interval", v))
        self._threshold_spin.valueChanged.connect(
            lambda v: self.config_mgr.set("hash_threshold", v))
        self._min_duration_spin.valueChanged.connect(
            lambda v: self.config_mgr.set("min_match_duration", v))
        self._match_ratio_spin.valueChanged.connect(
            lambda v: self.config_mgr.set("min_match_ratio", v / 100.0))
        self._auto_cut_check.toggled.connect(
            lambda v: self.config_mgr.set("auto_cut", v))
        self._material_position_combo.currentIndexChanged.connect(
            lambda idx: self.config_mgr.set("material_position",
                ["anywhere", "beginning", "end", "both"][idx]))
        self._position_margin_spin.valueChanged.connect(
            lambda v: self.config_mgr.set("position_search_margin", v))
        self._limit_head_tail_check.toggled.connect(
            lambda v: self.config_mgr.set("limit_head_tail", v))
        self._head_tail_time_spin.valueChanged.connect(
            lambda v: self.config_mgr.set("head_tail_time", v))
        self._enable_frame_filter_check.toggled.connect(
            lambda v: self.config_mgr.set("enable_frame_filter", v))
        self._frame_dark_spin.valueChanged.connect(
            lambda v: self.config_mgr.set("frame_dark_threshold", v))
        self._frame_bright_spin.valueChanged.connect(
            lambda v: self.config_mgr.set("frame_bright_threshold", v))
        self._enable_coarse_filter_check.toggled.connect(
            lambda v: self.config_mgr.set("enable_coarse_filter", v))
        self._coarse_interval_spin.valueChanged.connect(
            lambda v: self.config_mgr.set("coarse_interval", v))
        self._use_hash_cache_check.toggled.connect(
            lambda v: self.config_mgr.set("use_hash_cache", v))
        self._worker_combo.currentTextChanged.connect(
            lambda v: self.config_mgr.set("max_workers", int(v) if v.isdigit() else 4))

    # ===== 文件操作 =====
    def _select_reference(self):
        """选择参照视频（支持多选）"""
        filepaths, _ = QFileDialog.getOpenFileNames(
            self, "选择参照视频（可多选）",
            self.config.reference_dir or os.path.expanduser("~"),
            "视频文件 (*.mp4 *.avi *.mov *.mkv *.wmv *.flv *.webm *.m4v *.ts);;所有文件 (*.*)"
        )
        if filepaths:
            for fp in filepaths:
                if fp not in self._reference_paths:
                    self._reference_paths.append(fp)
            self.config_mgr.set("reference_dir", os.path.dirname(filepaths[0]))
            self._update_ref_label()
            names = ", ".join(os.path.basename(fp) for fp in filepaths)
            self.statusBar().showMessage(f"参照视频: {names}", 3000)
            logger.info(f"选择 {len(filepaths)} 个参照视频")

    def _select_reference_folder(self):
        """批量导入文件夹到素材库"""
        folder = QFileDialog.getExistingDirectory(
            self, "选择素材文件夹",
            self.config.reference_dir or os.path.expanduser("~")
        )
        if not folder:
            return

        added = 0
        for root, dirs, files in os.walk(folder):
            for f in files:
                fp = os.path.join(root, f)
                if is_video_file(fp) and fp not in self._reference_paths:
                    self._reference_paths.append(fp)
                    added += 1

        if added > 0:
            self.config_mgr.set("reference_dir", folder)
            self._update_ref_label()
            self.statusBar().showMessage(f"素材库批量导入 {added} 个视频", 3000)
            logger.info(f"素材库批量导入 {added} 个视频 from {folder}")
        else:
            QMessageBox.information(self, "提示", "未在所选文件夹中找到新的视频文件。")

    def _clear_references(self):
        """清空素材库"""
        self._reference_paths.clear()
        self._ref_label.setText("未选择参照视频")
        self.statusBar().showMessage("素材库已清空", 2000)

    def _select_targets(self):
        """选择目标视频"""
        filepaths, _ = QFileDialog.getOpenFileNames(
            self, "选择目标视频",
            self.config.target_dir or os.path.expanduser("~"),
            "视频文件 (*.mp4 *.avi *.mov *.mkv *.wmv *.flv *.webm *.m4v *.ts);;所有文件 (*.*)"
        )
        added = 0
        for fp in filepaths:
            if fp and fp not in self._target_paths and fp not in self._reference_paths:
                self._target_paths.append(fp)
                item = QListWidgetItem(f"🎬 {os.path.basename(fp)}")
                item.setToolTip(fp)
                self._target_list.addItem(item)
                added += 1

        if added > 0:
            self.config_mgr.set("target_dir", os.path.dirname(filepaths[0]))
            self._update_target_count()
            self.statusBar().showMessage(f"添加 {added} 个目标视频", 3000)
            logger.info(f"添加 {added} 个目标视频")

    def _select_target_folder(self):
        """选择包含目标视频的文件夹"""
        folder = QFileDialog.getExistingDirectory(
            self, "选择目标文件夹",
            self.config.target_dir or os.path.expanduser("~")
        )
        if folder:
            added = 0
            for root, dirs, files in os.walk(folder):
                for f in files:
                    fp = os.path.join(root, f)
                    if is_video_file(fp) and fp not in self._target_paths and fp not in self._reference_paths:
                        self._target_paths.append(fp)
                        item = QListWidgetItem(f"🎬 {os.path.basename(fp)}")
                        item.setToolTip(fp)
                        self._target_list.addItem(item)
                        added += 1

            if added > 0:
                self.config_mgr.set("target_dir", folder)
                self._update_target_count()
                self.statusBar().showMessage(f"从文件夹添加 {added} 个视频", 3000)
                logger.info(f"从文件夹 {folder} 添加 {added} 个视频")
            else:
                QMessageBox.information(self, "提示", "未在所选文件夹中找到视频文件。")

    def _remove_selected_targets(self):
        """移除选中的目标视频"""
        selected = self._target_list.selectedItems()
        if not selected:
            return

        for item in selected:
            fp = item.toolTip()
            if fp in self._target_paths:
                self._target_paths.remove(fp)
            row = self._target_list.row(item)
            self._target_list.takeItem(row)

        self._update_target_count()
        logger.info(f"移除 {len(selected)} 个目标视频")

    def _clear_targets(self):
        """清空目标视频列表"""
        self._target_paths.clear()
        self._target_list.clear()
        self._update_target_count()

    def _clear_all(self):
        """清空所有列表"""
        self._reference_paths.clear()
        self._ref_label.setText("未选择参照视频")
        self._clear_targets()
        self._clear_results()
        self.statusBar().showMessage("已清空", 2000)

    def _update_target_count(self):
        """更新目标文件计数"""
        count = len(self._target_paths)
        self._target_count_label.setText(f"共 {count} 个文件")

    def _select_output_dir(self):
        """选择输出目录"""
        folder = QFileDialog.getExistingDirectory(
            self, "选择输出目录",
            self.config.output_dir or os.path.expanduser("~")
        )
        if folder:
            self._output_dir_edit.setText(folder)
            self.config_mgr.set("output_dir", folder)

    def _restore_directories(self):
        """恢复上次的目录设置"""
        if self.config.reference_dir:
            pass  # 仅用于文件对话框的默认路径
        if self.config.output_dir:
            self._output_dir_edit.setText(self.config.output_dir)

    # ===== 拖放支持 =====
    def dragEnterEvent(self, event: QDragEnterEvent):
        """拖入事件"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent):
        """放下事件"""
        urls = event.mimeData().urls()
        video_paths = []
        for url in urls:
            fp = url.toLocalFile()
            if os.path.isfile(fp) and is_video_file(fp):
                video_paths.append(fp)

        if not video_paths:
            return

        # 如果还没有参照视频，拖入的作为参照
        if not self._reference_paths:
            ref_path = video_paths[0]
            self._reference_paths.append(ref_path)
            self._update_ref_label()
            video_paths = video_paths[1:]
            logger.info(f"拖放添加参照视频: {ref_path}")

        # 其余作为目标
        added = 0
        for fp in video_paths:
            if fp not in self._target_paths and fp not in self._reference_paths:
                self._target_paths.append(fp)
                item = QListWidgetItem(f"🎬 {os.path.basename(fp)}")
                item.setToolTip(fp)
                self._target_list.addItem(item)
                added += 1

        if added > 0:
            self._update_target_count()
            logger.info(f"拖放添加 {added} 个目标视频")

    # ===== 处理控制 =====
    def _update_ref_label(self):
        """更新参照视频标签显示"""
        count = len(self._reference_paths)
        if count == 0:
            self._ref_label.setText("未选择参照视频")
        elif count == 1:
            self._ref_label.setText(f"📹 {os.path.basename(self._reference_paths[0])}")
            self._ref_label.setToolTip(self._reference_paths[0])
        else:
            names = ", ".join(os.path.basename(p) for p in self._reference_paths[:3])
            if count > 3:
                names += f" ...等{count}个"
            self._ref_label.setText(f"📹 素材库({count}个): {names}")
            self._ref_label.setToolTip("\n".join(self._reference_paths))

    def _get_hash_algorithm_key(self) -> str:
        """获取哈希算法 key"""
        idx = self._algorithm_combo.currentIndex()
        return ["dhash", "phash", "ahash", "combined"][idx]

    def _get_worker_count(self) -> int:
        """获取当前选择的并发线程数"""
        if hasattr(self, '_worker_combo'):
            try:
                return int(self._worker_combo.currentText())
            except ValueError:
                pass
        return self.config.max_workers

    def _start_processing(self):
        """开始处理"""
        # 验证
        if not self._reference_paths:
            QMessageBox.warning(self, "提示", "请先选择至少一个参照视频！")
            return

        if not self._target_paths:
            QMessageBox.warning(self, "提示", "请先添加至少一个目标视频！")
            return

        if self._is_processing:
            QMessageBox.warning(self, "提示", "正在处理中，请等待完成或先停止。")
            return

        # 创建处理器
        output_dir = self._output_dir_edit.text() or os.path.dirname(self._reference_paths[0])
        material_position = ["anywhere", "beginning", "end", "both"][
            self._material_position_combo.currentIndex()]
        processor = VideoProcessor(
            sample_interval=self._sample_interval_spin.value(),
            hash_threshold=self._threshold_spin.value(),
            min_match_ratio=self._match_ratio_spin.value() / 100.0 if hasattr(self, '_match_ratio_spin') else 0.10,
            min_match_duration=self._min_duration_spin.value(),
            hash_algorithm=self._get_hash_algorithm_key(),
            auto_cut=self._auto_cut_check.isChecked(),
            output_dir=output_dir,
            max_workers=self._get_worker_count(),
            use_gpu=self._gpu_check.isChecked() if hasattr(self, '_gpu_check') else True,
            material_position=material_position,
            position_search_margin=self._position_margin_spin.value(),
            limit_head_tail=self._limit_head_tail_check.isChecked(),
            head_tail_time=self._head_tail_time_spin.value(),
            enable_frame_filter=self._enable_frame_filter_check.isChecked(),
            frame_dark_threshold=self._frame_dark_spin.value(),
            frame_bright_threshold=self._frame_bright_spin.value(),
            enable_coarse_filter=self._enable_coarse_filter_check.isChecked(),
            coarse_interval=self._coarse_interval_spin.value(),
            use_hash_cache=self._use_hash_cache_check.isChecked() if hasattr(self, '_use_hash_cache_check') else True,
        )

        # 创建工作线程
        self._process_worker = ProcessWorker()
        self._process_worker.setup(
            list(self._reference_paths),
            list(self._target_paths),
            processor,
            auto_cut=self._auto_cut_check.isChecked(),
            overwrite_original=self._overwrite_check.isChecked() if hasattr(self, '_overwrite_check') else False,
        )
        self._process_worker.progress.connect(self._on_process_progress)
        self._process_worker.file_progress.connect(self._on_file_progress)
        self._process_worker.file_done.connect(self._on_file_done)
        self._process_worker.batch_done.connect(self._on_batch_done)
        self._process_worker.error.connect(self._on_process_error)
        self._process_worker.log.connect(self._on_worker_log)

        # 更新 UI 状态
        self._is_processing = True
        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._btn_export.setEnabled(False)
        self._clear_results()
        self._progress_bar.setValue(0)
        self._progress_bar.setFormat("处理中...")

        self._process_worker.start()
        logger.info(f"开始处理 {len(self._target_paths)} 个文件")

    def _stop_processing(self):
        """停止处理"""
        if self._process_worker and self._process_worker.isRunning():
            reply = QMessageBox.question(
                self, "确认", "确定要停止当前处理吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._process_worker.cancel()
                self.statusBar().showMessage("正在停止...", 2000)

    def _on_process_progress(self, stage: str, percent: int, message: str):
        """处理进度更新"""
        self._progress_bar.setValue(percent)
        self._progress_bar.setFormat(f"{message} ({percent}%)")
        self._status_label.setText(message)

    def _on_file_progress(self, current: int, total: int, filename: str):
        """文件进度更新"""
        self.statusBar().showMessage(f"处理中: [{current}/{total}] {filename}")

    def _on_file_done(self, report: ProcessReport):
        """单个文件处理完成"""
        self._add_result_row(report)

    def _on_batch_done(self, batch_report: BatchReport):
        """批量处理完成"""
        self._is_processing = False
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._btn_export.setEnabled(True)
        self._last_batch_report = batch_report

        self._progress_bar.setValue(100)
        duration_str = f"{batch_report.total_processing_time:.1f}s"

        summary = (
            f"处理完成: {batch_report.processed_files}/{batch_report.total_files} 个文件, "
            f"发现匹配 {batch_report.files_with_matches} 个, "
            f"总共 {batch_report.total_segments} 段重复, "
            f"耗时 {duration_str}"
        )
        self._progress_bar.setFormat(summary[:120])
        self._result_summary.setText(summary)
        self._status_label.setText("处理完成")
        self.statusBar().showMessage(f"处理完成，耗时 {duration_str}", 5000)
        logger.info(summary)

    def _on_process_error(self, error_msg: str):
        """处理错误"""
        self._is_processing = False
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._progress_bar.setFormat(f"错误: {error_msg[:80]}")
        self._status_label.setText("处理出错")
        QMessageBox.critical(self, "处理错误", f"处理过程中发生错误:\n\n{error_msg}")
        logger.error(f"处理错误: {error_msg}")

    def _on_worker_log(self, level: str, message: str):
        """工作线程日志"""
        log_func = {
            "DEBUG": logger.debug,
            "INFO": logger.info,
            "WARNING": logger.warning,
            "ERROR": logger.error,
        }.get(level, logger.info)
        log_func(f"[Worker] {message}")

    # ===== 结果显示 =====
    def _add_result_row(self, report: ProcessReport):
        """添加结果行到表格"""
        from PyQt6.QtGui import QColor
        row = self._table.rowCount()
        self._table.insertRow(row)

        # 文件名（存储完整路径用于打开）
        name_item = QTableWidgetItem(report.video_name)
        name_item.setToolTip(report.video_path)
        name_item.setData(Qt.ItemDataRole.UserRole, report.video_path)
        self._table.setItem(row, 0, name_item)

        # 状态
        status_map = {
            "completed": ("✅ 完成", QColor("#6bdb6b")),
            "no_match": ("🔍 无匹配", QColor("#f0c040")),
            "error": ("❌ 错误", QColor("#f04040")),
            "skipped": ("⏭ 跳过", QColor("#888888")),
        }
        status_text, status_color = status_map.get(report.status, (report.status, QColor("#e8e8e8")))
        status_item = QTableWidgetItem(status_text)
        status_item.setForeground(status_color)
        self._table.setItem(row, 1, status_item)

        # 数据列
        dur_pct = (report.total_match_duration / report.video_duration * 100) if report.video_duration > 0 else 0
        data = [
            f"{report.video_duration:.1f}s",       # col 2 时长
            str(report.segments_found),            # col 3 片段数
            "",                                    # col 4 匹配素材（下方单独设置）
            f"{report.total_match_duration:.1f}s", # col 5 重复时长
            f"{dur_pct:.1f}%",                      # col 6 重复占比
            f"{report.processing_time:.1f}s",      # col 7 处理耗时
        ]
        for col, val in enumerate(data, 2):
            item = QTableWidgetItem(val)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, col, item)

        # 匹配素材列：标记本文件匹配到了素材库中的哪些文件
        matched_item = QTableWidgetItem(self._format_matched_refs(report))
        matched_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        matched_item.setToolTip("\n".join(report.matched_references) if report.matched_references else "")
        matched_item.setForeground(QColor("#4fc3f7") if report.matched_references else QColor("#888888"))
        self._table.setItem(row, 4, matched_item)

        # 输出/操作列：如果有裁切结果，显示打开链接
        if report.cut_result and report.cut_result.success:
            out_path = report.cut_result.output_path
            action_text = f"📂 打开目录"
            action_item = QTableWidgetItem(action_text)
            action_item.setToolTip(f"打开: {os.path.dirname(out_path)}")
            action_item.setData(Qt.ItemDataRole.UserRole, out_path)
            action_item.setForeground(QColor("#0078d4"))
            self._table.setItem(row, 8, action_item)
        elif report.status == "completed" and report.segments_found > 0:
            # 检测到重复但没有裁切
            action_item = QTableWidgetItem("未裁切")
            action_item.setForeground(QColor("#f0c040"))
            self._table.setItem(row, 8, action_item)
        else:
            self._table.setItem(row, 8, QTableWidgetItem(
                report.error_message[:40] if report.error_message else "无操作"))

        self._table.scrollToBottom()

    def _format_matched_refs(self, report) -> str:
        """格式化匹配素材列显示：素材库文件名列表"""
        refs = getattr(report, 'matched_references', None) or []
        if not refs:
            return "—"
        names = [os.path.basename(p) for p in refs]
        return "、".join(names)

    def _show_segment_details(self, index):
        """双击结果行：打开文件目录 或 显示片段详情"""
        row = index.row()
        if row >= self._table.rowCount():
            return

        # 检查是否点击了"打开目录"列（列8）
        col = index.column()
        item = self._table.item(row, 8)
        if item and col == 8:
            out_path = item.data(Qt.ItemDataRole.UserRole)
            if out_path:
                folder = os.path.dirname(out_path)
                if os.path.exists(folder):
                    os.startfile(folder)
                    self.statusBar().showMessage(f"已打开: {folder}", 3000)
                elif os.path.exists(out_path):
                    os.startfile(os.path.dirname(out_path))
                return

        # 否则显示片段详情
        if not self._last_batch_report:
            return

        reports = self._last_batch_report.file_reports
        if row >= len(reports):
            return

        report = reports[row]
        if not report.detection or not report.detection.segments:
            QMessageBox.information(self, "详情", "该文件未发现重复片段。")
            return

        lines = [
            f"文件: {report.video_name}",
        ]
        matched = getattr(report, 'matched_references', None) or []
        if matched:
            lines.append("匹配素材: " + "、".join(os.path.basename(p) for p in matched))
        lines.append(f"发现 {len(report.detection.segments)} 个重复片段:")
        lines.append("")
        for i, seg in enumerate(report.detection.segments, 1):
            lines.append(
                f"  片段 {i}: "
                f"[{seg.target_start_time:.1f}s - {seg.target_end_time:.1f}s] "
                f"({seg.duration:.1f}s) "
                f"相似度: {seg.avg_similarity:.1f}%"
            )

        if report.cut_result:
            lines.append("")
            if report.cut_result.success:
                lines.append(f"✅ 裁切成功: {os.path.basename(report.cut_result.output_path)}")
                lines.append(f"   移除 {report.cut_result.removed_duration:.1f}s 重复内容")
            else:
                lines.append(f"❌ 裁切失败: {report.cut_result.error_message}")

        QMessageBox.information(self, "处理详情", "\n".join(lines))

    def _clear_results(self):
        """清空结果表格"""
        self._table.setRowCount(0)
        self._result_summary.setText("待处理...")
        self._last_batch_report = None
        self._btn_export.setEnabled(False)

    # ===== 报表导出 =====
    def _export_report(self, format_type: str):
        """导出报表"""
        if not self._last_batch_report:
            QMessageBox.warning(self, "提示", "没有可导出的处理结果。")
            return

        exporter = ReportExporter(self._output_dir_edit.text() or os.path.expanduser("~"))

        format_map = {
            "csv": ("CSV 文件 (*.csv)", exporter.export_csv),
            "json": ("JSON 文件 (*.json)", exporter.export_json),
            "excel": ("Excel 文件 (*.xlsx)", exporter.export_excel),
            "html": ("HTML 文件 (*.html)", exporter.export_html),
        }

        if format_type not in format_map:
            return

        file_filter, export_func = format_map[format_type]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"video_dedup_report_{timestamp}.{format_type}"

        filepath, _ = QFileDialog.getSaveFileName(
            self, f"导出{format_type.upper()}报表",
            os.path.join(self._output_dir_edit.text() or os.path.expanduser("~"), default_name),
            file_filter
        )

        if filepath:
            try:
                result_path = export_func(self._last_batch_report, filepath)
                if result_path:
                    QMessageBox.information(self, "导出成功", f"报表已导出到:\n{result_path}")
                    logger.info(f"报表已导出 ({format_type}): {result_path}")
                else:
                    QMessageBox.warning(self, "导出失败", "报表导出失败，请检查日志。")
            except Exception as e:
                QMessageBox.critical(self, "导出错误", f"导出失败:\n{e}")
                logger.error(f"导出失败: {e}")

    # ===== 日志 =====
    def _refresh_log_view(self):
        """刷新日志显示"""
        handler = get_memory_handler()
        if not handler:
            return

        filter_text = self._log_filter_combo.currentText()
        level_map = {
            "全部": None,
            "DEBUG": 10,
            "INFO": 20,
            "WARNING": 30,
            "ERROR": 40,
        }
        level = level_map.get(filter_text)

        records = handler.get_records(level=level, count=300)

        lines = []
        for rec in records:
            # 按级别着色
            color = {
                "DEBUG": "#888888",
                "INFO": "#e8e8e8",
                "WARNING": "#f0c040",
                "ERROR": "#f04040",
                "CRITICAL": "#ff4040",
            }.get(rec.levelname, "#e8e8e8")

            # 转义 HTML 特殊字符，避免日志内容破坏 HTML（可能引发 Qt 渲染异常）
            msg = html.escape(rec.getMessage().replace("\n", " "))
            lines.append(
                f'<span style="color:{color}">'
                f'{rec.asctime} | {rec.levelname:8} | {msg}'
                f'</span>'
            )

        # 最新日志在底部（标准日志查看器顺序），仅在内容变化时更新（避免闪烁）
        new_html = "<br>".join(lines)
        if new_html == getattr(self, "_last_log_html", None):
            return

        # 更新前记录滚动状态，更新后恢复用户位置
        scrollbar = self._log_text.verticalScrollBar()
        was_at_bottom = scrollbar.value() >= scrollbar.maximum() - 20
        saved_value = scrollbar.value()

        self._log_text.setHtml(new_html)
        self._last_log_html = new_html

        if was_at_bottom:
            # 原本在底部：跟随最新日志，自动滚动到底部
            scrollbar.setValue(scrollbar.maximum())
        else:
            # 正在上翻查看历史日志：保持原滚动位置，不强制拉回
            scrollbar.setValue(saved_value)

    def _clear_log(self):
        """清空日志"""
        handler = get_memory_handler()
        if handler:
            handler.clear()
        self._log_text.clear()
        self._last_log_html = ""

    # ===== 设置 =====
    def _save_settings(self):
        """保存当前设置"""
        self.config_mgr.set("sample_interval", self._sample_interval_spin.value())
        self.config_mgr.set("hash_threshold", self._threshold_spin.value())
        self.config_mgr.set("min_match_duration", self._min_duration_spin.value())
        if hasattr(self, '_match_ratio_spin'):
            self.config_mgr.set("min_match_ratio", self._match_ratio_spin.value() / 100.0)
        self.config_mgr.set("auto_cut", self._auto_cut_check.isChecked())
        self.config_mgr.set("keep_duplicates", self._keep_dup_check.isChecked())
        self.config_mgr.set("output_dir", self._output_dir_edit.text())
        self.config_mgr.set("max_workers", self._get_worker_count())
        self.config_mgr.set("use_gpu", self._gpu_check.isChecked() if hasattr(self, '_gpu_check') else True)
        self.config_mgr.set("material_position",
            ["anywhere", "beginning", "end", "both"][self._material_position_combo.currentIndex()])
        self.config_mgr.set("position_search_margin", self._position_margin_spin.value())
        self.config_mgr.set("limit_head_tail", self._limit_head_tail_check.isChecked())
        self.config_mgr.set("head_tail_time", self._head_tail_time_spin.value())
        self.config_mgr.set("enable_frame_filter", self._enable_frame_filter_check.isChecked())
        self.config_mgr.set("frame_dark_threshold", self._frame_dark_spin.value())
        self.config_mgr.set("frame_bright_threshold", self._frame_bright_spin.value())
        self.config_mgr.set("enable_coarse_filter", self._enable_coarse_filter_check.isChecked())
        self.config_mgr.set("coarse_interval", self._coarse_interval_spin.value())
        self.config_mgr.set("use_hash_cache", self._use_hash_cache_check.isChecked())
        self.statusBar().showMessage("设置已保存", 2000)
        logger.info("用户设置已保存")

    def _clear_hash_cache(self):
        """清空磁盘哈希缓存"""
        from .hasher import clear_hash_cache
        removed = clear_hash_cache()
        self.statusBar().showMessage(f"已清空哈希缓存（删除 {removed} 个缓存文件）", 3000)
        logger.info(f"已清空哈希缓存，删除 {removed} 个文件")

    def _toggle_theme(self):
        """切换主题"""
        new_theme = "light" if self.config.theme == "dark" else "dark"
        self.config_mgr.set("theme", new_theme)
        app = QApplication.instance()
        if new_theme == "dark":
            app.setPalette(get_dark_palette())
        else:
            app.setPalette(QApplication.style().standardPalette())
        app.setStyleSheet(get_theme_stylesheet(new_theme))
        self.statusBar().showMessage(f"主题已切换为: {new_theme}", 2000)

    def _show_about(self):
        """显示关于对话框"""
        QMessageBox.about(
            self, "关于 - 视频去重工具",
            "<h3>视频去重工具 v1.0</h3>"
            "<p>基于视频帧哈希比对的重复片段检测与裁切工具。</p>"
            "<p><b>核心功能:</b></p>"
            "<ul>"
            "<li>多算法帧哈希比对 (dHash/pHash/aHash)</li>"
            "<li>滑动窗口重复片段检测</li>"
            "<li>自动视频裁切</li>"
            "<li>文件夹监控与自动处理</li>"
            "<li>多线程批量处理</li>"
            "<li>多格式报表导出 (CSV/JSON/Excel/HTML)</li>"
            "</ul>"
            "<p>使用 OpenCV + PyQt6 构建</p>"
        )

    # ===== 窗口事件 =====
    def closeEvent(self, event):
        """窗口关闭事件"""
        if self._is_processing:
            reply = QMessageBox.question(
                self, "确认", "正在处理中，确定要退出吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return
            self._stop_processing()

        # 停止监控
        if self._watch_worker and self._watch_worker.isRunning():
            self._watch_worker.stop()
            self._watch_worker.wait(3000)

        # 保存设置
        self._save_settings()
        self._log_timer.stop()
        logger.info("应用退出")
        event.accept()
