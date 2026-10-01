import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import App from "./App";
import { rpc } from "./api";

vi.mock("./api", async (original) => {
  const actual = await original<typeof import("./api")>();
  const segment = (id: string, group: string, speaker: string) => ({
    id, start_ms: 0, end_ms: 2000, text: "內容", raw_text: "內容", speaker, words: [],
    alignment_status: "valid", speaker_group: group, needs_confirmation: id === "b" });
  const group = (label: string, name: string, seconds: number, segments: number) => ({
    label, name, name_source: "auto", seconds, segments, match_reason: null, similarity: null,
    excerpt_count: 4, speaker_id: null });
  const project = { id: "p1", title: "週會", filename: "週會.wav", duration_ms: 60000,
    revision: 3, created: 1, transcript: { schema_version: 1, duration_ms: 60000, language: "zh",
      segments: [segment("a", "speaker_00", "講者 1"), segment("b", "speaker_01", "講者 2")] },
    captions: null, warnings: [], media_path: "/p/source.wav", media_info: { has_video: false },
    speaker_summary: { groups: [group("speaker_00", "講者 1", 40, 1), group("speaker_01", "講者 2", 20, 1)],
      needs_review: 1, created: 1, speaker_count: null, observed: 2, ignored_groups: 0 } };
  return { ...actual, desktop: true,
    rpc: vi.fn().mockImplementation((method: string) =>
      Promise.resolve(method === "voiceprint.list" ? [] : project)),
    api: { dirty: vi.fn().mockResolvedValue(undefined), projects: vi.fn().mockResolvedValue([project]),
      project: vi.fn().mockResolvedValue(project), jobs: vi.fn().mockResolvedValue([]),
      status: vi.fn().mockResolvedValue({ models: { available: true, runtime_available: true,
        diarization_available: true, model: { name: "breeze", engine: "mlx" } },
        hardware: { cores: 8, memory_gb: 16, cuda: false, apple_silicon: true, concurrent_stages: true } }),
      media: (path: string) => path } };
});
afterEach(cleanup);

async function openSpeakers() {
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "週會" }));
  fireEvent.click(await screen.findByRole("button", { name: /講者$/ }));
}

it("重新命名講者分群時帶上目前版本", async () => {
  await openSpeakers();
  const name = await screen.findByLabelText("speaker_00 名稱");
  fireEvent.change(name, { target: { value: "王經理" } });
  fireEvent.blur(name);
  await waitFor(() =>
    expect(rpc).toHaveBeenCalledWith("speaker.rename_group",
      { project_id: "p1", expected_revision: 3, group: "speaker_00", name: "王經理" }));
});

it("可把過度分群合併，並提供註冊聲紋入口", async () => {
  await openSpeakers();
  const merges = await screen.findAllByLabelText("合併到");
  fireEvent.change(merges[1], { target: { value: "speaker_00" } });
  await waitFor(() =>
    expect(rpc).toHaveBeenCalledWith("speaker.merge",
      { project_id: "p1", expected_revision: 3, source: "speaker_01", target: "speaker_00" }));
  expect(screen.getAllByRole("button", { name: "註冊聲紋" })).toHaveLength(2);
});
