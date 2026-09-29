import { useCallback, useEffect, useRef, useState } from "react";
import { useVirtualizer, defaultRangeExtractor } from "@tanstack/react-virtual";
import {
  AudioLines,
  Plus,
  FolderOpen,
  Settings2,
  ShieldCheck,
  ArrowUpFromLine,
  ChevronRight,
  FileAudio,
  Search,
  MoreHorizontal,
  Play,
  FileText,
  Captions,
  Sparkles,
  Check,
  LoaderCircle,
  X,
  AlertCircle,
  Download,
  Undo2,
  Redo2,
  Scissors,
  Merge,
  ArrowRight,
  HardDrive,
  Mic2,
} from "lucide-react";
import { api, desktop, message, rpc, stages, statuses, time } from "./api";
import type {
  AppStatus,
  Cue,
  Job,
  Project,
  ProjectSummary,
  Segment,
} from "./types";

type Tab = "transcript" | "captions" | "summary";
const noop = () => {};

export default function App() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [project, setProjectState] = useState<Project | null>(null);
  const projectRef = useRef<Project | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [status, setStatus] = useState<AppStatus | null>(null);
  const [tab, setTab] = useState<Tab>("transcript");
  const [settings, setSettings] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [search, setSearch] = useState("");
  const [projectSearch, setProjectSearch] = useState("");
  const [language, setLanguage] = useState("zh");
  const [saveState, setSaveState] = useState("已儲存");
  const [editing, setEditing] = useState<string | null>(null);
  const [position, setPosition] = useState(0);
  const [playError, setPlayError] = useState(false);
  const [format, setFormat] = useState("srt");
  const [split, setSplit] = useState<Cue | null>(null);
  const [undo, setUndo] = useState<number[]>([]);
  const [redo, setRedo] = useState<number[]>([]);
  const [confirmation, setConfirmation] = useState<{
    title: string;
    text: string;
    run: () => void;
  } | null>(null);
  const player = useRef<HTMLMediaElement | null>(null);
  const saveQueue = useRef(Promise.resolve());
  const refreshGeneration = useRef(0);
  const setProject = useCallback((value: Project | null) => {
    projectRef.current = value;
    setProjectState(value);
  }, []);

  const refresh = useCallback(async () => {
    if (!desktop) return;
    const [list, jobList, appStatus] = await Promise.all([
      api.projects(),
      api.jobs(),
      api.status(),
    ]);
    setProjects(list);
    setJobs(jobList);
    setStatus(appStatus);
  }, []);
  useEffect(() => {
    refresh().catch((e) => setError(message(e)));
    const interval = setInterval(
      () => refresh().catch((e) => setError(message(e))),
      2000,
    );
    return () => clearInterval(interval);
  }, [refresh]);

  const markDraft = useCallback(() => setSaveState("尚未儲存"), []);
  const markSaved = useCallback(() => setSaveState("已儲存"), []);
  useEffect(() => {
    api.dirty(saveState !== "已儲存").catch(() => {});
  }, [saveState]);
  const activeJob = project
    ? jobs.find((j) => j.project_id === project.id)
    : null;
  const working = activeJob && ["queued", "running"].includes(activeJob.status);
  useEffect(() => {
    if (!project || editing || saveState !== "已儲存") return;
    const latest = projects.find((p) => p.id === project.id);
    if (latest && latest.revision !== project.revision) {
      const id = project.id;
      api
        .project(id)
        .then((p) => {
          if (projectRef.current?.id === id) setProject(p);
        })
        .catch((e) => setError(message(e)));
    }
  }, [projects, project, editing, saveState, setProject]);

  const act = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await fn();
      await refresh();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  };
  const open = async (id: string) => {
    if (saveState !== "已儲存") {
      setError("請先完成目前的儲存，再切換專案。");
      return;
    }
    const generation = ++refreshGeneration.current;
    await act(async () => {
      const p = await api.project(id);
      if (generation !== refreshGeneration.current) return;
      setProject(p);
      setEditing(null);
      setSearch("");
      setUndo([]);
      setRedo([]);
      setTab("transcript");
      setPosition(0);
      setPlayError(false);
    });
  };
  const importFile = () =>
    act(async () => {
      const p = await api.importMedia();
      if (p) {
        setProject(p);
        setTab("transcript");
        setEditing(null);
        setUndo([]);
        setRedo([]);
        setPlayError(false);
        setPosition(0);
      }
    });
  const seek = (ms: number) => {
    if (player.current) {
      player.current.currentTime = ms / 1000;
      player.current.play().catch(() => {});
    }
  };

  const saveSegment = useCallback(
    (id: string, text: string, speaker: string): Promise<void> => {
      setSaveState("儲存中");
      const task = saveQueue.current
        .catch(() => {})
        .then(async () => {
          const current = projectRef.current;
          if (!current) return;
          const before = current.revision;
          const p = await rpc<Project>("transcript.edit", {
            project_id: current.id,
            expected_revision: before,
            segment_id: id,
            text,
            speaker,
          });
          if (projectRef.current?.id === p.id) {
            setProject(p);
            setUndo((old) => [...old, before]);
            setRedo([]);
            setSaveState("已儲存");
          }
        })
        .catch((e) => {
          setSaveState("儲存失敗");
          setError(message(e));
          throw e;
        });
      saveQueue.current = task;
      return task;
    },
    [setProject],
  );
  const restore = (direction: "undo" | "redo") =>
    act(async () => {
      const current = projectRef.current;
      const stack = direction === "undo" ? undo : redo;
      if (!current || !stack.length) return;
      const p = await rpc<Project>("transcript.restore", {
        project_id: current.id,
        expected_revision: current.revision,
        target_revision: stack[stack.length - 1],
      });
      if (direction === "undo") {
        setUndo(stack.slice(0, -1));
        setRedo((old) => [...old, current.revision]);
      } else {
        setRedo(stack.slice(0, -1));
        setUndo((old) => [...old, current.revision]);
      }
      setProject(p);
      setEditing(null);
    });
  const captionCommand = (method: string, params: Record<string, unknown>) =>
    act(async () => {
      const current = projectRef.current!;
      setProject(
        await rpc<Project>(method, {
          project_id: current.id,
          expected_revision: current.revision,
          expected_track_revision: current.captions?.revision,
          ...params,
        }),
      );
    });
  const generate = () => {
    const run = () =>
      captionCommand("caption.generate", {
        replace: true,
        max_chars: project?.captions?.max_chars ?? 18,
      });
    if (project?.captions)
      setConfirmation({
        title: "重新產生字幕",
        text: "這會取代目前字幕的拆句與時間設定，逐字稿不會改變。",
        run,
      });
    else run();
  };
  const editLocked = busy || saveState !== "已儲存";
  const visibleProjects = projects.filter((p) =>
    p.title.toLocaleLowerCase().includes(projectSearch.toLocaleLowerCase()),
  );

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <button
          className="brand"
          onClick={() => {
            if (!editLocked) {
              setProject(null);
              setEditing(null);
            }
          }}
          aria-label="回到首頁"
        >
          <span className="brand-icon">
            <AudioLines size={22} />
          </span>
          <span>
            transcript<span className="brand-plus">+</span>
          </span>
        </button>
        <button
          className="new-project"
          onClick={importFile}
          disabled={!desktop || busy || saveState !== "已儲存"}
        >
          <Plus size={17} />
          新增專案
        </button>
        <div className="nav-label">工作空間</div>
        <button
          className={`nav-item ${!project ? "selected" : ""}`}
          onClick={() => {
            if (!editLocked) setProject(null);
          }}
        >
          <FolderOpen size={17} />
          所有專案<span className="count">{projects.length}</span>
        </button>
        <div className="nav-label section-label">最近專案</div>
        <div className="recent-list">
          {projects.slice(0, 8).map((p) => (
            <button
              key={p.id}
              className={`recent-item ${p.id === project?.id ? "current" : ""}`}
              onClick={() => open(p.id)}
              disabled={busy}
            >
              <FileAudio size={15} />
              <span>{p.title}</span>
            </button>
          ))}
        </div>
        <div className="sidebar-bottom">
          <div className="local-note">
            <ShieldCheck size={18} />
            <div>
              <strong>你的內容，只在這裡</strong>
              <span>本機處理・無雲端上傳</span>
            </div>
          </div>
          <button className="nav-item" onClick={() => setSettings(true)}>
            <Settings2 size={17} />
            模型與設定
            <span
              className={`status-dot ${status?.models.available ? "ready" : ""}`}
            />
          </button>
          <div className="version">
            桌面開發版 <span>v0.1.0</span>
          </div>
        </div>
      </aside>
      <main className="main">
        <header className="topbar">
          <div>
            <span>工作空間</span>
            <ChevronRight size={13} />
            <strong>{project ? project.title : "所有專案"}</strong>
          </div>
          <div className="top-status">
            <span className="dot" />
            {desktop ? "本機工作空間" : "瀏覽器介面預覽"}
            <span className="avatar">TP</span>
          </div>
        </header>
        {(error || notice) && (
          <div
            role={error ? "alert" : "status"}
            className={`toast ${error ? "error" : "success"}`}
          >
            <AlertCircle size={16} />
            <span>{error || notice}</span>
            <button
              aria-label="關閉訊息"
              onClick={() => {
                setError("");
                setNotice("");
              }}
            >
              <X size={16} />
            </button>
          </div>
        )}
        {!project ? (
          <section className="home">
            <div className="page-heading">
              <div>
                <div className="eyebrow">YOUR WORDS, YOUR WORKSPACE</div>
                <h1>讓每一句話，都有下一步。</h1>
                <p>從一份錄音，開始整理逐字稿、字幕與想法。</p>
              </div>
              <span className="outline-label">
                <HardDrive size={14} />
                本機優先
              </span>
            </div>
            <button
              className="import-zone"
              onClick={importFile}
              disabled={!desktop || busy}
            >
              <div className="sound-lines">
                {[
                  12, 25, 18, 36, 49, 30, 55, 40, 22, 45, 60, 34, 48, 24, 14,
                ].map((h, i) => (
                  <i key={i} style={{ height: h }} />
                ))}
              </div>
              <span className="import-icon">
                {busy ? (
                  <LoaderCircle className="spin" />
                ) : (
                  <ArrowUpFromLine size={25} />
                )}
              </span>
              <strong>
                {busy ? "正在匯入你的檔案…" : "把聲音，變成可以編輯的文字"}
              </strong>
              <span>
                {desktop
                  ? "選擇電腦中的影音檔案，建立新專案"
                  : "請啟動桌面應用程式，即可匯入本機影音"}
              </span>
              <span className="file-types">
                MP4 <b>·</b> MOV <b>·</b> MP3 <b>·</b> M4A <b>·</b> WAV{" "}
                <em>最長 120 分鐘</em>
              </span>
              <span className="import-button">
                選擇影音檔案 <ArrowRight size={15} />
              </span>
            </button>
            <div className="library-heading">
              <h2>
                我的專案 <span>{projects.length}</span>
              </h2>
              <label className="search">
                <Search size={15} />
                <input
                  aria-label="搜尋專案"
                  placeholder="搜尋專案"
                  value={projectSearch}
                  onChange={(e) => setProjectSearch(e.target.value)}
                />
              </label>
            </div>
            {visibleProjects.length ? (
              <div className="project-grid">
                {visibleProjects.map((p) => {
                  const j = jobs.find((j) => j.project_id === p.id);
                  return (
                    <button
                      key={p.id}
                      className="project-card"
                      onClick={() => open(p.id)}
                      disabled={busy}
                    >
                      <div className="card-top">
                        <span className="file-icon">
                          <FileAudio size={24} />
                        </span>
                        <span
                          className={`badge ${j?.status === "completed" ? "green" : ""}`}
                        >
                          {j ? statuses[j.status] : "待轉錄"}
                        </span>
                      </div>
                      <h3>{p.title}</h3>
                      <p>{p.filename}</p>
                      <div className="card-footer">
                        <span>
                          {time(p.duration_ms)} <b>·</b>{" "}
                          {new Date(p.created * 1000).toLocaleDateString(
                            "zh-TW",
                          )}
                        </span>
                        <ArrowRight size={15} />
                      </div>
                    </button>
                  );
                })}
              </div>
            ) : (
              <div className="empty-library">
                <FolderOpen size={24} />
                <strong>
                  {projectSearch
                    ? "找不到符合的專案"
                    : "第一個專案，從這裡開始"}
                </strong>
                <p>
                  {projectSearch
                    ? "試試其他關鍵字。"
                    : "匯入後的內容會儲存在這裡，隨時可以回來繼續。"}
                </p>
              </div>
            )}
            <div className="workflow">
              <span>
                <span className="step">1</span>匯入影音
              </span>
              <ChevronRight size={14} />
              <span>
                <span className="step">2</span>轉錄與校對
              </span>
              <ChevronRight size={14} />
              <span>
                <span className="step">3</span>整理字幕
              </span>
              <ChevronRight size={14} />
              <span>
                <span className="step">4</span>匯出你的作品
              </span>
            </div>
          </section>
        ) : (
          <section className="workspace">
            <div className="workspace-heading">
              <div>
                <h1>{project.title}</h1>
                <p>
                  {time(project.duration_ms)} <b>·</b> {project.filename}{" "}
                  <b>·</b> 版本 {project.revision}
                </p>
              </div>
              <div className="export-controls">
                <select
                  aria-label="匯出格式"
                  value={format}
                  onChange={(e) => setFormat(e.target.value)}
                >
                  {["srt", "vtt", "txt", "json"].map((f) => (
                    <option key={f}>{f}</option>
                  ))}
                </select>
                <button
                  className="primary"
                  disabled={!project.transcript || editLocked}
                  onClick={() =>
                    act(async () => {
                      const path = await api.export(project, format);
                      if (path) setNotice(`已匯出至 ${path}`);
                    })
                  }
                >
                  <Download size={15} />
                  匯出
                </button>
              </div>
            </div>
            <div className="workspace-grid">
              <div className="editor-panel">
                <div className="tabs">
                  <button
                    className={tab === "transcript" ? "active" : ""}
                    onClick={() => {
                      if (!editLocked) {
                        setTab("transcript");
                        setEditing(null);
                      }
                    }}
                  >
                    <FileText size={16} />
                    逐字稿
                  </button>
                  <button
                    className={tab === "captions" ? "active" : ""}
                    onClick={() => {
                      if (!editLocked) {
                        setTab("captions");
                        setEditing(null);
                      }
                    }}
                  >
                    <Captions size={17} />
                    字幕
                  </button>
                  <button
                    className={tab === "summary" ? "active" : ""}
                    onClick={() => {
                      if (!editLocked) {
                        setTab("summary");
                        setEditing(null);
                      }
                    }}
                  >
                    <Sparkles size={16} />
                    摘要與待辦
                  </button>
                  <span
                    className={`save-state ${saveState === "儲存失敗" ? "danger" : ""}`}
                  >
                    {saveState === "已儲存" ? (
                      <Check size={13} />
                    ) : (
                      <LoaderCircle size={13} className="spin" />
                    )}
                    {saveState}
                  </span>
                </div>
                {tab === "transcript" && (
                  <>
                    <div className="editor-toolbar">
                      <label className="search">
                        <Search size={15} />
                        <input
                          aria-label="搜尋逐字稿"
                          disabled={!!editing}
                          placeholder="搜尋逐字稿…"
                          value={search}
                          onChange={(e) => setSearch(e.target.value)}
                        />
                      </label>
                      <button
                        className="icon-button"
                        title="復原"
                        aria-label="復原"
                        disabled={!undo.length || editLocked || !!editing}
                        onClick={() => restore("undo")}
                      >
                        <Undo2 size={16} />
                      </button>
                      <button
                        className="icon-button"
                        title="重做"
                        aria-label="重做"
                        disabled={!redo.length || editLocked || !!editing}
                        onClick={() => restore("redo")}
                      >
                        <Redo2 size={16} />
                      </button>
                    </div>
                    {project.transcript ? (
                      project.transcript.segments.length ? (
                        <TranscriptList
                          segments={project.transcript.segments.filter((s) =>
                            (s.text + s.speaker)
                              .toLocaleLowerCase()
                              .includes(search.toLocaleLowerCase()),
                          )}
                          position={position}
                          editing={editing}
                          onEdit={(id) => {
                            if (saveState === "已儲存") setEditing(id);
                          }}
                          onSeek={seek}
                          onSave={saveSegment}
                          onDraft={markDraft}
                          onClean={markSaved}
                          onDone={() => setEditing(null)}
                        />
                      ) : (
                        <Empty
                          icon={<Mic2 />}
                          title="未偵測到語音"
                          text="這段影音没有辨識到語音內容，請確認錄音或嘗試其他模型。"
                        />
                      )
                    ) : (
                      <Empty
                        icon={<AudioLines />}
                        title={working ? "正在把聲音整理成文字" : "影音已就緒"}
                        text={
                          working
                            ? "你可以先播放錄音。完成後，逐字稿會出現在這裡。"
                            : "選擇語言並開始本機轉錄，完成後即可點擊文字校對。"
                        }
                      />
                    )}
                  </>
                )}
                {tab === "captions" && (
                  <>
                    <div className="editor-toolbar">
                      <span className="muted">
                        {project.captions?.cues.length ?? 0} 則字幕 · 每行{" "}
                        {project.captions?.max_chars ?? 18} 字
                      </span>
                      <button
                        className="secondary"
                        disabled={!project.transcript || editLocked}
                        onClick={generate}
                      >
                        <Sparkles size={14} />
                        {project.captions ? "重新產生" : "產生字幕"}
                      </button>
                    </div>
                    {project.captions_stale && (
                      <div className="inline-warning">
                        <AlertCircle size={16} />
                        逐字稿已修改，請重新產生字幕後再編輯或匯出。
                      </div>
                    )}
                    {project.captions ? (
                      <div className="cue-list">
                        {project.captions.cues.map((cue, i) => (
                          <CaptionRow
                            key={cue.id}
                            cue={cue}
                            index={i}
                            disabled={!!project.captions_stale || editLocked}
                            reasons={
                              project.warnings.find((w) => w.cue_id === cue.id)
                                ?.reasons ?? []
                            }
                            seek={seek}
                            split={() => setSplit(cue)}
                            merge={() =>
                              captionCommand("caption.merge", {
                                cue_id: cue.id,
                              })
                            }
                            changeTime={(start_ms, end_ms) =>
                              captionCommand("caption.time", {
                                cue_id: cue.id,
                                start_ms,
                                end_ms,
                              })
                            }
                          />
                        ))}
                      </div>
                    ) : (
                      <Empty
                        icon={<Captions />}
                        title="讓文字跟上聲音的節奏"
                        text="完成轉錄後，系統會依可靠詞界建立字幕，你可以繼續拆句與微調時間。"
                      />
                    )}
                  </>
                )}
                {tab === "summary" && (
                  <Empty
                    icon={<Sparkles />}
                    title="摘要與待辦尚未啟用"
                    text="目前開發版先提供轉錄與字幕流程。本機摘要模型、原文引用及待辦整理將在後續階段接入。"
                  />
                )}
              </div>
              <aside className="detail-panel">
                <div className="media-card">
                  <div className="media-heading">
                    <span>原始影音</span>
                    <FileAudio size={15} />
                  </div>
                  <div
                    className={`media-preview ${project.media_info.has_video ? "video" : ""}`}
                  >
                    {project.media_info.has_video ? (
                      <video
                        ref={(el) => {
                          player.current = el;
                        }}
                        key={project.id}
                        src={api.media(project.media_path)}
                        controls
                        onTimeUpdate={(e) =>
                          setPosition(e.currentTarget.currentTime * 1000)
                        }
                        onError={() => setPlayError(true)}
                      />
                    ) : (
                      <>
                        <div className="audio-art">
                          <AudioLines size={52} />
                          <span>
                            {project.filename.split(".").pop()?.toUpperCase()}{" "}
                            AUDIO
                          </span>
                        </div>
                        <audio
                          ref={(el) => {
                            player.current = el;
                          }}
                          key={project.id}
                          src={api.media(project.media_path)}
                          controls
                          onTimeUpdate={(e) =>
                            setPosition(e.currentTarget.currentTime * 1000)
                          }
                          onError={() => setPlayError(true)}
                        />
                      </>
                    )}
                  </div>
                  {playError && (
                    <div className="inline-warning">
                      系統播放器不支援此影音編碼；轉錄仍可執行，目前尚未提供播放代理檔。
                    </div>
                  )}
                  <div className="playback-options">
                    <span>
                      {time(position)} / {time(project.duration_ms)}
                    </span>
                    <select
                      aria-label="播放速度"
                      defaultValue="1"
                      onChange={(e) => {
                        if (player.current)
                          player.current.playbackRate = Number(e.target.value);
                      }}
                    >
                      {[0.75, 1, 1.25, 1.5, 2].map((rate) => (
                        <option key={rate} value={rate}>
                          {rate}×
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
                <div className="processing-card">
                  <h3>轉錄設定</h3>
                  <label className="field-label">
                    語音語言
                    <select
                      value={language}
                      onChange={(e) => setLanguage(e.target.value)}
                      disabled={!!working}
                    >
                      <option value="zh">中文（保留中英混用）</option>
                      <option value="en">英文</option>
                      <option value="">自動偵測</option>
                    </select>
                  </label>
                  <div className="model-line">
                    <span
                      className={`status-dot ${status?.models.available ? "ready" : ""}`}
                    />
                    <span>
                      {status?.models.model?.name ?? "尚未設定本機模型"}
                    </span>
                    <button
                      onClick={() => setSettings(true)}
                      aria-label="變更模型"
                    >
                      <Settings2 size={14} />
                    </button>
                  </div>
                  {working ? (
                    <button
                      className="secondary full"
                      disabled={busy}
                      onClick={() =>
                        act(async () => {
                          await rpc("job.cancel", { job_id: activeJob.id });
                        })
                      }
                    >
                      停止處理
                    </button>
                  ) : (
                    <button
                      className="primary full"
                      disabled={
                        busy ||
                        !status?.models.available ||
                        !status.models.runtime_available ||
                        editLocked
                      }
                      onClick={() => {
                        const run = () =>
                          act(async () => {
                            await rpc("job.start", {
                              project_id: project.id,
                              language,
                            });
                          });
                        if (project.transcript)
                          setConfirmation({
                            title: "重新轉錄",
                            text: "這會建立新的逐字稿版本，並使現有字幕過期。",
                            run,
                          });
                        else run();
                      }}
                    >
                      <Play size={14} />
                      {project.transcript ? "重新轉錄" : "開始本機轉錄"}
                    </button>
                  )}
                </div>
                {activeJob && (
                  <div className="job-card">
                    <div>
                      <span
                        className={`badge ${activeJob.status === "completed" ? "green" : ""}`}
                      >
                        {statuses[activeJob.status]}
                      </span>
                      <span className="muted">第 {activeJob.attempt} 次</span>
                    </div>
                    <strong>
                      {stages[activeJob.stage] ?? activeJob.stage}
                    </strong>
                    {working && (
                      <>
                        <div className="progress">
                          <i
                            style={{
                              width:
                                activeJob.processed_ms == null
                                  ? "20%"
                                  : `${Math.max(2, Math.min(100, (activeJob.processed_ms / project.duration_ms) * 100))}%`,
                            }}
                          />
                        </div>
                        <small>
                          {activeJob.processed_ms == null
                            ? "正在準備，進度尚無法估計"
                            : `已處理 ${time(activeJob.processed_ms)} / ${time(project.duration_ms)}`}
                        </small>
                      </>
                    )}
                    {activeJob.error && (
                      <p className="danger">{activeJob.error}</p>
                    )}
                    {["failed", "cancelled", "interrupted"].includes(
                      activeJob.status,
                    ) && (
                      <button
                        className="secondary"
                        disabled={busy}
                        onClick={() =>
                          act(async () => {
                            await rpc("job.retry", { job_id: activeJob.id });
                          })
                        }
                      >
                        重試工作
                      </button>
                    )}
                  </div>
                )}
                <div className="tip">
                  <ShieldCheck size={17} />
                  <p>
                    影音與文字保存在這台電腦。轉錄期間可以繼續校對；版本不同時不會覆蓋你的修改。
                  </p>
                </div>
              </aside>
            </div>
          </section>
        )}
      </main>
      {settings && (
        <div
          className="modal-backdrop"
          onClick={() => !busy && setSettings(false)}
        >
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="settings-title"
            className="modal"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-heading">
              <h2 id="settings-title">模型與本機設定</h2>
              <button aria-label="關閉設定" onClick={() => setSettings(false)}>
                <X size={20} />
              </button>
            </div>
            <div className="model-illustration">
              <HardDrive size={32} />
              <div>
                <strong>離線語音辨識</strong>
                <span>faster-whisper · CPU INT8</span>
              </div>
            </div>
            <p>
              選擇已準備好的 CTranslate2
              模型資料夾。此開發版不會自動下載模型，也不會把錄音傳至雲端。
            </p>
            <div className="settings-facts">
              <span>轉錄引擎</span>
              <strong>
                {status
                  ? status.models.runtime_available
                    ? "已安裝"
                    : "尚未安裝"
                  : "請從桌面開啟"}
              </strong>
              <span>使用中的模型</span>
              <strong>{status?.models.model?.name ?? "尚未設定"}</strong>
              <span>資料位置</span>
              <code>{status?.data_dir ?? "桌面啟動後建立"}</code>
            </div>
            <div className="inline-warning">
              講者自動分離、AI
              摘要及模型下載管理尚在開發中。目前可手動修改每段講者名稱。
            </div>
            <button
              className="primary full"
              disabled={!desktop || busy}
              onClick={() =>
                act(async () => {
                  const model = await api.chooseModel();
                  if (model) setNotice("已驗證並設定本機模型。");
                })
              }
            >
              {busy ? (
                <LoaderCircle size={16} className="spin" />
              ) : (
                <FolderOpen size={16} />
              )}
              選擇本機模型資料夾
            </button>
            <p className="footnote">
              需包含
              model.bin、config.json、tokenizer.json。模型檔案會先計算校驗碼，大型模型可能需要一些時間。
            </p>
          </section>
        </div>
      )}
      {split && (
        <SplitDialog
          cue={split}
          onClose={() => setSplit(null)}
          onSubmit={async (offset, manual_ms) => {
            const current = projectRef.current!;
            try {
              setProject(
                await rpc<Project>("caption.split", {
                  project_id: current.id,
                  expected_revision: current.revision,
                  expected_track_revision: current.captions?.revision,
                  cue_id: split.id,
                  offset,
                  manual_ms,
                }),
              );
              setSplit(null);
            } catch (e) {
              throw new Error(message(e));
            }
          }}
        />
      )}
      {confirmation && (
        <div className="modal-backdrop">
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="confirm-title"
          >
            <div className="modal-heading">
              <h2 id="confirm-title">{confirmation.title}</h2>
            </div>
            <p>{confirmation.text}</p>
            <div className="confirm-actions">
              <button
                className="secondary"
                autoFocus
                onClick={() => setConfirmation(null)}
              >
                取消
              </button>
              <button
                className="primary"
                onClick={() => {
                  const run = confirmation.run;
                  setConfirmation(null);
                  run();
                }}
              >
                確認{confirmation.title}
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

function Empty({
  icon,
  title,
  text,
}: {
  icon: React.ReactNode;
  title: string;
  text: string;
}) {
  return (
    <div className="empty-state">
      <span>{icon}</span>
      <h3>{title}</h3>
      <p>{text}</p>
    </div>
  );
}

function TranscriptList({
  segments,
  editing,
  position,
  onEdit,
  onSeek,
  onSave,
  onDraft,
  onClean,
  onDone,
}: {
  segments: Segment[];
  editing: string | null;
  position: number;
  onEdit: (id: string) => void;
  onSeek: (ms: number) => void;
  onSave: (id: string, text: string, speaker: string) => Promise<void>;
  onDraft: () => void;
  onClean: () => void;
  onDone: () => void;
}) {
  const parent = useRef<HTMLDivElement>(null);
  const virtual = useVirtualizer({
    count: segments.length,
    getScrollElement: () => parent.current,
    estimateSize: () => 116,
    overscan: 8,
    rangeExtractor: (range) => {
      const indices = defaultRangeExtractor(range);
      const index = segments.findIndex((s) => s.id === editing);
      return index < 0
        ? indices
        : [...new Set([...indices, index])].sort((a, b) => a - b);
    },
  });
  if (!segments.length)
    return (
      <Empty
        icon={<Search />}
        title="沒有符合的段落"
        text="請試試其他關鍵字。"
      />
    );
  return (
    <div className="transcript-list" ref={parent}>
      <div style={{ height: virtual.getTotalSize(), position: "relative" }}>
        {virtual.getVirtualItems().map((row) => {
          const s = segments[row.index];
          return (
            <article
              ref={virtual.measureElement}
              data-index={row.index}
              key={s.id}
              style={{
                position: "absolute",
                top: 0,
                left: 0,
                width: "100%",
                transform: `translateY(${row.start}px)`,
              }}
              className={`segment ${position >= s.start_ms && position < s.end_ms ? "playing" : ""}`}
            >
              <button
                className="timestamp"
                onClick={() => onSeek(s.start_ms)}
                title="從這裡播放"
              >
                {time(s.start_ms)}
              </button>
              <div className="segment-content">
                {editing === s.id ? (
                  <SegmentEditor
                    key={s.id}
                    segment={s}
                    save={onSave}
                    draft={onDraft}
                    clean={onClean}
                    done={onDone}
                  />
                ) : (
                  <>
                    <div className="speaker">
                      <span className="speaker-dot" />
                      {s.speaker || "未標記講者"}
                      {s.alignment_status !== "valid" && (
                        <span className="timing-hint">詞時間待核對</span>
                      )}
                      <button
                        className="edit-text"
                        onClick={() => onEdit(s.id)}
                      >
                        編輯
                      </button>
                    </div>
                    <p onDoubleClick={() => onEdit(s.id)}>{s.text}</p>
                  </>
                )}
              </div>
            </article>
          );
        })}
      </div>
    </div>
  );
}

export function SegmentEditor({
  segment,
  save,
  draft,
  done,
  clean = noop,
}: {
  segment: Segment;
  save: (id: string, text: string, speaker: string) => Promise<void>;
  draft: () => void;
  done: () => void;
  clean?: () => void;
}) {
  const [text, setText] = useState(segment.text),
    [speaker, setSpeaker] = useState(segment.speaker);
  const [error, setError] = useState(""),
    [saving, setSaving] = useState(false);
  const persisted = useRef({ text: segment.text, speaker: segment.speaker });
  const generation = useRef(0);
  const inFlight = useRef(false);
  const latest = useRef({ text, speaker });
  latest.current = { text, speaker };
  const flush = useCallback(async () => {
    if (inFlight.current) return false;
    const value = latest.current;
    if (
      value.text === persisted.current.text &&
      value.speaker === persisted.current.speaker
    )
      return true;
    if (!value.text.trim()) {
      setError("文字不可空白。");
      return false;
    }
    inFlight.current = true;
    const stamp = ++generation.current;
    setSaving(true);
    setError("");
    try {
      await save(segment.id, value.text, value.speaker);
      persisted.current = value;
      if (
        latest.current.text !== value.text ||
        latest.current.speaker !== value.speaker
      ) {
        draft();
        return false;
      }
      return true;
    } catch (e) {
      setError(message(e));
      return false;
    } finally {
      inFlight.current = false;
      if (stamp === generation.current) setSaving(false);
    }
  }, [save, segment.id, draft]);
  useEffect(() => {
    if (saving) return;
    if (
      text === persisted.current.text &&
      speaker === persisted.current.speaker
    ) {
      clean();
      return;
    }
    if (error) return;
    const timer = setTimeout(() => {
      flush();
    }, 800);
    return () => clearTimeout(timer);
  }, [text, speaker, flush, saving, error, clean]);
  return (
    <div className="segment-editor">
      <input
        aria-label="講者名稱"
        value={speaker}
        placeholder="講者名稱"
        maxLength={80}
        onChange={(e) => {
          setSpeaker(e.target.value);
          setError("");
          draft();
        }}
      />
      <textarea
        aria-label="編輯逐字稿"
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setError("");
          draft();
        }}
        rows={4}
        autoFocus
      />
      <div>
        <span className="muted">停止輸入後自動儲存</span>
        <button
          className="secondary"
          disabled={saving}
          onClick={async () => {
            if (await flush()) done();
          }}
        >
          {saving ? "儲存中" : "完成"}
        </button>
      </div>
      {error && (
        <p role="alert" className="danger">
          {error}
        </p>
      )}
    </div>
  );
}

function CaptionRow({
  cue,
  index,
  disabled,
  reasons,
  seek,
  split,
  merge,
  changeTime,
}: {
  cue: Cue;
  index: number;
  disabled: boolean;
  reasons: string[];
  seek: (ms: number) => void;
  split: () => void;
  merge: () => void;
  changeTime: (a: number, b: number) => void;
}) {
  const [start, setStart] = useState((cue.start_ms / 1000).toFixed(3));
  const [end, setEnd] = useState((cue.end_ms / 1000).toFixed(3));
  useEffect(() => {
    setStart((cue.start_ms / 1000).toFixed(3));
    setEnd((cue.end_ms / 1000).toFixed(3));
  }, [cue.start_ms, cue.end_ms]);
  return (
    <article className="cue">
      <div className="cue-number">{String(index + 1).padStart(2, "0")}</div>
      <div className="cue-content">
        <button className="cue-text" onClick={() => seek(cue.start_ms)}>
          {cue.text}
        </button>
        <div className="cue-times">
          <label>
            起
            <input
              aria-label={`字幕 ${index + 1} 起始秒數`}
              type="number"
              step="0.001"
              min="0"
              value={start}
              disabled={disabled}
              onChange={(e) => setStart(e.target.value)}
            />
          </label>
          <span>→</span>
          <label>
            迄
            <input
              aria-label={`字幕 ${index + 1} 結束秒數`}
              type="number"
              step="0.001"
              min="0"
              value={end}
              disabled={disabled}
              onChange={(e) => setEnd(e.target.value)}
            />
          </label>
          <button
            className="text-button"
            disabled={disabled}
            onClick={() =>
              changeTime(
                Math.round(Number(start) * 1000),
                Math.round(Number(end) * 1000),
              )
            }
          >
            套用
          </button>
          <span className="timing-hint">
            {cue.timing_status === "valid"
              ? "詞界對齊"
              : cue.timing_status === "manual"
                ? "手動時間"
                : "片段時間"}
          </span>
        </div>
        {reasons.length > 0 && (
          <div className="cue-warning">{reasons.join(" · ")}</div>
        )}
      </div>
      <div className="cue-actions">
        <button
          className="icon-button"
          disabled={disabled}
          onClick={split}
          title="拆分字幕"
          aria-label={`拆分字幕 ${index + 1}`}
        >
          <Scissors size={15} />
        </button>
        <button
          className="icon-button"
          disabled={disabled}
          onClick={merge}
          title="與下一則合併"
          aria-label={`合併字幕 ${index + 1}`}
        >
          <Merge size={15} />
        </button>
      </div>
    </article>
  );
}

function SplitDialog({
  cue,
  onClose,
  onSubmit,
}: {
  cue: Cue;
  onClose: () => void;
  onSubmit: (offset: number, time?: number) => Promise<void>;
}) {
  const [offset, setOffset] = useState(0),
    [manual, setManual] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  return (
    <div className="modal-backdrop">
      <section
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="split-title"
      >
        <div className="modal-heading">
          <h2 id="split-title">拆分字幕</h2>
          <button aria-label="關閉拆分" onClick={onClose}>
            <X size={18} />
          </button>
        </div>
        <p>在文字中點選拆分位置。可靠詞界可自動計時，否則需要輸入拆分時間。</p>
        <textarea
          className="split-text"
          aria-label="選擇拆分位置"
          readOnly
          value={cue.text}
          onSelect={(e) => {
            const element = e.currentTarget;
            setOffset(
              Array.from(element.value.slice(0, element.selectionStart)).length,
            );
          }}
        />
        <p className="muted">目前位置：第 {offset} 個字元後</p>
        <label className="field-label">
          手動拆分時間（秒，可留空）
          <input
            aria-label="手動拆分時間"
            type="number"
            step="0.001"
            value={manual}
            onChange={(e) => setManual(e.target.value)}
            placeholder={`${(cue.start_ms / 1000).toFixed(3)} ～ ${(cue.end_ms / 1000).toFixed(3)}`}
          />
        </label>
        {error && (
          <p className="danger" role="alert">
            {error}
          </p>
        )}
        <button
          className="primary full"
          disabled={busy || offset === 0}
          onClick={async () => {
            setBusy(true);
            try {
              await onSubmit(
                offset,
                manual ? Math.round(Number(manual) * 1000) : undefined,
              );
            } catch (e) {
              setError(message(e));
            } finally {
              setBusy(false);
            }
          }}
        >
          <Scissors size={15} />
          拆成兩則字幕
        </button>
      </section>
    </div>
  );
}
