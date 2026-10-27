import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Save, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
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
      <div className="flex shrink-0 items-center gap-3 border-b border-border bg-surface px-4 py-2.5">
        <IconButton label="回到环境列表" icon={<ArrowLeft className="h-4 w-4" />} onClick={() => navigate("/profiles")} />
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-md font-semibold text-fg">{title}</h1>
          <p className="truncate text-xs text-fg-3">{editor.form.name || "未命名"}</p>
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
        <div className="mx-auto grid max-w-[1400px] grid-cols-1 gap-6 px-6 py-5 xl:grid-cols-[minmax(0,1fr)_300px] 2xl:grid-cols-[160px_minmax(0,1fr)_320px]">
          <nav aria-label="表单分区" className="sticky top-0 z-10 -mx-1 flex gap-1 overflow-x-auto rounded-md border border-border bg-surface/95 p-1 backdrop-blur xl:col-span-2 2xl:col-span-1 2xl:top-5 2xl:h-fit 2xl:flex-col 2xl:border-0 2xl:bg-transparent 2xl:p-0 2xl:backdrop-blur-none">
            {SECTIONS.map((section) => (
              <button
                key={section.id}
                type="button"
                aria-current={active === section.id ? "true" : undefined}
                onClick={() => jump(section.id)}
                className={cn(
                  "shrink-0 whitespace-nowrap rounded px-3 py-1.5 text-left text-sm transition-colors duration-fast",
                  active === section.id ? "bg-accent-soft font-medium text-accent" : "text-fg-2 hover:bg-surface-2 hover:text-fg",
                )}
              >
                {section.label}
              </button>
            ))}
          </nav>

          <div className="flex min-w-0 flex-col gap-5">
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
            <BasicSection ref={nameRef} editor={editor} profileId={profile?.id ?? null} groups={groups} hostOS={hostOS} nameError={nameError} onNameChange={() => setNameError(null)} seedDeviceLabel={seedDeviceLabel(profile)} />
            <ProxySection editor={editor} presets={presets} />
            <FingerprintSection editor={editor} hostOS={hostOS} hostScreen={hostScreen} isEdit={isEdit} />
            <MoreFingerprintSection editor={editor} hostOS={hostOS} />
            <AdvancedSection editor={editor} profileId={profile?.id ?? null} hostOS={hostOS} />
          </div>

          <div className="min-w-0 xl:sticky xl:top-16 xl:h-fit 2xl:top-5">
            <SummaryPanel editor={editor} hostOS={hostOS} hostScreen={hostScreen} isEdit={isEdit} />
          </div>
        </div>
      </div>

      <div className="flex shrink-0 flex-wrap items-center justify-end gap-3 border-t border-border bg-surface px-4 py-2.5">
        <span className={cn("mr-auto flex items-center gap-2 text-sm", editor.dirty ? "text-fg" : "text-fg-3")} aria-live="polite">
          {editor.dirty && <span aria-hidden className="h-2 w-2 rounded-full bg-warning" />}
          {editor.dirty ? "有未保存的修改" : isEdit ? "没有修改" : "填好名称即可创建，其余都有默认值"}
        </span>
        <Button onClick={() => navigate("/profiles")}>取消</Button>
        <Button type="submit" variant="primary" icon={<Save className="h-3.5 w-3.5" />} loading={saving}>
          {isEdit ? "保存" : "创建"}
          <Kbd tone="inverse">{formatShortcut("mod+s")}</Kbd>
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
