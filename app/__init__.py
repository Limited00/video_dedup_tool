"""视频去重工具 - Video Deduplication Tool"""

import subprocess
import sys

__version__ = "1.0.0"
__author__ = "Video Dedup Tool"


def subprocess_no_window_kwargs() -> dict:
    """返回用于抑制子进程弹出控制台窗口的 kwargs。

    应用以 PyInstaller ``--noconsole``（GUI 子系统）打包，父进程没有控制台；
    此时直接拉起 ffmpeg/ffprobe/nvidia-smi 等控制台程序会让 Windows 为每个
    子进程新开一个控制台窗口，批量裁切时会弹出成百上千个窗口导致系统卡死。
    加入 ``CREATE_NO_WINDOW`` 后子进程在无窗口状态下运行，stdout/stderr 管道
    仍正常可用。非 Windows 平台返回空字典。
    """
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}
