import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  api,
  type DeviceTemplateSummary,
  type Profile,
  type SentenceDraftResult,
  type SentenceOptions,
} from "../lib/api";
import { EnvironmentManager } from "./EnvironmentManager";

function profile(overrides: Partial<Profile>): Profile {
  return {
    id: "p1",
    name: "画像一",
    status: "stopped",
    group_name: "未分组",
    proxy: null,
    proxy_geo: null,
    notes: null,
    tags: [],
    browser_engine: "cloakbrowser",
    disposable: false,
    last_exit_reason: null,
    last_opened_at: null,
    updated_at: "2026-10-23T00:00:00Z",
    ...overrides,
  } as unknown as Profile;
}

const OPTIONS: SentenceOptions = {
  countries: [
    { code: "JP", name: "日本", locale: "ja-JP", timezone: "Asia/Tokyo" },
    { code: "US", name: "美国", locale: "en-US", timezone: "America/New_York" },
  ],
  cities: {
    US: [
      { name: "Seattle", name_zh: "西雅图", timezone: "America/Los_Angeles" },
      { name: "New York", name_zh: "纽约", timezone: "America/New_York" },
    ],
    JP: [
      { name: "Tokyo", name_zh: "东京", timezone: "Asia/Tokyo" },
      { name: "Osaka", name_zh: "大阪", timezone: "Asia/Tokyo" },
    ],
  },
  interests: [
    { id: "camping", name: "露营户外", targets: ["youtube", "google"] },
    { id: "photography", name: "摄影", targets: ["youtube", "google"] },
    { id: "gaming", name: "游戏电竞", targets: ["youtube", "x"] },
  ],
  targets: [
    { id: "google", name: "Google" },
    { id: "youtube", name: "YouTube" },
    { id: "x", name: "X" },
  ],
};

const TEMPLATES: DeviceTemplateSummary[] = [
  {
    id: "tpl-a", name: "模板甲", family: "intel-igpu", cpu: "Intel i5-12400",
    gpu_vendor: "Google Inc. (Intel)", gpu_renderer: "ANGLE (Intel, Intel(R) UHD Graphics 730 Direct3D11)",
    screen_width: 1920, screen_height: 1080, hardware_concurrency: 12, device_memory: 8,
    device_scale_factor: 1,
  },
  {
    id: "tpl-b", name: "模板乙", family: "nvidia-rtx40", cpu: "Intel i7-13700",
    gpu_vendor: "Google Inc. (NVIDIA)", gpu_renderer: "ANGLE (NVIDIA, GeForce RTX 4060 Direct3D11)",
    screen_width: 2560, screen_height: 1440, hardware_concurrency: 16, device_memory: 8,
    device_scale_factor: 1,
  },
];

function draft(overrides: Partial<SentenceDraftResult> = {}): SentenceDraftResult {
  return {
    source: "fallback",
    spec: {
      country: "US", city: "Seattle", interests: ["camping", "photography"],
      persona_notes: null, purpose: null, disposable: false,
    },
    assembled: {
      name: "西雅图 · 露营摄影 10-23-a1b2",
      platform: "windows",
      device_profile: "tpl-a",
      screen_width: 1920, screen_height: 1080,
      gpu_vendor: "Google Inc. (Intel)", gpu_renderer: "ANGLE (Intel, UHD)",
      hardware_concurrency: 12, device_memory: 8,
      timezone: "America/Los_Angeles", locale: "en-US",
      warmup_targets: ["youtube", "google"], warmup_enabled: true,
      warmup_persona: "西雅图，喜欢露营、摄影",
      notes: "一句话建号：建个美国号，西雅图，平时喜欢露营和摄影",
      disposable: false,
      fingerprint_options: { noise: false, storage_quota_mb: 50000 },
    },
    warnings: ["未配置 AI，已用关键词解析（理解有限）"],
    ...overrides,
  };
}

function renderManager(onRefresh = vi.fn().mockResolvedValue(undefined)) {
  const async = () => vi.fn().mockResolvedValue(undefined);
  const utils = render(
    <EnvironmentManager
      profiles={[]}
      groups={[]}
      proxyPresets={[]}
      trashProfiles={[]}
      error={null}
      authRequired={false}
      authUsername={null}
      versions={null}
      onNew={vi.fn()}
      onEdit={vi.fn()}
      onDuplicate={async()}
      onDelete={async()}
      onUpdateNotes={async()}
      onLaunch={async()}
      onBatchLaunch={async()}
      onStop={async()}
      onBatchStop={async()}
      onRefresh={onRefresh}
      onCreateGroup={async()}
      onDeleteGroup={async()}
      onCreateProxyPreset={async()}
      onCreateProxyPresets={async()}
      onDeleteProxyPreset={async()}
      onRestoreProfile={async()}
      onPurgeProfile={async()}
      onAccount={vi.fn()}
      onLogout={vi.fn()}
    />,
  );
  return { ...utils, onRefresh };
}

function mockSentenceApi(draftResult: SentenceDraftResult = draft()) {
  vi.spyOn(api, "draftFromSentence").mockResolvedValue(draftResult);
  vi.spyOn(api, "getSentenceOptions").mockResolvedValue(OPTIONS);
  vi.spyOn(api, "listDeviceTemplates").mockResolvedValue(TEMPLATES);
  return vi.spyOn(api, "createFromSentence").mockResolvedValue({
    ...profile({ id: "new-1", name: draftResult.assembled.name }),
    warnings: [],
  });
}

async function openPreview(sentence = "建个美国号，西雅图，平时喜欢露营和摄影") {
  fireEvent.change(screen.getByLabelText("一句话建号"), { target: { value: sentence } });
  fireEvent.click(screen.getByRole("button", { name: /一句话建号/ }));
  await screen.findByText("一句话建号预览");
}

afterEach(() => vi.restoreAllMocks());

describe("EnvironmentManager one-sentence profile creation", () => {
  it("submits the sentence, previews the draft with a fallback badge, and confirms with edits", async () => {
    const create = mockSentenceApi();
    const { onRefresh } = renderManager();

    await openPreview();

    expect(screen.getByText("关键词解析")).toBeTruthy();
    expect(screen.getByText("未配置 AI，已用关键词解析（理解有限）")).toBeTruthy();
    expect((screen.getByLabelText("画像名称") as HTMLInputElement).value).toBe("西雅图 · 露营摄影 10-23-a1b2");
    expect((screen.getByLabelText("城市") as HTMLSelectElement).value).toBe("Seattle");

    fireEvent.change(screen.getByLabelText("画像名称"), { target: { value: "我的西雅图号" } });
    fireEvent.click(screen.getByRole("button", { name: "确认创建" }));

    await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
    const payload = create.mock.calls[0][0];
    expect(payload.sentence).toBe("建个美国号，西雅图，平时喜欢露营和摄影");
    expect(payload.assembled.name).toBe("我的西雅图号");
    expect(payload.assembled.device_profile).toBe("tpl-a");
    expect(payload.assembled.timezone).toBe("America/Los_Angeles");
    await waitFor(() => expect(onRefresh).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByText("一句话建号预览")).toBeNull());
  });

  it("links country → cities/locale/timezone and city → timezone", async () => {
    mockSentenceApi();
    renderManager();
    await openPreview();

    const timezone = screen.getByLabelText("时区") as HTMLSelectElement;
    expect(timezone.value).toBe("America/Los_Angeles");

    fireEvent.change(screen.getByLabelText("城市"), { target: { value: "New York" } });
    expect(timezone.value).toBe("America/New_York");

    fireEvent.change(screen.getByLabelText("国家"), { target: { value: "JP" } });
    const city = screen.getByLabelText("城市") as HTMLSelectElement;
    expect(city.value).toBe("");
    expect([...city.options].map((option) => option.value)).toContain("Tokyo");
    expect([...city.options].map((option) => option.value)).not.toContain("Seattle");
    expect(timezone.value).toBe("Asia/Tokyo");
    expect((screen.getByLabelText("语言区域") as HTMLInputElement).value).toBe("ja-JP");
  });

  it("shows an AI badge and the data-sharing note for LLM drafts", async () => {
    mockSentenceApi(draft({ source: "llm", warnings: [] }));
    renderManager();
    await openPreview();

    expect(screen.getByText("AI 解析")).toBeTruthy();
    expect(screen.getByText(/发送到你配置的模型接口/)).toBeTruthy();
  });

  it("pre-checks the disposable box when the sentence asked for it", async () => {
    mockSentenceApi(draft({
      spec: { country: "US", city: "Seattle", interests: [], persona_notes: null, purpose: null, disposable: true },
      assembled: { ...draft().assembled, disposable: true },
    }));
    renderManager();
    await openPreview();

    expect((screen.getByLabelText("一次性画像") as HTMLInputElement).checked).toBe(true);
  });

  it("shows the backend 422 detail under the toolbar and opens no dialog", async () => {
    vi.spyOn(api, "draftFromSentence").mockRejectedValue(new Error("没认出国家，请在句子里写明国家"));
    renderManager();

    fireEvent.change(screen.getByLabelText("一句话建号"), { target: { value: "来个号" } });
    fireEvent.click(screen.getByRole("button", { name: /一句话建号/ }));

    expect(await screen.findByText("没认出国家，请在句子里写明国家")).toBeTruthy();
    expect(screen.queryByText("一句话建号预览")).toBeNull();
  });

  it("disables the input while parsing so it cannot be submitted twice", async () => {
    let resolveDraft: (value: SentenceDraftResult) => void = () => {};
    const pending = new Promise<SentenceDraftResult>((resolve) => { resolveDraft = resolve; });
    const draftSpy = vi.spyOn(api, "draftFromSentence").mockReturnValue(pending);
    vi.spyOn(api, "getSentenceOptions").mockResolvedValue(OPTIONS);
    vi.spyOn(api, "listDeviceTemplates").mockResolvedValue(TEMPLATES);
    renderManager();

    const input = screen.getByLabelText("一句话建号") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "建个美国号" } });
    const button = screen.getByRole("button", { name: /一句话建号/ });
    fireEvent.click(button);

    await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(true));
    expect(screen.getByText("解析中...")).toBeTruthy();
    expect(input.disabled).toBe(true);
    expect(draftSpy).toHaveBeenCalledTimes(1);

    resolveDraft(draft());
    await screen.findByText("一句话建号预览");
  });
});
