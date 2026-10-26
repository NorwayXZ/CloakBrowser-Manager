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
import time
import weakref
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeout

logger = logging.getLogger("cloakbrowser.manager.page_control")

ALLOWED_SCHEMES = frozenset({"http", "https"})
_REF_RE = re.compile(r"^e\d+$")
_SELECTOR_RE = re.compile(r"^(text|role|label|placeholder|css)=(.*)$", re.S)
_ROLE_RE = re.compile(r"^([A-Za-z][\w-]*)(?:\[name=(?:\"([^\"]*)\"|'([^']*)'|([^\]]*))\])?$")
NAV_TIMEOUT_MS = 30_000
ACTION_TIMEOUT_MS = 10_000
MAX_WAIT_MS = 30_000
MAX_SNAPSHOT_ELEMENTS = 400
MAX_SNAPSHOT_TEXT_LINES = 250
SCROLL_DEFAULT_PX = 600
MAX_TEXT_LEN = 20_000
MAX_BATCH_STEPS = 20
MAX_UPLOAD_FILES = 10
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_DOWNLOAD_RECORDS = 50
DOWNLOAD_WAIT_S = 15.0
_BATCH_VERBS = frozenset(
    {"navigate", "click", "type", "press_key", "scroll", "wait_for", "back", "get_text", "dialog", "tabs", "upload"}
)
SETTLE_TIMEOUT_S = 10.0
DIALOG_AUTO_DISMISS_S = 120.0
TEXT_DEFAULT_CHARS = 6_000
TEXT_MAX_CHARS = 20_000


# Returned by _guarded when the action opened a JS dialog before it could finish.
_DIALOG = object()


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
    downloads: list = field(default_factory=list)
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

    def __init__(self, files_dir: Path | None = None) -> None:
        self._states: dict[str, _ProfileState] = {}
        # The only folder agents may upload from and the one downloads land in.
        self._files_dir = files_dir
        # JS dialogs (alert/confirm/prompt/beforeunload) waiting for the agent, per page.
        self._dialogs: "weakref.WeakKeyDictionary[Any, Any]" = weakref.WeakKeyDictionary()
        self._dialog_events: "weakref.WeakKeyDictionary[Any, asyncio.Event]" = weakref.WeakKeyDictionary()
        self._dialog_timers: "weakref.WeakKeyDictionary[Any, Any]" = weakref.WeakKeyDictionary()
        self._background: set[Any] = set()  # actions left running behind an open dialog

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

            def on_dialog(dialog: Any) -> None:
                # An open dialog freezes the page; keep it for browser_dialog and make
                # sure a vanished agent cannot leave the page frozen for good.
                self._dialogs[page] = dialog
                self._dialog_events.setdefault(page, asyncio.Event()).set()
                timer = asyncio.get_running_loop().call_later(
                    DIALOG_AUTO_DISMISS_S, lambda: asyncio.ensure_future(self._auto_dismiss(page, dialog))
                )
                self._dialog_timers[page] = timer

            def on_download(download: Any) -> None:
                # Register the record right away, so a list call made a moment later sees it.
                record: dict[str, Any] = {"filename": None, "path": None, "bytes": None, "status": "saving", "url": None}
                state.downloads.append(record)
                del state.downloads[:-MAX_DOWNLOAD_RECORDS]
                asyncio.ensure_future(self._save_download(profile_id, download, record))

            page.on("request", on_request)
            page.on("dialog", on_dialog)
            page.on("download", on_download)
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

    @staticmethod
    def _describe_dialog(dialog: Any) -> dict[str, Any]:
        return {"type": dialog.type, "message": dialog.message, "default_value": dialog.default_value or None}

    async def _page_info(self, context: Any, page: Any) -> dict[str, Any]:
        dialog = self._dialogs.get(page)
        if dialog is not None:
            # An open dialog blocks page.title(); report the dialog instead.
            return {
                "url": page.url, "title": "", "tab": self._tab_index(context, page),
                "dialog": self._describe_dialog(dialog),
                "dialog_hint": "页面被一个 JS 对话框挡住了，先调 browser_dialog(accept 或 dismiss)。",
            }
        try:
            title = await page.title()
        except PlaywrightError:
            title = ""
        return {"url": page.url, "title": title, "tab": self._tab_index(context, page)}

    def _raise_if_dialog(self, page: Any) -> None:
        dialog = self._dialogs.get(page)
        if dialog is not None:
            raise PageControlError(
                "dialog_open",
                f"页面有一个未处理的 {dialog.type} 对话框：{dialog.message[:120]!r}。先调 browser_dialog。",
            )

    async def _auto_dismiss(self, page: Any, dialog: Any) -> None:
        if self._dialogs.get(page) is not dialog:
            return
        self._dialogs.pop(page, None)
        try:
            await dialog.dismiss()
        except PlaywrightError:
            pass

    async def _guarded(self, page: Any, awaitable: Any) -> Any:
        """Run a page action; if it opens a JS dialog first (which freezes the page and
        would hang the action) return ``_DIALOG`` and let the action finish behind it."""
        event = self._dialog_events.setdefault(page, asyncio.Event())
        event.clear()
        task = asyncio.ensure_future(awaitable)
        waiter = asyncio.ensure_future(event.wait())
        try:
            done, _ = await asyncio.wait({task, waiter}, return_when=asyncio.FIRST_COMPLETED)
        except asyncio.CancelledError:
            task.cancel()
            waiter.cancel()
            raise
        waiter.cancel()
        if task in done:
            return task.result()
        self._background.add(task)
        task.add_done_callback(self._background.discard)
        task.add_done_callback(lambda t: t.cancelled() or t.exception())  # consume late errors
        return _DIALOG

    async def dialog(
        self, context: Any, profile_id: str, action: str, text: str | None = None
    ) -> dict[str, Any]:
        if action not in ("accept", "dismiss"):
            raise PageControlError("invalid_argument", "action 只能是 accept 或 dismiss。")
        state = self._state(profile_id)
        candidates = [state.page, *_live_pages(context)]
        page = next((p for p in candidates if p is not None and p in self._dialogs), None)
        if page is None:
            raise PageControlError("no_dialog", "现在没有待处理的 JS 对话框。")
        dialog = self._dialogs[page]
        described = self._describe_dialog(dialog)
        try:
            if action == "accept":
                await dialog.accept(text) if text is not None else await dialog.accept()
            else:
                await dialog.dismiss()
        except (PlaywrightError, PlaywrightTimeout) as exc:
            raise self._wrap(exc, "处理对话框") from exc
        finally:
            self._dialogs.pop(page, None)
            timer = self._dialog_timers.pop(page, None)
            if timer is not None:
                timer.cancel()
            event = self._dialog_events.get(page)
            if event is not None:
                event.clear()
        await asyncio.sleep(0.3)  # the action that raised it can finish now
        info = await self._page_info(context, page)
        return {**info, "handled": action, "handled_dialog": described}

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

    @staticmethod
    def _locator(page: Any, selector: str) -> Any:
        """A Playwright locator for ``text=…`` / ``role=…`` / ``label=…`` / ``placeholder=…`` / ``css=…``."""
        match = _SELECTOR_RE.match(selector)
        if match is None:
            raise PageControlError(
                "invalid_argument",
                f"看不懂选择器「{selector}」。用快照里的 ref（如 e3），或 text=… / role=button[name=\"…\"] / "
                "label=… / placeholder=… / css=…",
            )
        kind, value = match.group(1), match.group(2).strip()
        if not value:
            raise PageControlError("invalid_argument", f"选择器 {kind}= 后面不能为空。")
        if kind == "text":
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                return page.get_by_text(value[1:-1], exact=True)
            return page.get_by_text(value)
        if kind == "role":
            role_match = _ROLE_RE.match(value)
            if role_match is None:
                raise PageControlError("invalid_argument", "role 选择器写法：role=button 或 role=button[name=\"登录\"]。")
            name = role_match.group(2) or role_match.group(3) or role_match.group(4)
            return page.get_by_role(role_match.group(1), name=name) if name else page.get_by_role(role_match.group(1))
        if kind == "label":
            return page.get_by_label(value)
        if kind == "placeholder":
            return page.get_by_placeholder(value)
        return page.locator(value)

    async def _target(self, page: Any, profile_id: str, ref: str, *, visible_only: bool = True) -> Any:
        """The element a ``ref`` names: a snapshot ref (``e3``) or a semantic selector.

        Selectors must match exactly one visible element in the top document, so a
        vague one fails loudly instead of clicking the wrong thing. ``visible_only=False``
        also considers hidden elements (file inputs are usually hidden behind a button).
        """
        ref = (ref or "").strip()
        if not ref or _REF_RE.match(ref):
            return self._element(profile_id, ref)
        try:
            locator = self._locator(page, ref)
            if visible_only:
                locator = locator.filter(visible=True)
            count = await locator.count()
            if count == 0:
                raise PageControlError("selector_not_found", f"页面上没有可见元素匹配 {ref}。先 browser_snapshot 看看页面现状。")
            if count > 1:
                raise PageControlError(
                    "ambiguous_selector",
                    f"{ref} 匹配到 {count} 个元素，写得更具体一些（加上 name=…），或者用 browser_snapshot 里的 ref。",
                )
            return await locator.element_handle(timeout=ACTION_TIMEOUT_MS)
        except PageControlError:
            raise
        except (PlaywrightError, PlaywrightTimeout) as exc:
            raise PageControlError("invalid_argument", f"选择器 {ref} 不可用：{str(exc).splitlines()[0][:160]}") from exc

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
        self._raise_if_dialog(page)
        try:
            response = await self._guarded(page, page.goto(target, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS))
            if response is _DIALOG:  # e.g. a beforeunload prompt on the page being left
                return await self._page_info(context, page)
        except (PlaywrightError, PlaywrightTimeout) as exc:
            if isinstance(exc, PlaywrightTimeout):
                raise self._wrap(exc, "打开网页") from exc
            raise PageControlError("navigation_failed", f"打不开 {target}：{str(exc).splitlines()[0][:200]}") from exc
        info = await self._page_info(context, page)
        info["status"] = response.status if response is not None else None
        return info

    async def back(self, context: Any, profile_id: str) -> dict[str, Any]:
        page = await self._current_page(context, profile_id, create=False)
        self._raise_if_dialog(page)
        try:
            await self._guarded(page, page.go_back(wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS))
        except (PlaywrightError, PlaywrightTimeout) as exc:
            raise self._wrap(exc, "后退") from exc
        return await self._page_info(context, page)

    # ── reading ────────────────────────────────────────────────────────────

    async def snapshot(
        self, context: Any, profile_id: str, *, viewport_only: bool = False
    ) -> dict[str, Any]:
        page = await self._current_page(context, profile_id)
        state = self._state(profile_id)
        self._raise_if_dialog(page)
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
        self._raise_if_dialog(page)
        await self._wait_idle(profile_id)
        offset = max(0, int(offset or 0))
        max_chars = max(100, min(int(max_chars or TEXT_DEFAULT_CHARS), TEXT_MAX_CHARS))
        try:
            if ref:
                text = await (await self._target(page, profile_id, ref)).inner_text()
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
        self._raise_if_dialog(page)
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
        page = await self._current_page(context, profile_id)
        self._raise_if_dialog(page)
        element = await self._target(page, profile_id, ref)
        before = _live_pages(context)
        started = self._state(profile_id).nav_counter
        try:
            await element.scroll_into_view_if_needed(timeout=ACTION_TIMEOUT_MS)
            clicked = await self._guarded(page, element.click(timeout=ACTION_TIMEOUT_MS))
            if clicked is _DIALOG:  # the click raised an alert/confirm: the page is frozen until handled
                return {**await self._page_info(context, page), "new_tab": False}
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
        page = await self._current_page(context, profile_id)
        self._raise_if_dialog(page)
        element = await self._target(page, profile_id, ref)
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
                pressed = await self._guarded(page, element.press("Enter", timeout=ACTION_TIMEOUT_MS))
                if pressed is _DIALOG:
                    return await self._page_info(context, page)
                await self._settle(profile_id, started)
        except (PlaywrightError, PlaywrightTimeout) as exc:
            raise self._wrap(exc, f"输入 {ref} ") from exc
        return await self._page_info(context, page)

    async def press_key(self, context: Any, profile_id: str, key: str) -> dict[str, Any]:
        key = (key or "").strip()
        if not key:
            raise PageControlError("invalid_argument", "缺少 key（如 Enter、Tab、Escape、ArrowDown、Control+A）。")
        page = await self._current_page(context, profile_id)
        self._raise_if_dialog(page)
        started = self._state(profile_id).nav_counter
        try:
            pressed = await self._guarded(page, page.keyboard.press(key))
            if pressed is _DIALOG:
                return await self._page_info(context, page)
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
        self._raise_if_dialog(page)
        dx, dy = deltas[direction]
        try:
            await page.mouse.wheel(dx * amount, dy * amount)
        except (PlaywrightError, PlaywrightTimeout) as exc:
            raise self._wrap(exc, "滚动") from exc
        return await self._page_info(context, page)

    async def wait_for(
        self, context: Any, profile_id: str, *, text: str | None = None, ms: int | None = None,
        text_gone: str | None = None, url: str | None = None, selector: str | None = None,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        """Wait until every given condition holds (each bounded by ``timeout_ms``).

        ``text`` appears, ``text_gone`` disappears, the URL contains ``url``, a
        semantic ``selector`` becomes visible, or just ``ms`` pass.
        """
        if not (text or text_gone or url or selector or ms is not None):
            raise PageControlError("invalid_argument", "text、text_gone、url、selector、ms 至少给一个。")
        timeout = max(100, min(int(timeout_ms or 15_000), MAX_WAIT_MS))
        page = await self._current_page(context, profile_id)
        self._raise_if_dialog(page)
        try:
            if text:
                await self._wait_condition(
                    page.get_by_text(text).first.wait_for(state="visible", timeout=timeout), f"文字「{text}」出现", timeout
                )
            if text_gone:
                await self._wait_condition(
                    page.get_by_text(text_gone).first.wait_for(state="hidden", timeout=timeout), f"文字「{text_gone}」消失", timeout
                )
            if url:
                await self._wait_condition(
                    page.wait_for_url(re.compile(re.escape(url)), timeout=timeout, wait_until="commit"),
                    f"网址包含「{url}」", timeout,
                )
            if selector:
                if _REF_RE.match(selector.strip()):
                    raise PageControlError("invalid_argument", "selector 要写语义选择器（text=… / role=… / css=…），不能用快照 ref。")
                await self._wait_condition(
                    self._locator(page, selector.strip()).first.wait_for(state="visible", timeout=timeout),
                    f"元素 {selector} 出现", timeout,
                )
            if ms is not None:
                await page.wait_for_timeout(max(0, min(int(ms), MAX_WAIT_MS)))
        except PageControlError:
            raise
        except (PlaywrightError, PlaywrightTimeout) as exc:
            raise self._wrap(exc, "等待") from exc
        return await self._page_info(context, page)

    @staticmethod
    async def _wait_condition(awaitable: Any, what: str, timeout: int) -> None:
        try:
            await awaitable
        except PlaywrightTimeout as exc:
            raise PageControlError("timeout", f"等待{what}超时（{timeout} ms）。browser_snapshot 看看页面现状。") from exc

    # ── batch ──────────────────────────────────────────────────────────────

    async def batch(
        self, context: Any, profile_id: str, steps: Any, *,
        snapshot_after: bool = True, viewport_only: bool = False, stop_on_error: bool = True,
    ) -> dict[str, Any]:
        """Run up to ``MAX_BATCH_STEPS`` page actions in one call.

        Each step is ``{"do": <verb>, ...}`` with the verb's own parameters
        (``dialog`` uses ``answer``/``text``; ``tabs`` uses ``tab_action``/``index``/``url``).
        A step that fails, or that raises a JS dialog the next step does not
        handle, stops the run; a snapshot of where it ended up is appended.
        """
        if not isinstance(steps, list) or not steps:
            raise PageControlError("invalid_argument", "steps 必须是非空数组，每项形如 {\"do\": \"click\", \"ref\": \"e3\"}。")
        if len(steps) > MAX_BATCH_STEPS:
            raise PageControlError("invalid_argument", f"一次最多 {MAX_BATCH_STEPS} 步，拆成几批。")
        for index, step in enumerate(steps):
            verb = step.get("do") if isinstance(step, dict) else None
            if verb not in _BATCH_VERBS:
                raise PageControlError(
                    "invalid_argument",
                    f"第 {index} 步的 do 必须是 {'/'.join(sorted(_BATCH_VERBS))} 之一（读页面用 snapshot_after，截图单独调）。",
                )

        records: list[dict[str, Any]] = []
        last: dict[str, Any] = {}
        stopped: str | None = None
        stopped_at: int | None = None
        for index, step in enumerate(steps):
            verb = step["do"]
            record: dict[str, Any] = {"i": index, "do": verb}
            try:
                result = await self._run_step(context, profile_id, verb, step)
            except PageControlError as exc:
                record.update(ok=False, reason=exc.reason, detail=exc.detail)
                records.append(record)
                if stop_on_error:
                    stopped, stopped_at = "error", index
                    break
                continue
            record["ok"] = True
            if verb == "get_text":
                record["text"] = result.get("text")
                record["next_offset"] = result.get("next_offset")
            if result.get("dialog"):
                record["dialog"] = result["dialog"]
            records.append(record)
            last = result
            nxt = steps[index + 1] if index + 1 < len(steps) else None
            if result.get("dialog") and not (nxt and nxt.get("do") == "dialog"):
                stopped, stopped_at = "dialog", index
                break

        out: dict[str, Any] = {
            "steps": records,
            "completed": sum(1 for r in records if r.get("ok")),
            "total": len(steps),
            "stopped": stopped,
            "stopped_at": stopped_at,
        }
        if snapshot_after and stopped != "dialog":
            try:
                snap = await self.snapshot(context, profile_id, viewport_only=viewport_only)
                out.update(snap)
            except PageControlError as exc:
                out["snapshot_error"] = {"reason": exc.reason, "detail": exc.detail}
        else:
            page = await self._current_page(context, profile_id, create=False)
            out.update(await self._page_info(context, page))
        if last.get("dialog") and "dialog" not in out:
            out["dialog"] = last["dialog"]
        return out

    async def _run_step(self, context: Any, profile_id: str, verb: str, step: dict[str, Any]) -> dict[str, Any]:
        def arg(name: str, default: Any = None) -> Any:
            value = step.get(name)
            return default if value is None else value

        if verb == "navigate":
            return await self.navigate(context, profile_id, str(arg("url", "")))
        if verb == "click":
            return await self.click(context, profile_id, str(arg("ref", "")))
        if verb == "type":
            return await self.type_text(context, profile_id, str(arg("ref", "")), arg("text"), submit=bool(arg("submit", False)))
        if verb == "press_key":
            return await self.press_key(context, profile_id, str(arg("key", "")))
        if verb == "scroll":
            return await self.scroll(context, profile_id, str(arg("direction", "down")), int(arg("amount", SCROLL_DEFAULT_PX)))
        if verb == "wait_for":
            return await self.wait_for(
                context, profile_id, text=arg("text"), ms=arg("ms"), text_gone=arg("text_gone"),
                url=arg("url"), selector=arg("selector"), timeout_ms=arg("timeout_ms"),
            )
        if verb == "back":
            return await self.back(context, profile_id)
        if verb == "get_text":
            return await self.get_text(
                context, profile_id, ref=arg("ref"), offset=int(arg("offset", 0)),
                max_chars=int(arg("max_chars", TEXT_DEFAULT_CHARS)), whole_page=bool(arg("whole_page", False)),
            )
        if verb == "dialog":
            return await self.dialog(context, profile_id, str(arg("answer", "")), arg("text"))
        if verb == "upload":
            return await self.upload(context, profile_id, str(arg("ref", "")), arg("paths"))
        if verb == "tabs":
            return await self.tabs(
                context, profile_id, str(arg("tab_action", "list")), index=arg("index"), url=arg("url")
            )
        raise PageControlError("invalid_argument", f"不支持的步骤 {verb}")

    # ── files ──────────────────────────────────────────────────────────────

    def _require_files_dir(self) -> Path:
        if self._files_dir is None:
            raise PageControlError("files_disabled", "这个 Manager 没有配置 agent 文件目录，上传下载不可用。")
        return self._files_dir

    async def _save_download(self, profile_id: str, download: Any, record: dict[str, Any]) -> None:
        """Save a download the page started into ``<files>/downloads/<profile>/``."""
        try:
            folder = self._require_files_dir() / "downloads" / profile_id
            folder.mkdir(parents=True, exist_ok=True)
            name = _safe_filename(download.suggested_filename)
            target = folder / f"{int(time.time())}-{name}"
            record["filename"] = name
            record["url"] = str(download.url).split("?", 1)[0][:200]
            await download.save_as(str(target))
            record.update(path=str(target), bytes=target.stat().st_size, status="done")
        except Exception as exc:  # a failed download must never take the Manager down
            record.update(status="failed", error=str(exc).splitlines()[0][:160] if str(exc) else type(exc).__name__)

    async def downloads(self, context: Any, profile_id: str) -> dict[str, Any]:
        """Files the profile downloaded (waits briefly for ones still being saved)."""
        folder = self._require_files_dir()
        state = self._state(profile_id)
        await asyncio.sleep(0.3)  # a download the last click started may still be arriving
        loop = asyncio.get_running_loop()
        deadline = loop.time() + DOWNLOAD_WAIT_S
        while any(r["status"] == "saving" for r in state.downloads) and loop.time() < deadline:
            await asyncio.sleep(0.2)
        return {
            "files_dir": str(folder),
            "downloads": list(reversed(state.downloads)),
            "note": "下载的文件保存在 files_dir 下；要上传的文件也必须放在 files_dir 里（browser_upload 只认这个目录）。",
        }

    def _upload_paths(self, paths: Any) -> list[str]:
        folder = self._require_files_dir().resolve()
        if not isinstance(paths, list) or not paths or not all(isinstance(p, str) and p for p in paths):
            raise PageControlError("invalid_argument", "paths 必须是非空的路径字符串数组。")
        if len(paths) > MAX_UPLOAD_FILES:
            raise PageControlError("invalid_argument", f"一次最多上传 {MAX_UPLOAD_FILES} 个文件。")
        resolved = []
        for raw in paths:
            path = Path(raw).expanduser().resolve()
            if not path.is_relative_to(folder):
                raise PageControlError(
                    "path_not_allowed",
                    f"只允许上传 {folder} 里的文件（防止把本机其他文件传给网站）。先把文件复制到那个目录。",
                )
            if not path.is_file():
                raise PageControlError("invalid_argument", f"文件不存在：{path}")
            if path.stat().st_size > MAX_UPLOAD_BYTES:
                raise PageControlError("invalid_argument", f"{path.name} 超过 {MAX_UPLOAD_BYTES // 1024 // 1024} MB。")
            resolved.append(str(path))
        return resolved

    async def upload(self, context: Any, profile_id: str, ref: str, paths: Any) -> dict[str, Any]:
        """Attach files to a file input, or to the chooser a button opens."""
        files = self._upload_paths(paths)
        page = await self._current_page(context, profile_id)
        self._raise_if_dialog(page)
        element = await self._target(page, profile_id, ref, visible_only=False)
        try:
            is_file_input = await element.evaluate("e => e.tagName === 'INPUT' && e.type === 'file'")
            if is_file_input:
                await element.set_input_files(files, timeout=ACTION_TIMEOUT_MS)
            else:
                async with page.expect_file_chooser(timeout=ACTION_TIMEOUT_MS) as chooser_info:
                    await element.click(timeout=ACTION_TIMEOUT_MS)
                chooser = await chooser_info.value
                await chooser.set_files(files)
        except (PlaywrightError, PlaywrightTimeout) as exc:
            raise self._wrap(exc, f"上传到 {ref} ") from exc
        info = await self._page_info(context, page)
        return {**info, "uploaded": [Path(f).name for f in files]}


def _safe_filename(name: str | None) -> str:
    cleaned = re.sub(r"[^\w.\- ()\u4e00-\u9fff]", "_", (name or "download").replace("\\", "/").split("/")[-1])
    cleaned = cleaned.strip(" .") or "download"
    return cleaned[:120]
