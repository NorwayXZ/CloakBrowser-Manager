"""Page-level control of a running profile for AI agents.

The Manager already holds a Playwright ``BrowserContext`` for every profile
launched in ``debug`` mode. This module drives pages through that context, so
an agent can navigate, read and click without opening a second CDP connection
(which would add its own ``Runtime.enable`` footprint to the page).

Design notes:

* **Snapshot with refs.** ``snapshot`` returns a compact text outline of what
  is on the page and hands out short refs (``e12``) for interactive elements.
  The refs point at live element handles kept here, not at attributes written
  into the page, so the page sees nothing of the agent's bookkeeping. A ref is
  only good until the next snapshot or navigation (``stale_ref``).
* **No local files.** Navigation is limited to http(s) and ``about:blank``;
  ``file:``, ``chrome:``, ``javascript:`` and ``data:`` are refused.
* **One current tab per profile**, switched with ``tabs(action="select")`` or
  by a click that opens a new tab.

Every function raises ``PageControlError(reason, detail)`` for expected
failures, which the HTTP layer turns into a structured error.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import weakref
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeout

logger = logging.getLogger("cloakbrowser.manager.page_control")

ALLOWED_SCHEMES = frozenset({"http", "https"})
NAV_TIMEOUT_MS = 30_000
ACTION_TIMEOUT_MS = 10_000
MAX_WAIT_MS = 30_000
MAX_SNAPSHOT_ELEMENTS = 400
MAX_SNAPSHOT_TEXT_LINES = 250
SCROLL_DEFAULT_PX = 600
MAX_TEXT_LEN = 20_000
SETTLE_TIMEOUT_S = 10.0
TEXT_DEFAULT_CHARS = 6_000
TEXT_MAX_CHARS = 20_000


class PageControlError(Exception):
    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


# Collects interactive elements (-> refs) and readable text, in document order.
# Walks element and text nodes (so text inside plain divs/spans is read too, and
# open shadow roots are entered); inline runs are merged into one text line.
# Returns { lines: string[], els: Element[], frames: number, truncated: boolean }.
_SNAPSHOT_JS = """
([maxEls, maxText, viewportOnly, refBase]) => {
  const INTERACTIVE = 'a[href],button,input,select,textarea,summary,[role=button],[role=link],'
    + '[role=checkbox],[role=tab],[role=menuitem],[role=switch],[role=option],[role=radio],'
    + '[contenteditable=""],[contenteditable=true]';
  const SKIP = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'HEAD', 'SVG', 'CANVAS', 'META', 'LINK']);
  const MAX_FRAMES = 6;
  const MAX_NODES = 8000;
  const clean = (s, n) => (s || '').replace(/\\s+/g, ' ').trim().slice(0, n);
  const vh = window.innerHeight, vw = window.innerWidth;
  const inView = (r) => r.bottom > 0 && r.top < vh && r.right > 0 && r.left < vw;
  const visible = (el) => {
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0') return false;
    if (s.display === 'contents') return true;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const roleOf = (el) => {
    const explicit = el.getAttribute('role');
    if (explicit) return explicit;
    const tag = el.tagName.toLowerCase();
    if (tag === 'a') return 'link';
    if (tag === 'button' || tag === 'summary') return 'button';
    if (tag === 'select') return 'combobox';
    if (tag === 'textarea') return 'textbox';
    if (tag === 'input') {
      const t = (el.getAttribute('type') || 'text').toLowerCase();
      if (t === 'checkbox') return 'checkbox';
      if (t === 'radio') return 'radio';
      if (['button', 'submit', 'reset', 'image'].includes(t)) return 'button';
      return 'textbox';
    }
    return 'generic';
  };
  const nameOf = (el) => {
    const tag = el.tagName.toLowerCase();
    let n = el.getAttribute('aria-label') || '';
    if (!n && el.labels && el.labels.length) n = el.labels[0].innerText;
    if (!n && tag === 'input') n = el.placeholder || el.title || el.name || '';
    if (!n && tag === 'input' && ['button', 'submit', 'reset'].includes(el.type)) n = el.value;
    if (!n && tag !== 'input' && tag !== 'select' && tag !== 'textarea') n = el.innerText;
    if (!n) {
      const by = el.getAttribute('aria-labelledby');
      if (by) n = by.split(/\\s+/).map((id) => { const t = document.getElementById(id); return t ? t.innerText : ''; }).join(' ');
    }
    if (!n) {
      const img = el.querySelector && el.querySelector('img[alt]');
      const svg = el.querySelector && el.querySelector('svg title');
      n = (img && img.alt) || (svg && svg.textContent) || '';
    }
    if (!n) n = el.title || el.alt || el.placeholder || el.name || el.id || '';
    return clean(n, 80);
  };
  const els = [];
  const lines = [];
  const frameEls = [];
  let textLines = 0;
  let visited = 0;
  let truncated = false;
  let pending = '';
  const flush = () => {
    const t = clean(pending, 200);
    pending = '';
    if (!t) return;
    if (textLines >= maxText) { truncated = true; return; }
    const line = 'text ' + JSON.stringify(t);
    if (lines.length && lines[lines.length - 1] === line) return;
    textLines++;
    lines.push(line);
  };
  const emitInteractive = (el) => {
    if (el.tagName === 'INPUT' && el.type === 'hidden') return;
    if (els.length >= maxEls) { truncated = true; return; }
    const ref = 'e' + (refBase + els.length);
    els.push(el);
    const bits = [];
    if (el.tagName === 'INPUT') {
      const t = (el.getAttribute('type') || 'text').toLowerCase();
      bits.push('type=' + t);
      if (t === 'password') bits.push('(value hidden)');
      else if (t === 'checkbox' || t === 'radio') bits.push(el.checked ? 'checked' : 'unchecked');
      else if (el.value) bits.push('value=' + JSON.stringify(clean(el.value, 60)));
    } else if (el.tagName === 'TEXTAREA' && el.value) {
      bits.push('value=' + JSON.stringify(clean(el.value, 60)));
    } else if (el.tagName === 'SELECT') {
      const o = el.options[el.selectedIndex];
      if (o) bits.push('selected=' + JSON.stringify(clean(o.text, 60)));
    } else if (el.tagName === 'A') {
      try {
        const u = new URL(el.href);
        const path = u.pathname.slice(0, 80) + (u.search ? '?…' : '');
        bits.push('href=' + (u.origin === location.origin ? '' : u.origin) + path);
      } catch (e) {}
    }
    if (el.disabled) bits.push('disabled');
    lines.push('[' + ref + '] ' + roleOf(el) + ' ' + JSON.stringify(nameOf(el)) + (bits.length ? ' ' + bits.join(' ') : ''));
  };
  const walk = (root, depth) => {
    for (let node = root.firstChild; node; node = node.nextSibling) {
      if (++visited > MAX_NODES || depth > 80) { truncated = true; return; }
      if (node.nodeType === 3) {
        if (viewportOnly && node.nodeValue && node.nodeValue.trim()) {
          const range = document.createRange();
          range.selectNodeContents(node);
          if (!inView(range.getBoundingClientRect())) continue;
        }
        if (node.nodeValue && node.nodeValue.trim()) pending += ' ' + node.nodeValue;
        if (pending.length > 200) flush();
        continue;
      }
      if (node.nodeType !== 1) continue;
      const el = node;
      if (SKIP.has(el.tagName.toUpperCase())) continue;
      if (!visible(el)) continue;
      if (viewportOnly) {
        const r = el.getBoundingClientRect();
        if ((r.width > 0 || r.height > 0) && !inView(r)) continue;
      }
      if (el.tagName === 'IFRAME' || el.tagName === 'FRAME') {
        flush();
        let where = '';
        try { const u = new URL(el.src, location.href); where = u.origin + u.pathname.slice(0, 60); } catch (e) { where = el.getAttribute('src') || ''; }
        if (frameEls.length < MAX_FRAMES) {
          frameEls.push(el);
          lines.push('iframe ' + JSON.stringify(clean(el.title, 60)) + ' src=' + where + ' (内容见下方 iframe 段)');
        } else {
          lines.push('iframe ' + JSON.stringify(clean(el.title, 60)) + ' src=' + where + ' (iframe 太多，未读取)');
        }
        continue;
      }
      if (el.matches(INTERACTIVE)) { flush(); emitInteractive(el); continue; }
      if (/^H[1-6]$/.test(el.tagName) && !el.querySelector(INTERACTIVE)) {
        const text = clean(el.innerText, 160);
        if (text) { flush(); lines.push('heading(' + el.tagName.toLowerCase() + ') ' + JSON.stringify(text)); }
        continue;
      }
      const display = getComputedStyle(el).display;
      const block = display !== 'inline' && display !== 'contents';
      if (block) flush();
      if (el.shadowRoot) walk(el.shadowRoot, depth + 1);
      walk(el, depth + 1);
      if (block) flush();
    }
  };
  walk(document.body || document.documentElement, 0);
  flush();
  return { lines, els, frameEls, frames: window.frames.length, truncated };
}
"""


# Page text, preferring the main content region over navigation and footers.
_PAGE_TEXT_JS = """
(wholePage) => {
  if (!document.body) return '';
  if (!wholePage) {
    const main = document.querySelector('main, [role=main]');
    if (main && main.innerText.trim().length > 200) return main.innerText;
    const articles = document.querySelectorAll('article');
    if (articles.length === 1 && articles[0].innerText.trim().length > 200) return articles[0].innerText;
  }
  return document.body.innerText;
}
"""


@dataclass
class _ProfileState:
    page: Any = None
    refs: dict[str, Any] = field(default_factory=dict)
    refs_page: Any = None
    snapshot_handles: list = field(default_factory=list)
    # True once the page loaded a new document after the last snapshot: its refs are dead.
    refs_stale: bool = False
    # Main-frame navigations seen on the current pages: how many have started,
    # and whether one is still waiting for its document to load.
    nav_counter: int = 0
    nav_pending: bool = False
    hooked: Any = field(default_factory=weakref.WeakSet)


def _check_url(url: str) -> str:
    url = (url or "").strip()
    if url == "about:blank":
        return url
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise PageControlError("invalid_argument", f"URL 不合法：{exc}") from exc
    if parts.scheme.lower() not in ALLOWED_SCHEMES or not parts.netloc:
        raise PageControlError(
            "invalid_argument", "只允许 http(s) 网址（或 about:blank）；file:、chrome:、javascript:、data: 一律拒绝。"
        )
    return url


def _live_pages(context: Any) -> list[Any]:
    return [page for page in context.pages if not page.is_closed()]


class PageController:
    """Page state for every profile; one instance lives in the Manager."""

    def __init__(self) -> None:
        self._states: dict[str, _ProfileState] = {}

    def forget(self, profile_id: str) -> None:
        self._states.pop(profile_id, None)

    # ── helpers ────────────────────────────────────────────────────────────

    def _state(self, profile_id: str) -> _ProfileState:
        return self._states.setdefault(profile_id, _ProfileState())

    def _use_page(self, profile_id: str, page: Any) -> Any:
        """Make ``page`` the current one and watch its navigations."""
        state = self._state(profile_id)
        state.page = page
        if page not in state.hooked:
            state.hooked.add(page)

            def on_request(request: Any) -> None:
                try:
                    if request.is_navigation_request() and request.frame == page.main_frame:
                        state.nav_counter += 1
                        state.nav_pending = True
                except Exception:  # service-worker or detached requests have no frame
                    pass

            def on_loaded(*_: Any) -> None:
                state.nav_pending = False
                if state.page is page:
                    state.refs.clear()  # a new document: element references from the old one are dead
                    state.refs_stale = True

            page.on("request", on_request)
            page.on("domcontentloaded", on_loaded)
            page.on("close", lambda *_: setattr(state, "nav_pending", False))
        return page

    async def _settle(self, profile_id: str, started_at: int) -> None:
        """After an action: give a navigation it caused a moment to start, then
        wait (bounded) until that navigation's document has loaded."""
        state = self._state(profile_id)
        await asyncio.sleep(0.3)
        if state.nav_counter == started_at and not state.nav_pending:
            return
        await self._wait_idle(profile_id)

    async def _wait_idle(self, profile_id: str) -> None:
        state = self._state(profile_id)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + SETTLE_TIMEOUT_S
        while state.nav_pending and loop.time() < deadline:
            await asyncio.sleep(0.1)

    async def _current_page(self, context: Any, profile_id: str, *, create: bool = True) -> Any:
        state = self._state(profile_id)
        if state.page is not None and not state.page.is_closed():
            return self._use_page(profile_id, state.page)
        pages = _live_pages(context)
        if pages:
            return self._use_page(profile_id, pages[-1])
        if create:
            return self._use_page(profile_id, await context.new_page())
        raise PageControlError("no_page", "这个画像没有打开的标签页。")

    def _tab_index(self, context: Any, page: Any) -> int:
        pages = _live_pages(context)
        return pages.index(page) if page in pages else -1

    async def _page_info(self, context: Any, page: Any) -> dict[str, Any]:
        try:
            title = await page.title()
        except PlaywrightError:
            title = ""
        return {"url": page.url, "title": title, "tab": self._tab_index(context, page)}

    async def _adopt_new_tab(self, context: Any, profile_id: str, before: list[Any]) -> bool:
        """After an action: if it opened a tab, make that the current one."""
        for page in _live_pages(context):
            if page not in before:
                self._use_page(profile_id, page)
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=5_000)
                except PlaywrightError:
                    pass
                return True
        return False

    @staticmethod
    def _wrap(exc: Exception, what: str) -> PageControlError:
        if isinstance(exc, PlaywrightTimeout):
            return PageControlError("timeout", f"{what}超时：{str(exc).splitlines()[0][:200]}")
        text = str(exc).splitlines()[0][:200] if str(exc) else type(exc).__name__
        if "Execution context was destroyed" in str(exc) or "navigation" in str(exc).lower():
            return PageControlError("page_navigating", f"页面正在跳转，稍等一下再试。（{text}）")
        if "not attached" in str(exc) or "detached" in str(exc):
            return PageControlError("stale_ref", f"页面已变化，元素引用失效。重新调用 browser_snapshot。（{text}）")
        return PageControlError("action_failed", f"{what}失败：{text}")

    def _element(self, profile_id: str, ref: str) -> Any:
        ref = (ref or "").strip()
        state = self._state(profile_id)
        if not ref:
            raise PageControlError("invalid_argument", "缺少 ref，先调用 browser_snapshot 拿元素引用。")
        element = state.refs.get(ref)
        if element is None and state.refs_stale:
            raise PageControlError(
                "stale_ref", f"页面已经跳转，{ref} 属于上一个页面。重新调用 browser_snapshot 取新的引用。"
            )
        if element is None:
            raise PageControlError(
                "unknown_ref", f"没有引用 {ref}。先调用 browser_snapshot，ref 只在最近一次快照内有效。"
            )
        return element

    # ── tabs ───────────────────────────────────────────────────────────────

    async def tabs(
        self, context: Any, profile_id: str, action: str = "list",
        index: int | None = None, url: str | None = None,
    ) -> dict[str, Any]:
        state = self._state(profile_id)
        try:
            if action == "list":
                current = await self._current_page(context, profile_id, create=False) if _live_pages(context) else None
                tabs = []
                for i, page in enumerate(_live_pages(context)):
                    info = await self._page_info(context, page)
                    tabs.append({"index": i, "url": info["url"], "title": info["title"], "current": page is current})
                return {"tabs": tabs}
            if action == "new":
                page = self._use_page(profile_id, await context.new_page())
                if url:
                    await page.goto(_check_url(url), wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                return await self._page_info(context, page)
            pages = _live_pages(context)
            if action in ("select", "close"):
                if index is None or not 0 <= int(index) < len(pages):
                    raise PageControlError("invalid_argument", f"index 超出范围（现有 {len(pages)} 个标签页，从 0 开始）。")
                page = pages[int(index)]
                if action == "select":
                    self._use_page(profile_id, page)
                    await page.bring_to_front()
                    return await self._page_info(context, page)
                await page.close()
                if state.page is page:
                    state.page = None
                return {"closed": int(index), "remaining": len(_live_pages(context))}
        except PageControlError:
            raise
        except (PlaywrightError, PlaywrightTimeout) as exc:
            raise self._wrap(exc, "标签页操作") from exc
        raise PageControlError("invalid_argument", "action 只能是 list/new/select/close。")

    # ── navigation ─────────────────────────────────────────────────────────

    async def navigate(self, context: Any, profile_id: str, url: str) -> dict[str, Any]:
        target = _check_url(url)
        page = await self._current_page(context, profile_id)
        try:
            response = await page.goto(target, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        except (PlaywrightError, PlaywrightTimeout) as exc:
            if isinstance(exc, PlaywrightTimeout):
                raise self._wrap(exc, "打开网页") from exc
            raise PageControlError("navigation_failed", f"打不开 {target}：{str(exc).splitlines()[0][:200]}") from exc
        info = await self._page_info(context, page)
        info["status"] = response.status if response is not None else None
        return info

    async def back(self, context: Any, profile_id: str) -> dict[str, Any]:
        page = await self._current_page(context, profile_id, create=False)
        try:
            await page.go_back(wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        except (PlaywrightError, PlaywrightTimeout) as exc:
            raise self._wrap(exc, "后退") from exc
        return await self._page_info(context, page)

    # ── reading ────────────────────────────────────────────────────────────

    async def snapshot(
        self, context: Any, profile_id: str, *, viewport_only: bool = False
    ) -> dict[str, Any]:
        page = await self._current_page(context, profile_id)
        state = self._state(profile_id)
        await self._wait_idle(profile_id)  # a navigation the last action started
        for attempt in range(3):
            try:
                lines, element_map, handles, frames, truncated = await self._collect(page, viewport_only)
                break
            except (PlaywrightError, PlaywrightTimeout) as exc:
                # The page navigated under us (a redirect, a slow submit): wait for the
                # new document and read again instead of failing the agent's call.
                if attempt < 2 and not isinstance(exc, PlaywrightTimeout) and "context was destroyed" in str(exc):
                    try:
                        await page.wait_for_load_state("domcontentloaded", timeout=int(SETTLE_TIMEOUT_S * 1000))
                    except PlaywrightError:
                        pass
                    continue
                raise self._wrap(exc, "读取页面") from exc
        for old in state.snapshot_handles:
            try:
                await old.dispose()
            except PlaywrightError:
                pass
        state.snapshot_handles = handles

        shown, size = [], 0
        for line in lines:
            if size + len(line) + 1 > MAX_TEXT_LEN:
                break
            shown.append(line)
            size += len(line) + 1
        omitted = len(lines) - len(shown)
        last_ref = max(
            (int(m.group(1)) for line in shown if (m := re.match(r"\[e(\d+)\]", line))), default=-1
        )
        state.refs = {ref: el for ref, el in element_map.items() if int(ref[1:]) <= last_ref}
        state.refs_stale = False
        state.refs_page = page
        more = bool(truncated) or omitted > 0
        if more:
            shown.append(
                f"… 页面还有内容没列出（{'视口内' if viewport_only else '整页'}）。"
                "往下 browser_scroll 后用 viewport_only=true 再快照，或用 browser_get_text 读正文。"
            )
        info = await self._page_info(context, page)
        return {
            **info,
            "elements": len(state.refs),
            "frames": frames,
            "truncated": more,
            "viewport_only": bool(viewport_only),
            "snapshot": "\n".join(shown),
        }

    async def _collect(self, page: Any, viewport_only: bool) -> tuple[list[str], dict[str, Any], list[Any], int, bool]:
        """Run the snapshot script in the page and in its visible iframes.

        Returns (lines, {ref: element}, handles to dispose later, frame count, truncated).
        Refs are numbered across frames, so a ref clicks the right element wherever it is.
        """
        handles: list[Any] = []
        element_map: dict[str, Any] = {}
        lines: list[str] = []

        async def run(target: Any, base: int) -> tuple[list[str], list[Any], int, bool]:
            args = [MAX_SNAPSHOT_ELEMENTS - base, MAX_SNAPSHOT_TEXT_LINES, bool(viewport_only), base]
            handle = await target.evaluate_handle(_SNAPSHOT_JS, args)
            handles.append(handle)
            props = await handle.get_properties()
            part_lines = await props["lines"].json_value()
            part_truncated = bool(await props["truncated"].json_value())
            frame_count = int(await props["frames"].json_value())
            els = await props["els"].get_properties()
            for key, element in els.items():
                node = element.as_element()
                if key.isdigit() and node is not None:
                    element_map[f"e{base + int(key)}"] = node
            frame_els: list[Any] = []
            frame_props = await props["frameEls"].get_properties()
            for item in frame_props.values():
                node = item.as_element()
                if node is not None:
                    frame_els.append(node)
            return part_lines, frame_els, frame_count, part_truncated

        main_lines, frame_els, frame_count, truncated = await run(page, 0)
        lines.extend(main_lines)
        for node in frame_els:
            if len(element_map) >= MAX_SNAPSHOT_ELEMENTS:
                truncated = True
                break
            try:
                frame = await node.content_frame()
                if frame is None:
                    continue
                part_lines, _, _, part_truncated = await run(frame, len(element_map))
            except (PlaywrightError, PlaywrightTimeout):
                lines.append("--- iframe 内容读取失败（可能正在加载或已被关闭）---")
                continue
            truncated = truncated or part_truncated
            lines.append(f"--- iframe {frame.url[:100]} ---")
            lines.extend(part_lines or ["（空）"])
        return lines, element_map, handles, frame_count, truncated

    async def get_text(
        self, context: Any, profile_id: str, *, ref: str | None = None,
        offset: int = 0, max_chars: int = TEXT_DEFAULT_CHARS, whole_page: bool = False,
    ) -> dict[str, Any]:
        """Plain text of the page (or one element) in pages of ``max_chars``.

        By default the page's main content is read when it has one (``<main>``,
        ``role=main`` or a single ``<article>``), which skips menus and footers;
        ``whole_page`` reads the full body.
        """
        page = await self._current_page(context, profile_id, create=False)
        await self._wait_idle(profile_id)
        offset = max(0, int(offset or 0))
        max_chars = max(100, min(int(max_chars or TEXT_DEFAULT_CHARS), TEXT_MAX_CHARS))
        try:
            if ref:
                text = await self._element(profile_id, ref).inner_text(timeout=ACTION_TIMEOUT_MS)
            else:
                text = await page.evaluate(_PAGE_TEXT_JS, bool(whole_page))
        except (PlaywrightError, PlaywrightTimeout) as exc:
            raise self._wrap(exc, "读取文字") from exc
        text = re.sub(r"\n{3,}", "\n\n", text or "")
        chunk = text[offset : offset + max_chars]
        end = offset + len(chunk)
        info = await self._page_info(context, page)
        return {
            **info,
            "text": chunk,
            "offset": offset,
            "total_chars": len(text),
            "next_offset": end if end < len(text) else None,
        }

    async def screenshot(
        self, context: Any, profile_id: str, *, full_page: bool = False, fmt: str = "jpeg"
    ) -> dict[str, Any]:
        if fmt not in ("jpeg", "png"):
            raise PageControlError("invalid_argument", "format 只能是 jpeg 或 png。")
        page = await self._current_page(context, profile_id, create=False)
        try:
            kwargs: dict[str, Any] = {"type": fmt, "full_page": full_page, "timeout": ACTION_TIMEOUT_MS * 2}
            if fmt == "jpeg":
                kwargs["quality"] = 80
            data = await page.screenshot(**kwargs)
        except (PlaywrightError, PlaywrightTimeout) as exc:
            raise self._wrap(exc, "截图") from exc
        info = await self._page_info(context, page)
        return {
            **info,
            "image": {"mime": f"image/{fmt}", "data": base64.b64encode(data).decode("ascii"), "bytes": len(data)},
        }

    # ── acting ─────────────────────────────────────────────────────────────

    async def click(self, context: Any, profile_id: str, ref: str) -> dict[str, Any]:
        element = self._element(profile_id, ref)
        page = await self._current_page(context, profile_id)
        before = _live_pages(context)
        started = self._state(profile_id).nav_counter
        try:
            await element.scroll_into_view_if_needed(timeout=ACTION_TIMEOUT_MS)
            await element.click(timeout=ACTION_TIMEOUT_MS)
            await self._settle(profile_id, started)  # a click may start a navigation
            new_tab = await self._adopt_new_tab(context, profile_id, before)
        except (PlaywrightError, PlaywrightTimeout) as exc:
            raise self._wrap(exc, f"点击 {ref} ") from exc
        info = await self._page_info(context, self._state(profile_id).page or page)
        info["new_tab"] = new_tab
        return info

    async def type_text(
        self, context: Any, profile_id: str, ref: str, text: str, *, submit: bool = False
    ) -> dict[str, Any]:
        element = self._element(profile_id, ref)
        page = await self._current_page(context, profile_id)
        if not isinstance(text, str):
            raise PageControlError("invalid_argument", "text 必须是字符串。")
        try:
            tag = await element.evaluate("e => e.tagName.toLowerCase()")
            if tag == "select":
                await element.select_option(label=text, timeout=ACTION_TIMEOUT_MS)
            else:
                await element.fill(text, timeout=ACTION_TIMEOUT_MS)
            if submit:
                started = self._state(profile_id).nav_counter
                await element.press("Enter", timeout=ACTION_TIMEOUT_MS)
                await self._settle(profile_id, started)
        except (PlaywrightError, PlaywrightTimeout) as exc:
            raise self._wrap(exc, f"输入 {ref} ") from exc
        return await self._page_info(context, page)

    async def press_key(self, context: Any, profile_id: str, key: str) -> dict[str, Any]:
        key = (key or "").strip()
        if not key:
            raise PageControlError("invalid_argument", "缺少 key（如 Enter、Tab、Escape、ArrowDown、Control+A）。")
        page = await self._current_page(context, profile_id)
        started = self._state(profile_id).nav_counter
        try:
            await page.keyboard.press(key)
            await self._settle(profile_id, started)  # Enter may submit a form
        except (PlaywrightError, PlaywrightTimeout) as exc:
            raise self._wrap(exc, f"按键 {key} ") from exc
        return await self._page_info(context, page)

    async def scroll(
        self, context: Any, profile_id: str, direction: str = "down", amount: int = SCROLL_DEFAULT_PX
    ) -> dict[str, Any]:
        deltas = {"down": (0, 1), "up": (0, -1), "right": (1, 0), "left": (-1, 0)}
        if direction not in deltas:
            raise PageControlError("invalid_argument", "direction 只能是 up/down/left/right。")
        amount = max(1, min(int(amount), 5000))
        page = await self._current_page(context, profile_id)
        dx, dy = deltas[direction]
        try:
            await page.mouse.wheel(dx * amount, dy * amount)
        except (PlaywrightError, PlaywrightTimeout) as exc:
            raise self._wrap(exc, "滚动") from exc
        return await self._page_info(context, page)

    async def wait_for(
        self, context: Any, profile_id: str, *, text: str | None = None, ms: int | None = None
    ) -> dict[str, Any]:
        page = await self._current_page(context, profile_id)
        try:
            if text:
                await page.get_by_text(text).first.wait_for(state="visible", timeout=MAX_WAIT_MS)
            elif ms is not None:
                await page.wait_for_timeout(max(0, min(int(ms), MAX_WAIT_MS)))
            else:
                raise PageControlError("invalid_argument", "text 和 ms 至少给一个。")
        except PageControlError:
            raise
        except (PlaywrightError, PlaywrightTimeout) as exc:
            raise self._wrap(exc, "等待") from exc
        return await self._page_info(context, page)
