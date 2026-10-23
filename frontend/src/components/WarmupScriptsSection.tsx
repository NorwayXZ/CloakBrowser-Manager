import { useCallback, useEffect, useRef, useState } from "react";
import { api, type WarmupScriptBatch, type WarmupScriptsInfo } from "../lib/api";

const DWELL_LABEL: Record<string, string> = {
  short: "短停",
  medium: "中停",
  long: "长停",
};

const STATUS_LABEL: Record<string, string> = {
  draft: "待审核",
  approved: "生效中",
  rejected: "已驳回",
  archived: "已归档",
};

function stepLine(step: WarmupScriptBatch["scripts"][number]["steps"][number]): string {
  const parts: string[] = [];
  parts.push(step.kind === "target" ? step.platform_name || step.platform || "目标平台" : "本地站点");
  if (step.search_query) parts.push(`搜「${step.search_query}」`);
  parts.push(DWELL_LABEL[step.dwell] ?? "中停");
  if (step.follow_link) parts.push("跟一条链接");
  return parts.join(" · ");
}

export function WarmupScriptsSection({ profileId }: { profileId: string }) {
  const [info, setInfo] = useState<WarmupScriptsInfo | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number | null>(null);

  const load = useCallback(async () => {
    try {
      setInfo(await api.getWarmupScripts(profileId));
    } catch {
      // 读取失败时保持现状，下次打开表单会再拉
    }
  }, [profileId]);

  useEffect(() => {
    void load();
  }, [load]);

  // 生成是后台任务：进行中就轮询，直到状态落定。
  useEffect(() => {
    if (!info?.generating) return;
    timer.current = window.setInterval(() => void load(), 2500);
    return () => {
      if (timer.current) window.clearInterval(timer.current);
    };
  }, [info?.generating, load]);

  const handleGenerate = async () => {
    setBusy("generate");
    setError(null);
    try {
      await api.generateWarmupScripts(profileId);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "生成失败");
    } finally {
      setBusy(null);
    }
  };

  const handleDecide = async (batch: WarmupScriptBatch, approve: boolean) => {
    setBusy(batch.batch_id);
    setError(null);
    try {
      if (approve) {
        await api.approveWarmupScriptBatch(profileId, batch.batch_id);
      } else {
        await api.rejectWarmupScriptBatch(profileId, batch.batch_id);
      }
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败");
    } finally {
      setBusy(null);
    }
  };

  if (!info) return null;

  return (
    <div className="mt-3 border-t border-slate-200 pt-3">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium text-slate-800">AI 剧本（一周包）</span>
        {info.llm_configured ? (
          <button
            type="button"
            disabled={info.generating || busy !== null}
            onClick={() => void handleGenerate()}
            className="rounded border border-slate-300 px-3 py-1 text-xs text-slate-700 disabled:opacity-50"
          >
            {info.generating ? "生成中…" : "生成新剧本"}
          </button>
        ) : null}
      </div>
      {!info.llm_configured && (
        <p className="mt-1 leading-5 text-slate-500">
          未配置 LLM：到左侧「AI 设置」填写接口地址、模型和密钥后，这里可以按画像人格生成一周的养号剧本，批准后自动按天轮换执行。
        </p>
      )}
      {info.llm_configured && (
        <p className="mt-1 leading-5 text-slate-500">
          剧本由 AI 离线编写、只包含访问与搜索意图，网址仍由 Manager 按平台目录生成；批准一批后，养号会按天轮换其中的剧本，没有生效剧本时继续用原来的随机计划。
        </p>
      )}
      {info.last_generation?.status === "error" && (
        <p className="mt-1 text-red-600">上次生成失败：{info.last_generation.error}</p>
      )}
      {error && <p className="mt-1 text-red-600">{error}</p>}
      {info.batches.length === 0 && info.llm_configured && (
        <p className="mt-2 text-slate-400">还没有生成过剧本。</p>
      )}
      <div className="mt-2 space-y-3">
        {info.batches.map((batch) => (
          <div key={batch.batch_id} className="rounded border border-slate-200 bg-white p-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-slate-600">
                {batch.created_at.slice(0, 16).replace("T", " ")}
                {" · "}
                <span className={batch.status === "approved" ? "font-medium text-emerald-700" : ""}>
                  {STATUS_LABEL[batch.status] ?? batch.status}
                </span>
                {batch.model && ` · ${batch.model}`}
              </span>
              {batch.status === "draft" && (
                <span className="flex gap-2">
                  <button
                    type="button"
                    disabled={busy !== null}
                    onClick={() => void handleDecide(batch, true)}
                    className="rounded bg-accent px-2.5 py-0.5 text-white disabled:opacity-50"
                  >
                    整批批准
                  </button>
                  <button
                    type="button"
                    disabled={busy !== null}
                    onClick={() => void handleDecide(batch, false)}
                    className="rounded border border-slate-300 px-2.5 py-0.5 text-slate-600 disabled:opacity-50"
                  >
                    驳回
                  </button>
                </span>
              )}
            </div>
            <div className="mt-1.5 space-y-1.5">
              {batch.scripts.map((script) => (
                <div key={script.id}>
                  <div className="font-medium text-slate-700">{script.theme || "（无主题）"}</div>
                  <ul className="ml-3 list-disc space-y-0.5 text-slate-500">
                    {script.steps.map((step, idx) => (
                      <li key={idx}>{stepLine(step)}</li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
