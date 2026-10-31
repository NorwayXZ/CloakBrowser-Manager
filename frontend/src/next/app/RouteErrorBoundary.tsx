import { Component, type ErrorInfo, type ReactNode } from "react";
import { log } from "../shared/log/logger";
import { ErrorState } from "../ui";

/**
 * A crash inside one page stays inside that page: the sidebar and toolbar keep
 * working, the error goes to manager.log, and "重新载入" re-mounts it.
 * The shell keys this boundary by path, so navigating away also clears it.
 */
export class RouteErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    log.error(`页面渲染出错：${error.message}`, { action: "render", detail: `${error.stack ?? ""}\n${info.componentStack ?? ""}` });
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="flex h-full items-center justify-center">
        <ErrorState
          title="这一页出了点问题"
          message={`${this.state.error.message || "未知错误"}。错误已写入日志。`}
          retryLabel="重新载入"
          onRetry={() => this.setState({ error: null })}
        />
      </div>
    );
  }
}
