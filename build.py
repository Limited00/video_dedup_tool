"""
打包构建脚本
============
使用 PyInstaller 将应用打包为独立可执行文件（Windows EXE / Linux 可执行）。

用法:
    python build.py                    # 打包为单文件（GPU 版，默认）
    python build.py --cpu              # 打包 CPU 版（不含 CuPy，体积更小）
    python build.py --onedir           # 目录模式（启动更快，AppImage 用）
    python build.py --appname NAME     # 自定义输出名
    python build.py --clean            # 清理后重新打包
    python build.py --install          # 安装依赖
"""

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

from app import __version__

# Windows 控制台默认 GBK 编码，emoji/中文 print 可能触发 UnicodeEncodeError；
# 统一将 stdout/stderr 重配为 UTF-8，保证打包脚本在 Windows 下也能正常运行。
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _has_module(name: str) -> bool:
    """检测模块是否已安装（用于可选依赖，如 cupy）。"""
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def check_pyinstaller():
    """检查 PyInstaller 是否已安装"""
    try:
        import PyInstaller
        return True
    except ImportError:
        return False


def install_requirements():
    """安装依赖"""
    print("📦 安装依赖...")
    req_path = Path(__file__).parent / "requirements.txt"
    subprocess.check_call([
        sys.executable, "-m", "pip", "install", "-r", str(req_path)
    ])
    subprocess.check_call([
        sys.executable, "-m", "pip", "install", "pyinstaller"
    ])


def clean_build():
    """清理构建文件"""
    root = Path(__file__).parent
    dirs_to_clean = ["build", "dist", "__pycache__"]
    for d in dirs_to_clean:
        dir_path = root / d
        if dir_path.exists():
            shutil.rmtree(dir_path)
            print(f"🧹 清理: {dir_path}")

    for spec in root.glob("*.spec"):
        spec.unlink()
        print(f"🧹 清理: {spec}")


def build(variant: str = "gpu", onedir: bool = False, appname: str = "VideoDedupTool"):
    """执行 PyInstaller 打包。

    Args:
        variant: "cpu" 或 "gpu"。gpu 变体在检测到 CuPy 时才收集其依赖，否则回退为 CPU。
        onedir: True 打包为目录模式，False 打包为单文件。
        appname: 输出可执行文件名。
    """
    root = Path(__file__).parent

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", appname,
        "--noconsole",
        "--clean",
        "--noconfirm",
        "--add-data", f"app{os.pathsep}app",
    ]

    if onedir:
        cmd.append("--onedir")
        print("📦 打包模式: 目录模式 (启动更快)")
    else:
        cmd.append("--onefile")
        print("📦 打包模式: 单文件")

    # 隐藏导入
    cmd.extend([
        "--hidden-import", "cv2",
        "--hidden-import", "numpy",
        "--hidden-import", "PIL",
        "--hidden-import", "openpyxl",
        "--hidden-import", "watchdog",
        "--hidden-import", "watchdog.observers",
        "--hidden-import", "watchdog.events",
        "--hidden-import", "queue",
        "--hidden-import", "json",
        "--hidden-import", "csv",
        "--hidden-import", "graphlib",
    ])

    # GPU 加速依赖：仅 gpu 变体且已安装 CuPy 时收集。
    # （CPU 变体/未装 CuPy 时若仍 --collect-all cupy，PyInstaller 会因找不到模块而失败。）
    if variant == "gpu" and _has_module("cupy"):
        print("🖥️ GPU 变体: 收集 CuPy / CUDA 运行时")
        cmd.extend([
            "--collect-all", "cupy",
            "--collect-all", "cupy_backends",
            "--hidden-import", "nvidia.cuda_runtime",
            "--hidden-import", "nvidia.cuda_nvrtc",
            "--hidden-import", "nvidia.nvjitlink",
            "--collect-data", "nvidia.cuda_runtime",
            "--collect-data", "nvidia.cuda_nvrtc",
            "--collect-data", "nvidia.nvjitlink",
        ])
    elif variant == "gpu":
        print("⚠️ 未检测到 CuPy，按 CPU 版打包（无 GPU 加速）")
    else:
        print("⚙️ CPU 变体: 不收集 CuPy")

    # 排除大型非必要模块
    cmd.extend([
        "--exclude-module", "matplotlib",
        "--exclude-module", "scipy",
        "--exclude-module", "pandas",
        "--exclude-module", "jupyter",
        "--exclude-module", "IPython",
        "--exclude-module", "tkinter",
        "--exclude-module", "unittest",
    ])

    # CPU 变体：显式排除 CuPy。gpu_utils.py 内含函数级 `import cupy`，
    # PyInstaller 静态分析仍会隐式收集 cupy/cupy_backends，导致 CPU 包体积膨胀
    # 并产生大量 CUDA DLL 缺失警告；运行时代码已有 try/except 回退 CPU，无需打包。
    if variant == "cpu":
        cmd.extend([
            "--exclude-module", "cupy",
            "--exclude-module", "cupy_backends",
            "--exclude-module", "cupyx",
            "--exclude-module", "nvidia",
        ])

    # 入口文件
    cmd.append(str(root / "main.py"))

    print(f"🔨 执行: {' '.join(cmd)}")
    subprocess.check_call(cmd)

    # 输出结果
    dist_dir = root / "dist"
    if dist_dir.exists():
        print(f"\n✅ 打包完成! 版本 v{__version__}，输出目录: {dist_dir}")
        if onedir:
            for d in dist_dir.iterdir():
                if d.is_dir():
                    print(f"   📁 {d.name}/")
        else:
            for exe in dist_dir.iterdir():
                if exe.is_file():
                    size_mb = exe.stat().st_size / (1024 * 1024)
                    print(f"   📄 {exe.name} ({size_mb:.1f} MB)")
    else:
        print("\n❌ 打包失败，未找到输出文件。")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="视频去重工具打包脚本")
    parser.add_argument("--cpu", action="store_true", help="打包 CPU 版（不含 CuPy，体积更小）")
    parser.add_argument("--gpu", action="store_true", help="打包 GPU 版（含 CuPy，默认）")
    parser.add_argument("--onedir", action="store_true", help="使用目录模式打包（非单文件）")
    parser.add_argument("--appname", default="VideoDedupTool", help="输出可执行文件名")
    parser.add_argument("--clean", action="store_true", help="清理构建文件后退出")
    parser.add_argument("--install", action="store_true", help="安装/更新依赖")
    args = parser.parse_args()

    variant = "cpu" if args.cpu else "gpu"

    if args.clean:
        clean_build()
        if not (args.onedir or args.install):
            return

    if args.install:
        install_requirements()

    if not check_pyinstaller():
        print("⚠ PyInstaller 未安装，正在安装...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    build(variant=variant, onedir=args.onedir, appname=args.appname)

    print("\n💡 提示: 生成的产物位于 dist/ 目录下。")
    if sys.platform == "win32":
        print("   首次运行可能需要安装 Visual C++ Redistributable。")


if __name__ == "__main__":
    main()
