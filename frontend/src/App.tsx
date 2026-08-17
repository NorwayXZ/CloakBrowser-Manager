import { useState, useCallback, useEffect } from "react";
import { useProfiles } from "./hooks/useProfiles";
import {
  api,
  setOnUnauthorized,
  type LaunchMode,
  type ProfileCreateData,
  type ProfileGroup,
  type ProxyPreset,
} from "./lib/api";
import type { Profile } from "./lib/api";
import { EnvironmentManager } from "./components/EnvironmentManager";
import { ProfileForm } from "./components/ProfileForm";
import { ProfileViewer } from "./components/ProfileViewer";
import { NativeWindowStatus } from "./components/NativeWindowStatus";
import { LoginPage } from "./components/LoginPage";
import { AccountSettings } from "./components/AccountSettings";

type AuthState = "checking" | "required" | "ok" | "error";
type View = "list" | "create" | "edit" | "view";

export default function App() {
  const [authState, setAuthState] = useState<AuthState>("checking");
  const [authRequired, setAuthRequired] = useState(false);
  const [authUsername, setAuthUsername] = useState<string | null>(null);

  useEffect(() => {
    setOnUnauthorized(() => setAuthState("required"));

    api.authStatus()
      .then(({ auth_required, authenticated, username }) => {
        setAuthRequired(auth_required);
        setAuthUsername(username);
        if (!auth_required || authenticated) {
          setAuthState("ok");
        } else {
          setAuthState("required");
        }
      })
      .catch((err) => {
        console.warn("[auth] status check failed:", err);
        setAuthState("error");
      });

    return () => setOnUnauthorized(null);
  }, []);

  if (authState === "checking") {
    return (
      <div className="h-screen flex items-center justify-center">
        <div className="text-gray-500 text-sm">加载中...</div>
      </div>
    );
  }

  if (authState === "error") {
    return (
      <div className="h-screen flex items-center justify-center bg-surface-0">
        <div className="text-center">
          <p className="text-red-400 text-sm mb-2">无法连接到服务</p>
          <button
          onClick={() => {
            setAuthState("checking");
            api.authStatus()
                .then(({ auth_required, authenticated, username }) => {
                  setAuthRequired(auth_required);
                  setAuthUsername(username);
                  setAuthState(!auth_required || authenticated ? "ok" : "required");
                })
                .catch(() => setAuthState("error"));
            }}
            className="text-xs text-gray-400 hover:text-gray-200 underline"
          >
            重试
          </button>
        </div>
      </div>
    );
  }

  if (authState === "required") {
    return (
      <LoginPage
        initialUsername={authUsername}
        onSuccess={(username) => {
          setAuthUsername(username ?? authUsername);
          setAuthState("ok");
        }}
      />
    );
  }

  return (
    <AppContent
      authRequired={authRequired}
      authUsername={authUsername}
      onAccountUpdated={setAuthUsername}
      onLogout={async () => {
        await api.logout();
        setAuthState("required");
      }}
    />
  );
}

interface AppContentProps {
  authRequired: boolean;
  authUsername: string | null;
  onAccountUpdated: (username: string | null) => void;
  onLogout: () => void;
}

function AppContent({ authRequired, authUsername, onAccountUpdated, onLogout }: AppContentProps) {
  const { profiles, loading, error, refresh, create, update, remove, launch, stop } = useProfiles();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [view, setView] = useState<View>("list");
  const [accountOpen, setAccountOpen] = useState(false);
  const [groups, setGroups] = useState<ProfileGroup[]>([]);
  const [proxyPresets, setProxyPresets] = useState<ProxyPreset[]>([]);
  const [trashProfiles, setTrashProfiles] = useState<Profile[]>([]);
  const [managerError, setManagerError] = useState<string | null>(null);

  const selected = profiles.find((p) => p.id === selectedId) ?? null;

  const normalizeBrowserEngine = (value: Profile["browser_engine"]) => (
    value === "cloakbrowser" || value === "system_chrome" || value === "auto" ? value : "auto"
  );

  const loadManagerData = useCallback(async () => {
    try {
      const [nextGroups, nextProxyPresets, nextTrashProfiles] = await Promise.all([
        api.listGroups(),
        api.listProxyPresets(),
        api.listDeletedProfiles(),
      ]);
      setGroups(nextGroups);
      setProxyPresets(nextProxyPresets);
      setTrashProfiles(nextTrashProfiles);
      setManagerError(null);
    } catch (err) {
      setManagerError(err instanceof Error ? err.message : "管理数据加载失败");
    }
  }, []);

  useEffect(() => {
    void loadManagerData();
  }, [loadManagerData]);

  const refreshAll = useCallback(async () => {
    await Promise.all([refresh(), loadManagerData()]);
  }, [loadManagerData, refresh]);

  const handleEdit = useCallback((id: string) => {
    setSelectedId(id);
    setView("edit");
  }, []);

  const handleNew = useCallback(() => {
    setSelectedId(null);
    setView("create");
  }, []);

  const handleCreate = useCallback(async (data: ProfileCreateData) => {
    const profile = await create(data);
    if (profile) {
      setSelectedId(null);
      setView("list");
      await refreshAll();
    }
  }, [create, refreshAll]);

  const handleUpdate = useCallback(async (data: ProfileCreateData) => {
    if (!selectedId) return;
    const saved = await update(selectedId, data);
    if (saved) {
      setView("list");
      await refreshAll();
    }
  }, [refreshAll, selectedId, update]);

  const handleDeleteById = useCallback(async (id: string) => {
    await remove(id);
    await loadManagerData();
    if (selectedId === id) {
      setSelectedId(null);
      setView("list");
    }
  }, [loadManagerData, remove, selectedId]);

  const handleFormDelete = useCallback(async () => {
    if (!selectedId) return;
    await handleDeleteById(selectedId);
  }, [handleDeleteById, selectedId]);

  const profileToCreateData = useCallback((profile: Profile): ProfileCreateData => ({
    name: `${profile.name} 副本`,
    browser_engine: normalizeBrowserEngine(profile.browser_engine),
    device_profile: profile.device_profile,
    fingerprint_seed: null,
    proxy: profile.proxy,
    timezone: profile.timezone,
    locale: profile.locale,
    platform: profile.platform,
    user_agent: profile.user_agent,
    screen_width: profile.screen_width,
    screen_height: profile.screen_height,
    gpu_vendor: profile.gpu_vendor,
    gpu_renderer: profile.gpu_renderer,
    hardware_concurrency: profile.hardware_concurrency,
    humanize: profile.humanize,
    human_preset: profile.human_preset,
    headless: profile.headless,
    geoip: profile.geoip,
    clipboard_sync: profile.clipboard_sync,
    auto_launch: false,
    group_name: profile.group_name,
    account_platform: profile.account_platform,
    cookies_json: profile.cookies_json,
    startup_urls: profile.startup_urls,
    color_scheme: profile.color_scheme,
    launch_args: profile.launch_args,
    notes: profile.notes,
    tags: profile.tags,
  }), []);

  const handleDuplicate = useCallback(async (profile: Profile) => {
    await create(profileToCreateData(profile));
    await refreshAll();
  }, [create, profileToCreateData, refreshAll]);

  const handleLaunchProfile = useCallback(async (id: string, launchMode: LaunchMode) => {
    const result = await launch(id, launchMode);
    if (result?.viewer_mode === "vnc") {
      setSelectedId(id);
      setView("view");
    } else {
      setView("list");
    }
  }, [launch]);

  const handleStopProfile = useCallback(async (id: string) => {
    await stop(id);
    if (selectedId === id && view === "view") {
      setSelectedId(null);
      setView("list");
    }
  }, [selectedId, stop, view]);

  const handleCreateGroup = useCallback(async (name: string, color?: string | null) => {
    await api.createGroup({ name, color });
    await loadManagerData();
  }, [loadManagerData]);

  const handleDeleteGroup = useCallback(async (id: string) => {
    await api.deleteGroup(id);
    await refreshAll();
  }, [refreshAll]);

  const handleCreateProxyPreset = useCallback(async (data: { name: string; proxy: string; mode: string }) => {
    await api.createProxyPreset(data);
    await loadManagerData();
  }, [loadManagerData]);

  const handleDeleteProxyPreset = useCallback(async (id: string) => {
    await api.deleteProxyPreset(id);
    await loadManagerData();
  }, [loadManagerData]);

  const handleRestoreProfile = useCallback(async (id: string) => {
    await api.restoreProfile(id);
    await refreshAll();
  }, [refreshAll]);

  const handlePurgeProfile = useCallback(async (id: string) => {
    await api.purgeProfile(id);
    await refreshAll();
  }, [refreshAll]);

  const handleVncDisconnect = useCallback(() => {
    setView("list");
  }, []);

  if (loading) {
    return (
      <div className="h-screen flex items-center justify-center">
        <div className="text-gray-500 text-sm">加载中...</div>
      </div>
    );
  }

  return (
    <div className="h-screen">
      {view === "list" && (
        <EnvironmentManager
          profiles={profiles}
          groups={groups}
          proxyPresets={proxyPresets}
          trashProfiles={trashProfiles}
          error={error || managerError}
          authRequired={authRequired}
          authUsername={authUsername}
          onNew={handleNew}
          onEdit={handleEdit}
          onDuplicate={handleDuplicate}
          onDelete={handleDeleteById}
          onLaunch={handleLaunchProfile}
          onStop={handleStopProfile}
          onRefresh={refreshAll}
          onCreateGroup={handleCreateGroup}
          onDeleteGroup={handleDeleteGroup}
          onCreateProxyPreset={handleCreateProxyPreset}
          onDeleteProxyPreset={handleDeleteProxyPreset}
          onRestoreProfile={handleRestoreProfile}
          onPurgeProfile={handlePurgeProfile}
          onAccount={() => setAccountOpen(true)}
          onLogout={onLogout}
        />
      )}

      {view === "create" && (
        <ProfileForm
          profile={null}
          groups={groups}
          proxyPresets={proxyPresets}
          onSave={handleCreate}
          onCancel={() => setView("list")}
        />
      )}

      {view === "edit" && selected && (
        <ProfileForm
          profile={selected}
          groups={groups}
          proxyPresets={proxyPresets}
          onSave={handleUpdate}
          onDelete={handleFormDelete}
          onCancel={() => {
            setSelectedId(null);
            setView("list");
          }}
        />
      )}

      {view === "view" && selected && selected.status === "running" && (
        selected.viewer_mode === "vnc" ? (
          <ProfileViewer
            key={selected.id}
            profileId={selected.id}
            cdpUrl={selected.cdp_url}
            clipboardSync={selected.clipboard_sync}
            onDisconnect={handleVncDisconnect}
          />
        ) : (
          <NativeWindowStatus
            key={selected.id}
            profileName={selected.name}
            cdpUrl={selected.cdp_url}
            browserEngine={selected.browser_engine}
            launchMode={selected.launch_mode}
          />
        )
      )}

      {accountOpen && (
        <AccountSettings
          username={authUsername}
          onClose={() => setAccountOpen(false)}
          onUpdated={onAccountUpdated}
        />
      )}
    </div>
  );
}
