"""Windows GDI+ rasterization without extra packages or a process per image."""

import ctypes
import os
from pathlib import Path
import tempfile
import threading

_runtime = None
_startup_lock = threading.Lock()


class _Rect(ctypes.Structure):
    _fields_ = [(name, ctypes.c_int) for name in ("x", "y", "width", "height")]


class _BitmapData(ctypes.Structure):
    _fields_ = [("width", ctypes.c_uint32), ("height", ctypes.c_uint32),
                ("stride", ctypes.c_int), ("format", ctypes.c_int),
                ("scan0", ctypes.c_void_p), ("reserved", ctypes.c_void_p)]


def _check(status):
    if status:
        raise OSError(f"GDI+ status {status}")


def _gdiplus():
    global _runtime
    with _startup_lock:
        if _runtime is not None:
            return _runtime
        class Startup(ctypes.Structure):
            _fields_ = [("version", ctypes.c_uint32), ("callback", ctypes.c_void_p),
                        ("background", ctypes.c_int), ("codecs", ctypes.c_int)]
        api = ctypes.WinDLL("gdiplus")
        pointer = ctypes.c_void_p
        signatures = {
            "GdiplusStartup": [ctypes.POINTER(pointer), ctypes.POINTER(Startup), pointer],
            "GdipLoadImageFromFile": [ctypes.c_wchar_p, ctypes.POINTER(pointer)],
            "GdipGetMetafileHeaderFromFile": [ctypes.c_wchar_p, pointer],
            "GdipCreateBitmapFromScan0": [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, pointer, ctypes.POINTER(pointer)],
            "GdipGetImageGraphicsContext": [pointer, ctypes.POINTER(pointer)],
            "GdipGraphicsClear": [pointer, ctypes.c_uint32],
            "GdipSetSmoothingMode": [pointer, ctypes.c_int],
            "GdipSetInterpolationMode": [pointer, ctypes.c_int],
            "GdipDrawImageRectI": [pointer, pointer, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int],
            "GdipSaveImageToFile": [pointer, ctypes.c_wchar_p, pointer, pointer],
            "GdipBitmapLockBits": [pointer, ctypes.POINTER(_Rect), ctypes.c_uint32, ctypes.c_int, ctypes.POINTER(_BitmapData)],
            "GdipBitmapUnlockBits": [pointer, ctypes.POINTER(_BitmapData)],
            "GdipDeleteGraphics": [pointer], "GdipDisposeImage": [pointer],
        }
        for name, args in signatures.items():
            getattr(api, name).argtypes = args
            getattr(api, name).restype = ctypes.c_int
        token = pointer()
        _check(api.GdiplusStartup(ctypes.byref(token), ctypes.byref(Startup(1, None, 0, 0)), None))
        _runtime = (api, token)
        return _runtime


def _rasterize(data, ext):
    import struct
    import uuid
    api, _ = _gdiplus()
    image, bitmap, graphics = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
    with tempfile.TemporaryDirectory(prefix="docx-ocr-") as directory:
        source, target = Path(directory) / f"formula.{ext}", Path(directory) / "formula.png"
        source.write_bytes(data)
        try:
            header = ctypes.create_string_buffer(256)
            _check(api.GdipGetMetafileHeaderFromFile(str(source), header))
            dpi_x, dpi_y = struct.unpack_from("ff", header, 16)
            width, height = struct.unpack_from("ii", header, 32)
            dpi = max(96, min(600, int(os.getenv("DOCX_EXTRACT_OCR_RASTER_DPI", "300"))))
            width = max(8, round(width / max(dpi_x, 1) * dpi))
            height = max(8, round(height / max(dpi_y, 1) * dpi))
            scale = min(1, 2400 / max(width, height))
            width, height = max(8, round(width * scale)), max(8, round(height * scale))
            _check(api.GdipLoadImageFromFile(str(source), ctypes.byref(image)))
            _check(api.GdipCreateBitmapFromScan0(width, height, 0, 0x26200A, None, ctypes.byref(bitmap)))
            _check(api.GdipGetImageGraphicsContext(bitmap, ctypes.byref(graphics)))
            _check(api.GdipGraphicsClear(graphics, 0xFFFFFFFF))
            _check(api.GdipSetSmoothingMode(graphics, 2))
            _check(api.GdipSetInterpolationMode(graphics, 7))
            _check(api.GdipDrawImageRectI(graphics, image, 0, 0, width, height))
            pixels = _BitmapData()
            _check(api.GdipBitmapLockBits(bitmap, ctypes.byref(_Rect(0, 0, width, height)), 1, 0x26200A, ctypes.byref(pixels)))
            try:
                first = pixels.scan0 + min(0, (height-1) * pixels.stride)
                raw = ctypes.string_at(first, abs(pixels.stride)*height)
                ink = raw.translate(bytes(1 if value < 250 else 0 for value in range(256))).strip(b"\0")
                if not ink:
                    raise ValueError("blank GDI+ render; preserve original vector")
            finally:
                api.GdipBitmapUnlockBits(bitmap, ctypes.byref(pixels))
            encoder = ctypes.create_string_buffer(uuid.UUID("557cf406-1a04-11d3-9a73-0000f81ef32e").bytes_le)
            _check(api.GdipSaveImageToFile(bitmap, str(target), encoder, None))
            return target.read_bytes()
        finally:
            if graphics.value:
                api.GdipDeleteGraphics(graphics)
            for handle in (bitmap, image):
                if handle.value:
                    api.GdipDisposeImage(handle)


def prepare_image(data: bytes, ext: str) -> tuple[bytes, str]:
    if ext.lower() == 'wmf':
        from .vector_fonts import prepare_wmf
        try:
            repaired, kind = prepare_wmf(data)
        except (ValueError, ImportError, OSError):
            return data, ext
        if kind == 'png':
            return repaired, kind
        data = repaired
    if os.name != "nt" or ext.lower() not in {"wmf", "emf"}:
        return data, ext
    try:
        return _rasterize(data, ext.lower()), "png"
    except (OSError, ValueError, OverflowError):
        # The original is still accepted by the server's LibreOffice fallback.
        return data, ext
