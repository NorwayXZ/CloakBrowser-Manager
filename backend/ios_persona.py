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
import base64
import json
import logging
import re
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
    # Canvas noise is not decided here: it follows the profile's fingerprint options
    # (new profiles get the recommended noise-off preset; "自动" leaves the kernel's default).
    args = [f"--fingerprint-platform={KERNEL_PLATFORM}"]
    seed = profile.get("fingerprint_seed")
    if seed is not None:
        args.insert(0, f"--fingerprint={seed}")
    args += [
        f"--fingerprint-gpu-vendor={profile.get('gpu_vendor') or GPU_VENDOR}",
        f"--fingerprint-gpu-renderer={profile.get('gpu_renderer') or GPU_RENDERER}",
        f"--fingerprint-hardware-concurrency={profile.get('hardware_concurrency') or HARDWARE_CONCURRENCY}",
        f"--fingerprint-max-touch-points={MAX_TOUCH_POINTS}",
        # Touch events from a tab's very first document (device emulation only reaches a tab a
        # moment later). --blink-settings pointer types were tried and fought the emulation.
        "--touch-events=enabled",
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
  // A method has no own `prototype` and cannot be constructed, like the native toString.
  const patched = markNative({ toString() {
    return nativeSources.has(this) ? nativeSources.get(this) : nativeToString.call(this);
  } }.toString, 'toString');
  try { Object.defineProperty(Function.prototype, 'toString', { value: patched, configurable: true, writable: true }); } catch (_) {}

  // Native getters throw on a receiver of the wrong kind; these do too.
  const getter = (name, value, brand) => markNative(Object.getOwnPropertyDescriptor({ get [name]() {
    if (!(this instanceof brand)) throw new TypeError('Illegal invocation');
    return value;
  } }, name).get, `get ${name}`);
  const dropFromPrototype = (proto, name) => { try { delete proto[name]; } catch (_) {} };
  if (typeof Navigator === 'function') {
    // Only Chrome has these; iOS Safari has none of them.
    for (const name of ['userAgentData', 'deviceMemory', 'connection', 'getBattery', 'bluetooth', 'usb', 'serial', 'hid', 'keyboard', 'xr',
      'presentation', 'ink', 'login', 'managed', 'virtualKeyboard', 'windowControlsOverlay', 'scheduling', 'cookieDeprecationLabel',
      'joinAdInterestGroup', 'leaveAdInterestGroup', 'updateAdInterestGroups', 'clearOriginJoinedAdInterestGroups', 'runAdAuction',
      'createAuctionNonce', 'getInterestGroupAdAuctionData', 'canLoadAdAuctionFencedFrame']) {
      dropFromPrototype(Navigator.prototype, name);
    }
    try {
      Object.defineProperty(Navigator.prototype, 'platform', { get: getter('platform', 'iPhone', Navigator), configurable: true });
    } catch (_) {}
    try {
      Object.defineProperty(Navigator.prototype, 'vendor', { get: getter('vendor', 'Apple Computer, Inc.', Navigator), configurable: true });
    } catch (_) {}
    try {
      Object.defineProperty(Navigator.prototype, 'standalone', { get: getter('standalone', false, Navigator), configurable: true, enumerable: true });
    } catch (_) {}
  }
  try { delete window.chrome; } catch (_) {}
  // Frames of other sites live in another process, where the emulated ratio does not follow.
  // devicePixelRatio is [Replaceable]: assigning to it turns it into a plain value.
  try {
    const ratio = { get devicePixelRatio() {
      if (!(this instanceof Window)) throw new TypeError('Illegal invocation');
      return __RATIO__;
    }, set devicePixelRatio(value) {
      Object.defineProperty(window, 'devicePixelRatio', { value, writable: true, configurable: true, enumerable: true });
    } };
    const descriptor = Object.getOwnPropertyDescriptor(ratio, 'devicePixelRatio');
    Object.defineProperty(window, 'devicePixelRatio', {
      get: markNative(descriptor.get, 'get devicePixelRatio'), set: markNative(descriptor.set, 'set devicePixelRatio'), configurable: true, enumerable: true,
    });
  } catch (_) {}

  // A worker from a data: URL has no request to rewrite either; put the patch in front of its code.
  if (typeof Worker === 'function') {
    const OriginalWorker = Worker;
    const WorkerProxy = new Proxy(OriginalWorker, {
      construct(target, args, newTarget) {
        try {
          const url = String(args[0]);
          const head = /^data:(?:text|application)\/(?:x-)?(?:javascript|ecmascript)([^,]*),/i.exec(url);
          if (head) {
            const rest = url.slice(head[0].length);
            args[0] = /;base64/i.test(head[1])
              ? head[0] + btoa(workerPatch + atob(decodeURIComponent(rest)))
              : head[0] + encodeURIComponent(workerPatch) + rest;
          }
        } catch (_) {}
        return Reflect.construct(target, args, newTarget === WorkerProxy ? target : newTarget);
      },
    });
    try {
      Object.defineProperty(window, 'Worker', { value: markNative(WorkerProxy, 'Worker'), configurable: true, writable: true });
      Object.defineProperty(OriginalWorker.prototype, 'constructor', { value: WorkerProxy, configurable: true, writable: true });
    } catch (_) {}
  }

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
      Object.defineProperty(OriginalBlob.prototype, 'constructor', { value: PatchedBlob, configurable: true, writable: true });
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
  const patched = markNative({ toString() {
    return nativeSources.has(this) ? nativeSources.get(this) : nativeToString.call(this);
  } }.toString, 'toString');
  try { Object.defineProperty(Function.prototype, 'toString', { value: patched, configurable: true, writable: true }); } catch (_) {}
  const getter = (name, value, brand) => markNative(Object.getOwnPropertyDescriptor({ get [name]() {
    if (!(this instanceof brand)) throw new TypeError('Illegal invocation');
    return value;
  } }, name).get, `get ${name}`);
  for (const name of ['userAgentData', 'deviceMemory', 'connection', 'usb', 'hid', 'serial']) {
    try { delete WorkerNavigator.prototype[name]; } catch (_) {}
  }
  try {
    Object.defineProperty(WorkerNavigator.prototype, 'platform', { get: getter('platform', 'iPhone', WorkerNavigator), configurable: true });
  } catch (_) {}
})();
"""
# One line, so the worker's own code keeps its line numbers.
WORKER_PATCH = (" ".join(WORKER_SCRIPT.split()) + ";").encode()
# A leading 'use strict' must stay the first statement or the worker silently loses strict mode.
_LEADING_STRICT = re.compile(rb"""\A\s*(?:/\*.*?\*/\s*|//[^\n]*\n\s*)*(?:'use strict'|"use strict")[ \t]*(?:;|(?=\r?\n)|\Z)""", re.S)
MAX_PATCHED_BYTES = 4 * 1024 * 1024


def patch_worker_source(source: bytes) -> bytes:
    """A worker script with the iPhone patch in front of its own code."""
    strict = _LEADING_STRICT.match(source)
    if not strict:
        return WORKER_PATCH + source
    end = strict.end()
    separator = b"" if source[:end].rstrip().endswith(b";") else b";"
    return source[:end] + separator + WORKER_PATCH + source[end:]


def init_script(profile: dict[str, Any]) -> str:
    """The page script for this profile's iPhone (its pixel ratio is the only part that varies)."""
    return _INIT_TEMPLATE.replace("__WORKER_PATCH__", json.dumps(WORKER_PATCH.decode())).replace("__RATIO__", str(pixel_ratio(profile)))


async def install_worker_patch(context: Any, profile: dict[str, Any]) -> None:
    """Put the patch in front of every worker script as the browser fetches it.

    Dedicated, shared and service workers, module workers and workers made by
    frames of other sites all load their script over the network (type "Other"),
    so rewriting the response reaches them before a single line of theirs runs:
    nothing to race against. A worker made from a blob or a data: URL has no
    request and is covered by the page script instead.
    """
    browser = getattr(context, "_cloak_browser", None) or getattr(context, "browser", None)
    new_session = getattr(browser, "new_browser_cdp_session", None)
    if not callable(new_session):
        logger.warning("iPhone worker patch skipped for %s: no browser-level CDP session", profile.get("id"))
        return
    session = await new_session()
    tasks: set[asyncio.Task] = set()
    try:
        context._ios_worker_session = (session, tasks)
    except Exception:
        pass

    async def let_through(event: dict[str, Any]) -> None:
        method = "Fetch.continueRequest" if event.get("responseErrorReason") else "Fetch.continueResponse"
        await session.send(method, {"requestId": event["requestId"]})

    async def paused(event: dict[str, Any]) -> None:
        try:
            headers = {h["name"].lower(): h["value"] for h in event.get("responseHeaders") or []}
            wanted = (
                event.get("responseStatusCode") == 200
                and not event.get("responseErrorReason")
                and "javascript" in headers.get("content-type", "").lower()
                and int(headers.get("content-length") or 0) <= MAX_PATCHED_BYTES
            )
            if not wanted:
                await let_through(event)
                return
            reply = await session.send("Fetch.getResponseBody", {"requestId": event["requestId"]})
            body = base64.b64decode(reply["body"]) if reply.get("base64Encoded", True) else reply["body"].encode()
            kept = [h for h in event["responseHeaders"] if h["name"].lower() not in {"content-length", "content-encoding", "transfer-encoding"}]
            await session.send("Fetch.fulfillRequest", {
                "requestId": event["requestId"],
                "responseCode": 200,
                "responseHeaders": kept,
                "body": base64.b64encode(patch_worker_source(body)).decode(),
            })
        except Exception as exc:
            logger.debug("iPhone worker patch skipped for %s: %s", profile.get("id"), exc)
            with suppress(Exception):
                await let_through(event)

    def on_paused(event: dict[str, Any]) -> None:
        task = asyncio.create_task(paused(event))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    session.on("Fetch.requestPaused", on_paused)
    await session.send("Fetch.enable", {"patterns": [{"resourceType": "Other", "requestStage": "Response"}]})


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

    done: set[int] = set()
    tasks: set[asyncio.Task] = set()

    def spawn(coroutine: Any) -> None:
        task = asyncio.create_task(coroutine)  # kept referenced until done, or it may be collected mid-way
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    async def patch_page(page: Any) -> None:
        if id(page) in done:
            return
        done.add(id(page))
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
        except Exception as exc:
            logger.warning("iPhone emulation skipped for a page of %s: %s", profile.get("id"), exc)

    # Hook first, then walk the tabs that exist: a tab opened while the walk awaits is not missed.
    try:
        context.on("page", lambda page: spawn(patch_page(page)))
    except Exception as exc:
        logger.debug("Could not register the iPhone page hook for %s: %s", profile.get("id"), exc)
    for page in list(getattr(context, "pages", []) or []):
        await patch_page(page)
    try:
        await install_worker_patch(context, profile)
    except Exception as exc:
        logger.warning("iPhone worker patch not installed for %s: %s", profile.get("id"), exc)
