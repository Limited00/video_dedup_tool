"""
CLI 无头模式冒烟测试
--------------------
验证 app.cli 可在不导入 PyQt6 的前提下加载，并覆盖路径收集、环境变量拆分、
参数合并等纯函数逻辑。无需真实视频文件。
"""

import os
import sys
import tempfile
import unittest


class TestHeadlessImport(unittest.TestCase):
    def test_no_pyqt6_import(self):
        """app.cli 及其核心依赖不得拉入 PyQt6（容器/无头环境没有 Qt）。"""
        import app.cli  # noqa: F401
        self.assertNotIn("PyQt6", sys.modules)
        self.assertNotIn("PyQt6.QtWidgets", sys.modules)


class TestPathHelpers(unittest.TestCase):
    def test_collect_video_files(self):
        from app.cli import _collect_video_files
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "sub"), exist_ok=True)
            v1 = os.path.join(d, "a.mp4")
            v2 = os.path.join(d, "sub", "b.mkv")
            txt = os.path.join(d, "note.txt")
            for p in (v1, v2, txt):
                with open(p, "w"):
                    pass
            # v1 同时通过目录扫描与直接传入，应去重
            files = _collect_video_files([d, v1])
            names = {os.path.basename(f) for f in files}
            self.assertEqual(names, {"a.mp4", "b.mkv"})
            self.assertEqual(len(files), 2)

    def test_split_paths(self):
        from app.cli import _split_paths
        self.assertEqual(set(_split_paths("/a,/b;/c")), {"/a", "/b", "/c"})
        self.assertEqual(_split_paths("  "), [])


class TestResolveParameters(unittest.TestCase):
    def test_overrides_defaults(self):
        from app.cli import _build_parser, _resolve_parameters
        args = _build_parser().parse_args(["--hash-threshold", "20", "--no-gpu"])
        final = _resolve_parameters(args)
        # 显式参数覆盖
        self.assertEqual(final["hash_threshold"], 20)
        self.assertFalse(final["use_gpu"])
        # 未指定的保持 AppConfig 默认值
        self.assertEqual(final["sample_interval"], 1.0)
        self.assertEqual(final["material_position"], "both")
        self.assertEqual(final["_format"], "csv,json")
        self.assertEqual(final["_overwrite"], False)

    def test_config_file_seeds_defaults(self):
        from app.cli import _build_parser, _resolve_parameters
        import json
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8") as f:
            json.dump({"hash_threshold": 30, "sample_interval": 0.5}, f)
            cfg = f.name
        try:
            args = _build_parser().parse_args(["--config", cfg])
            final = _resolve_parameters(args)
            self.assertEqual(final["hash_threshold"], 30)
            self.assertEqual(final["sample_interval"], 0.5)
            # 未在配置中的字段仍取默认值
            self.assertEqual(final["merge_gap"], 1.0)
        finally:
            os.unlink(cfg)


if __name__ == "__main__":
    unittest.main()
