<p align="center">
  <h1 align="center">🎬 Video Dedup Tool</h1>
  <p align="center"><b>视频去重工具</b> — 基于感知哈希的智能视频重复片段检测与裁切</p>
</p>

<p align="center">
  <a href="README.md">English</a> | <b>简体中文</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.9+-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/platform-Windows%2010%2F11-0078d4.svg" alt="Platform">
  <img src="https://img.shields.io/badge/gui-PyQt6-green.svg" alt="GUI">
  <img src="https://img.shields.io/badge/license-MIT-yellow.svg" alt="License">
  <img src="https://img.shields.io/badge/GPU-CUDA%20%7C%20CuPy-76b900.svg" alt="GPU">
</p>

---

## 📖 概述

**Video Dedup Tool** 是一款 Windows 桌面应用程序，通过比对参考素材库来检测并去除视频中的重复片段。它使用感知哈希（dHash/pHash/aHash），配合 **numpy 向量化的汉明距离计算** 实现近乎即时的帧匹配，并使用 **FFmpeg 流复制** 实现无重编码的无损裁切。

> **使用场景**：你有一个原始视频片段库（素材库），想检查目标视频中是否包含这些片段的拷贝，并自动去除重复部分。

## ✨ 功能特性

| 分类 | 功能 |
|----------|---------|
| 🔍 **检测** | 多算法感知哈希（dHash / pHash / aHash），numpy 向量化批量比对 |
| 📏 **智能过滤** | 素材时长占比阈值 — 仅标记覆盖参考片段 ≥X% 时长的片段 |
| ⚡ **性能** | `grab()`/`retrieve()` 跳帧（提速 3.6 倍），向量化距离矩阵（检测仅 0.05s） |
| 🖥️ **GPU 加速** | CuPy 后端批量处理帧 + FFmpeg NVENC 硬件编码（可选） |
| 🧵 **并行处理** | `ThreadPoolExecutor` 多文件并发处理，最多可配置 16 个工作线程 |
| ✂️ **裁切** | FFmpeg 流复制裁切（无损），可选原位覆盖源文件 |
| 👁 **文件夹监控** | 实时文件系统监听（watchdog + 轮询兜底），自动将新视频加入队列 |
| 📊 **报告** | 导出 CSV / JSON / Excel (xlsx) / HTML，含每段相似度详情 |
| 🎨 **现代 UI** | Windows 11 Fluent 设计深色主题，支持拖拽，可折叠面板 |
| 📦 **便携 EXE** | PyInstaller 打包的独立可执行文件，无需安装 Python |

## 🚀 快速开始

### 环境要求

- **Windows 10 / 11**（64 位）
- **FFmpeg** — 视频裁切所必需。[点此下载](https://ffmpeg.org/download.html)，并确保 `ffmpeg.exe` 在 `PATH` 中。
- **Python 3.9+**（仅源码安装时需要）
- **NVIDIA GPU + CuPy**（可选，用于 GPU 加速）

### 方式 A：从源码运行

```bash
git clone https://github.com/Limited00/video_dedup_tool.git
cd video_dedup_tool

pip install -r requirements.txt
python main.py
```

### 方式 B：便携 EXE

从 [Releases](https://github.com/Limited00/video_dedup_tool/releases) 下载 `VideoDedupTool.exe` 直接运行 — 无需安装 Python。

### 可选：GPU 加速

```bash
pip install cupy-cuda12x    # RTX 40/50 系列（CUDA 12.x）
pip install cupy-cuda11x    # RTX 20/30 系列（CUDA 11.x）
```

## 📖 使用指南

### 工作流程

```
1. 建立素材库  →  2. 添加目标视频  →  3. 检测  →  4. 查看结果  →  5. 裁切导出
```

1. **建立素材库** — 点击 `➕ 添加视频` 或 `📂 导入文件夹` 填充参考素材库，支持拖拽。
2. **添加目标视频** — 导入需要扫描重复内容的视频。
3. **配置参数** — 调整采样间隔、相似度阈值和匹配比例。
4. **开始处理** — 点击 `▶ 开始` 运行检测（多线程）。
5. **查看结果** — 在结果表中查看检测到的片段，双击查看详情。
6. **裁切导出** — 启用自动裁切，原位去除重复部分或生成 `_dedup.mp4` 副本。

### 检测参数

| 参数 | 默认值 | 说明 |
|-----------|---------|-------------|
| **采样间隔** | 1.0 s | 帧采样频率。越小越精确，但越慢。 |
| **相似度阈值** | 10 | 汉明距离（0–64）。越小匹配越严格。推荐 10。 |
| **匹配比例** | 10% | 仅当片段时长 ≥（素材时长 × 比例）时才被标记。 |
| **最短片段** | 0.5 s | 忽略短于此值的片段。 |
| **哈希算法** | dHash | dHash（快）/ pHash（对缩放鲁棒）/ aHash（最快）/ 组合。 |
| **并发数** | 4 | 并行处理的文件数量。 |

### 裁切模式

| 选项 | 行为 |
|--------|----------|
| ☐ 自动裁切关闭 | 仅检测 — 不修改任何文件。 |
| ☑ 自动裁切 + ☐ 覆盖 | 在原文件旁生成 `*_dedup.mp4`。 |
| ☑ 自动裁切 + ☑ 覆盖 | 直接替换原文件（无备份）。 |

### 搜索位置与首尾限定

**素材位置** 限制在每个目标视频中搜索素材的区域。搜索窗口大小由*最长的素材片段*决定：`窗口 = 最长素材 ×（1 + 搜索余量）`。

| 值 | 行为 |
|-------|----------|
| `anywhere` | 搜索整个视频（最稳妥，最慢）。 |
| `beginning` / `end` | 仅搜索开头或结尾区域（提速 50–80%）。 |
| `both` | 同时搜索首尾（用于片头/片尾素材）。 |

**首尾时间限定（可选）** — 启用后，识别**和**裁切仅在每个目标视频的前后 *N* 秒内进行，跳过中间部分以加速长视频：

| 条件 | 行为 |
|-----------|----------|
| 视频时长 < *N* | 不跳过 — 全量识别整个视频。 |
| 首尾窗口重叠 | 全量识别（窗口已覆盖整个视频）。 |
| 其他情况 | 仅头部 `[0, N]` + 尾部 `[时长−N, 时长]`，跳过中间部分。 |

> 启用此选项会**覆盖** `素材位置` / `搜索余量` 的范围计算。

### 帧过滤与粗筛

两项可选加速策略，灵感来自 VideoDuplicateFinder，默认均**关闭**。

**帧过滤** — 丢弃过暗/过亮帧（黑帧、过曝/纯色帧），避免产生噪声哈希：

| 设置 | 默认值 | 含义 |
|---------|---------|---------|
| `enable_frame_filter` | 关闭 | 启用亮度过滤。 |
| `frame_dark_threshold` | 16 | 丢弃平均灰度低于此值的帧。 |
| `frame_bright_threshold` | 240 | 丢弃平均灰度高于此值的帧。 |

被丢弃的帧会在采样中形成间隙；相邻片段会由合并间隔设置重新合并。

**粗筛** — 在进行完整逐帧比对前，先稀疏采样目标视频并用宽松阈值做门控。若粗筛阶段无匹配，则完全跳过精筛（当目标视频不含素材时速度极快）：

| 设置 | 默认值 | 含义 |
|---------|---------|---------|
| `enable_coarse_filter` | 关闭 | 启用两阶段 粗筛→精筛 流水线。 |
| `coarse_interval` | 5.0 s | 粗筛采样间隔。 |

> ⚠️ 权衡：短于 `coarse_interval` 的素材片段可能落在粗筛采样点之间而被漏检，因此门控使用宽松阈值（`hash_threshold + 5`），且默认**关闭**。仅当大多数目标视频预期不含素材时才启用。

## 🏗️ 架构

```
video_dedup_tool/
├── main.py                  # 应用入口
├── build.py                 # PyInstaller 打包脚本
├── requirements.txt         # Python 依赖
└── app/
    ├── main_window.py       # GUI（PyQt6，约 1400 行）
    ├── hasher.py            # 感知哈希（dHash/pHash/aHash）+ grab/retrieve 跳帧
    ├── detector.py          # numpy 向量化重复检测（uint64 popcount 矩阵）
    ├── cutter.py            # FFmpeg 流复制裁切，带自动回退
    ├── processor.py         # 处理流水线 + ThreadPoolExecutor 并发
    ├── gpu_utils.py         # GPU 检测、CuPy 批量处理、NVENC 编码
    ├── watcher.py           # 文件夹监控（watchdog + 轮询）
    ├── workers.py           # QThread 工作线程，用于异步 GUI 操作
    ├── report.py            # CSV / JSON / Excel / HTML 报告导出
    ├── config.py            # 基于 JSON 的持久化设置（%APPDATA%）
    ├── logger.py            # 双通道日志（文件 + 内存供 GUI 使用）
    └── styles.py            # Windows 11 深/浅色 QSS 主题
```

### 数据流

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  视频文件     │───▶│  FrameHasher │───▶│  Detector    │───▶│  Cutter      │
│ (素材+目标)   │    │  dHash/pHash │    │  numpy XOR   │    │  FFmpeg copy │
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
                           │                    │                    │
                     GPU (CuPy)          uint64 矩阵        流复制
                     批量 resize         C 语言 O(N×M)      500MB 约 1.5s
```

## ⚡ 性能

在 **RTX 5060 Ti + Windows 11** 上测试：32 分钟 1080p 目标视频（484 MB），对比 9 段素材库（共 470 MB）：

| 阶段 | 耗时 | 方法 |
|-------|------|--------|
| 素材哈希（9 段，644 帧） | 9.4 s | OpenCV + grab/retrieve 跳帧 |
| 目标哈希（1921s 视频，1922 帧） | 17.0 s | OpenCV + grab/retrieve 跳帧 |
| 向量化检测（644 × 1922） | **0.05 s** | numpy uint64 位异或矩阵 |
| FFmpeg 裁切（→ 398 MB 输出） | 1.7 s | 流复制（`-c copy`） |
| **总计** | **约 26 s** | |

> 检测速度随 O(N_ref × N_target / chunk_size) 扩展，得益于 numpy 的 C 级向量化。瓶颈是受 I/O 限制的视频解码，而非匹配算法本身。

## 🔧 从源码构建

```bash
# 安装依赖
pip install -r requirements.txt

# 运行应用
python main.py

# 打包为独立 EXE（onedir 模式 — 启动更快）
python build.py --onedir

# 打包为单文件 EXE
python build.py

# 清理构建产物
python build.py --clean
```

输出的 EXE 位于 `dist/VideoDedupTool/`。

## 🧪 测试

```bash
# 快速集成测试（无需视频文件，验证所有模块导入和基本功能）
python test_integration.py

# 全面测试套件（覆盖所有核心模块和新功能）
python test_comprehensive.py
```

## 📄 许可证

本项目基于 MIT 许可证发布。详见 [LICENSE](LICENSE)。

> **免责声明**：视频处理可能涉及版权问题。用户有责任确保遵守适用法律。

---

<p align="center">
  <sub>Built with Python · PyQt6 · OpenCV · NumPy · FFmpeg · CuPy</sub>
</p>
