import sys
sys.path.insert(0, '.')
import os
import traceback
from app.gpu_utils import _ensure_cuda_dll_path, _patch_cupy_headers

_ensure_cuda_dll_path()

try:
    import cupy
    import cupy._core.core as _core
    _patch_cupy_headers()
    print("cupy.__file__ =", cupy.__file__ if hasattr(cupy, '__file__') else None)
    print("core.__file__ =", getattr(_core, '__file__', None))
    hdr = _core._get_header_dir_path()
    print("_get_header_dir_path() =", hdr)
    print("  hdr exists:", os.path.isdir(hdr))
    print("  cupy/complex.cuh exists:", os.path.isfile(os.path.join(hdr, 'cupy', 'complex.cuh')))
    try:
        print("_get_cccl_include_options() =", _core._get_cccl_include_options())
    except Exception as e:
        print("_get_cccl_include_options error:", type(e).__name__, e)

    x = cupy.array([1, 2, 3]) + cupy.array([4, 5, 6])
    y = cupy.asnumpy(x)
    print("GPU compute OK:", y)
    print("PROBE_PASS")
except Exception as e:
    print("GPU compute FAILED:", type(e).__name__, e)
    traceback.print_exc()
    print("PROBE_FAIL")
