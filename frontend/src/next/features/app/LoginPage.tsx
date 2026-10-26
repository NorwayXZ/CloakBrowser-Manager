import { useQueryClient } from "@tanstack/react-query";
import { Lock, LogIn } from "lucide-react";
import { useState, type FormEvent } from "react";
import { isApiError } from "../../shared/api/client";
import { Banner, Button, FormField, Input } from "../../ui";
import { settingsApi } from "../settings/api";
import { appKeys, type AuthStatus } from "./api";

/** Shown instead of the panel while a password is set and this device is not signed in. */
export function LoginPage({ initialUsername }: { initialUsername: string | null }) {
  const queryClient = useQueryClient();
  const [username, setUsername] = useState(initialUsername || "admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const result = await settingsApi.login(username.trim(), password);
      queryClient.setQueryData<AuthStatus>(appKeys.auth, { auth_required: true, authenticated: true, username: result.username ?? username.trim() });
      // Anything fetched while signed out was a 401; fetch it again.
      void queryClient.invalidateQueries({ predicate: (query) => query.queryKey[0] !== "auth" });
    } catch (err) {
      setPassword("");
      setError(isApiError(err) && err.kind !== "http" ? "连接不到 Manager 服务，请确认它正在运行。" : err instanceof Error ? err.message : String(err));
      setLoading(false);
    }
  };

  return (
    <main className="flex h-full items-center justify-center overflow-auto bg-canvas p-4">
      <div className="w-full max-w-sm rounded-lg border border-border bg-surface p-6 shadow-raised">
        <div className="mb-6 flex flex-col items-center text-center">
          <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-md bg-accent-soft text-accent">
            <Lock className="h-5 w-5" aria-hidden />
          </div>
          <h1 className="text-lg font-semibold text-fg">CloakBrowser Manager</h1>
          <p className="mt-1 text-sm text-fg-2">输入管理员账号和密码</p>
        </div>
        <form className="flex flex-col gap-4" onSubmit={(event) => void submit(event)}>
          <FormField label="用户名">
            <Input value={username} autoComplete="username" autoFocus={!initialUsername} onChange={(event) => setUsername(event.target.value)} />
          </FormField>
          <FormField label="密码">
            <Input
              type="password"
              value={password}
              autoComplete="current-password"
              autoFocus={Boolean(initialUsername)}
              onChange={(event) => {
                setPassword(event.target.value);
                setError(null);
              }}
            />
          </FormField>
          {error && <Banner tone="danger">{error}</Banner>}
          <Button type="submit" variant="primary" className="w-full" icon={<LogIn className="h-4 w-4" />} loading={loading} disabled={loading || !username.trim() || !password}>
            {loading ? "登录中…" : "登录"}
          </Button>
        </form>
      </div>
    </main>
  );
}
