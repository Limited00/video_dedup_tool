"""
打包构建脚本
============
使用 PyInstaller 将应用打包为独立 EXE 文件。

用法:
    python build.py              # 打包为单文件 EXE
    python build.py --onedir     # 打包为目录模式（启动更快）
    python build.py --clean      # 清理后重新打包
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path


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


def build_exe(onedir=False):
    """执行 PyInstaller 打包"""
    root = Path(__file__).parent

    # 基础参数
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "VideoDedupTool",
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
        print("📦 打包模式: 单文件 EXE")

    # Windows 特定选项
    # 注意：不使用 --uac-admin。本工具仅读写用户视频目录，无需管理员权限；
    # 且管理员权限会让打包产物以提权运行，导致文件被锁定、无法正常结束进程。

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

    # CuPy GPU 加速依赖：
    # 1) cupy 通过 Cython 动态导入一些子模块（如 cupy_backends.cuda._softlink），
    #    以及 NVRTC JIT 编译所需的头文件数据，PyInstaller 静态分析无法发现，
    #    需要 --collect-all 完整收集。
    # 2) nvidia.* 的 hook 用于收集 CUDA 运行时 DLL（nvrtc/nvjitlink 等）。
    cmd.extend([
        "--collect-all", "cupy",
        "--collect-all", "cupy_backends",
        "--hidden-import", "nvidia.cuda_runtime",
        "--hidden-import", "nvidia.cuda_nvrtc",
        "--hidden-import", "nvidia.nvjitlink",
        # nvidia 包的 include/*.h 头文件属于 data，需额外收集（cupy 的 NVRTC 编译要用）
        "--collect-data", "nvidia.cuda_runtime",
        "--collect-data", "nvidia.cuda_nvrtc",
        "--collect-data", "nvidia.nvjitlink",
    ])

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

    # 入口文件
    cmd.append(str(root / "main.py"))

    print(f"🔨 执行: {' '.join(cmd)}")
    subprocess.check_call(cmd)

    # 输出结果
    dist_dir = root / "dist"
    if dist_dir.exists():
        print(f"\n✅ 打包完成! 输出目录: {dist_dir}")
        for exe in dist_dir.rglob("*.exe"):
            size_mb = exe.stat().st_size / (1024 * 1024)
            print(f"   📁 {exe.name} ({size_mb:.1f} MB)")
    else:
        print("\n❌ 打包失败，未找到输出文件。")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="视频去重工具打包脚本")
    parser.add_argument("--onedir", action="store_true", help="使用目录模式打包（非单文件）")
    parser.add_argument("--clean", action="store_true", help="清理构建文件后退出")
    parser.add_argument("--install", action="store_true", help="安装/更新依赖")
    args = parser.parse_args()

    if args.clean:
        clean_build()
        if not (args.onedir or args.install):
            return

    if args.install:
        install_requirements()

    if not check_pyinstaller():
        print("⚠ PyInstaller 未安装，正在安装...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    build_exe(onedir=args.onedir)

    print("\n💡 提示: 生成的 EXE 位于 dist/ 目录下。")
    print("   首次运行可能需要安装 Visual C++ Redistributable。")


if __name__ == "__main__":
    main()
