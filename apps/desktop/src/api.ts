import { convertFileSrc, invoke, isTauri } from "@tauri-apps/api/core";
import type {
  AppStatus,
  Job,
  ModelStatus,
  Project,
  ProjectSummary,
} from "./types";

export const desktop = isTauri();
export function rpc<T>(
  method: string,
  params: Record<string, unknown> = {},
): Promise<T> {
  if (!desktop)
    return Promise.reject(
      new Error("請從桌面應用程式開啟，瀏覽器目前僅供介面預覽。"),
    );
  return invoke<T>("rpc", { method, params });
}
export const api = {
  dirty: (dirty: boolean) =>
    desktop ? invoke<void>("set_dirty", { dirty }) : Promise.resolve(),
  status: () => rpc<AppStatus>("app.status"),
  projects: () => rpc<ProjectSummary[]>("project.list"),
  project: (project_id: string) => rpc<Project>("project.get", { project_id }),
  jobs: () => rpc<Job[]>("job.list"),
  importMedia: () => invoke<Project | null>("import_media"),
  chooseModel: () => invoke<ModelStatus | null>("choose_model"),
  export: (project: Project, format: string) =>
    invoke<string | null>("export_file", {
      projectId: project.id,
      expectedRevision: project.revision,
      format,
    }),
  media: (path: string) => convertFileSrc(path),
};

export function time(ms: number): string {
  const seconds = Math.floor(Math.max(0, ms) / 1000);
  return `${Math.floor(seconds / 60)
    .toString()
    .padStart(2, "0")}:${(seconds % 60).toString().padStart(2, "0")}`;
}
export function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
export const stages: Record<string, string> = {
  queued: "等待處理",
  preprocess: "準備音訊",
  model_loading: "正在載入模型",
  asr: "正在轉錄",
  saving: "正在儲存逐字稿",
  complete: "轉錄完成",
  no_speech: "未偵測到語音",
};
export const statuses: Record<string, string> = {
  queued: "排隊中",
  running: "處理中",
  completed: "已完成",
  failed: "處理失敗",
  cancelled: "已取消",
  interrupted: "已中斷",
};
