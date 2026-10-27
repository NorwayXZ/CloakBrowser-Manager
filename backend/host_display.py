"""The computer's own screen size, for profiles whose screen follows it.

Detection sites compare ``screen.width``/``height`` with CSS media queries
(``device-width``/``device-height``). The kernel only spoofs the former, so a
screen that differs from the real display is reported as an inconsistent
fingerprint. Profiles that follow the real display avoid the mismatch.
"""

from __future__ import annotations

import ctypes
import logging
import platform
import sys

logger = logging.getLogger(__name__)

COREGRAPHICS_PATH = "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
MIN_WIDTH = 320
MIN_HEIGHT = 240


class _CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class _CGSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


class _CGRect(ctypes.Structure):
    _fields_ = [("origin", _CGPoint), ("size", _CGSize)]


def _macos_primary_screen() -> tuple[float, float]:
    cg = ctypes.CDLL(COREGRAPHICS_PATH)
    cg.CGMainDisplayID.restype = ctypes.c_uint32
    cg.CGDisplayBounds.argtypes = [ctypes.c_uint32]
    cg.CGDisplayBounds.restype = _CGRect
    # The main display carries the menu bar; new browser windows open on it.
    # Its bounds are in points, which is what the browser reports as screen size.
    rect = cg.CGDisplayBounds(cg.CGMainDisplayID())
    return rect.size.width, rect.size.height


def primary_screen_size() -> tuple[int, int] | None:
    """Logical size of the screen new browser windows open on, if known."""
    if sys.platform != "darwin":
        return None
    try:
        width, height = _macos_primary_screen()
    except (OSError, AttributeError, ValueError) as exc:
        logger.warning("Could not read the screen size: %s", exc)
        return None
    size = int(round(width)), int(round(height))
    if size[0] < MIN_WIDTH or size[1] < MIN_HEIGHT:
        return None
    return size


def _macos_primary_visible_frame() -> tuple[float, float, float, float, float]:
    """(screen height, visible x, visible y from the bottom, visible width, visible height).

    NSScreen's visibleFrame is the area left after the menu bar and the Dock.
    The first screen in NSScreen.screens is the one with the menu bar.
    """
    objc = ctypes.CDLL("/usr/lib/libobjc.A.dylib")
    ctypes.CDLL("/System/Library/Frameworks/AppKit.framework/AppKit")
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    send = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(("objc_msgSend", objc))
    send_index = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong)(
        ("objc_msgSend", objc)
    )
    # Structs this size come back through a hidden pointer on Intel, which
    # objc_msgSend_stret handles; Apple silicon returns them directly.
    rect_symbol = "objc_msgSend_stret" if platform.machine() == "x86_64" else "objc_msgSend"
    send_rect = ctypes.CFUNCTYPE(_CGRect, ctypes.c_void_p, ctypes.c_void_p)((rect_symbol, objc))

    def sel(name: bytes) -> int:
        return objc.sel_registerName(name)

    pool = send(send(objc.objc_getClass(b"NSAutoreleasePool"), sel(b"alloc")), sel(b"init"))
    try:
        screens = send(objc.objc_getClass(b"NSScreen"), sel(b"screens"))
        if not screens:
            raise ValueError("no screens")
        screen = send_index(screens, sel(b"objectAtIndex:"), 0)
        frame = send_rect(screen, sel(b"frame"))
        visible = send_rect(screen, sel(b"visibleFrame"))
        return (frame.size.height, visible.origin.x - frame.origin.x, visible.origin.y - frame.origin.y,
                visible.size.width, visible.size.height)
    finally:
        send(pool, sel(b"drain"))


def primary_visible_frame() -> tuple[int, int, int, int] | None:
    """Area of the menu-bar screen left by the menu bar and Dock, if known.

    Returned as (left, top, width, height) in screen points from the top-left
    corner, the way browsers place windows and report screen.avail*.
    """
    if sys.platform != "darwin":
        return None
    try:
        screen_height, x, y_from_bottom, width, height = _macos_primary_visible_frame()
    except (OSError, AttributeError, ValueError) as exc:
        logger.warning("Could not read the screen's visible area: %s", exc)
        return None
    left = int(round(x))
    top = int(round(screen_height - (y_from_bottom + height)))
    frame = left, top, int(round(width)), int(round(height))
    if frame[2] < MIN_WIDTH or frame[3] < MIN_HEIGHT or top < 0:
        return None
    return frame
