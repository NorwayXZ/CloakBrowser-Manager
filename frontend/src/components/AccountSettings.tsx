import { KeyRound, X } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { api } from "../lib/api";

interface AccountSettingsProps {
  username: string | null;
  onClose: () => void;
  onUpdated: (username: string | null) => void;
}

export function AccountSettings({ username, onClose, onUpdated }: AccountSettingsProps) {
  const [nextUsername, setNextUsername] = useState(username || "admin");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setNextUsername(username || "admin");
  }, [username]);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setMessage(null);

    if (newPassword && newPassword !== confirmPassword) {
      setError("两次输入的新密码不一致");
      return;
    }

    setSaving(true);
    try {
      const result = await api.updateAuthAccount({
        current_password: currentPassword,
        username: nextUsername.trim(),
        new_password: newPassword || null,
      });
      onUpdated(result.username);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setMessage("已保存");
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 px-4">
      <div className="w-full max-w-sm rounded-md border border-border bg-surface-1 shadow-xl">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <div className="flex items-center gap-2">
            <KeyRound className="h-4 w-4 text-accent" />
            <h2 className="text-sm font-semibold text-slate-900">账号设置</h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1 text-slate-500 hover:text-slate-900"
            title="关闭"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-3 p-4">
          <div>
            <label className="label">用户名</label>
            <input
              className="input"
              value={nextUsername}
              onChange={(event) => setNextUsername(event.target.value)}
              minLength={3}
              maxLength={64}
            />
          </div>
          <div>
            <label className="label">当前密码</label>
            <input
              type="password"
              className="input"
              value={currentPassword}
              onChange={(event) => setCurrentPassword(event.target.value)}
              required
            />
          </div>
          <div>
            <label className="label">新密码</label>
            <input
              type="password"
              className="input"
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
              minLength={8}
              placeholder="不修改可留空"
            />
          </div>
          <div>
            <label className="label">确认新密码</label>
            <input
              type="password"
              className="input"
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
              minLength={newPassword ? 8 : undefined}
            />
          </div>

          {error && <p className="text-xs text-red-400">{error}</p>}
          {message && <p className="text-xs text-green-400">{message}</p>}

          <button
            type="submit"
            disabled={saving || !currentPassword || !nextUsername.trim()}
            className="btn-primary w-full disabled:opacity-50"
          >
            {saving ? "保存中..." : "保存"}
          </button>
        </form>
      </div>
    </div>
  );
}
