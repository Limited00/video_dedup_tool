"""
Qt 样式表 - Windows 11 风格
提供深色 / 浅色主题的 QSS 样式。
"""

DARK_THEME_QSS = r"""
/* ===== 全局 ===== */
QMainWindow {
    background-color: #1f1f1f;
    color: #e8e8e8;
}
QWidget {
    background-color: #1f1f1f;
    color: #e8e8e8;
    font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
    font-size: 13px;
}

/* ===== 菜单栏 ===== */
QMenuBar {
    background-color: #2d2d2d;
    color: #e8e8e8;
    border-bottom: 1px solid #3d3d3d;
    padding: 2px;
}
QMenuBar::item {
    padding: 6px 12px;
    border-radius: 4px;
    margin: 2px 2px;
}
QMenuBar::item:selected {
    background-color: #3d3d3d;
}
QMenu {
    background-color: #2d2d2d;
    color: #e8e8e8;
    border: 1px solid #3d3d3d;
    border-radius: 8px;
    padding: 4px;
}
QMenu::item {
    padding: 8px 32px 8px 16px;
    border-radius: 4px;
}
QMenu::item:selected {
    background-color: #0078d4;
}
QMenu::separator {
    height: 1px;
    background-color: #3d3d3d;
    margin: 4px 8px;
}

/* ===== 工具栏 ===== */
QToolBar {
    background-color: #2d2d2d;
    border-bottom: 1px solid #3d3d3d;
    padding: 4px;
    spacing: 6px;
}
QToolButton {
    background-color: transparent;
    color: #e8e8e8;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 8px 14px;
    font-size: 13px;
}
QToolButton:hover {
    background-color: #3d3d3d;
    border-color: #4d4d4d;
}
QToolButton:pressed {
    background-color: #0078d4;
    border-color: #0078d4;
}

/* ===== 按钮 ===== */
QPushButton {
    background-color: #0078d4;
    color: white;
    border: none;
    border-radius: 6px;
    padding: 8px 18px;
    font-size: 13px;
    font-weight: 500;
    min-height: 20px;
}
QPushButton:hover {
    background-color: #1a8ad4;
}
QPushButton:pressed {
    background-color: #005a9e;
}
QPushButton:disabled {
    background-color: #4d4d4d;
    color: #888888;
}
QPushButton#secondaryBtn {
    background-color: #3d3d3d;
    color: #e8e8e8;
    border: 1px solid #4d4d4d;
}
QPushButton#secondaryBtn:hover {
    background-color: #4d4d4d;
}
QPushButton#dangerBtn {
    background-color: #c42b1c;
}
QPushButton#dangerBtn:hover {
    background-color: #d93426;
}
QPushButton#successBtn {
    background-color: #107c10;
}
QPushButton#successBtn:hover {
    background-color: #139413;
}

/* ===== 输入框 ===== */
QLineEdit, QSpinBox, QDoubleSpinBox {
    background-color: #2d2d2d;
    color: #e8e8e8;
    border: 1px solid #4d4d4d;
    border-radius: 6px;
    padding: 8px 10px;
    font-size: 13px;
    selection-background-color: #0078d4;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: #0078d4;
    border-width: 2px;
    padding: 7px 9px;
}

/* ===== 下拉框 ===== */
QComboBox {
    background-color: #2d2d2d;
    color: #e8e8e8;
    border: 1px solid #4d4d4d;
    border-radius: 6px;
    padding: 8px 10px;
    min-width: 80px;
}
QComboBox:hover {
    border-color: #5d5d5d;
}
QComboBox:focus {
    border-color: #0078d4;
}
QComboBox::drop-down {
    border: none;
    width: 28px;
}
QComboBox QAbstractItemView {
    background-color: #2d2d2d;
    color: #e8e8e8;
    border: 1px solid #4d4d4d;
    border-radius: 6px;
    selection-background-color: #0078d4;
    outline: none;
}

/* ===== 复选框 / 单选框 ===== */
QCheckBox, QRadioButton {
    color: #e8e8e8;
    spacing: 8px;
    padding: 4px 0;
}
QCheckBox::indicator, QRadioButton::indicator {
    width: 18px;
    height: 18px;
    border: 2px solid #6d6d6d;
    border-radius: 4px;
    background-color: #2d2d2d;
}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {
    background-color: #0078d4;
    border-color: #0078d4;
}
QRadioButton::indicator {
    border-radius: 10px;
}

/* ===== 分组框 ===== */
QGroupBox {
    color: #e8e8e8;
    border: 1px solid #3d3d3d;
    border-radius: 8px;
    margin-top: 12px;
    padding: 16px 12px 12px 12px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 8px;
    background-color: #1f1f1f;
}

/* ===== 标签页 ===== */
QTabWidget::pane {
    border: 1px solid #3d3d3d;
    border-radius: 8px;
    background-color: #1f1f1f;
    top: -1px;
}
QTabBar::tab {
    background-color: #2d2d2d;
    color: #a0a0a0;
    border: 1px solid #3d3d3d;
    border-bottom: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    padding: 10px 20px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background-color: #1f1f1f;
    color: #e8e8e8;
    border-bottom: 2px solid #0078d4;
}
QTabBar::tab:hover:!selected {
    background-color: #353535;
    color: #d0d0d0;
}

/* ===== 表格 ===== */
QTableWidget, QTableView {
    background-color: #2d2d2d;
    color: #e8e8e8;
    border: 1px solid #3d3d3d;
    border-radius: 8px;
    gridline-color: #3d3d3d;
    selection-background-color: #0078d4;
    selection-color: white;
    outline: none;
}
QTableWidget::item, QTableView::item {
    padding: 6px 10px;
}
QHeaderView::section {
    background-color: #353535;
    color: #e8e8e8;
    border: none;
    border-right: 1px solid #3d3d3d;
    border-bottom: 2px solid #4d4d4d;
    padding: 8px 10px;
    font-weight: 600;
}

/* ===== 列表 ===== */
QListWidget, QListView {
    background-color: #2d2d2d;
    color: #e8e8e8;
    border: 1px solid #3d3d3d;
    border-radius: 8px;
    outline: none;
    padding: 4px;
}
QListWidget::item, QListView::item {
    padding: 8px 10px;
    border-radius: 4px;
    margin: 1px 0;
}
QListWidget::item:selected, QListView::item:selected {
    background-color: #0078d4;
    color: white;
}
QListWidget::item:hover:!selected, QListView::item:hover:!selected {
    background-color: #353535;
}

/* ===== 文本编辑框 ===== */
QTextEdit, QPlainTextEdit {
    background-color: #1a1a1a;
    color: #d4d4d4;
    border: 1px solid #3d3d3d;
    border-radius: 8px;
    padding: 8px;
    font-family: "Cascadia Code", "Consolas", "Courier New", monospace;
    font-size: 12px;
    selection-background-color: #0078d4;
}

/* ===== 滚动条 ===== */
QScrollBar:vertical {
    background-color: transparent;
    width: 10px;
    margin: 0;
    border-radius: 5px;
}
QScrollBar::handle:vertical {
    background-color: #5d5d5d;
    border-radius: 5px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background-color: #7d7d7d;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    background-color: transparent;
    height: 10px;
    border-radius: 5px;
}
QScrollBar::handle:horizontal {
    background-color: #5d5d5d;
    border-radius: 5px;
    min-width: 30px;
}
QScrollBar::handle:horizontal:hover {
    background-color: #7d7d7d;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}

/* ===== 进度条 ===== */
QProgressBar {
    background-color: #2d2d2d;
    border: 1px solid #3d3d3d;
    border-radius: 6px;
    text-align: center;
    color: #e8e8e8;
    font-size: 12px;
    height: 22px;
}
QProgressBar::chunk {
    background-color: #0078d4;
    border-radius: 5px;
}

/* ===== 状态栏 ===== */
QStatusBar {
    background-color: #2d2d2d;
    color: #a0a0a0;
    border-top: 1px solid #3d3d3d;
    padding: 2px 8px;
}

/* ===== 分割线 ===== */
QSplitter::handle {
    background-color: #3d3d3d;
    width: 2px;
    height: 2px;
}

/* ===== 工具提示 ===== */
QToolTip {
    background-color: #3d3d3d;
    color: #e8e8e8;
    border: 1px solid #5d5d5d;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
}

/* ===== 滑块 ===== */
QSlider::groove:horizontal {
    background-color: #3d3d3d;
    height: 4px;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background-color: #0078d4;
    width: 18px;
    height: 18px;
    margin: -8px 0;
    border-radius: 9px;
}
QSlider::handle:horizontal:hover {
    background-color: #1a8ad4;
}

/* ===== 标签 ===== */
QLabel#titleLabel {
    font-size: 18px;
    font-weight: 600;
    color: #e8e8e8;
}
QLabel#subtitleLabel {
    font-size: 14px;
    color: #a0a0a0;
}
QLabel#statusGood {
    color: #6bdb6b;
    font-weight: 600;
}
QLabel#statusWarning {
    color: #f0c040;
    font-weight: 600;
}
QLabel#statusError {
    color: #f04040;
    font-weight: 600;
}

/* ===== 树形视图 ===== */
QTreeWidget, QTreeView {
    background-color: #2d2d2d;
    color: #e8e8e8;
    border: 1px solid #3d3d3d;
    border-radius: 8px;
    outline: none;
}
QTreeWidget::item, QTreeView::item {
    padding: 6px 8px;
    border-radius: 4px;
}
QTreeWidget::item:selected, QTreeView::item:selected {
    background-color: #0078d4;
}
QTreeWidget::item:hover:!selected, QTreeView::item:hover:!selected {
    background-color: #353535;
}
"""

LIGHT_THEME_QSS = r"""
QMainWindow {
    background-color: #f3f3f3;
    color: #1a1a1a;
}
QWidget {
    background-color: #f3f3f3;
    color: #1a1a1a;
    font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
    font-size: 13px;
}
QMenuBar {
    background-color: #ffffff;
    color: #1a1a1a;
    border-bottom: 1px solid #e0e0e0;
}
QMenuBar::item:selected { background-color: #e8e8e8; }
QMenu {
    background-color: #ffffff;
    color: #1a1a1a;
    border: 1px solid #e0e0e0;
    border-radius: 8px;
}
QMenu::item:selected { background-color: #0078d4; color: white; }
QToolBar {
    background-color: #ffffff;
    border-bottom: 1px solid #e0e0e0;
}
QToolButton { color: #1a1a1a; }
QToolButton:hover { background-color: #e8e8e8; }
QToolButton:pressed { background-color: #0078d4; color: white; }
QPushButton {
    background-color: #0078d4;
    color: white;
    border: none;
    border-radius: 6px;
    padding: 8px 18px;
    min-height: 20px;
}
QPushButton:hover { background-color: #1a8ad4; }
QPushButton:disabled { background-color: #c0c0c0; color: #808080; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: #ffffff;
    color: #1a1a1a;
    border: 1px solid #c0c0c0;
    border-radius: 6px;
    padding: 8px 10px;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border-color: #0078d4;
}
QGroupBox {
    border: 1px solid #e0e0e0;
    border-radius: 8px;
    margin-top: 12px;
    padding: 16px 12px 12px 12px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 8px;
    background-color: #f3f3f3;
}
QTabWidget::pane { border: 1px solid #e0e0e0; border-radius: 8px; background-color: #ffffff; }
QTabBar::tab {
    background-color: #f0f0f0;
    color: #606060;
    border: 1px solid #e0e0e0;
    border-bottom: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    padding: 10px 20px;
}
QTabBar::tab:selected {
    background-color: #ffffff;
    color: #1a1a1a;
    border-bottom: 2px solid #0078d4;
}
QTableWidget, QTableView, QListWidget, QListView, QTreeWidget, QTreeView {
    background-color: #ffffff;
    color: #1a1a1a;
    border: 1px solid #e0e0e0;
    border-radius: 8px;
    gridline-color: #e8e8e8;
    selection-background-color: #0078d4;
    selection-color: white;
}
QHeaderView::section {
    background-color: #f5f5f5;
    color: #1a1a1a;
    border-bottom: 2px solid #d0d0d0;
    padding: 8px 10px;
}
QTextEdit, QPlainTextEdit {
    background-color: #ffffff;
    color: #1a1a1a;
    border: 1px solid #e0e0e0;
    border-radius: 8px;
    font-family: "Cascadia Code", "Consolas", "Courier New", monospace;
    font-size: 12px;
}
QProgressBar {
    background-color: #e8e8e8;
    border: 1px solid #d0d0d0;
    border-radius: 6px;
    text-align: center;
}
QProgressBar::chunk { background-color: #0078d4; border-radius: 5px; }
QStatusBar { background-color: #ffffff; color: #606060; border-top: 1px solid #e0e0e0; }
QScrollBar:vertical { background-color: transparent; width: 10px; }
QScrollBar::handle:vertical { background-color: #c0c0c0; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background-color: #a0a0a0; }
QScrollBar:horizontal { background-color: transparent; height: 10px; }
QScrollBar::handle:horizontal { background-color: #c0c0c0; border-radius: 5px; min-width: 30px; }
QSlider::groove:horizontal { background-color: #d0d0d0; height: 4px; border-radius: 2px; }
QSlider::handle:horizontal { background-color: #0078d4; width: 18px; height: 18px; margin: -8px 0; border-radius: 9px; }
QLabel#titleLabel { font-size: 18px; font-weight: 600; color: #1a1a1a; }
QLabel#subtitleLabel { font-size: 14px; color: #606060; }
"""


def get_theme_stylesheet(theme: str = "dark") -> str:
    """获取指定主题的 QSS 样式表"""
    if theme == "light":
        return LIGHT_THEME_QSS
    return DARK_THEME_QSS


def get_dark_palette():
    """获取深色主题的 QPalette（作为 QSS 的补充）"""
    from PyQt6.QtGui import QPalette, QColor
    from PyQt6.QtCore import Qt

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(31, 31, 31))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(232, 232, 232))
    palette.setColor(QPalette.ColorRole.Base, QColor(45, 45, 45))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(61, 61, 61))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(232, 232, 232))
    palette.setColor(QPalette.ColorRole.Text, QColor(232, 232, 232))
    palette.setColor(QPalette.ColorRole.Button, QColor(45, 45, 45))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(232, 232, 232))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 80, 80))
    palette.setColor(QPalette.ColorRole.Link, QColor(0, 120, 212))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(0, 120, 212))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(128, 128, 128))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(128, 128, 128))
    return palette
