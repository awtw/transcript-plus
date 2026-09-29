import { afterEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { SegmentEditor } from "./App";
import type { Segment } from "./types";

afterEach(cleanup);
const segment: Segment = {
  id: "s1",
  text: "原始文字",
  raw_text: "原始文字",
  speaker: "",
  start_ms: 0,
  end_ms: 2000,
  alignment_status: "valid",
  words: [],
};

describe("逐字稿自動儲存", () => {
  it("失敗後不會無限重試或自動覆寫", async () => {
    const save = vi.fn().mockRejectedValue(new Error("版本衝突"));
    render(
      <SegmentEditor
        segment={segment}
        save={save}
        draft={vi.fn()}
        done={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByLabelText("編輯逐字稿"), {
      target: { value: "保留草稿" },
    });
    fireEvent.click(screen.getByRole("button", { name: "完成" }));
    await screen.findByRole("alert");
    await new Promise((resolve) => setTimeout(resolve, 1000));
    expect(save).toHaveBeenCalledTimes(1);
  });

  it("改回已保存的文字會清除未儲存狀態", async () => {
    const clean = vi.fn(),
      save = vi.fn();
    render(
      <SegmentEditor
        segment={segment}
        save={save}
        draft={vi.fn()}
        done={vi.fn()}
        clean={clean}
      />,
    );
    clean.mockClear();
    fireEvent.change(screen.getByLabelText("編輯逐字稿"), {
      target: { value: "暫時修改" },
    });
    fireEvent.change(screen.getByLabelText("編輯逐字稿"), {
      target: { value: segment.text },
    });
    await waitFor(() => expect(clean).toHaveBeenCalled());
    expect(save).not.toHaveBeenCalled();
  });
  it("停止輸入後只保存最終文字", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    const draft = vi.fn();
    render(
      <SegmentEditor
        segment={segment}
        save={save}
        draft={draft}
        done={vi.fn()}
      />,
    );
    const field = screen.getByLabelText("編輯逐字稿");
    fireEvent.change(field, { target: { value: "第一次修改" } });
    fireEvent.change(field, { target: { value: "最終修改" } });
    await waitFor(
      () => expect(save).toHaveBeenCalledWith("s1", "最終修改", ""),
      { timeout: 1800 },
    );
    expect(save).toHaveBeenCalledTimes(1);
    expect(draft).toHaveBeenCalled();
  });

  it("保存失敗保留草稿並允許重試", async () => {
    const save = vi
      .fn()
      .mockRejectedValueOnce(new Error("版本衝突"))
      .mockResolvedValue(undefined);
    const done = vi.fn();
    render(
      <SegmentEditor
        segment={segment}
        save={save}
        draft={vi.fn()}
        done={done}
      />,
    );
    fireEvent.change(screen.getByLabelText("編輯逐字稿"), {
      target: { value: "不可以遺失的草稿" },
    });
    fireEvent.click(screen.getByRole("button", { name: "完成" }));
    await screen.findByRole("alert");
    expect(
      (screen.getByLabelText("編輯逐字稿") as HTMLTextAreaElement).value,
    ).toBe("不可以遺失的草稿");
    expect(done).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "完成" }));
    await waitFor(() => expect(done).toHaveBeenCalledTimes(1));
  });

  it("空白文字不會送出或結束編輯", async () => {
    const save = vi.fn(),
      done = vi.fn();
    render(
      <SegmentEditor
        segment={segment}
        save={save}
        draft={vi.fn()}
        done={done}
      />,
    );
    fireEvent.change(screen.getByLabelText("編輯逐字稿"), {
      target: { value: "   " },
    });
    fireEvent.click(screen.getByRole("button", { name: "完成" }));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(save).not.toHaveBeenCalled();
    expect(done).not.toHaveBeenCalled();
  });

  it("請求途中繼續打字，完成後會保存較新的草稿", async () => {
    let resolve: (() => void) | undefined;
    const save = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise<void>((r) => {
            resolve = r;
          }),
      )
      .mockResolvedValue(undefined);
    render(
      <SegmentEditor
        segment={segment}
        save={save}
        draft={vi.fn()}
        done={vi.fn()}
      />,
    );
    const field = screen.getByLabelText("編輯逐字稿");
    fireEvent.change(field, { target: { value: "先儲存這段" } });
    await waitFor(() => expect(save).toHaveBeenCalledTimes(1), {
      timeout: 1800,
    });
    fireEvent.change(field, { target: { value: "請求中新增文字" } });
    resolve!();
    await waitFor(
      () => expect(save).toHaveBeenLastCalledWith("s1", "請求中新增文字", ""),
      { timeout: 2000 },
    );
    expect(save).toHaveBeenCalledTimes(2);
  });
});
