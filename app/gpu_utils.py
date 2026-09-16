"""
GPU 加速工具模块
----------------
检测本地 GPU、提供 CUDA/CuPy 加速的帧处理操作。
支持 NVIDIA GPU (CUDA) 加速，自动回退 CPU。
"""

import os
import sys
import logging
import threading
from typing import Optional, Tuple
from dataclasses import dataclass

from . import subprocess_no_window_kwargs

logger = logging.getLogger("VideoDedup.GPU")

# 全局锁：保护 CuPy 导入和 GPU 初始化（避免多线程竞态）
_gpu_init_lock = threading.Lock()
_gpu_backend_initialized = False
_gpu_xp_module = None  # 缓存的 numpy/cupy 模块

# 是否已将内置 CUDA DLL 目录加入搜索路径
_cuda_dll_path_added = False
# 保持 os.add_dll_directory() 返回的 cookie 存活——否则会被立即垃圾回收，
# 目录随即从 DLL 搜索路径中被移除（导致加进去等于没加）。
_dll_directory_cookies = []

# 是否已把 cupy 自带头文件重定位到 ASCII 目录
_cupy_headers_patched = False
# 缓存的 ASCII 工作目录
_ascii_workdir = None


def _is_ascii(s):
    """判断字符串是否仅含 ASCII 字符。"""
    try:
        s.encode('ascii')
        return True
    except (UnicodeEncodeError, AttributeError):
        return False


def _get_ascii_workdir():
    """返回一个仅含 ASCII 字符的可写目录，用于重定位 CUDA 头文件。

    NVRTC（nvrtcCompileProgram）在 Windows 上无法处理 ``-I`` 包含路径里的非 ASCII
    字符（例如中文安装目录名），会报 ``NVRTC_ERROR_COMPILATION``。源码运行时
    site-packages 路径通常是 ASCII 的，因此只有「打包 + 安装路径含非 ASCII 字符」
    时才需要把头文件重定位到此处。
    """
    global _ascii_workdir
    if _ascii_workdir is not None:
        return _ascii_workdir

    candidates = [
        os.environ.get('TEMP'),
        os.environ.get('TMP'),
        os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Temp'),
        r'C:\Windows\Temp',
    ]
    for cand in candidates:
        if cand and _is_ascii(cand) and os.path.isdir(cand):
            workdir = os.path.join(cand, 'VideoDedupTool_cuda')
            try:
                os.makedirs(workdir, exist_ok=True)
                _ascii_workdir = workdir
                return workdir
            except OSError:
                continue
    import tempfile
    workdir = os.path.join(tempfile.gettempdir(), 'VideoDedupTool_cuda')
    os.makedirs(workdir, exist_ok=True)
    _ascii_workdir = workdir
    return workdir


def _ensure_cuda_dll_path():
    """为打包后的应用提供 CUDA 运行时环境（DLL + 头文件 + CUDA_PATH）。

    PyInstaller 打包后，nvidia 包被收集到 ``_MEIPASS/nvidia/<pkg>/`` 子目录，
    而 cupy 通过 ``cuda-pathfinder`` 定位 DLL 和头文件。pathfinder 在打包环境里：
    1. 无法通过 site-packages / 系统路径找到这些文件；
    2. 最终会退回到「canary 探针」——用 ``sys.executable -m ...`` 拉起子进程，
       而打包后的 ``sys.executable`` 是 EXE 本身，无法当作 Python 解释器运行，
       子进程挂死 10 秒后超时，导致 GPU 初始化失败回退 CPU。

    这里把 ``nvidia/*/bin`` 和 ``nvidia/*/include`` 汇总成一个合成的 CUDA 工具
    包根目录，并设置 ``CUDA_PATH``，让 pathfinder 走 env-var 分支命中，从而绕开
    canary 子进程。
    """
    global _cuda_dll_path_added
    if _cuda_dll_path_added:
        return
    _cuda_dll_path_added = True

    # 仅在打包（frozen）环境下生效；源码运行时由 pip 安装的 nvidia 包自行提供。
    if not getattr(sys, 'frozen', False):
        return

    try:
        import glob
        import shutil

        base = getattr(sys, '_MEIPASS', None) or os.path.dirname(sys.executable)

        # 1) 把每个 nvidia 包的 bin 目录加入 DLL 搜索路径
        bin_dirs = sorted(glob.glob(os.path.join(base, 'nvidia', '*', 'bin')))
        for dll_dir in bin_dirs:
            try:
                _dll_directory_cookies.append(os.add_dll_directory(dll_dir))
            except OSError:
                pass

        # NVRTC 无法处理非 ASCII 路径；若安装路径含中文等字符，把合成 CUDA 工具包
        # 根目录放到 ASCII 临时目录，否则内核编译会失败。
        synth_parent = base if _is_ascii(base) else _get_ascii_workdir()

        # 2) 汇总出合成 CUDA 工具包根目录：include/ + bin/
        synth_root = os.path.join(synth_parent, '_cuda_kit')
        synth_include = os.path.join(synth_root, 'include')
        synth_bin = os.path.join(synth_root, 'bin')
        os.makedirs(synth_include, exist_ok=True)
        os.makedirs(synth_bin, exist_ok=True)

        # 汇总头文件（cuda_runtime.h / nvrtc.h / nvJitLink.h 等）
        for inc_dir in sorted(glob.glob(os.path.join(base, 'nvidia', '*', 'include'))):
            for entry in os.listdir(inc_dir):
                src = os.path.join(inc_dir, entry)
                dst = os.path.join(synth_include, entry)
                if os.path.isdir(src):
                    if not os.path.exists(dst):
                        shutil.copytree(src, dst)
                else:
                    if not os.path.exists(dst):
                        shutil.copy2(src, dst)

        # 汇总 DLL（cudart/nvrtc/nvjitlink 等）
        for dll in sorted(glob.glob(os.path.join(base, 'nvidia', '*', 'bin', '*.dll'))):
            dst = os.path.join(synth_bin, os.path.basename(dll))
            if not os.path.exists(dst):
                shutil.copy2(dll, dst)

        # 3) 设置 CUDA_PATH / CUDA_HOME，让 cuda-pathfinder 命中 env-var 分支
        os.environ['CUDA_PATH'] = synth_root
        os.environ.setdefault('CUDA_HOME', synth_root)
        try:
            _dll_directory_cookies.append(os.add_dll_directory(synth_bin))
        except OSError:
            pass
        logger.info(f"已配置合成 CUDA 工具包路径: {synth_root}")
    except Exception as e:  # noqa: BLE001 - 失败不应影响主流程
        logger.debug(f"配置合成 CUDA 工具包路径失败: {e}")


def _patch_cupy_headers():
    """把 cupy 自带头文件重定位到 ASCII 目录并改写其 include-dir 访问函数。

    cupy 14 在 import 时根据 .pyd 自身 ``__file__`` 计算头文件目录并缓存。打包后
    该目录落在非 ASCII 的安装路径下，NVRTC 无法通过 ``-I`` 打开其中的 .cuh 头文件
    （报 ``cannot open source file "cupy/complex.cuh"``）。这里把 ``cupy/_core/include``
    复制到 ASCII 临时目录，并 monkey-patch
    ``cupy._core.core._get_header_dir_path`` / ``_get_cccl_include_options``。
    """
    global _cupy_headers_patched
    if _cupy_headers_patched:
        return
    _cupy_headers_patched = True

    if not getattr(sys, 'frozen', False):
        return

    try:
        import shutil
        import cupy._core.core as _core
        import cupy.cuda.compiler as _compiler

        src = _core._get_header_dir_path()
        if src is None or _is_ascii(src):
            return

        workdir = _get_ascii_workdir()
        dst = os.path.join(workdir, 'cupy_include')
        if not os.path.isdir(dst):
            shutil.copytree(src, dst)

        try:
            _core._get_header_dir_path = lambda: dst
        except Exception:
            pass

        try:
            orig_cccl = tuple(_core._get_cccl_include_options())
            new_cccl = tuple(o.replace(src, dst) for o in orig_cccl)
            _core._get_cccl_include_options = lambda: new_cccl
        except Exception:
            pass

        # 关键：cupy._core.core.assemble_cupy_compiler_options 是 Cython 编译的
        # cdef 函数，内部直接 C 调用 _get_header_dir_path，上面的 monkey-patch
        # 对它无效。因此必须在最终调用 nvrtc 前拦截并改写 -I 选项里的非 ASCII 路径。
        _orig_nvrtc_compile = _compiler._NVRTCProgram.compile

        def _patched_compile(self, options=(), log_stream=None):
            new_options = tuple(o.replace(src, dst) for o in options)
            return _orig_nvrtc_compile(self, new_options, log_stream)

        _compiler._NVRTCProgram.compile = _patched_compile

        logger.info(f"已将 cupy 头文件重定位到 ASCII 目录: {dst}")
    except Exception as e:  # noqa: BLE001 - 失败不应影响主流程
        logger.debug(f"重定位 cupy 头文件失败: {e}")


@dataclass
class GPUInfo:
    """GPU 信息"""
    available: bool = False
    name: str = ""
    memory_mb: int = 0
    driver_version: str = ""
    cuda_available: bool = False
    cupy_available: bool = False
    ffmpeg_nvenc: bool = False
    opencv_cuda: bool = False


# 全局 GPU 信息缓存
_gpu_info: Optional[GPUInfo] = None


def detect_gpu() -> GPUInfo:
    """检测系统 GPU 和加速能力"""
    global _gpu_info
    if _gpu_info is not None:
        return _gpu_info

    info = GPUInfo()

    # 1. 检测 NVIDIA GPU (via nvidia-smi)
    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version",
             "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10,
            **subprocess_no_window_kwargs(),
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split(", ")
            if len(parts) >= 2:
                info.available = True
                info.name = parts[0]
                info.memory_mb = int(parts[1].replace(" MiB", ""))
                info.driver_version = parts[2] if len(parts) > 2 else ""
                logger.info(f"GPU 检测: {info.name} ({info.memory_mb}MB)")
    except Exception as e:
        logger.debug(f"nvidia-smi 检测失败: {e}")

    # 2. 检测 OpenCV CUDA
    try:
        import cv2
        if hasattr(cv2, 'cuda'):
            count = cv2.cuda.getCudaEnabledDeviceCount()
            info.opencv_cuda = count > 0
    except Exception:
        pass

    # 3. 检测 CuPy
    try:
        _ensure_cuda_dll_path()
        import warnings
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=".*CUDA path.*")
            warnings.filterwarnings("ignore", category=UserWarning)
            import cupy
        _patch_cupy_headers()
        info.cupy_available = True
        info.cuda_available = True
        logger.info("CuPy 可用 - GPU 加速已启用")
    except ImportError as e:
        logger.info(f"CuPy 未安装，使用 CPU 模式（{e}）")
    except Exception as e:  # noqa: BLE001 - 记录真实失败原因
        logger.info(f"CuPy 加载失败，使用 CPU 模式（{type(e).__name__}: {e}）")

    # 4. 检测 FFmpeg NVENC
    try:
        import subprocess
        result = subprocess.run(
            ["ffmpeg", "-encoders"], capture_output=True, text=True, timeout=10,
            **subprocess_no_window_kwargs(),
        )
        if "h264_nvenc" in result.stdout or "hevc_nvenc" in result.stdout:
            info.ffmpeg_nvenc = True
            logger.info("FFmpeg NVENC 编码器可用")
    except Exception:
        pass

    _gpu_info = info
    return info


def get_gpu_info() -> GPUInfo:
    """获取 GPU 信息（缓存版本，线程安全）。

    首次调用时通过锁保证 detect_gpu() 只执行一次，避免多个工作线程并发触发
    nvidia-smi / cupy 导入 / 头文件复制等副作用。
    """
    global _gpu_info
    if _gpu_info is None:
        with _gpu_init_lock:
            if _gpu_info is None:
                _gpu_info = detect_gpu()
    return _gpu_info


def try_install_cupy():
    """尝试自动安装 CuPy"""
    try:
        import subprocess
        logger.info("正在安装 CuPy (GPU 加速库)...")
        # 检测 CUDA 版本
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=cuda_version", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10,
            **subprocess_no_window_kwargs(),
        )
        cuda_ver = result.stdout.strip().replace("CUDA Version: ", "")
        # 选择对应的 cupy 包
        if cuda_ver.startswith("12"):
            pkg = "cupy-cuda12x"
        elif cuda_ver.startswith("11"):
            pkg = "cupy-cuda11x"
        else:
            pkg = "cupy"

        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", pkg, "-q"],
            timeout=120,
            **subprocess_no_window_kwargs(),
        )
        logger.info(f"CuPy ({pkg}) 安装完成")
        return True
    except Exception as e:
        logger.warning(f"CuPy 自动安装失败: {e}，将使用 CPU 模式")
        return False


# ---- GPU 加速的帧操作 ----

class GPUFrameProcessor:
    """GPU 加速的帧处理器（CuPy 后端，自动回退 CPU）"""

    def __init__(self, use_gpu: bool = True):
        self.use_gpu = use_gpu
        self._xp = None  # numpy or cupy
        self._gpu_enabled = False
        self._init_backend()

    def _init_backend(self):
        """初始化计算后端（线程安全）"""
        global _gpu_backend_initialized, _gpu_xp_module

        if not self.use_gpu:
            import numpy as np
            self._xp = np
            self._gpu_enabled = False
            return

        # 如果全局已初始化，直接复用
        if _gpu_backend_initialized:
            self._xp = _gpu_xp_module
            self._gpu_enabled = (_gpu_xp_module is not None and
                                 hasattr(_gpu_xp_module, 'cuda'))
            return

        # 加锁初始化，避免多线程竞态
        with _gpu_init_lock:
            if _gpu_backend_initialized:
                self._xp = _gpu_xp_module
                self._gpu_enabled = (_gpu_xp_module is not None and
                                     hasattr(_gpu_xp_module, 'cuda'))
                return

            try:
                _ensure_cuda_dll_path()
                import warnings
                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore", message=".*CUDA path.*")
                    import cupy as cp
                _patch_cupy_headers()
                # 真正测试 GPU 计算（不仅仅是 import）—— 有些环境 CuPy 能 import
                # 但缺少 CUDA toolkit headers，实际计算时会失败
                try:
                    _test = cp.array([1, 2, 3]) + cp.array([4, 5, 6])
                    _ = cp.asnumpy(_test)
                except Exception as compute_err:
                    import numpy as np
                    _gpu_xp_module = np
                    self._xp = np
                    self._gpu_enabled = False
                    logger.warning(
                        f"GPU 帧处理器: CuPy 已安装但 GPU 计算失败，回退 CPU。"
                        f"原因: {compute_err}。"
                        f"请尝试: pip install cupy-cuda12x[ctk]"
                    )
                    _gpu_backend_initialized = True
                    return

                _gpu_xp_module = cp
                self._xp = cp
                self._gpu_enabled = True
                # 尝试获取 GPU 设备详情
                try:
                    props = cp.cuda.runtime.getDeviceProperties(0)
                    gpu_name = props['name'].decode() if isinstance(props.get('name'), bytes) else props.get('name', 'GPU')
                    free_mem, total_mem = cp.cuda.runtime.memGetInfo()
                    logger.info(
                        f"GPU 帧处理器: CuPy 后端已启用 "
                        f"(设备: {gpu_name}, "
                        f"显存: {free_mem // (1024**2)}MB / {total_mem // (1024**2)}MB)"
                    )
                except Exception:
                    logger.info("GPU 帧处理器: CuPy 后端已启用 (GPU 计算验证通过)")
            except ImportError:
                import numpy as np
                _gpu_xp_module = np
                self._xp = np
                self._gpu_enabled = False
                logger.info("GPU 帧处理器: CuPy 不可用，回退 CPU")
            finally:
                _gpu_backend_initialized = True

    @property
    def gpu_enabled(self) -> bool:
        return self._gpu_enabled

    def resize_gray(self, frame, target_size: Tuple[int, int]):
        """
        图像缩放 + 灰度化。
        输入 BGR numpy 数组，输出指定尺寸的灰度 numpy 数组。

        统一走 cv2（BGR2GRAY + INTER_AREA），保证与 CPU 路径哈希结果完全一致。
        之前的 GPU 最近邻采样 + 浮点灰度化与 cv2 的 INTER_AREA + 整数取整结果不同，
        会导致 dHash 值与 CPU 路径对不上（参考库走 CPU、目标视频走 GPU 时检测失效）。
        """
        import cv2
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return cv2.resize(gray, target_size, interpolation=cv2.INTER_AREA)

    def batch_resize_gray(self, frames, target_size: Tuple[int, int]):
        """
        批量缩放 + 灰度化。
        输入帧列表 [(frame, timestamp, index), ...]
        输出 [(gray_array, timestamp, index), ...]

        为保证与单帧路径哈希一致，这里用 cv2 逐帧处理（与 resize_gray 完全一致）。
        """
        import cv2

        if not frames:
            return []

        results = []
        for frame, ts, idx in frames:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            resized = cv2.resize(gray, target_size, interpolation=cv2.INTER_AREA)
            results.append((resized, ts, idx))
        return results

    def batch_compute_dhash(self, gray_frames, hash_size: int = 8):
        """
        批量计算 dHash（numpy 向量化位打包）。
        输入: [(gray_array_(size)x(size+1), ts, idx), ...]
        输出: [(dhash_int, ts, idx), ...]
        """
        import numpy as np

        if not gray_frames:
            return []

        n = len(gray_frames)
        nbits = hash_size * hash_size
        # 批量差分：相邻列比较，得到 nbits 位
        batch = np.array([g for g, _, _ in gray_frames])  # (n, size, size+1)
        diff = batch[:, :, 1:] > batch[:, :, :-1]          # (n, size, size) -> nbits
        flat = diff.reshape(n, -1)                          # (n, nbits)
        # 位打包：flat[0] 是最高位。dHash 是 64 位，最高位 1<<63 超出有符号 int64
        # 范围，必须用 uint64。
        multipliers = np.array(
            [1 << (nbits - 1 - i) for i in range(nbits)], dtype=np.uint64
        )
        hashes = (flat.astype(np.uint64) * multipliers).sum(axis=1)
        return [(int(hashes[i]), gray_frames[i][1], gray_frames[i][2]) for i in range(n)]


# ---- FFmpeg GPU 编码 ----

def get_ffmpeg_gpu_encoder() -> Optional[str]:
    """获取可用的 FFmpeg GPU 编码器"""
    info = get_gpu_info()
    if not info.ffmpeg_nvenc:
        return None
    # RTX 5060 Ti 支持 h264_nvenc 和 hevc_nvenc
    return "h264_nvenc"


def build_ffmpeg_gpu_encode_cmd(input_path: str, output_path: str,
                                 start_time: float, duration: float) -> list:
    """
    构建使用 GPU 硬件编码的 FFmpeg 命令。
    使用 NVENC 进行硬件加速编码。
    """
    encoder = get_ffmpeg_gpu_encoder()
    if encoder:
        return [
            "ffmpeg", "-y",
            "-hwaccel", "cuda", "-hwaccel_output_format", "cuda",
            "-ss", str(start_time), "-t", str(duration),
            "-i", input_path,
            "-c:v", encoder, "-preset", "p4",
            "-b:v", "5M", "-maxrate", "10M", "-bufsize", "10M",
            "-c:a", "aac", "-b:a", "128k",
            output_path
        ]
    else:
        # CPU 回退
        return [
            "ffmpeg", "-y",
            "-ss", str(start_time), "-t", str(duration),
            "-i", input_path,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            output_path
        ]
