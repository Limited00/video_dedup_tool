<p align="center">
  <h1 align="center">🎬 Video Dedup Tool</h1>
  <p align="center"><b>视频去重工具</b> — 基于感知哈希的智能视频重复片段检测与裁切</p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.9+-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/platform-Windows%2010%2F11-0078d4.svg" alt="Platform">
  <img src="https://img.shields.io/badge/gui-PyQt6-green.svg" alt="GUI">
  <img src="https://img.shields.io/badge/license-MIT-yellow.svg" alt="License">
  <img src="https://img.shields.io/badge/GPU-CUDA%20%7C%20CuPy-76b900.svg" alt="GPU">
</p>

---

## 📖 Overview

**Video Dedup Tool** is a Windows desktop application that detects and removes duplicate video segments by comparing against a reference material library. It uses perceptual hashing (dHash/pHash/aHash) with **numpy-vectorized Hamming distance computation** to achieve near-instant frame matching, and **FFmpeg stream-copy** for lossless cutting without re-encoding.

> **Use Case**: You have a library of original video clips (素材库). You want to check if any target videos contain copies of those clips, and automatically remove the duplicated portions.

## ✨ Features

| Category | Feature |
|----------|---------|
| 🔍 **Detection** | Multi-algorithm perceptual hashing (dHash / pHash / aHash) with numpy-vectorized batch comparison |
| 📏 **Smart Filtering** | Material-length-ratio threshold — only segments covering ≥X% of a reference clip are flagged |
| ⚡ **Performance** | `grab()`/`retrieve()` frame skipping (3.6× faster), vectorized distance matrix (0.05s detection) |
| 🖥️ **GPU Acceleration** | CuPy backend for batched frame processing + FFmpeg NVENC hardware encoding (optional) |
| 🧵 **Parallel** | `ThreadPoolExecutor` for concurrent multi-file processing, configurable up to 16 workers |
| ✂️ **Cutting** | FFmpeg stream-copy cutting (no quality loss), optional in-place overwrite of source files |
| 👁 **Folder Monitor** | Real-time filesystem watching (watchdog + polling fallback), auto-queues new videos |
| 📊 **Reports** | Export to CSV / JSON / Excel (xlsx) / HTML with per-segment similarity details |
| 🎨 **Modern UI** | Windows 11 Fluent Design dark theme, drag-and-drop, collapsible panels |
| 📦 **Portable EXE** | PyInstaller-packaged standalone executable, no Python required |

## 🚀 Quick Start

### Prerequisites

- **Windows 10 / 11** (64-bit)
- **FFmpeg** — required for video cutting. [Download here](https://ffmpeg.org/download.html) and ensure `ffmpeg.exe` is in your `PATH`.
- **Python 3.9+** (source install only)
- **NVIDIA GPU + CuPy** (optional, for GPU acceleration)

### Option A: Run from Source

```bash
git clone https://github.com/your-username/video-dedup-tool.git
cd video-dedup-tool

pip install -r requirements.txt
python main.py
```

### Option B: Portable EXE

Download `VideoDedupTool.exe` from [Releases](https://github.com/your-username/video-dedup-tool/releases) and run directly — no Python installation needed.

### Optional: GPU Acceleration

```bash
pip install cupy-cuda12x    # For RTX 40/50 series (CUDA 12.x)
pip install cupy-cuda11x    # For RTX 20/30 series (CUDA 11.x)
```

## 📖 Usage Guide

### Workflow

```
1. Build Material Library  →  2. Add Target Videos  →  3. Detect  →  4. Review  →  5. Cut & Export
```

1. **Build Material Library** — Click `➕ Add Videos` or `📂 Import Folder` to populate the reference library. Supports drag-and-drop.
2. **Add Target Videos** — Import videos you want to scan for duplicate content.
3. **Configure Parameters** — Adjust sampling interval, similarity threshold, and match ratio.
4. **Start Processing** — Click `▶ Start` to run detection (multi-threaded).
5. **Review Results** — Inspect detected segments in the results table; double-click for details.
6. **Cut & Export** — Enable auto-cut to remove duplicates in-place or generate `_dedup.mp4` copies.

### Detection Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| **Sample Interval** | 1.0 s | Frame sampling rate. Lower = more accurate but slower. |
| **Similarity Threshold** | 10 | Hamming distance (0–64). Lower = stricter matching. 10 is recommended. |
| **Match Ratio** | 10% | A segment is flagged only if its duration ≥ (material duration × ratio). |
| **Min Segment** | 0.5 s | Ignore segments shorter than this. |
| **Hash Algorithm** | dHash | dHash (fast) / pHash (robust to scaling) / aHash (fastest) / Combined. |
| **Concurrency** | 4 | Number of files to process in parallel. |

### Cutting Modes

| Option | Behavior |
|--------|----------|
| ☐ Auto-cut OFF | Detection only — no files modified. |
| ☑ Auto-cut + ☐ Overwrite | Generates `*_dedup.mp4` alongside the original. |
| ☑ Auto-cut + ☑ Overwrite | Replaces the original file directly (no backup). |

### Search Position & Head/Tail Limit

**Material Position** restricts where the material is searched in each target video. The search window is sized from the *longest material clip*: `window = longest_material × (1 + search margin)`.

| Value | Behavior |
|-------|----------|
| `anywhere` | Search the entire video (safest, slowest). |
| `beginning` / `end` | Search only the start or end region (50–80% faster). |
| `both` | Search both the head and tail (for intro/outro material). |

**Head/Tail Time Limit (optional)** — when enabled, recognition **and** cutting operate only within the first and last *N* seconds of each target video, skipping the middle to accelerate long videos:

| Condition | Behavior |
|-----------|----------|
| Video duration < *N* | No skipping — full recognition of the entire video. |
| Head and tail windows overlap | Full recognition (the windows cover the whole video). |
| Otherwise | Head `[0, N]` + tail `[duration−N, duration]` only; the middle is skipped. |

> Enabling this option **overrides** the `Material Position` / `Search Margin` range calculation.

### Frame Filtering & Coarse Pre-screening

Two optional accelerations inspired by VideoDuplicateFinder, both **off by default**.

**Frame Filtering** — drop over-dark / over-bright frames (black frames, overexposed / flat-color frames) so they don't produce noisy hashes:

| Setting | Default | Meaning |
|---------|---------|---------|
| `enable_frame_filter` | off | Enable brightness filtering. |
| `frame_dark_threshold` | 16 | Drop frames whose mean grayscale is below this. |
| `frame_bright_threshold` | 240 | Drop frames whose mean grayscale is above this. |

Dropped frames create gaps in sampling; nearby segments are re-merged by the merge-gap setting.

**Coarse Pre-screening** — before the full frame-by-frame pass, sample the target sparsely and gate with a relaxed threshold. If nothing matches at the coarse level, the fine pass is skipped entirely (fast when targets contain no material):

| Setting | Default | Meaning |
|---------|---------|---------|
| `enable_coarse_filter` | off | Enable the two-stage coarse→fine pipeline. |
| `coarse_interval` | 5.0 s | Coarse sampling interval. |

> ⚠️ Trade-off: material clips shorter than `coarse_interval` may fall between coarse samples and be missed, so the gate uses a relaxed threshold (`hash_threshold + 5`) and is **off by default**. Enable it only when most target videos are expected to contain no material.

## 🏗️ Architecture

```
video_dedup_tool/
├── main.py                  # Application entry point
├── build.py                 # PyInstaller packaging script
├── requirements.txt         # Python dependencies
└── app/
    ├── main_window.py       # GUI (PyQt6, ~1400 lines)
    ├── hasher.py            # Perceptual hashing (dHash/pHash/aHash) + grab/retrieve frame skipping
    ├── detector.py          # Numpy-vectorized duplicate detection (uint64 popcount matrix)
    ├── cutter.py            # FFmpeg stream-copy cutting with automatic fallback
    ├── processor.py         # Processing pipeline + ThreadPoolExecutor concurrency
    ├── gpu_utils.py         # GPU detection, CuPy batch processing, NVENC encoding
    ├── watcher.py           # Folder monitoring (watchdog + polling)
    ├── workers.py           # QThread workers for async GUI operation
    ├── report.py            # CSV / JSON / Excel / HTML report export
    ├── config.py            # JSON-based persistent settings (%APPDATA%)
    ├── logger.py            # Dual-channel logging (file + in-memory for GUI)
    └── styles.py            # Windows 11 dark/light QSS theme
```

### Data Flow

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Video Files │───▶│  FrameHasher │───▶│  Detector    │───▶│  Cutter      │
│  (ref+target)│    │  dHash/pHash │    │  numpy XOR   │    │  FFmpeg copy │
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
                           │                    │                    │
                     GPU (CuPy)          uint64 matrix        Stream copy
                     batch resize        O(N×M) in C          ~1.5s for 500MB
```

## ⚡ Performance

Tested on **RTX 5060 Ti + Windows 11** with a 32-minute 1080p target video (484 MB) against a 9-clip material library (470 MB total):

| Stage | Time | Method |
|-------|------|--------|
| Material hashing (9 clips, 644 frames) | 9.4 s | OpenCV + grab/retrieve skip |
| Target hashing (1921s video, 1922 frames) | 17.0 s | OpenCV + grab/retrieve skip |
| Vectorized detection (644 × 1922) | **0.05 s** | numpy uint64 bitwise XOR matrix |
| FFmpeg cutting (→ 398 MB output) | 1.7 s | Stream copy (`-c copy`) |
| **Total** | **~26 s** | |

> Detection speed scales as O(N_ref × N_target / chunk_size) with numpy's C-level vectorization. The bottleneck is I/O-bound video decoding, not the matching algorithm.

## 🔧 Build from Source

```bash
# Install dependencies
pip install -r requirements.txt

# Run the app
python main.py

# Package as standalone EXE (onedir mode — faster startup)
python build.py --onedir

# Package as single-file EXE
python build.py

# Clean build artifacts
python build.py --clean
```

The output EXE is located in `dist/VideoDedupTool/`.

## 🧪 Testing

```bash
# Integration test (no video files needed)
python test_integration.py

# Real-file test (requires sample videos)
python test_with_videos.py
```

## 📄 License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

> **Disclaimer**: Video processing may involve copyright considerations. Users are responsible for ensuring compliance with applicable laws.

---

<p align="center">
  <sub>Built with Python · PyQt6 · OpenCV · NumPy · FFmpeg · CuPy</sub>
</p>
