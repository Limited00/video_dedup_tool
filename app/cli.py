"""
无头命令行入口 (headless CLI)
-----------------------------
不依赖 PyQt6 的命令行模式，用于 Linux 服务器 / 容器部署。

支持两种运行模式：
1. 批处理（默认）：一次性处理目标目录中的全部视频，导出报告后退出。
2. 监控守护（--watch）：常驻监听目标目录，新视频自动入队处理（轮询方式，
   对容器 bind-mount 比 watchdog 事件更可靠）。

用法:
    python cli.py --reference refs/ --target targets/ --output-dir out/ --format csv,json
    python cli.py --reference refs/ --target targets/ --watch --watch-interval 5
    python main.py --cli --help   # 等价入口

环境变量（便于 docker compose 配置）:
    VIDEO_DEDUP_REFERENCE   素材路径，多个用 os.pathsep 或逗号分隔
    VIDEO_DEDUP_TARGET      目标路径
    VIDEO_DEDUP_OUTPUT_DIR  输出目录
    VIDEO_DEDUP_CONFIG      配置文件（AppConfig 导出的 JSON）路径
    VIDEO_DEDUP_AUTO_CUT    1/true/yes 时启用自动裁切
    VIDEO_DEDUP_FORMAT      报告格式，逗号分隔：csv,json,html,xlsx
"""

import argparse
import json
import logging
import os
import re
import signal
import sys
import threading
import time
from dataclasses import asdict
from typing import List, Optional

from . import __version__
from .config import AppConfig
from .logger import setup_logging, get_logger
from .watcher import is_video_file, FolderWatcher

logger = get_logger("VideoDedup.CLI")

# AppConfig 字段中可直接透传给 VideoProcessor 构造参数的键（命名一一对应）
PROCESSOR_KEYS = [
    "sample_interval", "hash_threshold", "min_match_ratio", "min_match_duration",
    "merge_gap", "hash_algorithm", "auto_cut", "max_workers", "use_gpu",
    "material_position", "position_search_margin", "limit_head_tail", "head_tail_time",
    "enable_frame_filter", "frame_dark_threshold", "frame_bright_threshold",
    "enable_coarse_filter", "coarse_interval", "use_hash_cache",
]

ALLOWED_FORMATS = {"csv", "json", "html", "xlsx"}


def _split_paths(value: str) -> List[str]:
    """把环境变量里的路径串拆成列表（支持 os.pathsep 与逗号）。"""
    parts = re.split(r"[,;]", value)
    # 再按平台 pathsep（Linux 为冒号）二次拆分，但 Windows 盘符 `C:` 需保留
    if os.pathsep not in (",", ";"):
        expanded: List[str] = []
        for p in parts:
            expanded.extend(p.split(os.pathsep))
        parts = expanded
    return [p.strip() for p in parts if p and p.strip()]


def _env_flag(name: str) -> Optional[bool]:
    """读取布尔型环境变量（1/true/yes/on 为 True，0/false/no/off 为 False）。"""
    raw = os.environ.get(name)
    if raw is None:
        return None
    v = raw.strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    return None


def _collect_video_files(paths: List[str]) -> List[str]:
    """把文件/目录列表展开为去重后的视频文件路径列表（目录递归扫描）。"""
    files: List[str] = []
    for p in paths:
        if os.path.isfile(p):
            if is_video_file(p):
                files.append(os.path.abspath(p))
        elif os.path.isdir(p):
            for root, _dirs, fs in os.walk(p):
                for f in fs:
                    fp = os.path.join(root, f)
                    if is_video_file(fp):
                        files.append(os.path.abspath(fp))
    seen = set()
    unique: List[str] = []
    for f in files:
        if f not in seen:
            seen.add(f)
            unique.append(f)
    return unique


def _load_config_file(path: str) -> dict:
    """加载 AppConfig 导出的 JSON，仅保留 AppConfig 已知字段。"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    valid = set(AppConfig.__dataclass_fields__)
    return {k: v for k, v in data.items() if k in valid}


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="videodedup",
        description="视频去重工具 - 无头命令行（Linux/容器部署）",
        add_help=True,
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    # 输入 / 输出
    p.add_argument("--reference", action="append", default=None, metavar="PATH",
                   help="素材视频文件或目录（可重复），目录递归扫描")
    p.add_argument("--target", action="append", default=None, metavar="PATH",
                   help="目标视频文件或目录（可重复），目录递归扫描")
    p.add_argument("--output-dir", default=None, metavar="DIR", help="报告输出目录")
    p.add_argument("--config", default=None, metavar="PATH",
                   help="配置文件（AppConfig 导出的 JSON），CLI 参数覆盖其值")

    # 检测参数（默认值与 AppConfig 对齐）
    p.add_argument("--sample-interval", type=float, default=None,
                   help="采样间隔（秒），默认 1.0")
    p.add_argument("--hash-threshold", type=int, default=None,
                   help="汉明距离阈值（0-64），默认 10")
    p.add_argument("--min-match-ratio", type=float, default=None,
                   help="最小匹配比例（相对素材时长），默认 0.10")
    p.add_argument("--min-match-duration", type=float, default=None,
                   help="最短片段时长（秒），默认 0.5")
    p.add_argument("--merge-gap", type=float, default=None,
                   help="相邻片段合并间隔（秒），默认 1.0")
    p.add_argument("--hash-algorithm", default=None,
                   choices=["dhash", "phash", "ahash", "combined"],
                   help="哈希算法，默认 dhash")
    p.add_argument("--material-position", default=None,
                   choices=["anywhere", "beginning", "end", "both"],
                   help="素材位置，默认 both")
    p.add_argument("--position-search-margin", type=float, default=None,
                   help="搜索边界余量（相对素材时长），默认 0.15")
    p.add_argument("--head-tail-time", type=float, default=None,
                   help="首尾限定时间（秒），默认 60")
    p.add_argument("--frame-dark-threshold", type=float, default=None,
                   help="帧过滤暗阈值（灰度均值），默认 16")
    p.add_argument("--frame-bright-threshold", type=float, default=None,
                   help="帧过滤亮阈值（灰度均值），默认 240")
    p.add_argument("--coarse-interval", type=float, default=None,
                   help="粗筛采样间隔（秒），默认 5.0")
    p.add_argument("--max-workers", type=int, default=None,
                   help="并发处理文件数，默认 4")

    # 布尔开关（默认 None 表示“未指定”，回退到配置/AppConfig 默认值）
    p.add_argument("--use-gpu", dest="use_gpu", action="store_true", default=None)
    p.add_argument("--no-gpu", dest="use_gpu", action="store_false",
                   help="禁用 GPU，强制 CPU")
    p.add_argument("--auto-cut", dest="auto_cut", action="store_true", default=None,
                   help="检测后自动裁切重复片段")
    p.add_argument("--no-auto-cut", dest="auto_cut", action="store_false")
    p.add_argument("--overwrite", action="store_true",
                   help="裁切后覆盖原文件（仅与 --auto-cut 配合）")
    p.add_argument("--limit-head-tail", dest="limit_head_tail", action="store_true",
                   default=None, help="仅识别/裁切首尾指定时间")
    p.add_argument("--no-limit-head-tail", dest="limit_head_tail", action="store_false")
    p.add_argument("--frame-filter", dest="enable_frame_filter", action="store_true",
                   default=None, help="过滤过暗/过亮帧")
    p.add_argument("--no-frame-filter", dest="enable_frame_filter", action="store_false")
    p.add_argument("--coarse-filter", dest="enable_coarse_filter", action="store_true",
                   default=None, help="启用整文件粗筛→精筛")
    p.add_argument("--no-coarse-filter", dest="enable_coarse_filter", action="store_false")
    p.add_argument("--hash-cache", dest="use_hash_cache", action="store_true", default=None)
    p.add_argument("--no-hash-cache", dest="use_hash_cache", action="store_false",
                   help="禁用磁盘哈希缓存")

    # 输出 / 日志
    p.add_argument("--format", default=None, metavar="FMT",
                   help="报告格式，逗号分隔：csv,json,html,xlsx（默认 csv,json）")
    p.add_argument("--report-prefix", default=None, metavar="PREFIX",
                   help="报告文件名前缀（默认带时间戳自动命名）")
    p.add_argument("--verbose", action="store_true", help="输出 DEBUG 级日志")
    p.add_argument("--quiet", action="store_true", help="仅输出 WARNING 及以上日志")

    # 监控守护
    p.add_argument("--watch", action="store_true",
                   help="常驻监控目标目录，新视频自动处理")
    p.add_argument("--watch-interval", type=int, default=None, metavar="SEC",
                   help="监控轮询间隔（秒），默认 5")
    p.add_argument("--no-watch-recursive", dest="watch_recursive", action="store_false",
                   default=True, help="监控时不递归子目录")
    p.add_argument("--skip-existing", action="store_true",
                   help="监控启动时不处理目录中已存在的文件")
    return p


def _resolve_parameters(args: argparse.Namespace) -> dict:
    """合并 配置文件 < 环境变量 < CLI 参数，返回最终配置字典。

    前 20 个键与 AppConfig 字段一致（可透传给 VideoProcessor），其余以 ``_`` 前缀
    为 CLI 专属字段。
    """
    final = asdict(AppConfig())

    # 1) 配置文件
    config_path = args.config or os.environ.get("VIDEO_DEDUP_CONFIG")
    if config_path and os.path.isfile(config_path):
        try:
            final.update(_load_config_file(config_path))
            logger.info(f"已加载配置文件: {config_path}")
        except (OSError, ValueError) as e:
            logger.warning(f"加载配置文件失败，忽略: {e}")

    # 2) 环境变量
    env_auto_cut = _env_flag("VIDEO_DEDUP_AUTO_CUT")
    if env_auto_cut is not None:
        final["auto_cut"] = env_auto_cut

    # 3) CLI 参数（仅覆盖显式给出的）
    for key in PROCESSOR_KEYS:
        val = getattr(args, key)
        if val is not None:
            final[key] = val

    # 4) CLI 专属字段（CLI 优先，回退环境变量）
    final["_reference"] = args.reference or _split_paths(os.environ.get("VIDEO_DEDUP_REFERENCE", ""))
    final["_target"] = args.target or _split_paths(os.environ.get("VIDEO_DEDUP_TARGET", ""))
    final["_output_dir"] = args.output_dir or os.environ.get("VIDEO_DEDUP_OUTPUT_DIR", "")
    final["_format"] = args.format or os.environ.get("VIDEO_DEDUP_FORMAT") or "csv,json"
    final["_overwrite"] = bool(args.overwrite)
    final["_watch_interval"] = args.watch_interval if args.watch_interval is not None else 5
    final["_watch_recursive"] = args.watch_recursive
    final["_skip_existing"] = bool(args.skip_existing)
    final["_report_prefix"] = args.report_prefix
    return final


def _export_reports(batch_report, formats: List[str], output_dir: str, prefix: Optional[str]):
    """按指定格式导出报告。"""
    from .report import ReportExporter
    exporter = ReportExporter(output_dir or os.getcwd())
    for fmt in formats:
        filepath = None
        if prefix:
            filepath = os.path.join(output_dir or ".", f"{prefix}.{fmt}")
        try:
            if fmt == "csv":
                exporter.export_csv(batch_report, filepath)
            elif fmt == "json":
                exporter.export_json(batch_report, filepath)
            elif fmt == "html":
                exporter.export_html(batch_report, filepath)
            elif fmt == "xlsx":
                exporter.export_excel(batch_report, filepath)
        except Exception as e:  # noqa: BLE001 - 单种格式失败不应中断整体
            logger.error(f"导出 {fmt} 报告失败: {e}")


def _make_batch(reports: List, reference_paths: List[str]):
    """把累积的单文件报告包装成 BatchReport（供 ReportExporter 使用）。"""
    from .processor import BatchReport
    return BatchReport(
        reference_path=", ".join(reference_paths),
        total_files=len(reports),
        processed_files=len(reports),
        files_with_matches=sum(1 for r in reports if r.segments_found > 0),
        total_segments=sum(r.segments_found for r in reports),
        total_match_duration=sum(r.total_match_duration for r in reports),
        total_processing_time=sum(r.processing_time for r in reports),
        file_reports=list(reports),
        start_time=0,
        end_time=time.time(),
    )


def _run_batch(processor, reference_paths, target_paths, final: dict) -> int:
    formats = final["_formats"]
    output_dir = final["_output_dir"] or ""
    prefix = final["_report_prefix"]

    batch = processor.process_batch(
        reference_paths,
        target_paths,
        auto_cut=final["auto_cut"],
        overwrite_original=final["_overwrite"],
    )
    _export_reports(batch, formats, output_dir, prefix)

    logger.info(
        f"处理完成: {batch.processed_files}/{batch.total_files} 文件, "
        f"匹配={batch.files_with_matches}, 重复片段={batch.total_segments}, "
        f"耗时={batch.total_processing_time:.1f}s"
    )
    return 0


def _run_watch(processor, reference_paths, target_paths, final: dict) -> int:
    formats = final["_formats"]
    output_dir = final["_output_dir"] or ""
    prefix = final["_report_prefix"]

    watch_dirs = [p for p in target_paths if os.path.isdir(p)]
    if not watch_dirs:
        logger.error("监控模式需要至少一个目标目录（--target 指向目录）")
        return 1

    reports: List = []

    def on_new_file(fp: str):
        logger.info(f"发现新视频，开始处理: {os.path.basename(fp)}")
        rep = processor.process_single(
            reference_paths,
            fp,
            auto_cut=final["auto_cut"],
            overwrite_original=final["_overwrite"],
        )
        reports.append(rep)
        if rep.status == "completed" and rep.segments_found > 0:
            logger.info(f"处理完成: {os.path.basename(fp)} -> {rep.segments_found} 段重复")
        elif rep.status == "no_match":
            logger.info(f"处理完成: {os.path.basename(fp)} -> 未发现重复")
        else:
            logger.warning(f"处理完成: {os.path.basename(fp)} -> {rep.status}: {rep.error_message}")
        _export_reports(_make_batch(reports, reference_paths), formats, output_dir, prefix)

    watcher = FolderWatcher(
        watch_dirs,
        on_new_file=on_new_file,
        interval=final["_watch_interval"],
        recursive=final["_watch_recursive"],
    )

    if not final["_skip_existing"]:
        existing = watcher.initial_scan()
        logger.info(f"初始扫描: {len(existing)} 个已有视频文件")
        for f in existing:
            on_new_file(f)

    stop = threading.Event()

    def _handle_signal(signum, frame):
        logger.info(f"收到信号 {signum}，正在停止...")
        stop.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    logger.info(f"开始监控 {len(watch_dirs)} 个目录（轮询间隔 {final['_watch_interval']}s）")
    while not stop.is_set():
        for f in watcher.scan():
            on_new_file(f)
        stop.wait(final["_watch_interval"])

    logger.info(f"监控结束，共处理 {len(reports)} 个文件")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    final = _resolve_parameters(args)

    # 日志级别
    if args.quiet:
        log_level = logging.WARNING
    elif args.verbose:
        log_level = logging.DEBUG
    else:
        log_level = logging.INFO
    setup_logging(log_level=log_level)

    # 报告格式
    formats = [f.strip().lower() for f in final["_format"].split(",") if f.strip()]
    bad = [f for f in formats if f not in ALLOWED_FORMATS]
    if bad:
        logger.error(f"不支持的报告格式: {', '.join(bad)}，可选: {sorted(ALLOWED_FORMATS)}")
        return 2
    final["_formats"] = formats

    reference_paths = _collect_video_files(final["_reference"])
    target_paths = _collect_video_files(final["_target"])

    if not reference_paths:
        logger.error("未找到素材视频（--reference 或 VIDEO_DEDUP_REFERENCE）")
        return 1
    if not args.watch and not target_paths:
        logger.error("未找到目标视频（--target 或 VIDEO_DEDUP_TARGET）")
        return 1

    logger.info(f"素材: {len(reference_paths)} 个文件")
    logger.info(f"目标: {len(target_paths)} 个文件（或目录）")

    from .processor import VideoProcessor
    kwargs = {k: final[k] for k in PROCESSOR_KEYS}
    kwargs["output_dir"] = final["_output_dir"] or ""
    processor = VideoProcessor(**kwargs)

    if args.watch:
        return _run_watch(processor, reference_paths, target_paths, final)
    return _run_batch(processor, reference_paths, target_paths, final)


if __name__ == "__main__":
    sys.exit(main())
