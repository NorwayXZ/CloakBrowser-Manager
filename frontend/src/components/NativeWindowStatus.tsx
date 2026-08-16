import { ExternalLink, Monitor } from "lucide-react";
import { CdpEndpointButton } from "./CdpEndpointButton";

interface NativeWindowStatusProps {
  profileName: string;
  cdpUrl: string | null;
  browserEngine?: string | null;
}

export function NativeWindowStatus({ profileName, cdpUrl, browserEngine }: NativeWindowStatusProps) {
  const isSystemChrome = browserEngine === "system_chrome";

  return (
    <div className="flex h-full items-center justify-center p-8">
      <div className="max-w-lg rounded-xl border border-border bg-surface-1 p-8 text-center">
        <Monitor className="mx-auto mb-4 h-10 w-10 text-accent" />
        <h2 className="text-lg font-medium text-gray-100">已在原生窗口打开</h2>
        <p className="mt-2 text-sm text-gray-400">
          {profileName} 正在这台电脑上运行。请在弹出的 {isSystemChrome ? "Google Chrome 原生" : "CloakBrowser/Chromium"} 窗口里浏览。
        </p>
        <div className="mt-5 flex items-center justify-center gap-2 text-xs text-gray-500">
          <ExternalLink className="h-3.5 w-3.5" />
          <span>自动化仍可通过 Manager CDP 使用</span>
          <CdpEndpointButton cdpUrl={cdpUrl} />
        </div>
      </div>
    </div>
  );
}
