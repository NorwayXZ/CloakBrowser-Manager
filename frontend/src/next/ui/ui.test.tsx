import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations, mockFetch, renderWithProviders, shellRoutes } from "../test/utils";
import { Gallery } from "../dev/Gallery";
import {
  Banner,
  Button,
  Checkbox,
  ConfirmProvider,
  CopyField,
  ErrorState,
  FormField,
  IconButton,
  Input,
  Switch,
  Tabs,
  ToastProvider,
  TooltipProvider,
  useConfirm,
  useToast,
} from ".";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("Button", () => {
  it("blocks clicks while loading and says it is busy", () => {
    const onClick = vi.fn();
    render(<Button loading onClick={onClick}>保存</Button>);
    const button = screen.getByRole("button", { name: "保存" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
    fireEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("defaults to type=button so it never submits a form by accident", () => {
    render(<Button>取消</Button>);
    expect(screen.getByRole("button", { name: "取消" })).toHaveAttribute("type", "button");
  });

  it("gives an icon-only button its label as accessible name", () => {
    render(
      <TooltipProvider>
        <IconButton label="编辑" icon={<span>✎</span>} />
      </TooltipProvider>,
    );
    expect(screen.getByRole("button", { name: "编辑" })).toBeInTheDocument();
  });
});

describe("FormField", () => {
  it("labels its control and links the error and description", () => {
    render(
      <FormField label="代理地址" description="主机:端口" error="端口必须是数字">
        <Input />
      </FormField>,
    );
    const input = screen.getByLabelText("代理地址");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription("端口必须是数字 主机:端口");
    expect(screen.getByRole("alert")).toHaveTextContent("端口必须是数字");
  });

  it("is not invalid without an error", () => {
    render(
      <FormField label="名称">
        <Input />
      </FormField>,
    );
    expect(screen.getByLabelText("名称")).not.toHaveAttribute("aria-invalid");
  });
});

describe("Checkbox and Switch", () => {
  function Toggles() {
    const [box, setBox] = useState(false);
    const [on, setOn] = useState(false);
    return (
      <>
        <Checkbox checked={box} onCheckedChange={setBox} label="跟随 IP" />
        <Switch checked={on} onCheckedChange={setOn} label="自动更新" description="启动时下载" />
      </>
    );
  }

  it("toggles by click and exposes the checked state", () => {
    render(<Toggles />);
    const box = screen.getByRole("checkbox", { name: "跟随 IP" });
    fireEvent.click(box);
    expect(box).toHaveAttribute("aria-checked", "true");
    const toggle = screen.getByRole("switch", { name: "自动更新" });
    expect(toggle).toHaveAccessibleDescription("启动时下载");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-checked", "true");
  });
});

describe("Confirm", () => {
  function Asker({ onResult }: { onResult: (ok: boolean) => void }) {
    const confirm = useConfirm();
    return <Button onClick={async () => onResult(await confirm({ title: "删除这个环境？", confirmLabel: "删除", danger: true }))}>删</Button>;
  }

  function setup() {
    const onResult = vi.fn();
    render(
      <TooltipProvider>
        <ConfirmProvider>
          <Asker onResult={onResult} />
        </ConfirmProvider>
      </TooltipProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "删" }));
    return onResult;
  }

  it("resolves true only from the confirm button", async () => {
    const onResult = setup();
    const dialog = await screen.findByRole("dialog", { name: "删除这个环境？" });
    expect(dialog).toContainElement(document.activeElement as HTMLElement);
    fireEvent.click(screen.getByRole("button", { name: "删除" }));
    await waitFor(() => expect(onResult).toHaveBeenCalledWith(true));
  });

  it("resolves false on cancel and on Escape", async () => {
    const onResult = setup();
    fireEvent.click(await screen.findByRole("button", { name: "取消" }));
    await waitFor(() => expect(onResult).toHaveBeenLastCalledWith(false));

    fireEvent.click(screen.getByRole("button", { name: "删" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(onResult).toHaveBeenCalledTimes(2));
    expect(onResult).toHaveBeenLastCalledWith(false);
  });
});

describe("Toast", () => {
  function Shower() {
    const toast = useToast();
    return (
      <>
        <Button onClick={() => toast.show({ tone: "success", title: "已保存" })}>ok</Button>
        <Button onClick={() => toast.show({ tone: "error", title: "启动失败", description: "授权无效" })}>bad</Button>
      </>
    );
  }

  it("announces errors assertively and others politely", () => {
    render(
      <ToastProvider>
        <Shower />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "ok" }));
    fireEvent.click(screen.getByRole("button", { name: "bad" }));
    expect(screen.getByRole("status")).toHaveTextContent("已保存");
    expect(screen.getByRole("alert")).toHaveTextContent("启动失败授权无效");
  });

  it("dismisses itself, errors later than the rest", () => {
    vi.useFakeTimers();
    render(
      <ToastProvider>
        <Shower />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "ok" }));
    fireEvent.click(screen.getByRole("button", { name: "bad" }));
    act(() => vi.advanceTimersByTime(4100));
    expect(screen.queryByText("已保存")).not.toBeInTheDocument();
    expect(screen.getByText("启动失败")).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(4000));
    expect(screen.queryByText("启动失败")).not.toBeInTheDocument();
  });

  it("can be closed by hand", () => {
    render(
      <ToastProvider>
        <Shower />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "ok" }));
    fireEvent.click(screen.getByRole("button", { name: "关闭提示" }));
    expect(screen.queryByText("已保存")).not.toBeInTheDocument();
  });
});

describe("feedback states", () => {
  it("ErrorState offers a retry", () => {
    const onRetry = vi.fn();
    render(<ErrorState message="连接不到 Manager 服务" onRetry={onRetry} />);
    expect(screen.getByRole("alert")).toHaveTextContent("连接不到 Manager 服务");
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(onRetry).toHaveBeenCalled();
  });

  it("Banner is an alert only for warnings and errors", () => {
    render(
      <>
        <Banner tone="info">提示</Banner>
        <Banner tone="danger">失败</Banner>
      </>,
    );
    expect(screen.getByRole("status")).toHaveTextContent("提示");
    expect(screen.getByRole("alert")).toHaveTextContent("失败");
  });
});

describe("CopyField", () => {
  it("copies and says so", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    render(
      <TooltipProvider>
        <CopyField label=" CDP 地址" value="http://127.0.0.1:8080/cdp" />
      </TooltipProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "复制 CDP 地址" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "已复制" })).toBeInTheDocument());
    expect(writeText).toHaveBeenCalledWith("http://127.0.0.1:8080/cdp");
  });

  it("tells the user to copy by hand when the clipboard is refused", async () => {
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText: vi.fn().mockRejectedValue(new Error("denied")) } });
    render(
      <TooltipProvider>
        <CopyField label="IP" value="203.0.113.24" />
      </TooltipProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "复制IP" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "复制失败，请手动选择" })).toBeInTheDocument());
  });
});

describe("Tabs", () => {
  it("moves between tabs with the arrow keys", async () => {
    function Demo() {
      const [value, setValue] = useState("a");
      return (
        <Tabs
          label="检测"
          value={value}
          onValueChange={setValue}
          tabs={[
            { value: "a", label: "报告", content: "报告内容" },
            { value: "b", label: "进化", content: "进化内容" },
          ]}
        />
      );
    }
    render(<Demo />);
    const first = screen.getByRole("tab", { name: "报告" });
    first.focus();
    fireEvent.keyDown(first, { key: "ArrowRight" });
    // Radix moves focus on the next tick.
    await waitFor(() => expect(screen.getByRole("tab", { name: "进化" })).toHaveFocus());
  });
});

describe("component gallery", () => {
  it("renders every component without accessibility violations", async () => {
    mockFetch(shellRoutes());
    const { container } = renderWithProviders(<Gallery />);
    expect(screen.getByRole("heading", { name: "组件展示" })).toBeInTheDocument();
    await expectNoAxeViolations(container);
  });
});
