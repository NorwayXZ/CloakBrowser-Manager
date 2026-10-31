import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, RefreshCw } from "lucide-react";
import { Link, NavLink, useLocation } from "react-router";
import { cn } from "../../shared/lib/cn";
import { Badge, Button, ErrorState, PageHeader, Section, Skeleton } from "../../ui";
import { checkKeys, checksApi, useCheckState, useEvolutionStatus, ACTIVE_PHASES } from "./api";
import { EvolutionTab } from "./EvolutionTab";
import { ReportsTab } from "./ReportsTab";

/** 检测: detection reports, the evolution loop and linkability analysis. */
export function ChecksPage() {
  const { pathname } = useLocation();
  const tab = pathname.endsWith("/evolution") ? "evolution" : pathname.endsWith("/links") ? "links" : "reports";
  const state = useCheckState();
  const evolution = useEvolutionStatus();
  const tabs = [
    { id: "reports", to: "/checks", label: "检测报告", badge: state.data && ACTIVE_PHASES.has(state.data.phase) ? "进行中" : null },
    { id: "evolution", to: "/checks/evolution", label: "进化", badge: evolution.data?.pending_proposals ? `${evolution.data.pending_proposals} 待批准` : evolution.data?.busy ? "进行中" : null },
    { id: "links", to: "/checks/links", label: "关联分析", badge: null },
  ];

  return (
    <div className="flex flex-col gap-5 px-6 pb-8 pt-2 lg:px-10">
      <PageHeader title="检测" description="用公开检测网站验收环境，在克隆上验证修复，找出会被关联到一起的环境。" />
      <nav aria-label="检测分类" className="glass flex w-fit max-w-full gap-1 overflow-x-auto rounded-full p-1.5">
        {tabs.map((item) => (
          <NavLink
            key={item.id}
            to={item.to}
            end
            aria-current={tab === item.id ? "page" : undefined}
            className={cn(
              "flex h-9 shrink-0 items-center gap-1.5 rounded-full px-5 text-sm font-medium transition-[background-color,color,box-shadow] duration-fast",
              tab === item.id ? "bg-surface text-fg shadow-raised" : "text-fg-2 hover:text-fg",
            )}
          >
            {item.label}
            {item.badge && <Badge tone="accent">{item.badge}</Badge>}
          </NavLink>
        ))}
      </nav>
      <div className="max-w-[1400px]">{tab === "evolution" ? <EvolutionTab /> : tab === "links" ? <LinkabilityTab /> : <ReportsTab />}</div>
    </div>
  );
}

const RISK = { high: { label: "高风险", tone: "danger" as const }, medium: { label: "中风险", tone: "warning" as const } };
const LEVEL: Record<string, string> = { strong: "强关联", medium: "中等关联" };

function LinkabilityTab() {
  const data = useQuery({ queryKey: checkKeys.linkability, queryFn: checksApi.linkability });
  return (
    <div className="flex flex-col gap-5">
      <Section
        id="linkability"
        title="关联分析"
        description="只用已保存的环境数据分析：共用代理出口、相同指纹种子、相同设备模板、相同硬件组合等信号叠加得越多，这些环境越容易被检测方关联成同一个人。分析不会启动浏览器，也不会改动任何环境。"
        actions={
          <Button icon={<RefreshCw className="h-4 w-4" />} loading={data.isFetching} onClick={() => void data.refetch()}>
            重新分析
          </Button>
        }
      >
        {data.isPending ? (
          <div className="flex flex-col gap-2" aria-busy="true" aria-label="正在分析">
            <Skeleton className="h-5 w-64" />
            <Skeleton className="h-20 w-full" />
          </div>
        ) : data.isError ? (
          <ErrorState title="关联分析没有完成" message={data.error.message} onRetry={() => void data.refetch()} />
        ) : data.data.clusters.length === 0 ? (
          <div className="flex items-start gap-3">
            <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-success" aria-hidden />
            <div>
              <p className="font-medium text-fg">没有发现可关联的环境组合</p>
              <p className="mt-0.5 text-sm text-fg-2">
                当前 {data.data.profile_count} 个环境之间没有共用出口、相同设备模板或相同硬件组合等强关联信号。时区和语言相同很常见，单独出现不计入关联。
              </p>
            </div>
          </div>
        ) : (
          <p className="text-sm text-fg-2">
            共 {data.data.profile_count} 个环境，其中 {data.data.profile_count - data.data.unclustered_count} 个落在 {data.data.clusters.length} 组关联里，其余 {data.data.unclustered_count} 个没有发现关联。
          </p>
        )}
      </Section>

      {data.data?.clusters
        .slice()
        .sort((a, b) => (a.risk === "high" ? -1 : 0) - (b.risk === "high" ? -1 : 0))
        .map((cluster) => {
          const risk = RISK[cluster.risk as keyof typeof RISK] ?? { label: cluster.risk, tone: "warning" as const };
          return (
            <section key={cluster.id} aria-label={`${risk.label}：${cluster.profiles.length} 个环境`} className="glass rounded-lg p-4">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={risk.tone}>{risk.label}</Badge>
                <h3 className="text-sm font-medium text-fg">{cluster.profiles.length} 个环境可能被关联成同一个人</h3>
              </div>
              <ul className="mt-2 flex flex-wrap gap-1.5" aria-label="这组环境">
                {cluster.profiles.map((profile) => (
                  <li key={profile.id}>
                    <Link to={`/profiles?p=${encodeURIComponent(profile.id)}`} className="inline-flex rounded-full bg-surface-2 px-2.5 py-1 text-xs font-medium text-fg hover:bg-accent-soft hover:text-accent">
                      {profile.name}
                    </Link>
                  </li>
                ))}
              </ul>
              <div className="mt-3 flex flex-col gap-2">
                {cluster.links.map((link) => (
                  <div key={`${link.a_id}-${link.b_id}`} className="rounded-md border border-border bg-surface-2 p-3">
                    <div className="flex flex-wrap items-center gap-2 text-sm">
                      <span className="font-medium text-fg">{link.a_name}</span>
                      <span className="text-fg-3" aria-label="和">
                        ↔
                      </span>
                      <span className="font-medium text-fg">{link.b_name}</span>
                      <Badge tone={link.level === "strong" ? "danger" : "warning"}>
                        {LEVEL[link.level] ?? link.level} · {link.score} 分
                      </Badge>
                    </div>
                    <ul className="mt-1.5 list-disc pl-5 text-xs text-fg-2">
                      {link.reasons.map((reason) => (
                        <li key={reason}>{reason}</li>
                      ))}
                    </ul>
                    {link.suggestions.map((suggestion) => (
                      <p key={suggestion} className="mt-1 text-xs text-fg-2">
                        建议：{suggestion}
                      </p>
                    ))}
                  </div>
                ))}
              </div>
            </section>
          );
        })}
    </div>
  );
}
