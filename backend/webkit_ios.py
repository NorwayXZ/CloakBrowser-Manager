"""Real Apple WebKit (JavaScriptCore + Safari stack) runtime for iOS iPhone profiles.

Unlike the Chromium-based look in ``ios_persona``, this engine runs genuine
Apple WebKit + JavaScriptCore on macOS:

* Real JSC engine intrinsics (``eval.toString().length === 37``, JSC stack frames,
  JSC math/regex/Intl semantics, ``GestureEvent``, ``TouchEvent``, no V8 tells).
* Real Apple WebKit Metal GPU strings (``Apple Inc.`` / ``Apple GPU``) natively.
* Real mobile viewport, CSS ``device-width``/``device-height`` media queries,
  ``pointer: coarse``, ``hover: none`` and touch events across frames.
* Real WebKit ICU ``timezone_id`` and ``locale`` across main frame, iframes and
  Workers, plus native HTTP/SOCKS5 proxy routing.
* A JSC-native init script (matching JSC's multi-line ``[native code]`` format
  and exact DOM ``TypeError`` messages) removes the remaining macOS-desktop /
  Playwright-automation tells: ``navigator.webdriver -> false``, ``delete window.safari``,
  ``navigator.platform -> 'iPhone'``, ``maxTouchPoints -> 5``, ``pdfViewerEnabled -> false``,
  empty ``PluginArray``/``MimeTypeArray``, phone ``outerHeight``, Worker parity,
  proxy WebRTC STUN suppression, and optional per-seed Canvas/Audio micro-noise.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import secrets
import subprocess
import sys
from contextlib import suppress
from pathlib import Path
from typing import Any, Callable

from . import ios_persona
from .fingerprint_options import parse_fingerprint_options

logger = logging.getLogger("cloakbrowser.manager.webkit_ios")

ENGINE = "webkit"
WEBKIT_DATA_SUBDIR = "webkit-data"
_INSTALL_LOCK = asyncio.Lock()


def playwright_browsers_cache_dir() -> Path:
    custom = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    if custom and custom != "0":
        return Path(custom).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(local) / "ms-playwright"
    return Path.home() / ".cache" / "ms-playwright"


def webkit_bundle_meta() -> dict[str, str]:
    """Expected WebKit revision and version from the bundled Playwright driver."""
    try:
        from playwright._impl._driver import compute_driver_executable

        _, cli_js = compute_driver_executable()
        browsers_json = Path(cli_js).parent / "browsers.json"
        data = json.loads(browsers_json.read_text(encoding="utf-8"))
        entry = next((b for b in data.get("browsers", []) if b.get("name") == "webkit"), None)
        if not entry:
            return {"revision": "", "version": ""}
        rev = str(entry.get("revision") or "")
        overrides = entry.get("revisionOverrides") or {}
        if sys.platform == "darwin":
            mac_major = platform.mac_ver()[0].split(".", 1)[0]
            if mac_major == "14":
                key = "mac14-arm64" if platform.machine().lower() in {"arm64", "aarch64"} else "mac14"
                rev = str(overrides.get(key) or rev)
        return {"revision": rev, "version": str(entry.get("browserVersion") or "")}
    except Exception:
        return {"revision": "", "version": ""}


def installed_webkit_dir() -> Path | None:
    cache = playwright_browsers_cache_dir()
    meta = webkit_bundle_meta()
    rev = meta.get("revision")
    if rev:
        target = cache / f"webkit-{rev}"
        if (target / "INSTALLATION_COMPLETE").exists():
            return target
    if cache.is_dir():
        for candidate in sorted(cache.glob("webkit-*"), reverse=True):
            if (candidate / "INSTALLATION_COMPLETE").exists():
                return candidate
    return None


def is_webkit_installed() -> bool:
    return installed_webkit_dir() is not None


def ensure_webkit_installed_sync() -> Path:
    """Ensure Playwright's Apple WebKit binary is present; auto-download if missing.

    Uses Playwright's bundled ``node`` + ``cli.js`` directly rather than
    ``sys.executable -m playwright``, so this works identically inside a frozen
    PyInstaller ``.app`` bundle and in a source checkout.
    """
    existing = installed_webkit_dir()
    if existing is not None:
        return existing

    from playwright._impl._driver import compute_driver_executable, get_driver_env

    driver_node, driver_cli = compute_driver_executable()
    logger.info("Apple WebKit runtime not yet cached; installing via bundled Playwright driver...")
    completed = subprocess.run(
        [str(driver_node), str(driver_cli), "install", "webkit"],
        env=get_driver_env(),
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    installed = installed_webkit_dir()
    if completed.returncode != 0 or installed is None:
        detail = (completed.stderr or completed.stdout or f"exit {completed.returncode}").strip().splitlines()
        msg = detail[-1] if detail else "下载失败"
        raise RuntimeError(f"自动下载苹果 WebKit 内核失败：{msg}")
    return installed


async def ensure_webkit_installed() -> Path:
    existing = installed_webkit_dir()
    if existing is not None:
        return existing
    async with _INSTALL_LOCK:
        existing = installed_webkit_dir()
        if existing is not None:
            return existing
        return await asyncio.to_thread(ensure_webkit_installed_sync)


# ── JSC-native iPhone Safari Stealth & Coherence Script ──────────────────────

_WORKER_TEMPLATE = r"""
(() => {
  'use strict';
  if (typeof WorkerNavigator !== 'function') return;
  const hc = __HC__;
  const nativeToString = Function.prototype.toString;
  const sharedMap = new WeakMap();
  const jscCode = (bare) => `function ${bare}() {\n\x20\x20\x20\x20[native code]\n}`;
  const mark = (fn, bare, fnName) => {
    try {
      if (fnName !== undefined) Object.defineProperty(fn, 'name', { value: fnName, configurable: true });
      sharedMap.set(fn, jscCode(bare));
    } catch (_) {}
    return fn;
  };
  const patchedToString = mark({
    toString() {
      if (typeof this === 'function' && sharedMap.has(this)) return sharedMap.get(this);
      return nativeToString.call(this);
    }
  }.toString, 'toString', 'toString');
  try {
    Object.defineProperty(Function.prototype, 'toString', {
      value: patchedToString, configurable: true, writable: true, enumerable: false,
    });
  } catch (_) {}

  const patchWorkerGetter = (prop, getVal) => {
    try {
      const desc = Object.getOwnPropertyDescriptor(WorkerNavigator.prototype, prop);
      if (!desc || !desc.get) return;
      const origGet = desc.get;
      const getter = mark(Object.getOwnPropertyDescriptor({
        get [prop]() {
          if (!(this instanceof WorkerNavigator)) return origGet.call(this);
          return getVal.call(this);
        }
      }, prop).get, prop, `get ${prop}`);
      Object.defineProperty(WorkerNavigator.prototype, prop, {
        get: getter, enumerable: desc.enumerable, configurable: desc.configurable,
      });
    } catch (_) {}
  };

  patchWorkerGetter('platform', () => 'iPhone');
  patchWorkerGetter('hardwareConcurrency', () => hc);
  patchWorkerGetter('webdriver', () => false);
})();
"""

_PAGE_TEMPLATE = r"""
(() => {
  'use strict';
  const cfg = __CONFIG__;
  const SECRET = __SECRET__;
  const workerPatch = __WORKER_PATCH__;

  // Share one WeakMap across same-origin frames (via unforgeable per-launch SECRET)
  // so fresh phantom iframes calling iframe.Function.prototype.toString.call(fn)
  // see exact JSC [native code] sources without exposing any global property.
  const nativeToString = Function.prototype.toString;
  let sharedMap = null;
  for (const host of [window.top, window.parent]) {
    try {
      if (host && host !== window) {
        const res = host.Function.prototype.toString.call(nativeToString, SECRET);
        if (res && typeof res.get === 'function' && typeof res.set === 'function') {
          sharedMap = res;
          break;
        }
      }
    } catch (_) {}
  }
  if (!sharedMap) sharedMap = new WeakMap();

  const jscCode = (bare) => `function ${bare}() {\n\x20\x20\x20\x20[native code]\n}`;
  const mark = (fn, bare, fnName) => {
    try {
      if (fnName !== undefined) Object.defineProperty(fn, 'name', { value: fnName, configurable: true });
      sharedMap.set(fn, jscCode(bare));
    } catch (_) {}
    return fn;
  };
  const patchedToString = mark({
    toString() {
      if (arguments.length === 1 && arguments[0] === SECRET) return sharedMap;
      if (typeof this === 'function' && sharedMap.has(this)) return sharedMap.get(this);
      return nativeToString.call(this);
    }
  }.toString, 'toString', 'toString');
  try {
    Object.defineProperty(Function.prototype, 'toString', {
      value: patchedToString, configurable: true, writable: true, enumerable: false,
    });
  } catch (_) {}

  // Concise getters/methods have no .prototype descriptor and delegate invalid
  // receivers back to WebKit's original C++ accessor for exact TypeError & stack depth.
  const patchGetter = (Proto, Ctor, prop, getVal) => {
    try {
      const desc = Object.getOwnPropertyDescriptor(Proto, prop);
      if (!desc || !desc.get) return;
      const origGet = desc.get;
      const getter = mark(Object.getOwnPropertyDescriptor({
        get [prop]() {
          if (!(this instanceof Ctor)) return origGet.call(this);
          return getVal.call(this);
        }
      }, prop).get, prop, `get ${prop}`);
      Object.defineProperty(Proto, prop, {
        get: getter, enumerable: desc.enumerable, configurable: desc.configurable,
      });
    } catch (_) {}
  };

  const patchMethod = (Proto, Ctor, prop, impl) => {
    try {
      const desc = Object.getOwnPropertyDescriptor(Proto, prop);
      if (!desc || typeof desc.value !== 'function') return;
      const origFn = desc.value;
      const fn = mark({
        [prop]() {
          if (!(this instanceof Ctor)) return origFn.apply(this, arguments);
          return impl.apply(this, arguments);
        }
      }[prop], prop, prop);
      Object.defineProperty(Proto, prop, {
        value: fn, writable: desc.writable, enumerable: desc.enumerable, configurable: desc.configurable,
      });
    } catch (_) {}
  };

  // Desktop macOS Safari exposes window.safari; iOS Mobile Safari does not.
  try { delete window.safari; } catch (_) {}

  // iOS Mobile Safari reports 0 plugins and 0 mimeTypes on real PluginArray / MimeTypeArray
  // prototypes (no ES6 Proxy so Object.getOwnPropertyNames & spread never trip Proxy invariants).
  if (typeof PluginArray === 'function' && typeof MimeTypeArray === 'function' && typeof Navigator === 'function') {
    try {
      const emptyIter = mark({ *[Symbol.iterator]() {} }[Symbol.iterator], '[Symbol.iterator]', '[Symbol.iterator]');
      patchGetter(PluginArray.prototype, PluginArray, 'length', () => 0);
      patchMethod(PluginArray.prototype, PluginArray, 'item', (index) => null);
      patchMethod(PluginArray.prototype, PluginArray, 'namedItem', (name) => null);
      patchMethod(PluginArray.prototype, PluginArray, 'refresh', () => undefined);
      Object.defineProperty(PluginArray.prototype, Symbol.iterator, {
        value: emptyIter, writable: true, enumerable: false, configurable: true,
      });

      patchGetter(MimeTypeArray.prototype, MimeTypeArray, 'length', () => 0);
      patchMethod(MimeTypeArray.prototype, MimeTypeArray, 'item', (index) => null);
      patchMethod(MimeTypeArray.prototype, MimeTypeArray, 'namedItem', (name) => null);
      Object.defineProperty(MimeTypeArray.prototype, Symbol.iterator, {
        value: emptyIter, writable: true, enumerable: false, configurable: true,
      });

      const emptyPlugins = Object.create(PluginArray.prototype);
      const emptyMimeTypes = Object.create(MimeTypeArray.prototype);
      patchGetter(Navigator.prototype, Navigator, 'plugins', () => emptyPlugins);
      patchGetter(Navigator.prototype, Navigator, 'mimeTypes', () => emptyMimeTypes);
    } catch (_) {}
  }

  if (typeof Navigator === 'function') {
    patchGetter(Navigator.prototype, Navigator, 'webdriver', () => false);
    patchGetter(Navigator.prototype, Navigator, 'platform', () => 'iPhone');
    patchGetter(Navigator.prototype, Navigator, 'maxTouchPoints', () => cfg.maxTouchPoints);
    patchGetter(Navigator.prototype, Navigator, 'hardwareConcurrency', () => cfg.hc);
    patchGetter(Navigator.prototype, Navigator, 'pdfViewerEnabled', () => false);
  }

  // Headed macOS window chrome adds titlebar height to outerHeight; clamp only when exceeding phone screen.
  if (typeof Window === 'function') {
    for (const [prop, maxVal] of [['outerWidth', cfg.width], ['outerHeight', cfg.height]]) {
      try {
        const owner = Object.getOwnPropertyDescriptor(window, prop) ? window : Window.prototype;
        const desc = Object.getOwnPropertyDescriptor(owner, prop);
        if (desc && desc.get) {
          const origGet = desc.get;
          const getter = mark(Object.getOwnPropertyDescriptor({
            get [prop]() {
              const raw = origGet.call(this);
              return typeof raw === 'number' && raw > maxVal ? maxVal : raw;
            }
          }, prop).get, prop, `get ${prop}`);
          Object.defineProperty(owner, prop, {
            get: getter, enumerable: desc.enumerable, configurable: desc.configurable,
          });
        }
      } catch (_) {}
    }
  }

  // Prevent unproxied UDP STUN leaks when the profile routes through a proxy.
  if (cfg.hasProxy && typeof RTCPeerConnection === 'function') {
    const OrigRTC = RTCPeerConnection;
    const stripStun = (rtcCfg) => {
      if (!rtcCfg || typeof rtcCfg !== 'object' || !Array.isArray(rtcCfg.iceServers)) return rtcCfg;
      const filtered = [];
      for (const srv of rtcCfg.iceServers) {
        if (!srv || typeof srv !== 'object') continue;
        const raw = srv.urls ?? srv.url;
        const list = (Array.isArray(raw) ? raw : raw ? [raw] : []).filter(
          (u) => typeof u === 'string' && !/^\s*stuns?:/i.test(u)
        );
        if (list.length > 0) filtered.push({ ...srv, urls: list });
      }
      return { ...rtcCfg, iceServers: filtered };
    };
    const WrappedRTC = function RTCPeerConnection() {
      if (!new.target) return OrigRTC.apply(this, arguments);
      const args = Array.prototype.slice.call(arguments);
      if (args.length > 0) args[0] = stripStun(args[0]);
      return Reflect.construct(OrigRTC, args, new.target === WrappedRTC ? OrigRTC : new.target);
    };
    try {
      Object.setPrototypeOf(WrappedRTC, OrigRTC);
      WrappedRTC.prototype = OrigRTC.prototype;
      Object.defineProperty(WrappedRTC, 'length', { value: OrigRTC.length, configurable: true });
      mark(WrappedRTC, 'RTCPeerConnection', 'RTCPeerConnection');
      Object.defineProperty(window, 'RTCPeerConnection', { value: WrappedRTC, configurable: true, writable: true });
      Object.defineProperty(OrigRTC.prototype, 'constructor', { value: WrappedRTC, configurable: true, writable: true });
      if ('webkitRTCPeerConnection' in window) {
        Object.defineProperty(window, 'webkitRTCPeerConnection', { value: WrappedRTC, configurable: true, writable: true });
      }
    } catch (_) {}
  }

  // Deterministic per-seed Canvas & OfflineAudioContext micro-noise so multiple iPhone profiles do not link.
  if (cfg.noise && typeof cfg.seed === 'number') {
    const seed0 = (cfg.seed >>> 0) || 1;
    const prng = (idx) => {
      let t = (seed0 + Math.imul(idx >>> 0, 0x9E3779B1)) >>> 0;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0);
    };

    if (typeof CanvasRenderingContext2D === 'function' && typeof HTMLCanvasElement === 'function') {
      const origGetImageData = CanvasRenderingContext2D.prototype.getImageData;
      const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
      const origToBlob = HTMLCanvasElement.prototype.toBlob;

      const nudgePixels = (data, width, height) => {
        const len = data.length;
        if (len < 64 || width < 4 || height < 4) return;
        const stride = width * 4;
        for (let y = 1; y < height - 1; y += 3) {
          for (let x = 1; x < width - 1; x += 5) {
            const i = y * stride + x * 4;
            if (data[i + 3] === 0) continue;
            // Only touch edge pixels where neighbours already differ (never flat fills).
            if (data[i] === data[i - 4] && data[i + 1] === data[i - 3] && data[i + 2] === data[i - 2]) continue;
            const r = prng(i);
            if ((r & 7) !== 0) continue;
            const ch = (r >>> 3) % 3;
            const delta = (r & 64) ? 1 : -1;
            const next = data[i + ch] + delta;
            if (next >= 0 && next <= 255) data[i + ch] = next;
          }
        }
      };

      const cloneNoisyCanvas = (canvas) => {
        try {
          if (!canvas || canvas.width < 4 || canvas.height < 4 || canvas.width > 4096 || canvas.height > 4096) return null;
          const ctx = canvas.getContext('2d');
          if (!ctx) return null;
          const copy = document.createElement('canvas');
          copy.width = canvas.width;
          copy.height = canvas.height;
          const copyCtx = copy.getContext('2d');
          if (!copyCtx) return null;
          const img = origGetImageData.call(ctx, 0, 0, canvas.width, canvas.height);
          nudgePixels(img.data, canvas.width, canvas.height);
          copyCtx.putImageData(img, 0, 0);
          return copy;
        } catch (_) {
          return null;
        }
      };

      patchMethod(CanvasRenderingContext2D.prototype, CanvasRenderingContext2D, 'getImageData', function(sx, sy, sw, sh) {
        const img = origGetImageData.apply(this, arguments);
        try { nudgePixels(img.data, img.width, img.height); } catch (_) {}
        return img;
      });
      patchMethod(HTMLCanvasElement.prototype, HTMLCanvasElement, 'toDataURL', function() {
        const noisy = cloneNoisyCanvas(this);
        return origToDataURL.apply(noisy || this, arguments);
      });
      patchMethod(HTMLCanvasElement.prototype, HTMLCanvasElement, 'toBlob', function(callback) {
        const noisy = cloneNoisyCanvas(this);
        return origToBlob.apply(noisy || this, arguments);
      });
    }

    // Nudge rendered OfflineAudioContext buffers once on completion so AudioBuffer.getChannelData
    // and AudioBuffer.copyFromChannel remain 100% native and sample-identical.
    const OAC = window.OfflineAudioContext || window.webkitOfflineAudioContext;
    if (typeof OAC === 'function' && OAC.prototype && typeof OAC.prototype.startRendering === 'function') {
      const origStart = OAC.prototype.startRendering;
      patchMethod(OAC.prototype, OAC, 'startRendering', function() {
        return origStart.apply(this, arguments).then((buf) => {
          try {
            const eps = ((seed0 % 97) - 48) * 1e-8;
            for (let ch = 0; ch < buf.numberOfChannels; ch++) {
              const arr = buf.getChannelData(ch);
              for (let i = 0; i < arr.length; i += 13) {
                if (arr[i] !== 0) arr[i] += eps * (((prng(i + ch * 997) & 1) === 0) ? 1 : -1);
              }
            }
          } catch (_) {}
          return buf;
        });
      });
    }
  }

  // Workers from data: URLs and Blobs get the same JSC WorkerNavigator patch before their code runs.
  if (typeof Worker === 'function') {
    const OriginalWorker = Worker;
    const WrappedWorker = function Worker(scriptURL) {
      if (!new.target) return OriginalWorker.apply(this, arguments);
      const args = Array.prototype.slice.call(arguments);
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
      return Reflect.construct(OriginalWorker, args, new.target === WrappedWorker ? OriginalWorker : new.target);
    };
    try {
      Object.setPrototypeOf(WrappedWorker, OriginalWorker);
      WrappedWorker.prototype = OriginalWorker.prototype;
      Object.defineProperty(WrappedWorker, 'length', { value: OriginalWorker.length, configurable: true });
      mark(WrappedWorker, 'Worker', 'Worker');
      Object.defineProperty(window, 'Worker', { value: WrappedWorker, configurable: true, writable: true });
      Object.defineProperty(OriginalWorker.prototype, 'constructor', { value: WrappedWorker, configurable: true, writable: true });
    } catch (_) {}
  }

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
    const PatchedBlob = function Blob() {
      if (!new.target) return OriginalBlob.apply(this, arguments);
      const args = Array.prototype.slice.call(arguments);
      if (args.length > 0 && wantsPatch(args[0], args[1])) {
        args[0] = [workerPatch + '\n', ...(Array.isArray(args[0]) ? args[0] : [args[0]])];
      }
      return Reflect.construct(OriginalBlob, args, new.target === PatchedBlob ? OriginalBlob : new.target);
    };
    try {
      Object.setPrototypeOf(PatchedBlob, OriginalBlob);
      PatchedBlob.prototype = OriginalBlob.prototype;
      Object.defineProperty(PatchedBlob, 'length', { value: OriginalBlob.length, configurable: true });
      mark(PatchedBlob, 'Blob', 'Blob');
      Object.defineProperty(window, 'Blob', { value: PatchedBlob, configurable: true, writable: true });
      Object.defineProperty(OriginalBlob.prototype, 'constructor', { value: PatchedBlob, configurable: true, writable: true });
    } catch (_) {}
  }
})();
"""


def worker_patch_bytes(profile: dict[str, Any]) -> bytes:
    hc = int(profile.get("hardware_concurrency") or ios_persona.HARDWARE_CONCURRENCY)
    script = _WORKER_TEMPLATE.replace("__HC__", str(hc))
    return (" ".join(script.split()) + ";").encode("utf-8")


def patch_webkit_worker_source(source: bytes, profile: dict[str, Any]) -> bytes:
    patch = worker_patch_bytes(profile)
    strict = ios_persona._LEADING_STRICT.match(source)
    if not strict:
        return patch + source
    end = strict.end()
    separator = b"" if source[:end].rstrip().endswith(b";") else b";"
    return source[:end] + separator + patch + source[end:]


def init_script(profile: dict[str, Any], *, has_proxy: bool = False) -> str:
    filled = ios_persona.with_defaults(profile)
    options = parse_fingerprint_options(filled)
    seed = filled.get("fingerprint_seed")
    cfg = {
        "width": int(filled["screen_width"]),
        "height": int(filled["screen_height"]),
        "hc": int(filled.get("hardware_concurrency") or ios_persona.HARDWARE_CONCURRENCY),
        "maxTouchPoints": ios_persona.MAX_TOUCH_POINTS,
        "hasProxy": bool(has_proxy),
        "noise": options.noise is not False and isinstance(seed, int),
        "seed": int(seed) if isinstance(seed, int) else None,
    }
    patch_str = worker_patch_bytes(filled).decode("utf-8")
    secret = secrets.token_hex(16)
    return (
        _PAGE_TEMPLATE
        .replace("__CONFIG__", json.dumps(cfg))
        .replace("__SECRET__", json.dumps(secret))
        .replace("__WORKER_PATCH__", json.dumps(patch_str))
    )


async def install_worker_route(context: Any, profile: dict[str, Any]) -> None:
    """Patch network-fetched Workers (Dedicated / Module / Shared / Service) in WebKit.

    Every non-worker request goes straight through ``route.continue_()`` untouched
    on WebKit's native network stack.
    """
    async def handle(route: Any) -> None:
        try:
            dest = (route.request.headers or {}).get("sec-fetch-dest", "").lower()
            if dest not in {"worker", "sharedworker", "serviceworker"}:
                await route.continue_()
                return
            response = await route.fetch()
            content_type = (response.headers or {}).get("content-type", "").lower()
            body = await response.body()
            if response.status == 200 and "javascript" in content_type and len(body) <= ios_persona.MAX_PATCHED_BYTES:
                patched = patch_webkit_worker_source(body, profile)
                headers = {
                    k: v for k, v in (response.headers or {}).items()
                    if k.lower() not in {"content-length", "content-encoding", "transfer-encoding"}
                }
                await route.fulfill(status=response.status, headers=headers, body=patched)
            else:
                await route.fulfill(response=response, body=body)
        except Exception as exc:
            logger.debug("WebKit worker route fallback for %s: %s", profile.get("id"), exc)
            with suppress(Exception):
                await route.continue_()

    await context.route("**/*", handle)


async def launch_webkit_ios_context(
    *,
    profile: dict[str, Any],
    user_data_dir: Path,
    headless: bool,
    browser_proxy: str | None,
    locale: str | None,
    timezone: str | None,
    geo_coords: dict[str, float] | None,
    geo_mode: str,
    profile_cookies: list[dict[str, Any]],
    startup_urls: list[str],
    humanize: bool = False,
    human_preset: str = "default",
    on_all_windows_closed: Callable[[], Any] | None = None,
) -> Any:
    """Launch a persistent Apple WebKit iPhone context and configure its tabs."""
    from playwright.async_api import async_playwright

    await ensure_webkit_installed()
    filled = ios_persona.with_defaults(profile)
    width = int(filled["screen_width"])
    height = int(filled["screen_height"])
    dpr = ios_persona.pixel_ratio(filled)
    ua = str(filled.get("user_agent") or ios_persona.USER_AGENT)
    webkit_dir = Path(user_data_dir) / WEBKIT_DATA_SUBDIR
    webkit_dir.mkdir(parents=True, exist_ok=True)

    kwargs: dict[str, Any] = {
        "headless": headless,
        "viewport": {"width": width, "height": height},
        "screen": {"width": width, "height": height},
        "device_scale_factor": dpr,
        "is_mobile": True,
        "has_touch": True,
        "user_agent": ua,
    }
    if locale:
        kwargs["locale"] = locale
    if timezone:
        kwargs["timezone_id"] = timezone
    color_scheme = filled.get("color_scheme")
    if color_scheme in {"light", "dark", "no-preference"}:
        kwargs["color_scheme"] = color_scheme
    if browser_proxy:
        kwargs["proxy"] = {"server": browser_proxy, "bypass": "127.0.0.1,localhost"}
    if geo_mode == "ip" and geo_coords:
        kwargs["geolocation"] = geo_coords
        kwargs["permissions"] = ["geolocation"]
    elif geo_mode == "block":
        kwargs["permissions"] = []

    pw = await async_playwright().start()
    context: Any | None = None
    closing = False
    try:
        context = await pw.webkit.launch_persistent_context(str(webkit_dir), **kwargs)
        script = init_script(filled, has_proxy=bool(browser_proxy))
        await context.add_init_script(script)
        await install_worker_route(context, filled)
        for existing_page in list(context.pages):
            with suppress(Exception):
                await existing_page.evaluate(script)

        if profile_cookies:
            try:
                await context.add_cookies(profile_cookies)
            except Exception as exc:
                logger.warning("WebKit cookie import failed for %s: %s", filled.get("id"), exc)

        if humanize:
            try:
                from cloakbrowser.human import patch_context_async
                from cloakbrowser.human.config import resolve_config

                patch_context_async(context, resolve_config(human_preset))
            except Exception as exc:
                logger.debug("Humanize patch skipped for WebKit: %s", exc)

        # Open startup URLs on headed launches (headless automation opens its own pages).
        if not headless and startup_urls:
            pages = list(context.pages)
            first_page = pages[0] if pages else await context.new_page()
            for idx, url in enumerate(startup_urls):
                target_page = first_page if idx == 0 else await context.new_page()
                try:
                    await target_page.goto(url, wait_until="domcontentloaded", timeout=15_000)
                except Exception as exc:
                    logger.debug("WebKit startup URL %s load warning: %s", url, exc)

        # macOS keeps Playwright.app running with 0 windows after the user closes the
        # last tab; detect empty context.pages and trigger clean profile shutdown.
        if not headless and on_all_windows_closed is not None:
            watch_tasks: set[asyncio.Task[Any]] = set()

            async def _check_last_window_closed() -> None:
                await asyncio.sleep(0.8)
                if closing or context is None:
                    return
                if len(context.pages) == 0:
                    res = on_all_windows_closed()
                    if asyncio.iscoroutine(res):
                        await res

            def _attach_page_close(page: Any) -> None:
                def _on_close(*_: Any) -> None:
                    if closing:
                        return
                    t = asyncio.create_task(_check_last_window_closed())
                    watch_tasks.add(t)
                    t.add_done_callback(watch_tasks.discard)

                page.on("close", _on_close)

            context.on("page", _attach_page_close)
            for pg in list(context.pages):
                _attach_page_close(pg)
    except BaseException:
        if context is not None:
            with suppress(Exception):
                await context.close()
        with suppress(Exception):
            await pw.stop()
        raise

    original_close = context.close

    async def close_with_cleanup(*, reason: str | None = None) -> None:
        nonlocal closing
        if closing:
            return
        closing = True
        try:
            if reason is None:
                await original_close()
            else:
                await original_close(reason=reason)
        except Exception as exc:
            logger.debug("WebKit context close failed: %s", exc)
        finally:
            with suppress(Exception):
                await pw.stop()

    context.close = close_with_cleanup
    context._cloak_playwright = pw
    return context
