import { useQueryClient } from "@tanstack/react-query";
import { Save } from "lucide-react";
import { useEffect, useState } from "react";
import { Badge, Banner, Button, ErrorState, FormField, Input, Section, Select, Skeleton, useToast } from "../../ui";
import { message, settingsApi, settingsKeys, useLlmSettings, type LlmSettings } from "./api";

const EFFORTS = ["low", "medium", "high", "max"];

function draftOf(status: LlmSettings) {
  return {
    base_url: status.base_url ?? "",
    model: status.model ?? "",
    executor_model: status.executor_model ?? "",
    executor_effort: status.executor_effort ?? "",
  };
}

/** 设置 › AI 接口: the bring-your-own-key LLM endpoint every AI feature shares. */
export function AiSection() {
  const llm = useLlmSettings();
  const title = "AI 接口";
  if (llm.isPending) {
    return (
      <Section id="ai" title={title}>
        <Skeleton className="h-48 w-full" />
      </Section>
    );
  }
  if (llm.isError) {
    return (
      <Section id="ai" title={title}>
        <ErrorState title="AI 接口设置没有读出来" message={llm.error.message} onRetry={() => void llm.refetch()} retrying={llm.isFetching} />
      </Section>
    );
  }
  return <AiForm status={llm.data} />;
}

function AiForm({ status }: { status: LlmSettings }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [draft, setDraft] = useState(() => draftOf(status));
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => setDraft(draftOf(status)), [status]);

  const changed = JSON.stringify(draft) !== JSON.stringify(draftOf(status)) || apiKey.trim() !== "";

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const next = await settingsApi.saveLlm({
        base_url: draft.base_url.trim(),
        model: draft.model.trim(),
        api_key: apiKey.trim() ? apiKey : null,
        executor_model: draft.executor_model.trim(),
        executor_effort: draft.executor_effort,
      });
      queryClient.setQueryData(settingsKeys.llm, next);
      setApiKey("");
      toast.show({ tone: "success", title: "AI 接口设置已保存" });
    } catch (err) {
      setError(message(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Section
      id="ai"
      title="AI 接口"
      description="自备密钥：填任意 OpenAI 兼容接口（OpenAI、DeepSeek、本地 Ollama 的兼容端点等）。没有配置时所有 AI 入口自动隐藏，其他功能不受影响。目前用于“AI 养号编排”：按画像人格离线生成一周的浏览剧本，人工批准后才生效。"
      actions={status.configured ? <Badge tone="success">已配置</Badge> : <Badge>未配置</Badge>}
    >
      <form
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          void save();
        }}
      >
        <FormField label="接口地址" description="填到版本根路径即可，Manager 会在后面拼上 /chat/completions。">
          <Input mono value={draft.base_url} placeholder="https://api.openai.com/v1" onChange={(event) => setDraft({ ...draft, base_url: event.target.value })} />
        </FormField>
        <FormField label="模型">
          <Input mono value={draft.model} placeholder="gpt-4o-mini" onChange={(event) => setDraft({ ...draft, model: event.target.value })} />
        </FormField>
        <FormField label="API 密钥" description="密钥只写不读：加密保存在这台电脑上，保存后这里不会再显示它。">
          <Input
            type="password"
            mono
            value={apiKey}
            placeholder={status.has_api_key ? "已配置（留空表示不修改）" : "sk-…"}
            autoComplete="new-password"
            spellCheck={false}
            onChange={(event) => setApiKey(event.target.value)}
          />
        </FormField>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField label="执行器模型" description="给“AI 驾驶员”预留：和上面共用接口地址与密钥，只换模型，讲究便宜快。功能还没上线，留空表示暂不指定。">
            <Input mono value={draft.executor_model} placeholder="claude-haiku-5-5" onChange={(event) => setDraft({ ...draft, executor_model: event.target.value })} />
          </FormField>
          <FormField label="执行强度" description="只对支持 effort 的模型生效；执行类任务建议 high。">
            <Select value={draft.executor_effort} onChange={(event) => setDraft({ ...draft, executor_effort: event.target.value })}>
              <option value="">默认（由服务商决定）</option>
              {EFFORTS.map((effort) => (
                <option key={effort} value={effort}>
                  {effort}
                </option>
              ))}
              {draft.executor_effort && !EFFORTS.includes(draft.executor_effort) && <option value={draft.executor_effort}>{draft.executor_effort}</option>}
            </Select>
          </FormField>
        </div>
        <p className="text-sm text-fg-2">
          {status.configured ? "已配置，AI 功能可用。" : "还没配置完整：接口地址、模型、密钥缺一不可，配好前 AI 入口保持隐藏。"}
        </p>
        {error && <Banner tone="danger" title="没有保存">{error}</Banner>}
        <div>
          <Button type="submit" variant="primary" icon={<Save className="h-4 w-4" />} loading={saving} disabled={saving || !changed}>
            保存设置
          </Button>
        </div>
      </form>
    </Section>
  );
}
