import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { JobProgress } from "./App";
import type { Job } from "./types";

afterEach(cleanup);
const job: Job = { id: "j", project_id: "p", title: "錄音", status: "running", stage: "asr", attempt: 1,
  processed_ms: 30000, error: null, created: 0, started: Date.now() / 1000 - 60 };
it("顯示引擎回報的時間與百分比", () => {
  render(<JobProgress job={job} duration={90000} />);
  expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe("33");
  expect(screen.getByText("已處理 00:30 / 01:30（33%）")).toBeTruthy();
  expect(screen.getByText(/已執行/)).toBeTruthy();
});
it("模型載入及儲存不假裝已完成辨識百分比", () => {
  const { rerender } = render(<JobProgress job={{ ...job, stage: "model_loading", processed_ms: null }} duration={90000} />);
  expect(screen.getByRole("progressbar").hasAttribute("aria-valuenow")).toBe(false);
  expect(screen.getByText(/尚未開始辨識/)).toBeTruthy();
  rerender(<JobProgress job={{ ...job, stage: "saving", processed_ms: 90000 }} duration={90000} />);
  expect(screen.getByText("音訊辨識完成，正在整理並儲存結果")).toBeTruthy();
});
it("第一段完成前清楚說明等待原因", () => {
  render(<JobProgress job={{ ...job, processed_ms: 0 }} duration={90000} />);
  expect(screen.getByText("正在辨識第一段音訊，完成後會更新進度")).toBeTruthy();
});
