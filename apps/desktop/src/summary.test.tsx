import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { SummaryPanel } from "./App";
import type { Project } from "./types";

const item = (kind: "summary" | "decision" | "action", text: string, owner: string | null = null) => ({
  id: text, kind, text, owner, deadline: null, commitment_quote: null,
  citations: [{ segment_id: "a", start_ms: 65000, end_ms: 70000, quote: "原文句子" }] });
const project = (over: Partial<Project> = {}) =>
  ({ id: "p1", title: "週會", duration_ms: 100000, revision: 2,
    transcript: { schema_version: 1, duration_ms: 100000, language: "zh", segments: [{ id: "a" }] },
    summary: { items: [item("decision", "改期"), item("action", "修缺陷", "小王"), item("summary", "討論")],
      model: "gemma", source_revision: 2, generated: 1, chunk_count: 1, covered_segments: 1, total_segments: 1 },
    summary_stale: false, ...over }) as unknown as Project;
const props = { ready: true, modelName: "gemma", serverFound: true, working: false, disabled: false,
  openSettings: vi.fn(), seek: vi.fn(), generate: vi.fn() };
afterEach(cleanup);

it("groups items by kind and jumps to the cited source", () => {
  const seek = vi.fn();
  render(<SummaryPanel {...props} seek={seek} project={project()} />);
  for (const heading of ["決議", "待辦", "討論重點"]) expect(screen.getByText(heading)).toBeTruthy();
  expect(screen.getByText("負責人：小王")).toBeTruthy();
  fireEvent.click(screen.getAllByText("01:05")[0]);
  expect(seek).toHaveBeenCalledWith(65000);
});

it("marks an out-of-date summary and disables source jumps", () => {
  render(<SummaryPanel {...props} project={project({ summary_stale: true })} />);
  expect(screen.getByText(/逐字稿在產生後已修改/)).toBeTruthy();
  expect((screen.getAllByText("01:05")[0] as HTMLButtonElement).disabled).toBe(true);
});

it("explains what is missing instead of offering a dead button", () => {
  render(<SummaryPanel {...props} ready={false} modelName={null} project={project({ summary: null })} />);
  expect(screen.getByText(/尚未設定本機摘要模型/)).toBeTruthy();
  expect((screen.getByText("產生摘要與待辦").closest("button") as HTMLButtonElement).disabled).toBe(true);
});
