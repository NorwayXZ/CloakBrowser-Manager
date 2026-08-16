import { useState, useCallback, useEffect } from "react";
import { KeyRound, Lock, PanelLeftClose, PanelLeft } from "lucide-react";
import { useProfiles } from "./hooks/useProfiles";
import { api, setOnUnauthorized, type LaunchMode, type ProfileCreateData } from "./lib/api";
import { ProfileList } from "./components/ProfileList";
import { ProfileForm } from "./components/ProfileForm";
import { ProfileViewer } from "./components/ProfileViewer";
import { NativeWindowStatus } from "./components/NativeWindowStatus";
import { LaunchButton } from "./components/LaunchButton";
import { FingerprintReportButton } from "./components/FingerprintReportButton";
import { StatusIndicator } from "./components/StatusIndicator";
import { LoginPage } from "./components/LoginPage";
import { AccountSettings } from "./components/AccountSettings";

type AuthState = "checking" | "required" | "ok" | "error";
type View = "empty" | "create" | "edit" | "view";

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
  const { profiles, loading, error, create, update, remove, launch, stop } = useProfiles();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [view, setView] = useState<View>("empty");
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [editDraft, setEditDraft] = useState<ProfileCreateData | null>(null);
  const [accountOpen, setAccountOpen] = useState(false);

  const selected = profiles.find((p) => p.id === selectedId) ?? null;

  const handleSelect = useCallback((id: string) => {
    setSelectedId(id);
    setEditDraft(null);
    const profile = profiles.find((p) => p.id === id);
    setView(profile?.status === "running" ? "view" : "edit");
  }, [profiles]);

  const handleNew = useCallback(() => {
    setSelectedId(null);
    setEditDraft(null);
    setView("create");
  }, []);

  const handleCreate = useCallback(async (data: ProfileCreateData) => {
    const profile = await create(data);
    if (profile) {
      setSelectedId(profile.id);
      setEditDraft(null);
      setView(profile.status === "running" ? "view" : "empty");
    }
  }, [create]);

  const handleUpdate = useCallback(async (data: ProfileCreateData) => {
    if (!selectedId) return;
    const saved = await update(selectedId, data);
    if (saved) {
      setEditDraft(null);
      setView(saved.status === "running" ? "view" : "empty");
    }
  }, [selectedId, update]);

  const handleDelete = useCallback(async () => {
    if (!selectedId) return;
    await remove(selectedId);
    setSelectedId(null);
    setEditDraft(null);
    setView("empty");
  }, [selectedId, remove]);

  const handleLaunchWithMode = useCallback(async (launchMode: LaunchMode) => {
    if (!selectedId) return;
    if (view === "edit" && editDraft) {
      const saved = await update(selectedId, editDraft);
      if (!saved) return;
      setEditDraft(null);
    }
    const result = await launch(selectedId, launchMode);
    if (result) setView("view");
  }, [editDraft, launch, selectedId, update, view]);

  const handleLaunch = useCallback(async () => {
    await handleLaunchWithMode("manual");
  }, [handleLaunchWithMode]);

  const handleDebugLaunch = useCallback(async () => {
    await handleLaunchWithMode("debug");
  }, [handleLaunchWithMode]);

  const handleStop = useCallback(async () => {
    if (!selectedId) return;
    await stop(selectedId);
    setView("empty");
  }, [selectedId, stop]);

  const handleVncDisconnect = useCallback(() => {
    setView("empty");
  }, []);

  if (loading) {
    return (
      <div className="h-screen flex items-center justify-center">
        <div className="text-gray-500 text-sm">加载中...</div>
      </div>
    );
  }

  return (
    <div className="h-screen flex">
      {/* Sidebar */}
      {sidebarOpen && (
        <div className="w-64 border-r border-border bg-surface-1 flex-shrink-0">
          <ProfileList
            profiles={profiles}
            selectedId={selectedId}
            onSelect={handleSelect}
            onNew={handleNew}
          />
        </div>
      )}

      {/* Main panel */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top bar */}
        <div className="flex items-center justify-between px-4 py-2 border-b border-border bg-surface-1">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setSidebarOpen(!sidebarOpen)}
              className="text-gray-500 hover:text-gray-300 p-1"
              title={sidebarOpen ? "隐藏侧边栏" : "显示侧边栏"}
            >
              {sidebarOpen ? <PanelLeftClose className="h-4 w-4" /> : <PanelLeft className="h-4 w-4" />}
            </button>
            {selected && (
              <div className="flex items-center gap-2">
                <StatusIndicator status={selected.status} size="md" />
                <span className="text-sm font-medium">{selected.name}</span>
                <span className="text-xs text-gray-500 capitalize">{selected.platform}</span>
                <span className="rounded bg-surface-3 px-1.5 py-0.5 text-[10px] text-gray-400">
                  {selected.browser_engine === "cloakbrowser" ? "伪装" : "原生"}
                </span>
              </div>
            )}
          </div>
          <div className="flex items-center gap-2">
            {selected && (
              <FingerprintReportButton
                profileId={selected.id}
                disabled={selected.status !== "running" || !selected.cdp_url}
                disabledReason={
                  selected.status !== "running"
                    ? "先启动浏览器"
                    : "日常启动未开启调试连接；请停止后用调试启动"
                }
              />
            )}
            {selected && (
              <LaunchButton
                status={selected.status}
                onLaunch={handleLaunch}
                onDebugLaunch={handleDebugLaunch}
                onStop={handleStop}
                launchLabel={view === "edit" ? "保存并启动" : "启动"}
                showDebugLaunch={selected.browser_engine !== "cloakbrowser"}
              />
            )}
            {authRequired && (
              <>
                <button
                  onClick={() => setAccountOpen(true)}
                  className="text-gray-500 hover:text-gray-300 p-1"
                  title="账号设置"
                >
                  <KeyRound className="h-3.5 w-3.5" />
                </button>
                <button
                  onClick={onLogout}
                  className="text-gray-500 hover:text-gray-300 p-1"
                  title="退出登录"
                >
                  <Lock className="h-3.5 w-3.5" />
                </button>
              </>
            )}
          </div>
        </div>

        {/* Error banner */}
        {error && (
          <div className="px-4 py-2 bg-red-600/15 border-b border-red-600/30 text-red-400 text-sm">
            {error}
          </div>
        )}

        {/* Content */}
        <div className="flex-1 overflow-y-auto overscroll-contain">
          {view === "empty" && (
            <div className="flex items-center justify-center h-full">
              <div className="text-center">
                <p className="text-gray-500 text-sm">选择一个配置，或新建一个配置</p>
              </div>
            </div>
          )}

          {view === "create" && (
            <ProfileForm
              profile={null}
              onSave={handleCreate}
              onCancel={() => setView("empty")}
            />
          )}

          {view === "edit" && selected && (
            <ProfileForm
              profile={selected}
              onSave={handleUpdate}
              onDelete={handleDelete}
              onCancel={() => {
                setSelectedId(null);
                setEditDraft(null);
                setView("empty");
              }}
              onDraftChange={setEditDraft}
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
        </div>
      </div>

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
