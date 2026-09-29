import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import App from "./App";
import { rpc } from "./api";

vi.mock("./api", async (original) => {
  const actual = await original<typeof import("./api")>();
  const project = { id: "p1", title: "測試錄音", filename: "錄音.m4a", duration_ms: 30000,
    revision: 0, created: 1, transcript: null, captions: null, warnings: [],
    media_path: "/projects/p1/original/source.m4a", media_info: { has_video: true } };
  return { ...actual, desktop: true, rpc: vi.fn().mockResolvedValue({ media_path: "/projects/p1/playback/audio.wav" }),
    api: { dirty: vi.fn().mockResolvedValue(undefined), projects: vi.fn().mockResolvedValue([project]),
      project: vi.fn().mockResolvedValue(project), jobs: vi.fn().mockResolvedValue([]),
      status: vi.fn().mockResolvedValue({ models: { available: true, runtime_available: true,
        model: { name: "breeze-asr-25-mlx", engine: "mlx" } } }), media: (path: string) => path } };
});
afterEach(cleanup);

it("舊 M4A 專案即使被標為影片，也能使用音訊控制並切換相容副本", async () => {
  const { container } = render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "測試錄音" }));
  await waitFor(() => expect(container.querySelector("audio")).toBeTruthy());
  expect(container.querySelector("video")).toBeNull();
  expect(container.querySelector("audio")?.controls).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "建立相容音訊供播放" }));
  await waitFor(() => expect(container.querySelector("audio")?.getAttribute("src")).toBe("/projects/p1/playback/audio.wav"));
  expect(rpc).toHaveBeenCalledWith("project.playback", { project_id: "p1" });
  expect((screen.getByLabelText("語音語言") as HTMLSelectElement).value).toBe("");
  expect((screen.getByRole("checkbox") as HTMLInputElement).checked).toBe(false);
});
