"""Leave the panel open and busy for a while, and see whether its memory keeps growing.

Own Manager on a throwaway data directory, example data, no browser launched.
One page stays open and moves between the main pages (the panel is a single-page
app, so every move mounts and unmounts a page, which is where leaks show) while
the 3-second status polling and the 1-second job polling keep running. After a
forced garbage collection the script samples the JS heap, the DOM node count
and the number of event listeners; a steady climb across the run is a leak.

    python scripts/soak_panel.py [minutes]        (default 10)

This is a compressed stand-in for "leave it open for 8 hours": it exercises far
more page changes per minute than a person does, but it cannot show anything
that only appears after hours of wall-clock time. Exit status 1 when the heap
at the end is more than 25% above its level after warm-up.
"""

from __future__ import annotations

import statistics
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from capture_baseline_ui import free_port, seed, start_server  # noqa: E402

ROUTES = ["/profiles", "/proxies", "/checks", "/checks/evolution", "/checks/links", "/data", "/data/trash", "/settings", "/settings/kernel", "/settings/about", "/profiles/new"]
SAMPLE_EVERY = 30
WARMUP_SAMPLES = 2


def sample(page, cdp) -> dict:
    cdp.send("HeapProfiler.collectGarbage")
    metrics = {m["name"]: m["value"] for m in cdp.send("Performance.getMetrics")["metrics"]}
    return {
        "heap_mb": metrics["JSHeapUsedSize"] / 1e6,
        "nodes": metrics["Nodes"],
        "listeners": metrics["JSEventListeners"],
    }


def main() -> int:
    minutes = float(sys.argv[1]) if len(sys.argv) > 1 else 10
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    proc = start_server(port)
    samples: list[dict] = []
    errors: list[str] = []
    moves = 0
    try:
        seed(base)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 900}, locale="zh-CN")
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            cdp = page.context.new_cdp_session(page)
            cdp.send("Performance.enable")
            page.goto(base + "/profiles")
            page.wait_for_selector("tr[data-row]")
            deadline = time.monotonic() + minutes * 60
            next_sample = time.monotonic() + SAMPLE_EVERY
            while time.monotonic() < deadline:
                route = ROUTES[moves % len(ROUTES)]
                # Client-side navigation, as a user clicking around does.
                page.evaluate("path => { history.pushState({}, '', path); dispatchEvent(new PopStateEvent('popstate')); }", route)
                page.wait_for_timeout(1500)
                moves += 1
                if time.monotonic() >= next_sample:
                    samples.append(sample(page, cdp))
                    s = samples[-1]
                    print(f"{len(samples) * SAMPLE_EVERY:>5}s  moves {moves:>4}  heap {s['heap_mb']:6.1f} MB  nodes {s['nodes']:>6.0f}  listeners {s['listeners']:>5.0f}", flush=True)
                    next_sample += SAMPLE_EVERY
            samples.append(sample(page, cdp))
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()

    settled = samples[WARMUP_SAMPLES:] if len(samples) > WARMUP_SAMPLES + 1 else samples
    base_heap = statistics.median(s["heap_mb"] for s in settled[:3])
    end_heap = statistics.median(s["heap_mb"] for s in settled[-3:])
    growth = (end_heap - base_heap) / base_heap * 100
    print(f"\n{moves} page changes over {minutes:g} min; heap {base_heap:.1f} → {end_heap:.1f} MB ({growth:+.0f}%); "
          f"nodes {settled[0]['nodes']:.0f} → {settled[-1]['nodes']:.0f}; listeners {settled[0]['listeners']:.0f} → {settled[-1]['listeners']:.0f}")
    if errors:
        print("page errors:", errors[:3], file=sys.stderr)
    return 1 if growth > 25 or errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
