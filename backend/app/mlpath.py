"""Import ml/kd_pipeline.py unchanged. kd_model.py is imported later (lazily, it needs torch) from the
model bundle folder first, because the bundle's copy is the one the weights were trained with."""
import os
import sys
import tempfile as _tempfile
import types
from contextlib import contextmanager

from .config import ML_DIR

if str(ML_DIR) not in sys.path:
    sys.path.append(str(ML_DIR))

import kd_pipeline as kp  # noqa: E402


if os.name == "nt":
    # kd_pipeline.SarvamASR writes each chunk to tempfile.NamedTemporaryFile() and then reopens it by name. Windows
    # refuses to reopen a file that is still open, so Sarvam speech-to-text failed on Windows workers. Instead of
    # editing the tested pipeline, give it a tempfile module whose NamedTemporaryFile is closed before use and
    # removed afterwards. Linux (HF Space, Kaggle) keeps the standard module.
    class _Named:
        def __init__(self, name):
            self.name = name

    @contextmanager
    def _named_temporary_file(suffix="", prefix="tmp", dir=None, **_):
        fd, name = _tempfile.mkstemp(suffix=suffix, prefix=prefix, dir=dir)
        os.close(fd)
        try:
            yield _Named(name)
        finally:
            try:
                os.remove(name)
            except OSError:
                pass            # still held open by the HTTP upload; Windows cleans %TEMP% later

    _shim = types.ModuleType("tempfile")
    _shim.__dict__.update({k: getattr(_tempfile, k) for k in dir(_tempfile) if not k.startswith("__")})
    _shim.NamedTemporaryFile = _named_temporary_file
    kp.tempfile = _shim

__all__ = ["kp"]
