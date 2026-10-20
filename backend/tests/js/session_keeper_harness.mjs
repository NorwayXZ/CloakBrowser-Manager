// Runs the generated session-keeper service worker against a fake chrome API.
// Usage: node session_keeper_harness.mjs <service_worker.js> <scenario>
import { readFileSync } from "node:fs";
import vm from "node:vm";

const [, , workerPath, scenario] = process.argv;
const listeners = {};
const on = (name) => ({ addListener: (fn) => { listeners[name] = fn; } });
const state = { windows: [], storage: {}, session: {}, created: [], createdWindows: [] };

const chrome = {
  windows: {
    getAll: async () => JSON.parse(JSON.stringify(state.windows)),
    create: async (opts) => { state.createdWindows.push(opts); return { tabs: opts.url.map((_u, i) => ({ id: 900 + i })) }; },
    onCreated: on("windows.onCreated"),
    onRemoved: on("windows.onRemoved"),
  },
  tabs: {
    create: async (opts) => { state.created.push(opts); return { id: 500 + state.created.length }; },
    update: async () => ({}),
    onCreated: on("tabs.onCreated"), onUpdated: on("tabs.onUpdated"), onMoved: on("tabs.onMoved"),
    onAttached: on("tabs.onAttached"), onDetached: on("tabs.onDetached"), onRemoved: on("tabs.onRemoved"),
  },
  storage: {
    local: {
      get: async (key) => ({ [key]: state.storage[key] }),
      set: async (obj) => { Object.assign(state.storage, obj); },
    },
    session: {
      get: async (key) => ({ [key]: state.session[key] }),
      set: async (obj) => { Object.assign(state.session, obj); },
    },
  },
  runtime: { onStartup: on("runtime.onStartup"), onInstalled: on("runtime.onInstalled") },
};

const pending = [];
const context = vm.createContext({
  chrome,
  JSON, Promise, Date, Array, console,
  // Timers run as soon as the current work settles, so the test needs no waiting.
  setTimeout: (fn) => { const p = Promise.resolve().then(fn); pending.push(p); return pending.length; },
  clearTimeout: () => {},
});
vm.runInContext(readFileSync(workerPath, "utf8"), context);

const settle = async () => { for (let i = 0; i < 20; i += 1) { await Promise.all(pending.splice(0)); await new Promise((r) => setImmediate(r)); } };
const tab = (url, extra = {}) => ({ url, pinned: false, active: false, ...extra });
const START = "http://127.0.0.1:18080/profile/p1/start";

if (scenario === "snapshot") {
  state.windows = [{ id: 1, tabs: [tab(START), tab("https://mail.example.com/", { active: true }), tab("https://shop.example.com/a", { pinned: true })] }];
  listeners["tabs.onUpdated"](1, { url: "https://shop.example.com/a" });
  await settle();
  // The last window closes: the snapshot must survive.
  state.windows = [];
  listeners["tabs.onRemoved"](2, { isWindowClosing: true });
  listeners["windows.onCreated"]({ id: 1 });
  await settle();
} else if (scenario === "one-of-two") {
  state.windows = [{ id: 1, tabs: [tab("https://a.example.com/")] }, { id: 2, tabs: [tab("https://b.example.com/")] }];
  listeners["windows.onCreated"]({ id: 2 });
  await settle();
  state.windows = [{ id: 1, tabs: [tab("https://a.example.com/")] }];
  listeners["tabs.onRemoved"](9, { isWindowClosing: false });
  await settle();
} else if (scenario === "restore") {
  state.storage.managerSessionSnapshot = { windows: [
    { tabs: [tab("https://mail.example.com/"), tab("https://shop.example.com/a", { pinned: true })] },
    { tabs: [tab("https://docs.example.com/")] },
  ] };
  state.windows = [{ id: 7, tabs: [tab(START)] }];
  // Both events can fire for one browser start; the tabs must open once.
  listeners["runtime.onStartup"]();
  listeners["runtime.onInstalled"]({ reason: "update" });
  await settle();
} else if (scenario === "already-restored") {
  state.storage.managerSessionSnapshot = { windows: [{ tabs: [tab("https://mail.example.com/")] }] };
  state.windows = [{ id: 7, tabs: [tab("https://mail.example.com/")] }];
  listeners["runtime.onStartup"]();
  await settle();
}

process.stdout.write(JSON.stringify(state));
