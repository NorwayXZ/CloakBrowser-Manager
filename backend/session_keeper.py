"""macOS: closing a profile's last window closes that browser, and keeps its tabs.

On macOS, closing a browser's last window leaves the app running with no
windows. The Manager still showed it as open, its Dock icon stayed, and when
it was quit later Chromium saved an empty session, so every tab was lost.

Two pieces fix that:

* Closing the last window makes Chromium shut that profile down at once —
  it releases every file in the profile folder while the process lives on
  (measured: 108 open files drop to 0 within a second; a minimized window
  keeps them all). The Manager watches for that and ends the browser the
  normal way. An extension cannot report it: it is stopped with the profile.
* A small profile-local MV3 extension keeps a snapshot of the open tabs and,
  on the next start, reopens it if Chromium restored no web page itself. It
  never overwrites the snapshot with "no windows" (closing the last window or
  quitting), has no content scripts, no web-accessible resources and no
  network access, so web pages cannot detect it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable

SESSION_KEEPER_DIRNAME = "manager-session-keeper"


WORKER = r"""
const CONFIG = __CONFIG__;
const SNAPSHOT_KEY = "managerSessionSnapshot";
// Give Chromium's own session restore time to open its windows first.
const RESTORE_DELAY_MS = 2500;

const isRestorable = (url) =>
  typeof url === "string" && /^https?:\/\//i.test(url) && !url.startsWith(CONFIG.managerOrigin);

const normalWindows = () => chrome.windows.getAll({ populate: true, windowTypes: ["normal"] });

const saveSnapshot = async () => {
  const windows = await normalWindows();
  // No windows means the last one is closing or the browser is quitting:
  // keep the previous snapshot so those tabs can come back.
  if (windows.length === 0) return;
  const saved = windows
    .map((win) => ({
      tabs: (win.tabs || [])
        .map((tab) => ({ url: tab.url || tab.pendingUrl, pinned: Boolean(tab.pinned), active: Boolean(tab.active) }))
        .filter((tab) => isRestorable(tab.url)),
    }))
    .filter((win) => win.tabs.length > 0);
  if (saved.length === 0) return;
  await chrome.storage.local.set({ [SNAPSHOT_KEY]: { windows: saved, savedAt: Date.now() } });
};

let snapshotTimer = null;
const scheduleSnapshot = () => {
  clearTimeout(snapshotTimer);
  snapshotTimer = setTimeout(() => { void saveSnapshot(); }, 400);
};

let restoreStarted = false;
const restoreIfNeeded = async () => {
  // The Manager rewrites this extension on every launch, so Chromium may
  // report an "update" (onInstalled) instead of onStartup, or both: run once
  // per worker (both events can arrive together) and once per browser session.
  if (restoreStarted) return;
  restoreStarted = true;
  const session = chrome.storage.session;
  if (session) {
    if ((await session.get("restoreChecked")).restoreChecked) return;
    await session.set({ restoreChecked: true });
  }
  await new Promise((resolve) => setTimeout(resolve, RESTORE_DELAY_MS));
  const stored = (await chrome.storage.local.get(SNAPSHOT_KEY))[SNAPSHOT_KEY];
  if (!stored || !Array.isArray(stored.windows) || stored.windows.length === 0) return;
  const windows = await normalWindows();
  const open = windows.flatMap((win) => win.tabs || []).map((tab) => tab.url || tab.pendingUrl);
  if (open.some(isRestorable)) return;  // Chromium restored the session itself.
  for (const [index, saved] of stored.windows.entries()) {
    if (index === 0 && windows.length > 0) {
      let first = true;
      for (const tab of saved.tabs) {
        await chrome.tabs.create({ windowId: windows[0].id, url: tab.url, pinned: tab.pinned, active: first });
        first = false;
      }
    } else {
      const created = await chrome.windows.create({ url: saved.tabs.map((tab) => tab.url), focused: false });
      for (const [i, tab] of saved.tabs.entries()) {
        if (tab.pinned && created.tabs && created.tabs[i]) await chrome.tabs.update(created.tabs[i].id, { pinned: true });
      }
    }
  }
};

chrome.tabs.onCreated.addListener(scheduleSnapshot);
chrome.tabs.onUpdated.addListener((_id, change) => { if (change.url || change.pinned !== undefined) scheduleSnapshot(); });
chrome.tabs.onMoved.addListener(scheduleSnapshot);
chrome.tabs.onAttached.addListener(scheduleSnapshot);
chrome.tabs.onDetached.addListener(scheduleSnapshot);
chrome.tabs.onRemoved.addListener((_id, info) => { if (!info.isWindowClosing) scheduleSnapshot(); });
chrome.windows.onCreated.addListener(scheduleSnapshot);
chrome.runtime.onStartup.addListener(() => { void restoreIfNeeded(); });
chrome.runtime.onInstalled.addListener(() => { void restoreIfNeeded(); });
""".strip()


GOOGLE_SEARCH_PROVIDER = {
    "name": "Google",
    "keyword": "google.com",
    "is_default": True,
    "encoding": "UTF-8",
    "search_url": "https://www.google.com/search?q={searchTerms}",
    "suggest_url": "https://www.google.com/complete/search?client=chrome&q={searchTerms}",
    "favicon_url": "https://www.google.com/favicon.ico",
}


def sync_session_keeper_extension(user_data_dir: Path, *, port: int) -> Path:
    """Write the tab-keeping extension into the profile folder."""
    extension_dir = user_data_dir / SESSION_KEEPER_DIRNAME
    extension_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "manifest_version": 3,
        "name": "CloakBrowser Manager",
        "version": "1.1.0",
        "description": "关闭最后一个窗口后，下次打开时恢复之前的标签；默认用 Google 搜索。",
        "permissions": ["tabs", "storage"],
        "background": {"service_worker": "service_worker.js"},
        # This kernel ships without Google and defaults to "No Search".
        # Writing the default into Preferences is undone by Chromium's
        # tamper protection (with a "settings were reset" dialog); an
        # extension override is the supported way.
        "chrome_settings_overrides": {"search_provider": GOOGLE_SEARCH_PROVIDER},
    }
    config = {"managerOrigin": f"http://127.0.0.1:{port}"}
    worker = WORKER.replace("__CONFIG__", json.dumps(config, separators=(",", ":")))
    (extension_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (extension_dir / "service_worker.js").write_text(worker, encoding="utf-8")
    return extension_dir


def remove_session_keeper_extension(user_data_dir: Path) -> None:
    shutil.rmtree(user_data_dir / SESSION_KEEPER_DIRNAME, ignore_errors=True)


def window_name_arg(profile_name: str | None) -> str | None:
    """Name the first window after the profile, shown in the Dock and Window menus."""
    name = " ".join(str(profile_name or "").split())[:60]
    return f"--window-name={name}" if name else None


def profile_files_open(
    pid: int,
    user_data_dir: Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> bool | None:
    """Whether the browser still holds files in its profile folder; None if unknown.

    False while the process runs means every window of the profile is closed.
    """
    profile_dir = os.path.realpath(user_data_dir / "Default") + os.sep
    try:
        result = runner(["lsof", "-p", str(pid), "-Fn"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode not in (0, 1):
        return None
    return any(line.startswith("n" + profile_dir) for line in result.stdout.splitlines())
