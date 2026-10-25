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
MAX_SNAPSHOT_ELEMENTS = 300
MAX_SNAPSHOT_TEXT_LINES = 80
SCROLL_DEFAULT_PX = 600
MAX_TEXT_LEN = 20_000


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
([maxEls, maxText]) => {
  const INTERACTIVE = 'a[href],button,input,select,textarea,summary,[role=button],[role=link],'
    + '[role=checkbox],[role=tab],[role=menuitem],[role=switch],[role=option],[role=radio],'
    + '[contenteditable=""],[contenteditable=true]';
  const SKIP = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'HEAD', 'SVG', 'CANVAS', 'META', 'LINK', 'IFRAME']);
  const MAX_NODES = 8000;
  const clean = (s, n) => (s || '').replace(/\\s+/g, ' ').trim().slice(0, n);
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
    if (!n) n = el.title || el.alt || el.placeholder || el.name || el.id || '';
    return clean(n, 80);
  };
  const els = [];
  const lines = [];
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
    const ref = 'e' + els.length;
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
      try { const u = new URL(el.href); bits.push('href=' + u.origin + u.pathname.slice(0, 80)); } catch (e) {}
    }
    if (el.disabled) bits.push('disabled');
    lines.push('[' + ref + '] ' + roleOf(el) + ' ' + JSON.stringify(nameOf(el)) + (bits.length ? ' ' + bits.join(' ') : ''));
  };
  const walk = (root, depth) => {
    for (let node = root.firstChild; node; node = node.nextSibling) {
      if (++visited > MAX_NODES || depth > 80) { truncated = true; return; }
      if (node.nodeType === 3) {
        if (node.nodeValue && node.nodeValue.trim()) pending += ' ' + node.nodeValue;
        if (pending.length > 200) flush();
        continue;
      }
      if (node.nodeType !== 1) continue;
      const el = node;
      if (SKIP.has(el.tagName.toUpperCase())) continue;
      if (!visible(el)) continue;
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
  return { lines, els, frames: window.frames.length, truncated };
}
"""


@dataclass
class _ProfileState:
    page: Any = None
    refs: dict[str, Any] = field(default_factory=dict)
    refs_page: Any = None
    snapshot_handle: Any = None


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

    async def _current_page(self, context: Any, profile_id: str, *, create: bool = True) -> Any:
        state = self._state(profile_id)
        if state.page is not None and not state.page.is_closed():
            return state.page
        pages = _live_pages(context)
        if pages:
            state.page = pages[-1]
        elif create:
            state.page = await context.new_page()
        else:
            raise PageControlError("no_page", "这个画像没有打开的标签页。")
        return state.page

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
                self._state(profile_id).page = page
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
        if "not attached" in str(exc) or "detached" in str(exc) or "Execution context was destroyed" in str(exc):
            return PageControlError("stale_ref", f"页面已变化，元素引用失效。重新调用 browser_snapshot。（{text}）")
        return PageControlError("action_failed", f"{what}失败：{text}")

    def _element(self, profile_id: str, ref: str) -> Any:
        ref = (ref or "").strip()
        state = self._state(profile_id)
        if not ref:
            raise PageControlError("invalid_argument", "缺少 ref，先调用 browser_snapshot 拿元素引用。")
        element = state.refs.get(ref)
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
                page = await context.new_page()
                state.page = page
                if url:
                    await page.goto(_check_url(url), wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                return await self._page_info(context, page)
            pages = _live_pages(context)
            if action in ("select", "close"):
                if index is None or not 0 <= int(index) < len(pages):
                    raise PageControlError("invalid_argument", f"index 超出范围（现有 {len(pages)} 个标签页，从 0 开始）。")
                page = pages[int(index)]
                if action == "select":
                    state.page = page
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

    async def snapshot(self, context: Any, profile_id: str) -> dict[str, Any]:
        page = await self._current_page(context, profile_id)
        state = self._state(profile_id)
        try:
            handle = await page.evaluate_handle(_SNAPSHOT_JS, [MAX_SNAPSHOT_ELEMENTS, MAX_SNAPSHOT_TEXT_LINES])
            props = await handle.get_properties()
            lines = await props["lines"].json_value()
            frames = await props["frames"].json_value()
            truncated = await props["truncated"].json_value()
            element_props = await props["els"].get_properties()
        except (PlaywrightError, PlaywrightTimeout) as exc:
            raise self._wrap(exc, "读取页面") from exc
        if state.snapshot_handle is not None:
            try:
                await state.snapshot_handle.dispose()
            except PlaywrightError:
                pass
        state.snapshot_handle = handle
        state.refs = {
            f"e{key}": element.as_element()
            for key, element in element_props.items()
            if key.isdigit() and element.as_element() is not None
        }
        state.refs_page = page
        info = await self._page_info(context, page)
        return {
            **info,
            "elements": len(state.refs),
            "frames": frames,
            "truncated": bool(truncated),
            "snapshot": "\n".join(lines)[:MAX_TEXT_LEN],
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
        try:
            await element.scroll_into_view_if_needed(timeout=ACTION_TIMEOUT_MS)
            await element.click(timeout=ACTION_TIMEOUT_MS)
            await asyncio.sleep(0.3)  # let a click-triggered tab or navigation start
            new_tab = await self._adopt_new_tab(context, profile_id, before)
            target = self._state(profile_id).page or page
            if not new_tab:
                try:
                    await target.wait_for_load_state("domcontentloaded", timeout=3_000)
                except PlaywrightError:
                    pass
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
                await element.press("Enter", timeout=ACTION_TIMEOUT_MS)
                await asyncio.sleep(0.3)
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=3_000)
                except PlaywrightError:
                    pass
        except (PlaywrightError, PlaywrightTimeout) as exc:
            raise self._wrap(exc, f"输入 {ref} ") from exc
        return await self._page_info(context, page)

    async def press_key(self, context: Any, profile_id: str, key: str) -> dict[str, Any]:
        key = (key or "").strip()
        if not key:
            raise PageControlError("invalid_argument", "缺少 key（如 Enter、Tab、Escape、ArrowDown、Control+A）。")
        page = await self._current_page(context, profile_id)
        try:
            await page.keyboard.press(key)
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
