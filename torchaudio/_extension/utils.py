import os
from pathlib import Path

import torch

import torchaudio
from torchaudio._internal.module_utils import is_module_available

_LIB_DIR = Path(__file__).parent.parent / "lib"


def _get_lib_path(lib: str):
    suffix = "pyd" if os.name == "nt" else "so"
    path = _LIB_DIR / f"{lib}.{suffix}"
    return path


def _load_lib(lib: str) -> bool:
    """Load extension module

    Note:
        In case `torchaudio` is deployed with `pex` format, the library file
        is not in a standard location.
        In this case, we expect that `libtorchaudio` is available somewhere
        in the search path of dynamic loading mechanism, so that importing
        `_torchaudio` will have library loader find and load `libtorchaudio`.
        This is the reason why the function should not raising an error when the library
        file is not found.

    Returns:
        bool:
            True if the library file is found AND the library loaded without failure.
            False if the library file is not found (like in the case where torchaudio
            is deployed with pex format, thus the shared library file is
            in a non-standard location.).
            If the library file is found but there is an issue loading the library,
            (such as missing dependency) then this function raises the exception as-is.

    Raises:
        Exception:
            If the library file is found, but there is an issue loading the library file,
            (when underlying `ctype.DLL` throws an exception), this function will pass
            the exception as-is, instead of catching it and returning bool.
            The expected case is `OSError` thrown by `ctype.DLL` when a dynamic dependency
            is not found.
            This behavior was chosen because the expected failure case is not recoverable.
            If a dependency is missing, then users have to install it.
    """
    path = _get_lib_path(lib)
    if not path.exists():
        return False
    torch.ops.load_library(path)
    torch.classes.load_library(path)
    return True


def _init_sox():
    _load_lib("libtorchaudio_sox")
    import torchaudio.lib._torchaudio_sox  # noqa

    torch.ops.torchaudio.sox_utils_set_verbosity(0)

    import atexit

    torch.ops.torchaudio.sox_effects_initialize_sox_effects()
    atexit.register(torch.ops.torchaudio.sox_effects_shutdown_sox_effects)


def _init_ffmpeg():
    if not is_module_available("torchaudio.lib._torchaudio_ffmpeg"):
        raise RuntimeError(
            "torchaudio is not compiled with FFmpeg integration. Please set USE_FFMPEG=1 when compiling torchaudio."
        )

    try:
        _load_lib("libtorchaudio_ffmpeg")
    except OSError as err:
        raise ImportError("FFmpeg libraries are not found. Please install FFmpeg.") from err

    import torchaudio.lib._torchaudio_ffmpeg  # noqa

    torch.ops.torchaudio.ffmpeg_init()
    if torch.ops.torchaudio.ffmpeg_get_log_level() > 8:
        torch.ops.torchaudio.ffmpeg_set_log_level(8)


def _init_dll_path():
    # On Windows Python-3.8+ has `os.add_dll_directory` call,
    # which is called to configure dll search path.
    # To find cuda related dlls we need to make sure the
    # conda environment/bin path is configured Please take a look:
    # https://stackoverflow.com/questions/59330863/cant-import-dll-module-in-python
    # Please note: if some path can't be added using add_dll_directory we simply ignore this path
    for path in os.environ.get("PATH", "").split(";"):
        if os.path.exists(path):
            try:
                os.add_dll_directory(path)
            except Exception:
                pass


def _check_cuda_version():
    version = torchaudio.lib._torchaudio.cuda_version()
    if version is not None and torch.version.cuda is not None:
        version_str = str(version)
        ta_version = f"{version_str[:-3]}.{version_str[-2]}"
        t_version = torch.version.cuda.split(".")
        t_version = f"{t_version[0]}.{t_version[1]}"
        if ta_version != t_version:
            raise RuntimeError(
                "Detected that PyTorch and TorchAudio were compiled with different CUDA versions. "
                f"PyTorch has CUDA version {t_version} whereas TorchAudio has CUDA version {ta_version}. "
                "Please install the TorchAudio version that matches your PyTorch version."
            )
    return version