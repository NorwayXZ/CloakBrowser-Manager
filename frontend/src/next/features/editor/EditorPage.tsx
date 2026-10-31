import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Check, Save, Trash2 } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useBlocker, useNavigate, useParams } from "react-router";
import { log } from "../../shared/log/logger";
import { cn } from "../../shared/lib/cn";
import { formatShortcut, useHotkeys } from "../../shared/lib/hotkeys";
import { Banner, Button, Dialog, EmptyState, ErrorState, IconButton, Kbd, Skeleton, useToast } from "../../ui";
import { useManagerStatus } from "../app/api";
import { profileKeys, profilesApi, useGroups, useProfiles } from "../profiles/api";
import { useProfileActions } from "../profiles/actions";
import type { Profile, ProfileCreate } from "../profiles/types";
import { useProxyPresets } from "./api";
import { SECTIONS, type EditorState } from "./model";
import { AdvancedSection } from "./sections/AdvancedSection";
import { BasicSection } from "./sections/BasicSection";
import { seedDeviceLabel } from "../profiles/format";
import { FingerprintSection, MoreFingerprintSection } from "./sections/FingerprintSections";
import { ProxySection } from "./sections/ProxySection";
import { SummaryPanel } from "./SummaryPanel";
import type { HostOS } from "./types";
import { readDraft, useEditor } from "./useEditor";

/** /profiles/new and /profiles/:id/edit: waits for what the form needs, then mounts it. */
export function EditorPage({ mode }: { mode: "new" | "edit" }) {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const status = useManagerStatus();
  const profiles = useProfiles();
  const groups = useGroups();
  const presets = useProxyPresets();

  if (status.isPending || (mode === "edit" && profiles.isPending)) return <EditorSkeleton />;
  if (status.isError) return <ErrorState message={status.error.message} onRetry={() => void status.refetch()} />;
  if (mode === "edit" && profiles.isError) return <ErrorState message={profiles.error.message} onRetry={() => void profiles.refetch()} />;
  const profile = mode === "edit" ? profiles.data?.find((p) => p.id === id) ?? null : null;
  if (mode === "edit" && !profile) {
    return <EmptyState title="没有这个环境" description="它可能已经被删除，或者移到了回收站。" action={<Button onClick={() => navigate("/profiles")}>回到环境列表</Button>} />;
  }

  return (
    <Editor
      key={profile?.id ?? "new"}
      profile={profile}
      hostOS={(status.data?.host_os as HostOS | undefined) ?? null}
      hostScreen={status.data?.host_screen ?? null}
      groups={groups.data ?? []}
      presets={presets.data ?? []}
    />
  );
}

/**
 * Creating an environment goes one question at a time. The five form sections
 * stay mounted (so nothing typed is lost and validation sees every field) and
 * the ones off the current step are folded away and made inert.
 */
const STEPS = [
  { label: "名称", sections: ["basic"], title: "先给它起个名字", desc: "名称只用来自己识别这个环境，不会写进网页指纹。" },
  { label: "网络", sections: ["proxy"], title: "这个环境怎么上网？", desc: "网络出口决定网站看到的位置。选好之后，时区和语言可以自动跟着出口走。" },
  { label: "设备", sections: ["fingerprint", "more-fingerprint"], title: "它是一台什么设备？", desc: "设备型号决定屏幕、CPU、显卡这些参数。不清楚就保持默认，它们已经是一套互相一致的组合。" },
  { label: "更多", sections: ["advanced"], title: "最后看看这些", desc: "默认已经按日常使用调好，不清楚用途的可以直接创建。" },
] as const;

function EditorSkeleton() {
  return (
    <div className="flex flex-col gap-4 p-6" aria-busy="true" aria-label="正在读取">
      <Skeleton className="h-7 w-48" />
      <Skeleton className="h-64 w-full max-w-form" />
      <Skeleton className="h-40 w-full max-w-form" />
    </div>
  );
}

function Editor({
  profile,
  hostOS,
  hostScreen,
  groups,
  presets,
}: {
  profile: Profile | null;
  hostOS: HostOS | null;
  hostScreen: number[] | null;
  groups: Parameters<typeof BasicSection>[0]["groups"];
  presets: Parameters<typeof ProxySection>[0]["presets"];
}) {
  const isEdit = profile !== null;
  const navigate = useNavigate();
  const toast = useToast();
  const queryClient = useQueryClient();
  const { trash } = useProfileActions();
  const editor = useEditor(profile, hostOS);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [nameError, setNameError] = useState<string | null>(null);
  const [draft, setDraft] = useState(() => readDraft(profile?.id ?? null));
  const [active, setActive] = useState<string>(SECTIONS[0].id);
  const wizard = !isEdit;
  const [step, setStep] = useState(0);
  const leaving = useRef(false);
  const nameRef = useRef<HTMLInputElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Ask before leaving with unsaved changes (in-app navigation and closing the window).
  const blocker = useBlocker(({ currentLocation, nextLocation }) => editor.dirty && !leaving.current && currentLocation.pathname !== nextLocation.pathname);
  useEffect(() => {
    if (!editor.dirty) return;
    const onBeforeUnload = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [editor.dirty]);

  const leave = (to: string) => {
    leaving.current = true;
    editor.discardDraft();
    navigate(to);
  };

  const save = async () => {
    if (saving) return;
    if (!editor.form.name.trim()) {
      setNameError("请填写名称");
      scrollToElement(nameRef.current, false);
      nameRef.current?.focus({ preventScroll: true });
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      const payload = editor.payload() as ProfileCreate;
      const saved = isEdit ? await profilesApi.update(profile.id, payload) : await profilesApi.create(payload);
      queryClient.setQueryData<Profile[]>(profileKeys.list, (list) =>
        list ? (isEdit ? list.map((p) => (p.id === saved.id ? saved : p)) : [saved, ...list]) : list,
      );
      void queryClient.invalidateQueries({ queryKey: profileKeys.list });
      toast.show({ tone: "success", title: isEdit ? `已保存「${saved.name}」` : `已创建「${saved.name}」`, description: isEdit ? "已经打开的浏览器要重新打开才会用上新配置。" : undefined });
      leave(`/profiles?p=${encodeURIComponent(saved.id)}`);
    } catch (error) {
      const text = error instanceof Error && error.message ? error.message : "保存失败，请检查输入后重试";
      log.warn("保存环境失败", { action: isEdit ? "profile.update" : "profile.create", detail: error });
      setSaveError(text);
      scrollRef.current?.scrollTo?.({ top: 0 });
    } finally {
      setSaving(false);
    }
  };

  useHotkeys([{ combo: "mod+s", whileTyping: true, handler: () => void save() }]);

  const goToStep = (target: number) => {
    // The name is the one thing a new environment needs: ask for it before moving on.
    if (target > 0 && step === 0 && !editor.form.name.trim()) {
      setNameError("请填写名称");
      nameRef.current?.focus({ preventScroll: true });
      return;
    }
    setStep(Math.max(0, Math.min(STEPS.length - 1, target)));
    scrollRef.current?.scrollTo?.({ top: 0 });
  };

  /** A form section; in the wizard, only the ones of the current step take part. */
  const pane = (sectionId: string, node: ReactNode) => {
    if (!wizard) return node;
    const on = (STEPS[step]!.sections as readonly string[]).includes(sectionId);
    return (
      <div key={sectionId} inert={!on} className={on ? undefined : "pointer-events-none max-h-0 overflow-hidden opacity-0"}>
        {node}
      </div>
    );
  };

  // Highlight the section in view.
  useEffect(() => {
    const root = scrollRef.current;
    if (!root || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries.filter((entry) => entry.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        const first = visible[0]?.target.id.replace(/^form-/, "");
        if (first) setActive(first);
      },
      { root, rootMargin: "0px 0px -65% 0px" },
    );
    SECTIONS.forEach((section) => {
      const el = document.getElementById(`form-${section.id}`);
      if (el) observer.observe(el);
    });
    return () => observer.disconnect();
  }, []);

  /**
   * Scroll only the editor's own pane. scrollIntoView would also scroll the
   * app shell around it and push the toolbar out of the window.
   */
  const scrollToElement = (el: HTMLElement | null, smooth = true) => {
    const root = scrollRef.current;
    if (!el || !root) return;
    // Leave room for the section tabs, which stick to the top below 1536 px.
    const offset = window.matchMedia?.("(min-width: 1536px)").matches ? 20 : 64;
    const top = el.getBoundingClientRect().top - root.getBoundingClientRect().top + root.scrollTop - offset;
    root.scrollTo?.({ top: Math.max(0, top), behavior: smooth ? "smooth" : "auto" });
  };

  const jump = (id: string) => {
    setActive(id);
    scrollToElement(document.getElementById(`form-${id}`));
  };

  const title = isEdit ? "编辑环境" : "新建环境";

  return (
    <form
      className="flex h-full min-h-0 flex-col"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      <div className="flex shrink-0 items-center gap-3 px-6 py-2.5 lg:px-10">
        <IconButton label="回到环境列表" icon={<ArrowLeft className="h-4 w-4" />} onClick={() => navigate("/profiles")} />
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-lg font-semibold tracking-tight text-fg">{title}</h1>
          <p className="truncate text-sm text-fg-3">{wizard ? `第 ${step + 1} 步，共 ${STEPS.length} 步 · ${editor.form.name || "未命名"}` : editor.form.name || "未命名"}</p>
        </div>
        {isEdit && (
          <Button
            variant="danger-ghost"
            icon={<Trash2 className="h-3.5 w-3.5" />}
            onClick={() =>
              void trash([profile]).then((done) => {
                if (done) leave("/profiles");
              })
            }
          >
            移到回收站
          </Button>
        )}
      </div>

      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
        <div className={cn("mx-auto grid max-w-[1400px] grid-cols-1 gap-6 px-6 py-5 lg:px-10", wizard ? "xl:grid-cols-[minmax(0,1fr)_340px]" : "xl:grid-cols-[minmax(0,1fr)_300px] 2xl:grid-cols-[160px_minmax(0,1fr)_320px]")}>
          {wizard ? (
            <ol aria-label="创建步骤" className="m-0 flex list-none items-center justify-center gap-2 p-0 xl:col-span-2">
              {STEPS.map((item, index) => {
                const done = index < step;
                const now = index === step;
                return (
                  <li key={item.label} className="flex items-center gap-2">
                    <button
                      type="button"
                      aria-current={now ? "step" : undefined}
                      onClick={() => goToStep(index)}
                      className="flex items-center gap-2.5 rounded-full py-1 pl-1 pr-3 text-sm transition-colors duration-fast hover:bg-surface/60"
                    >
                      <span
                        className={cn(
                          "flex h-8 w-8 items-center justify-center rounded-full text-sm font-semibold",
                          done && "bg-switch-on text-accent-on",
                          now && "bg-gradient-to-br from-accent-fill to-accent-fill-2 text-accent-on shadow-raised",
                          !done && !now && "border border-border-strong/50 bg-surface/70 text-fg-2",
                        )}
                      >
                        {done ? <Check className="h-4 w-4" strokeWidth={3} aria-hidden /> : index + 1}
                      </span>
                      <span className={cn(now ? "font-semibold text-fg" : "text-fg-2")}>{item.label}</span>
                    </button>
                    {index < STEPS.length - 1 && <span aria-hidden className={cn("h-0.5 w-8 rounded-full", done ? "bg-switch-on" : "bg-border-strong/30")} />}
                  </li>
                );
              })}
            </ol>
          ) : (
          <nav aria-label="表单分区" className="glass-strong sticky top-0 z-10 -mx-1 flex gap-1 overflow-x-auto rounded-full p-1 xl:col-span-2 2xl:col-span-1 2xl:top-5 2xl:h-fit 2xl:flex-col 2xl:rounded-lg 2xl:p-1.5">
            {SECTIONS.map((section) => (
              <button
                key={section.id}
                type="button"
                aria-current={active === section.id ? "true" : undefined}
                onClick={() => jump(section.id)}
                className={cn(
                  "shrink-0 whitespace-nowrap rounded-full px-4 py-2 text-left text-sm transition-colors duration-fast",
                  active === section.id ? "bg-surface font-semibold text-fg shadow-raised" : "text-fg-2 hover:text-fg",
                )}
              >
                {section.label}
              </button>
            ))}
          </nav>
          )}

          <div className="flex min-w-0 flex-col gap-5">
            {wizard && (
              <div>
                <div className="text-sm font-semibold text-accent">第 {step + 1} 步，共 {STEPS.length} 步</div>
                <h2 className="mt-1 text-lg font-bold tracking-tight text-fg">{STEPS[step]!.title}</h2>
                <p className="mt-1 text-md text-fg-2">{STEPS[step]!.desc}</p>
              </div>
            )}
            {draft && (
              <Banner
                tone="info"
                title="有一份没保存的修改"
                action={
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant="primary"
                      onClick={() => {
                        editor.restore(draft.state as EditorState);
                        setDraft(null);
                      }}
                    >
                      恢复
                    </Button>
                    <Button
                      size="sm"
                      onClick={() => {
                        editor.discardDraft();
                        setDraft(null);
                      }}
                    >
                      丢弃
                    </Button>
                  </div>
                }
              >
                上次编辑到 {new Date(draft.at).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })}，页面重新加载前没有保存。
              </Banner>
            )}
            {saveError && (
              <Banner tone="danger" title="没有保存">
                {saveError}
              </Banner>
            )}
            {pane("basic", <BasicSection ref={nameRef} editor={editor} profileId={profile?.id ?? null} groups={groups} hostOS={hostOS} nameError={nameError} onNameChange={() => setNameError(null)} seedDeviceLabel={seedDeviceLabel(profile)} />)}
            {pane("proxy", <ProxySection editor={editor} presets={presets} />)}
            {pane("fingerprint", <FingerprintSection editor={editor} hostOS={hostOS} hostScreen={hostScreen} isEdit={isEdit} />)}
            {pane("more-fingerprint", <MoreFingerprintSection editor={editor} hostOS={hostOS} />)}
            {pane("advanced", <AdvancedSection editor={editor} profileId={profile?.id ?? null} hostOS={hostOS} />)}
          </div>

          <div className="min-w-0 xl:sticky xl:top-16 xl:h-fit 2xl:top-5">
            <SummaryPanel editor={editor} hostOS={hostOS} hostScreen={hostScreen} isEdit={isEdit} />
          </div>
        </div>
      </div>

      <div className="glass-strong mx-4 mb-2 flex shrink-0 flex-wrap items-center justify-end gap-3 rounded-full px-5 py-2.5 lg:mx-10">
        <span className={cn("mr-auto flex items-center gap-2 text-sm", editor.dirty ? "text-fg" : "text-fg-3")} aria-live="polite">
          {editor.dirty && <span aria-hidden className="h-2 w-2 rounded-full bg-warning" />}
          {editor.dirty ? "有改动尚未保存" : isEdit ? "没有修改" : "填好名称即可创建，其余都有默认值"}
        </span>
        <Button onClick={() => navigate("/profiles")}>取消</Button>
        {wizard && step > 0 && (
          <Button icon={<ArrowLeft className="h-3.5 w-3.5" />} onClick={() => goToStep(step - 1)}>
            上一步
          </Button>
        )}
        {wizard && step < STEPS.length - 1 && (
          <Button variant="primary" onClick={() => goToStep(step + 1)}>
            下一步
            <ArrowRight className="h-3.5 w-3.5" aria-hidden />
          </Button>
        )}
        <Button type="submit" variant={wizard && step < STEPS.length - 1 ? "secondary" : "primary"} icon={<Save className="h-3.5 w-3.5" />} loading={saving}>
          {isEdit ? "保存" : "创建"}
          <Kbd tone={wizard && step < STEPS.length - 1 ? "default" : "inverse"}>{formatShortcut("mod+s")}</Kbd>
        </Button>
      </div>

      {blocker.state === "blocked" && (
        <Dialog
          open
          size="sm"
          onOpenChange={(open) => !open && blocker.reset?.()}
          title="放弃没保存的修改？"
          description="离开后，这次的修改不会保存。"
          footer={
            <>
              <Button onClick={() => blocker.reset?.()} autoFocus>
                继续编辑
              </Button>
              <Button
                variant="danger"
                onClick={() => {
                  editor.discardDraft();
                  blocker.proceed?.();
                }}
              >
                放弃修改
              </Button>
            </>
          }
        />
      )}
    </form>
  );
}
