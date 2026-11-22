"""iPhone (iOS Safari) look for a profile.

The kernel is Chromium and only knows windows / macos / linux, so an iPhone
persona is layered on top of the macOS kernel: Chromium's device emulation
supplies the user agent, ``navigator.platform``, the mobile viewport, the
device pixel ratio and touch input, and a small page script removes what only
Chrome has (Client Hints, ``deviceMemory``, ``window.chrome``). Anything that
reads those values sees an iPhone. A probe of the engine itself (V8 versus
JavaScriptCore) still sees Chrome: this is a look, not a Safari.
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import suppress
from typing import Any

logger = logging.getLogger(__name__)

PLATFORM = "ios"
# Chromium's navigator.platform / the kernel's own platform on an iPhone persona.
NAVIGATOR_PLATFORM = "iPhone"
# What the kernel itself is told: the host's. Only macOS hosts are supported, so
# fonts, GPU stack and input behave like the Apple device the persona claims.
KERNEL_PLATFORM = "macos"
MAX_TOUCH_POINTS = 5
GPU_VENDOR = "Apple Inc."
GPU_RENDERER = "Apple GPU"
HARDWARE_CONCURRENCY = 6

# Safari freezes the OS part of its user agent; this is a real shipped string.
IOS_VERSION = "18_6"
SAFARI_VERSION = "18.6"
USER_AGENT = (
    f"Mozilla/5.0 (iPhone; CPU iPhone OS {IOS_VERSION} like Mac OS X) AppleWebKit/605.1.15 "
    f"(KHTML, like Gecko) Version/{SAFARI_VERSION} Mobile/15E148 Safari/604.1"
)

# id -> (name, CSS width, CSS height, device pixel ratio). Sizes are the portrait
# viewport Safari reports in screen.width/height. Keep in step with
# frontend/src/next/features/editor/deviceProfiles.ts.
IPHONES: dict[str, tuple[str, int, int, int]] = {
    "iphone_se3": ("iPhone SE (第 3 代)", 375, 667, 2),
    "iphone_13": ("iPhone 13", 390, 844, 3),
    "iphone_14": ("iPhone 14", 390, 844, 3),
    "iphone_15": ("iPhone 15", 393, 852, 3),
    "iphone_15_pro_max": ("iPhone 15 Pro Max", 430, 932, 3),
    "iphone_16": ("iPhone 16", 393, 852, 3),
    "iphone_16_pro": ("iPhone 16 Pro", 402, 874, 3),
    "iphone_16_pro_max": ("iPhone 16 Pro Max", 440, 956, 3),
}
DEFAULT_IPHONE = "iphone_15"


def is_ios(profile: dict[str, Any]) -> bool:
    return profile.get("platform") == PLATFORM


def pixel_ratio(profile: dict[str, Any]) -> int:
    """The device pixel ratio of the profile's iPhone, falling back to the size."""
    preset = IPHONES.get(str(profile.get("device_profile") or ""))
    if preset:
        return preset[3]
    for _, width, height, ratio in IPHONES.values():
        if (width, height) == (profile.get("screen_width"), profile.get("screen_height")):
            return ratio
    return 3


def with_defaults(profile: dict[str, Any]) -> dict[str, Any]:
    """The profile with the iPhone-only fields filled in where it left them empty.

    The window is a phone: the screen follows the preset, never this computer's display.
    """
    preset = IPHONES.get(str(profile.get("device_profile") or "")) or IPHONES[DEFAULT_IPHONE]
    filled = dict(profile)
    if not filled.get("screen_width") or not filled.get("screen_height") or filled.get("screen_width", 0) > 500:
        filled["screen_width"], filled["screen_height"] = preset[1], preset[2]
    filled["user_agent"] = filled.get("user_agent") or USER_AGENT
    filled["hardware_concurrency"] = filled.get("hardware_concurrency") or HARDWARE_CONCURRENCY
    filled["device_memory"] = None
    filled["gpu_vendor"] = filled.get("gpu_vendor") or GPU_VENDOR
    filled["gpu_renderer"] = filled.get("gpu_renderer") or GPU_RENDERER
    return filled


def persona_args(profile: dict[str, Any]) -> list[str]:
    """Kernel switches for an iPhone persona on a macOS host."""
    args = [f"--fingerprint-platform={KERNEL_PLATFORM}", "--fingerprint-noise=false"]
    seed = profile.get("fingerprint_seed")
    if seed is not None:
        args.insert(0, f"--fingerprint={seed}")
    args += [
        f"--fingerprint-gpu-vendor={profile.get('gpu_vendor') or GPU_VENDOR}",
        f"--fingerprint-gpu-renderer={profile.get('gpu_renderer') or GPU_RENDERER}",
        f"--fingerprint-hardware-concurrency={profile.get('hardware_concurrency') or HARDWARE_CONCURRENCY}",
        f"--fingerprint-max-touch-points={MAX_TOUCH_POINTS}",
        # A phone has no Dock: the available screen is the whole screen.
        "--fingerprint-taskbar-height=0",
    ]
    if profile.get("screen_width"):
        args.append(f"--fingerprint-screen-width={profile['screen_width']}")
    if profile.get("screen_height"):
        args.append(f"--fingerprint-screen-height={profile['screen_height']}")
    return args


# Safari has none of these; Chrome does. Removed on the prototype, so
# `'userAgentData' in navigator` is false exactly as it is in Safari.
_INIT_TEMPLATE = r"""
(() => {
  const workerPatch = __WORKER_PATCH__;
  const nativeToString = Function.prototype.toString;
  const nativeSources = new WeakMap();
  const markNative = (fn, name) => { try { nativeSources.set(fn, `function ${name}() { [native code] }`); } catch (_) {} return fn; };
  const patched = markNative(function toString() {
    return nativeSources.has(this) ? nativeSources.get(this) : nativeToString.call(this);
  }, 'toString');
  try { Object.defineProperty(Function.prototype, 'toString', { value: patched, configurable: true, writable: true }); } catch (_) {}

  const getter = (name, value) => markNative(Object.getOwnPropertyDescriptor({ get [name]() { return value; } }, name).get, `get ${name}`);
  const dropFromPrototype = (proto, name) => { try { delete proto[name]; } catch (_) {} };
  if (typeof Navigator === 'function') {
    dropFromPrototype(Navigator.prototype, 'userAgentData');
    dropFromPrototype(Navigator.prototype, 'deviceMemory');
    try {
      Object.defineProperty(Navigator.prototype, 'platform', { get: getter('platform', 'iPhone'), configurable: true });
    } catch (_) {}
    try {
      Object.defineProperty(Navigator.prototype, 'vendor', { get: getter('vendor', 'Apple Computer, Inc.'), configurable: true });
    } catch (_) {}
    try {
      Object.defineProperty(Navigator.prototype, 'standalone', { get: getter('standalone', false), configurable: true });
    } catch (_) {}
  }
  try { delete window.chrome; } catch (_) {}
  // Frames of other sites live in another process, where the emulated ratio does not follow.
  try { Object.defineProperty(window, 'devicePixelRatio', { get: getter('devicePixelRatio', __RATIO__), configurable: true, enumerable: true }); } catch (_) {}

  // A worker made from a blob (what fingerprint probes use) starts with the same
  // patch in front of its own code: nothing can run in between, so there is no race.
  if (typeof Blob === 'function') {
    const OriginalBlob = Blob;
    const wantsPatch = (parts, options) => {
      try {
        const type = String((options && options.type) || '').toLowerCase();
        if (!/(javascript|ecmascript)/.test(type)) return false;
        if (!Array.isArray(parts)) return true;
        const head = parts.filter((part) => typeof part === 'string').join('\n').slice(0, 2000);
        return !head || /postMessage|onmessage|addEventListener\s*\(\s*['"]message|importScripts|navigator|Intl|OffscreenCanvas/.test(head);
      } catch (_) { return false; }
    };
    const PatchedBlob = function Blob(parts, options) {
      const next = wantsPatch(parts, options) ? [workerPatch + '\n', ...(Array.isArray(parts) ? parts : [parts])] : parts;
      return new OriginalBlob(next, options);
    };
    try {
      Object.setPrototypeOf(PatchedBlob, OriginalBlob);
      PatchedBlob.prototype = OriginalBlob.prototype;
      Object.defineProperty(PatchedBlob, 'name', { value: 'Blob' });
      Object.defineProperty(PatchedBlob, 'length', { value: OriginalBlob.length });
      Object.defineProperty(window, 'Blob', { value: markNative(PatchedBlob, 'Blob'), configurable: true, writable: true });
    } catch (_) {}
  }
})();
"""


# Workers run in their own global: the page script never reaches them, and without
# this they still say MacIntel, 16 GB and Client Hints.
WORKER_SCRIPT = r"""
(() => {
  if (typeof WorkerNavigator !== 'function') return;
  const nativeToString = Function.prototype.toString;
  const nativeSources = new WeakMap();
  const markNative = (fn, name) => { try { nativeSources.set(fn, `function ${name}() { [native code] }`); } catch (_) {} return fn; };
  const patched = markNative(function toString() {
    return nativeSources.has(this) ? nativeSources.get(this) : nativeToString.call(this);
  }, 'toString');
  try { Object.defineProperty(Function.prototype, 'toString', { value: patched, configurable: true, writable: true }); } catch (_) {}
  const getter = (name, value) => markNative(Object.getOwnPropertyDescriptor({ get [name]() { return value; } }, name).get, `get ${name}`);
  try { delete WorkerNavigator.prototype.userAgentData; } catch (_) {}
  try { delete WorkerNavigator.prototype.deviceMemory; } catch (_) {}
  try {
    Object.defineProperty(WorkerNavigator.prototype, 'platform', { get: getter('platform', 'iPhone'), configurable: true });
  } catch (_) {}
})();
"""
WORKER_TARGETS = {"worker", "shared_worker", "service_worker"}


def init_script(profile: dict[str, Any]) -> str:
    """The page script for this profile's iPhone (its pixel ratio is the only part that varies)."""
    return _INIT_TEMPLATE.replace("__WORKER_PATCH__", json.dumps(WORKER_SCRIPT)).replace("__RATIO__", str(pixel_ratio(profile)))



async def apply_emulation(context: Any, profile: dict[str, Any]) -> None:
    """Apply the iPhone device emulation to every page of a CDP-backed context.

    Emulation overrides live as long as the DevTools session that set them, so
    the sessions are kept on the context instead of being detached.
    """
    new_cdp_session = getattr(context, "new_cdp_session", None)
    if not callable(new_cdp_session):
        return
    width = int(profile["screen_width"])
    height = int(profile["screen_height"])
    ratio = pixel_ratio(profile)
    user_agent = str(profile.get("user_agent") or USER_AGENT)
    sessions: list[Any] = []
    try:
        context._ios_cdp_sessions = sessions
    except Exception:
        pass

    async def patch_worker(session: Any, event: dict[str, Any]) -> None:
        """Run the worker script before the worker's own code, then let it start."""
        worker_id = event.get("sessionId")
        info = event.get("targetInfo") or {}
        if not worker_id or not event.get("waitingForDebugger"):
            return

        async def to_worker(call_id: int, method: str, params: dict[str, Any] | None = None) -> None:
            message = json.dumps({"id": call_id, "method": method, "params": params or {}})
            await session.send("Target.sendMessageToTarget", {"sessionId": worker_id, "message": message})

        try:
            if info.get("type") in WORKER_TARGETS:
                await to_worker(1, "Runtime.evaluate", {"expression": WORKER_SCRIPT})
        except Exception as exc:
            logger.debug("iPhone worker patch skipped for %s: %s", profile.get("id"), exc)
        finally:
            with suppress(Exception):
                await to_worker(2, "Runtime.runIfWaitingForDebugger")

    async def patch_page(page: Any) -> None:
        try:
            session = await new_cdp_session(page)
            sessions.append(session)
            await session.send("Emulation.setUserAgentOverride", {
                "userAgent": user_agent,
                "platform": NAVIGATOR_PLATFORM,
            })
            await session.send("Emulation.setDeviceMetricsOverride", {
                "width": width, "height": height, "deviceScaleFactor": ratio, "mobile": True,
                "screenWidth": width, "screenHeight": height,
            })
            await session.send("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": MAX_TOUCH_POINTS})
            await session.send("Emulation.setEmitTouchEventsForMouse", {"enabled": True, "configuration": "mobile"})
            session.on("Target.attachedToTarget", lambda event: asyncio.create_task(patch_worker(session, event)))
            await session.send("Target.setAutoAttach", {"autoAttach": True, "waitForDebuggerOnStart": True, "flatten": False})
        except Exception as exc:
            logger.warning("iPhone emulation skipped for a page of %s: %s", profile.get("id"), exc)

    for page in list(getattr(context, "pages", []) or []):
        await patch_page(page)
    try:
        context.on("page", lambda page: asyncio.create_task(patch_page(page)))
    except Exception as exc:
        logger.debug("Could not register the iPhone page hook for %s: %s", profile.get("id"), exc)
