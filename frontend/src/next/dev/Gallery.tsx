import { Archive, Copy, Inbox, MoreHorizontal, Pencil, Play, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import {
  Badge,
  Banner,
  Button,
  Card,
  Checkbox,
  CopyField,
  Dialog,
  EmptyState,
  ErrorState,
  FormField,
  IconButton,
  Input,
  KeyValueList,
  Kbd,
  Menu,
  MenuItem,
  MenuSeparator,
  PageHeader,
  ProgressBar,
  Section,
  Select,
  Skeleton,
  StatusDot,
  Switch,
  Table,
  Tabs,
  TD,
  TH,
  THead,
  TR,
  Textarea,
  useConfirm,
  useToast,
} from "../ui";

/**
 * Every component in every state, for review in both themes and for the
 * automated layout / accessibility checks. Reachable at /__ui; not linked
 * from the navigation. Content is example data.
 */
export function Gallery() {
  const toast = useToast();
  const confirm = useConfirm();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [checked, setChecked] = useState(true);
  const [switchOn, setSwitchOn] = useState(true);
  const [tab, setTab] = useState("one");

  return (
    <div className="flex flex-col gap-6 p-6">
      <PageHeader
        title="组件展示"
        description="设计系统里每个组件的各种状态（示例数据）。"
        actions={<Button variant="primary" icon={<Plus className="h-4 w-4" />}>主要操作</Button>}
      />

      <Section title="按钮" description="默认、悬停、按下、键盘聚焦、禁用、加载中">
        <div className="flex flex-col gap-3">
          {(["primary", "secondary", "ghost", "danger"] as const).map((variant) => (
            <div key={variant} className="flex flex-wrap items-center gap-2">
              <Button variant={variant}>{variant}</Button>
              <Button variant={variant} icon={<Play className="h-4 w-4" />}>带图标</Button>
              <Button variant={variant} size="sm">小号</Button>
              <Button variant={variant} disabled>禁用</Button>
              <Button variant={variant} loading>加载中</Button>
            </div>
          ))}
          <div className="flex flex-wrap items-center gap-2">
            <IconButton label="编辑" icon={<Pencil className="h-4 w-4" />} />
            <IconButton label="复制" variant="secondary" icon={<Copy className="h-4 w-4" />} />
            <IconButton label="删除" variant="danger" icon={<Trash2 className="h-4 w-4" />} />
            <IconButton label="正在处理" icon={<Archive className="h-4 w-4" />} loading />
            <IconButton label="不可用" icon={<Archive className="h-4 w-4" />} disabled />
            <Kbd>⌘K</Kbd>
          </div>
        </div>
      </Section>

      <Section title="表单">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <FormField label="名称" required description="只用于你自己识别这个环境。">
            <Input placeholder="例如 Amazon Seller #1" defaultValue="TikTok JP 02" />
          </FormField>
          <FormField label="代理地址" error="端口必须是 1–65535 之间的数字">
            <Input mono defaultValue="socks5://203.0.113.24:99999" />
          </FormField>
          <FormField label="分组">
            <Select defaultValue="us">
              <option value="none">未分组</option>
              <option value="us">美国账号</option>
              <option value="jp">日本账号</option>
            </Select>
          </FormField>
          <FormField label="不可编辑">
            <Input disabled defaultValue="macOS" />
          </FormField>
          <FormField label="备注" className="md:col-span-2">
            <Textarea placeholder="记录账号用途、注意事项" />
          </FormField>
          <div className="flex flex-col gap-3">
            <Checkbox checked={checked} onCheckedChange={setChecked} label="出口 IP 决定时区和语言" />
            <Checkbox checked="indeterminate" onCheckedChange={() => undefined} label="部分选中" />
            <Checkbox checked={false} onCheckedChange={() => undefined} label="禁用" disabled />
          </div>
          <div className="flex flex-col gap-4">
            <Switch checked={switchOn} onCheckedChange={setSwitchOn} label="自动更新内核" description="启动浏览器时下载新版本。" />
            <Switch checked={false} onCheckedChange={() => undefined} label="禁用的开关" disabled />
          </div>
        </div>
      </Section>

      <Section title="状态与反馈">
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center gap-2">
            <Badge>中性</Badge>
            <Badge tone="accent">防检测浏览器</Badge>
            <Badge tone="success">通过</Badge>
            <Badge tone="warning">有提示</Badge>
            <Badge tone="danger">未通过</Badge>
            <Badge tone="info">一次性</Badge>
          </div>
          <div className="flex flex-wrap items-center gap-4">
            <StatusDot status="running" label="运行中" />
            <StatusDot status="stopped" label="昨天 21:10" />
            <StatusDot status="busy" label="启动中" />
            <StatusDot status="error" label="上次启动失败" />
          </div>
          <Banner tone="info" title="提示">下次启动浏览器时生效。</Banner>
          <Banner tone="success" title="备份完成">CloakBrowser-backup-20261024-120000.zip，39 MB。</Banner>
          <Banner tone="warning" title="授权并发已满">请先关闭其他防检测浏览器，再打开这个环境。</Banner>
          <Banner tone="danger" title="恢复没有完成" action={<Button size="sm">重试</Button>}>
            备份文件格式不正确。当前数据没有改动。
          </Banner>
          <div className="flex flex-col gap-2">
            <ProgressBar value={42} label="下载内核" />
            <ProgressBar value={null} label="正在检测" />
          </div>
          <div className="flex flex-col gap-2">
            <Skeleton className="h-4 w-2/3" />
            <Skeleton className="h-4 w-1/2" />
          </div>
          <CopyField label=" CDP 地址" value="http://127.0.0.1:8080/api/profiles/3f2a9c1e/cdp" />
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => toast.show({ tone: "success", title: "已保存" })}>成功提示</Button>
            <Button onClick={() => toast.show({ tone: "error", title: "启动失败", description: "CloakBrowser 授权服务器连接失败。" })}>失败提示</Button>
            <Button onClick={() => toast.show({ title: "已移到回收站", action: { label: "撤销", onClick: () => undefined } })}>可撤销提示</Button>
          </div>
        </div>
      </Section>

      <Section title="容器">
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => setDialogOpen(true)}>打开对话框</Button>
            <Button
              variant="danger"
              onClick={async () => {
                const ok = await confirm({
                  title: "彻底删除这个环境？",
                  description: "浏览器数据、Cookie 和登录状态都会被删除，不能恢复。",
                  confirmLabel: "彻底删除",
                  danger: true,
                });
                toast.show({ tone: ok ? "success" : "info", title: ok ? "已确认" : "已取消" });
              }}
            >
              确认对话框
            </Button>
            <Menu trigger={<IconButton label="更多操作" variant="secondary" icon={<MoreHorizontal className="h-4 w-4" />} />}>
              <MenuItem icon={<Pencil className="h-4 w-4" />} onSelect={() => undefined}>编辑</MenuItem>
              <MenuItem icon={<Copy className="h-4 w-4" />} onSelect={() => undefined}>复制</MenuItem>
              <MenuItem icon={<Archive className="h-4 w-4" />} onSelect={() => undefined} disabled>归档（不可用）</MenuItem>
              <MenuSeparator />
              <MenuItem icon={<Trash2 className="h-4 w-4" />} onSelect={() => undefined} danger>移到回收站</MenuItem>
            </Menu>
          </div>
          <Tabs
            label="示例页签"
            value={tab}
            onValueChange={setTab}
            tabs={[
              { value: "one", label: "检测报告", content: <p className="text-fg-2">第一个页签的内容。</p> },
              { value: "two", label: "进化", content: <p className="text-fg-2">第二个页签的内容。</p> },
              { value: "three", label: "关联分析", content: <p className="text-fg-2">第三个页签的内容。</p> },
            ]}
          />
          <Card>
            <KeyValueList
              items={[
                { label: "出口 IP", value: <span className="font-mono">203.0.113.24</span> },
                { label: "时区 / 语言", value: "America/Los_Angeles · en-US" },
                { label: "User-Agent", value: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36" },
              ]}
            />
          </Card>
          <Table label="示例表格">
            <THead>
              <tr>
                <TH>名称</TH>
                <TH>出口</TH>
                <TH>状态</TH>
                <TH className="text-right">操作</TH>
              </tr>
            </THead>
            <tbody>
              <TR selected>
                <TD className="font-medium">Amazon Seller #1</TD>
                <TD className="font-mono text-fg-2">203.0.113.24</TD>
                <TD><StatusDot status="running" label="运行中" /></TD>
                <TD className="text-right"><Button size="sm">关闭</Button></TD>
              </TR>
              <TR>
                <TD className="font-medium">Etsy UK</TD>
                <TD className="font-mono text-fg-2">192.0.2.55</TD>
                <TD><StatusDot status="stopped" label="3 天前" /></TD>
                <TD className="text-right"><Button size="sm" variant="primary">打开</Button></TD>
              </TR>
            </tbody>
          </Table>
        </div>
      </Section>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card padded={false}>
          <EmptyState icon={Inbox} title="还没有环境" description="新建第一个环境，或者从备份恢复。" action={<Button variant="primary">新建环境</Button>} />
        </Card>
        <Card padded={false}>
          <ErrorState message="无法连接 Manager。" onRetry={() => undefined} />
        </Card>
      </div>

      <Dialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        title="打开前检查"
        description="检查的是配置一致性，不是“反检测分数”。"
        footer={
          <>
            <Button onClick={() => setDialogOpen(false)}>取消</Button>
            <Button variant="primary" onClick={() => setDialogOpen(false)}>继续启动</Button>
          </>
        }
      >
        <Banner tone="warning" title="有 1 条提示">稳定原生模式使用本机 Chrome 和真实硬件。</Banner>
      </Dialog>
    </div>
  );
}
