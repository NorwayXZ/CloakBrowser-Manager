import { useQueryClient } from "@tanstack/react-query";
import { LogOut, Save, ShieldCheck } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Banner, Button, FormField, Input, Section, Skeleton, useToast } from "../../ui";
import { appKeys, useAuthStatus, type AuthStatus } from "../app/api";
import { message, settingsApi } from "./api";
import { useLogout } from "./auth";

/** 设置 › 账号与安全: change the admin name or password, sign out. */
export function AccountSection() {
  const auth = useAuthStatus();
  if (auth.isPending) {
    return (
      <Section id="account" title="账号与安全">
        <Skeleton className="h-40 w-full" />
      </Section>
    );
  }
  if (!auth.data?.auth_required) {
    return (
      <Section id="account" title="账号与安全">
        <div className="flex items-start gap-3">
          <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-fg-3" aria-hidden />
          <div className="text-sm text-fg-2">
            <p className="font-medium text-fg">没有开启登录保护</p>
            <p className="mt-1">
              面板只接受这台电脑本机访问，并会拒绝其他网站发起的修改请求，所以默认不需要密码。要开启登录，在启动 Manager 前设置环境变量 ADMIN_PASSWORD（可以同时设置 ADMIN_USERNAME，默认 admin），之后就能在这里改用户名和密码。
            </p>
          </div>
        </div>
      </Section>
    );
  }
  return <AccountForm username={auth.data.username} />;
}

function AccountForm({ username }: { username: string | null }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const logout = useLogout();
  const [name, setName] = useState(username || "admin");
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [signingOut, setSigningOut] = useState(false);

  const mismatch = next !== "" && again !== "" && next !== again;
  const tooShort = next !== "" && next.length < 8;
  const nameInvalid = name.trim().length < 3;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (next && next !== again) {
      setError("两次输入的新密码不一致");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const result = await settingsApi.saveAccount({ current_password: current, username: name.trim(), new_password: next || null });
      queryClient.setQueryData<AuthStatus>(appKeys.auth, (old) => (old ? { ...old, username: result.username } : old));
      setCurrent("");
      setNext("");
      setAgain("");
      toast.show({ tone: "success", title: next ? "用户名和密码已保存" : "用户名已保存" });
    } catch (err) {
      setError(message(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-col gap-5">
      <Section id="account" title="管理员账号" description="改用户名或密码都要先输入当前密码。保存后这台设备保持登录。">
        <form className="flex flex-col gap-4" onSubmit={(event) => void submit(event)}>
          <FormField label="用户名" error={nameInvalid ? "用户名至少 3 个字符" : undefined}>
            <Input value={name} autoComplete="username" minLength={3} maxLength={64} onChange={(event) => setName(event.target.value)} />
          </FormField>
          <FormField label="当前密码" required>
            <Input type="password" value={current} autoComplete="current-password" required onChange={(event) => setCurrent(event.target.value)} />
          </FormField>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <FormField label="新密码" description="不修改可以留空；至少 8 个字符。" error={tooShort ? "新密码至少 8 个字符" : undefined}>
              <Input type="password" value={next} autoComplete="new-password" onChange={(event) => setNext(event.target.value)} />
            </FormField>
            <FormField label="确认新密码" error={mismatch ? "两次输入的新密码不一致" : undefined}>
              <Input type="password" value={again} autoComplete="new-password" disabled={!next} onChange={(event) => setAgain(event.target.value)} />
            </FormField>
          </div>
          {error && <Banner tone="danger" title="没有保存">{error}</Banner>}
          <div>
            <Button
              type="submit"
              variant="primary"
              icon={<Save className="h-4 w-4" />}
              loading={saving}
              disabled={saving || !current || nameInvalid || tooShort || mismatch || (next !== "" && again === "")}
            >
              保存
            </Button>
          </div>
        </form>
      </Section>

      <Section id="sign-out" title="退出登录" description="退出后回到登录页。连不上 Manager 时也会在这台设备上退出。">
        <Button
          icon={<LogOut className="h-4 w-4" />}
          loading={signingOut}
          onClick={() => {
            setSigningOut(true);
            void logout();
          }}
        >
          退出登录
        </Button>
      </Section>
    </div>
  );
}
