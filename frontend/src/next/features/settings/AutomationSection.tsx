import { useQueryClient } from "@tanstack/react-query";
import { Save } from "lucide-react";
import { useEffect, useState } from "react";
import { Banner, Button, ErrorState, FormField, Input, Section, Skeleton, useToast } from "../../ui";
import { message, settingsApi, settingsKeys, useHours, type AutomationHours } from "./api";

/**
 * 设置 › 自动化: the window scheduled automation (warm-up, evolution) may
 * start in. Outside it a scheduled run waits; manual runs are not affected.
 */
export function AutomationSection() {
  const hours = useHours();
  const title = "自动化时段";
  if (hours.isPending) {
    return (
      <Section id="automation" title={title}>
        <Skeleton className="h-24 w-full" />
      </Section>
    );
  }
  if (hours.isError) {
    return (
      <Section id="automation" title={title}>
        <ErrorState title="自动化时段没有读出来" message={hours.error.message} onRetry={() => void hours.refetch()} retrying={hours.isFetching} />
      </Section>
    );
  }
  return <HoursForm state={hours.data} />;
}

function HoursForm({ state }: { state: AutomationHours }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [value, setValue] = useState(state.hours ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => setValue(state.hours ?? ""), [state.hours]);

  const trimmed = value.trim();
  const changed = trimmed !== (state.hours ?? "");

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const next = await settingsApi.saveHours(trimmed === "" ? null : trimmed);
      queryClient.setQueryData(settingsKeys.hours, next);
      setValue(next.hours ?? "");
      toast.show({ tone: "success", title: next.hours ? `自动化时段已设为 ${next.hours}` : "已取消自动化时段限制" });
    } catch (err) {
      // The backend explains what is wrong with the format; keep the input as typed.
      setError(message(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Section
      id="automation"
      title="自动化时段"
      description="定时养号、自动进化只在这个时段内启动，时段外自动推迟；手动触发不受影响。自动化全程无头运行，不会弹出浏览器窗口。"
    >
      <form
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          void save();
        }}
      >
        <div className="flex flex-wrap items-start gap-2">
          <FormField label="允许的时段" description="格式 HH-HH，按这台电脑的本地时间，可以跨夜，比如 23-07；留空表示不限制。" error={error} className="w-full max-w-xs">
            <Input
              mono
              value={value}
              placeholder="如 09-18"
              inputMode="numeric"
              onChange={(event) => {
                setValue(event.target.value);
                setError(null);
              }}
            />
          </FormField>
          <Button type="submit" variant="primary" className="sm:mt-6" icon={<Save className="h-4 w-4" />} loading={saving} disabled={saving || !changed}>
            保存
          </Button>
        </div>
        {state.hours ? (
          state.open_now ? (
            <Banner tone="success">现在在时段（{state.hours}）内，定时任务会按计划启动。</Banner>
          ) : (
            <Banner tone="warning">现在不在时段（{state.hours}）内，定时任务会推迟到时段内再启动。</Banner>
          )
        ) : (
          <p className="text-sm text-fg-2">现在不限制时段，定时任务到点就启动。</p>
        )}
      </form>
    </Section>
  );
}
