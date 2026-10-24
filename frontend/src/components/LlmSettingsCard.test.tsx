import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../lib/api";
import { LlmSettingsCard } from "./LlmSettingsCard";

afterEach(() => vi.restoreAllMocks());

const status = {
  configured: true, base_url: "https://llm.example/v1", model: "m1", has_api_key: true,
  executor_model: null, executor_effort: null,
};

describe("LlmSettingsCard", () => {
  it("clears a stored API key", async () => {
    vi.spyOn(api, "getLlmSettings").mockResolvedValue(status);
    const update = vi.spyOn(api, "updateLlmSettings").mockResolvedValue({ ...status, configured: false, has_api_key: false });
    render(<LlmSettingsCard />);

    fireEvent.click(await screen.findByRole("button", { name: "清除已保存的密钥" }));

    await waitFor(() => expect(update).toHaveBeenCalledOnce());
    expect(update.mock.calls[0][0]).toMatchObject({ clear_api_key: true, api_key: null });
    expect(await screen.findByText("API 密钥已清除。")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "清除已保存的密钥" })).toBeNull();
  });
});
