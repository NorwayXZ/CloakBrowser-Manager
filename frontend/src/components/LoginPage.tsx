import { useState, type FormEvent } from "react";
import { Lock } from "lucide-react";
import { api } from "../lib/api";

interface LoginPageProps {
  onSuccess: (username?: string | null) => void;
  initialUsername?: string | null;
}

export function LoginPage({ onSuccess, initialUsername }: LoginPageProps) {
  const [username, setUsername] = useState(initialUsername || "admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const result = await api.login(username.trim(), password);
      onSuccess(result.username);
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="h-screen flex items-center justify-center bg-surface-0">
      <div className="w-80">
        <div className="flex flex-col items-center mb-6">
          <div className="h-10 w-10 rounded-lg bg-accent/10 flex items-center justify-center mb-3">
            <Lock className="h-5 w-5 text-accent" />
          </div>
          <h1 className="text-lg font-semibold text-slate-900">
            CloakBrowser Manager
          </h1>
          <p className="text-xs text-slate-500 mt-1">输入管理员账号和密码</p>
        </div>
        <form onSubmit={handleSubmit} className="space-y-3">
          <input
            type="text"
            className="input"
            placeholder="用户名"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoFocus
          />
          <input
            type="password"
            className="input"
            placeholder="密码"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {error && <p className="text-red-400 text-xs">{error}</p>}
          <button
            type="submit"
            disabled={loading || !username.trim() || !password}
            className="btn-primary w-full disabled:opacity-50"
          >
            {loading ? "登录中..." : "登录"}
          </button>
        </form>
      </div>
    </div>
  );
}
