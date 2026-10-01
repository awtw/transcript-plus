#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde_json::{json, Value};
use std::{
    fs,
    io::{BufRead, BufReader, Write},
    path::PathBuf,
    process::{Child, ChildStdin, Command, Stdio},
    sync::{
        atomic::{AtomicBool, AtomicU64, Ordering},
        mpsc, Mutex,
    },
    time::Duration,
};
use tauri::Manager;
use tauri_plugin_dialog::DialogExt;

/// Windows canonicalize() yields `\\?\` paths that CTranslate2 and ONNX Runtime cannot open.
fn plain_path(path: PathBuf) -> PathBuf {
    let text = path.to_string_lossy();
    if let Some(rest) = text.strip_prefix(r"\\?\UNC\") {
        return PathBuf::from(format!(r"\\{rest}"));
    }
    match text.strip_prefix(r"\\?\") {
        Some(rest) => PathBuf::from(rest),
        None => path,
    }
}

struct Core {
    io: Mutex<Option<(ChildStdin, mpsc::Receiver<Value>)>>,
    child: Mutex<Child>,
    counter: AtomicU64,
    dirty: AtomicBool,
    exit_allowed: AtomicBool,
    exit_pending: AtomicBool,
    root: PathBuf,
    #[cfg(windows)]
    _job: WindowsJob,
}

impl Core {
    fn start(app: &tauri::App) -> Result<Self, Box<dyn std::error::Error>> {
        let root = app.path().app_local_data_dir()?;
        fs::create_dir_all(root.join("logs"))?;
        let mut command;
        if cfg!(debug_assertions) {
            let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .ancestors()
                .nth(3)
                .unwrap()
                .to_path_buf();
            let python = if cfg!(windows) {
                repo.join(".venv/Scripts/python.exe")
            } else {
                repo.join(".venv/bin/python")
            };
            command = Command::new(python);
            command
                .args(["-m", "transcript_plus"])
                .env("PYTHONPATH", repo.join("core"));
        } else {
            let name = if cfg!(windows) {
                "transcript-core.exe"
            } else {
                "transcript-core"
            };
            command = Command::new(app.path().resource_dir()?.join("core").join(name));
        }
        command
            .arg("--data-dir")
            .arg(&root)
            .env("PYTHONIOENCODING", "utf-8")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::from(fs::File::create(root.join("logs/core.log"))?));
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x08000000); // CREATE_NO_WINDOW
        }
        let mut child = command.spawn()?;
        #[cfg(windows)]
        let job = WindowsJob::attach(&child)?;
        let stdin = child.stdin.take().ok_or("核心輸入無法建立")?;
        let stdout = child.stdout.take().ok_or("核心輸出無法建立")?;
        let (send, receive) = mpsc::channel();
        std::thread::spawn(move || {
            let mut reader = BufReader::new(stdout);
            loop {
                let mut line = String::new();
                match reader.read_line(&mut line) {
                    Ok(0) | Err(_) => break,
                    Ok(_) => {
                        if line.len() > 32 * 1024 * 1024 {
                            break;
                        }
                        if let Ok(value) = serde_json::from_str(&line) {
                            if send.send(value).is_err() {
                                break;
                            }
                        }
                    }
                }
            }
        });
        Ok(Self {
            io: Mutex::new(Some((stdin, receive))),
            child: Mutex::new(child),
            counter: AtomicU64::new(1),
            dirty: AtomicBool::new(false),
            exit_allowed: AtomicBool::new(false),
            exit_pending: AtomicBool::new(false),
            root,
            #[cfg(windows)]
            _job: job,
        })
    }

    fn request(&self, method: &str, params: Value) -> Result<Value, String> {
        let id = self.counter.fetch_add(1, Ordering::Relaxed);
        let mut io = self.io.lock().map_err(|_| "核心通訊已中斷")?;
        let (stdin, receiver) = io.as_mut().ok_or_else(|| self.stopped_message())?;
        let message = json!({"protocol_version":1,"request_id":id,"method":method,"params":params});
        writeln!(stdin, "{}", message)
            .and_then(|_| stdin.flush())
            .map_err(|_| self.stopped_message())?;
        // Imports and model integrity checks may scan several GB; UI remains responsive.
        loop {
            let response = receiver
                .recv_timeout(Duration::from_secs(180))
                .map_err(|error| match error {
                    mpsc::RecvTimeoutError::Timeout => "核心逾時未回應，請稍後重試或重新啟動".to_string(),
                    mpsc::RecvTimeoutError::Disconnected => self.stopped_message(),
                })?;
            if response.get("request_id").and_then(Value::as_u64) != Some(id) {
                continue;
            }
            if let Some(error) = response.get("error") {
                return Err(error
                    .get("message")
                    .and_then(Value::as_str)
                    .unwrap_or("操作失敗")
                    .to_string());
            }
            return response
                .get("result")
                .cloned()
                .ok_or_else(|| "核心回應格式錯誤".into());
        }
    }

    /// Say why the core is gone (exit code, log location) instead of a generic failure.
    fn stopped_message(&self) -> String {
        let code = self
            .child
            .lock()
            .ok()
            .and_then(|mut child| child.try_wait().ok().flatten())
            .and_then(|status| status.code());
        match code {
            Some(code) => format!("轉錄核心已結束（代碼 {code}），請重新啟動；詳細原因見 {}", self.root.join("logs/core.log").display()),
            None => "核心通訊已中斷，請重新啟動".to_string(),
        }
    }

    fn shutdown(&self) {
        if let Ok(mut io) = self.io.lock() {
            io.take();
        } // EOF asks Python to stop its worker tree.
        if let Ok(mut child) = self.child.lock() {
            for _ in 0..60 {
                if matches!(child.try_wait(), Ok(Some(_))) {
                    return;
                }
                std::thread::sleep(Duration::from_millis(100));
            }
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

fn allow_media(app: &tauri::AppHandle, value: &Value) -> Result<(), String> {
    if let Some(path) = value.get("media_path").and_then(Value::as_str) {
        let state = app.state::<Core>();
        let path = PathBuf::from(path)
            .canonicalize()
            .map_err(|_| "影音檔案不存在")?;
        let base = state
            .root
            .join("projects")
            .canonicalize()
            .map_err(|_| "專案目錄不存在")?;
        if !path.starts_with(base) {
            return Err("影音路徑超出專案範圍".into());
        }
        app.asset_protocol_scope()
            .allow_file(path)
            .map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
async fn rpc(app: tauri::AppHandle, method: String, params: Value) -> Result<Value, String> {
    const ALLOWED: &[&str] = &[
        "app.status",
        "project.list",
        "project.get",
        "project.playback",
        "job.list",
        "job.start",
        "job.cancel",
        "job.retry",
        "transcript.edit",
        "transcript.restore",
        "caption.generate",
        "caption.split",
        "caption.merge",
        "caption.time",
        "glossary.set",
        "speaker.analyze",
        "speaker.rename_group",
        "speaker.assign",
        "speaker.merge",
        "speaker.rematch",
        "voiceprint.list",
        "voiceprint.register",
        "voiceprint.rename",
        "voiceprint.delete",
        "voiceprint.enable",
    ];
    if !ALLOWED.contains(&method.as_str()) {
        return Err("不允許的操作".into());
    }
    tauri::async_runtime::spawn_blocking(move || {
        let result = app.state::<Core>().request(&method, params)?;
        allow_media(&app, &result)?;
        Ok(result)
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
async fn import_media(app: tauri::AppHandle) -> Result<Option<Value>, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let window = app.get_webview_window("main").ok_or("找不到主視窗")?;
        let file = app
            .dialog()
            .file()
            .set_parent(&window)
            .set_title("匯入影音")
            .add_filter("影音檔案", &["wav", "mp3", "m4a", "mp4", "mov"])
            .blocking_pick_file();
        let Some(file) = file else {
            return Ok(None);
        };
        let path = file
            .into_path()
            .map_err(|e| e.to_string())?
            .canonicalize()
            .map_err(|e| e.to_string())?;
        let result = app
            .state::<Core>()
            .request("project.import", json!({"path":path}))?;
        allow_media(&app, &result)?;
        Ok(Some(result))
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
async fn choose_model(app: tauri::AppHandle) -> Result<Option<Value>, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let window = app.get_webview_window("main").ok_or("找不到主視窗")?;
        let Some(file) = app
            .dialog()
            .file()
            .set_parent(&window)
            .set_title("選擇本機模型資料夾")
            .blocking_pick_folder()
        else {
            return Ok(None);
        };
        let path = file
            .into_path()
            .map_err(|e| e.to_string())?
            .canonicalize()
            .map(plain_path)
            .map_err(|e| e.to_string())?;
        app.state::<Core>()
            .request("model.configure", json!({"path":path}))
            .map(Some)
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
async fn choose_speaker_models(app: tauri::AppHandle) -> Result<Option<Value>, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let window = app.get_webview_window("main").ok_or("找不到主視窗")?;
        let Some(file) = app
            .dialog()
            .file()
            .set_parent(&window)
            .set_title("選擇講者模型資料夾（含 segmentation 與 nemo_en_titanet_small.onnx）")
            .blocking_pick_folder()
        else {
            return Ok(None);
        };
        let path = file
            .into_path()
            .map_err(|e| e.to_string())?
            .canonicalize()
            .map(plain_path)
            .map_err(|e| e.to_string())?;
        app.state::<Core>()
            .request("model.configure_speakers", json!({"path":path}))
            .map(Some)
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
async fn export_file(
    app: tauri::AppHandle,
    project_id: String,
    expected_revision: u64,
    format: String,
) -> Result<Option<String>, String> {
    if !["txt", "srt", "vtt", "json"].contains(&format.as_str()) {
        return Err("不支援的格式".into());
    }
    tauri::async_runtime::spawn_blocking(move || {
        let rendered = app.state::<Core>().request(
            "export.render",
            json!({"project_id":project_id,"expected_revision":expected_revision,"format":format}),
        )?;
        let name = rendered["filename"].as_str().unwrap_or("transcript.txt");
        let safe: String = name
            .chars()
            .map(|c| if "<>:\"/\\|?*".contains(c) { '_' } else { c })
            .collect();
        let window = app.get_webview_window("main").ok_or("找不到主視窗")?;
        let Some(file) = app
            .dialog()
            .file()
            .set_parent(&window)
            .set_title("匯出檔案")
            .set_file_name(&safe)
            .blocking_save_file()
        else {
            return Ok(None);
        };
        let path = file.into_path().map_err(|e| e.to_string())?;
        let parent = path
            .parent()
            .ok_or("匯出路徑無效")?
            .canonicalize()
            .map_err(|e| e.to_string())?;
        let filename = path.file_name().ok_or("匯出檔名無效")?;
        let destination = parent.join(filename);
        if destination.is_symlink() {
            return Err("請選擇一般檔案作為匯出位置".into());
        }
        let content = rendered["content"].as_str().ok_or("匯出內容無效")?;
        let mut temporary = tempfile::NamedTempFile::new_in(&parent).map_err(|e| e.to_string())?;
        temporary
            .write_all(content.as_bytes())
            .map_err(|e| e.to_string())?;
        temporary.as_file().sync_all().map_err(|e| e.to_string())?;
        temporary.persist(&destination).map_err(|e| e.to_string())?;
        Ok(Some(destination.to_string_lossy().into_owned()))
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
fn set_dirty(app: tauri::AppHandle, dirty: bool) {
    app.state::<Core>().dirty.store(dirty, Ordering::Relaxed);
}

#[cfg(windows)]
struct WindowsJob(windows_sys::Win32::Foundation::HANDLE);
#[cfg(windows)]
unsafe impl Send for WindowsJob {}
#[cfg(windows)]
unsafe impl Sync for WindowsJob {}
#[cfg(windows)]
impl WindowsJob {
    fn attach(child: &Child) -> Result<Self, std::io::Error> {
        use std::os::windows::io::AsRawHandle;
        use windows_sys::Win32::{Foundation::CloseHandle, System::JobObjects::*};
        unsafe {
            let handle = CreateJobObjectW(std::ptr::null(), std::ptr::null());
            if handle.is_null() {
                return Err(std::io::Error::last_os_error());
            }
            let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            if SetInformationJobObject(
                handle,
                JobObjectExtendedLimitInformation,
                &info as *const _ as *const _,
                std::mem::size_of_val(&info) as u32,
            ) == 0
                || AssignProcessToJobObject(handle, child.as_raw_handle() as _) == 0
            {
                let error = std::io::Error::last_os_error();
                CloseHandle(handle);
                return Err(error);
            }
            Ok(Self(handle))
        }
    }
}
#[cfg(windows)]
impl Drop for WindowsJob {
    fn drop(&mut self) {
        unsafe {
            windows_sys::Win32::Foundation::CloseHandle(self.0);
        }
    }
}

fn request_exit(app: tauri::AppHandle) {
    if app
        .state::<Core>()
        .exit_pending
        .swap(true, Ordering::Relaxed)
    {
        return;
    }
    tauri::async_runtime::spawn_blocking(move || {
        let core = app.state::<Core>();
        let dirty = core.dirty.load(Ordering::Relaxed);
        let jobs = core.request("job.list", json!({})).unwrap_or(json!([]));
        let active = jobs.as_array().is_some_and(|jobs| {
            jobs.iter()
                .any(|j| j["status"] == "running" || j["status"] == "queued")
        });
        if dirty || active {
            let text = if dirty {
                "尚有未儲存的文字。退出將放棄草稿並停止目前工作，確定退出？"
            } else {
                "仍有處理中的工作。退出會停止工作，已完成的結果會保留，下次可重試。確定退出？"
            };
            if !app
                .dialog()
                .message(text)
                .title("退出 Transcript Plus")
                .buttons(tauri_plugin_dialog::MessageDialogButtons::OkCancelCustom(
                    "退出".into(),
                    "繼續使用".into(),
                ))
                .blocking_show()
            {
                core.exit_pending.store(false, Ordering::Relaxed);
                return;
            }
        }
        core.exit_allowed.store(true, Ordering::Relaxed);
        app.exit(0);
    });
}

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            let core = Core::start(app)?;
            app.manage(core);
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                request_exit(window.app_handle().clone());
            }
        })
        .invoke_handler(tauri::generate_handler![
            rpc,
            import_media,
            choose_model,
            choose_speaker_models,
            export_file,
            set_dirty
        ])
        .build(tauri::generate_context!())
        .expect("桌面應用程式無法啟動");
    app.run(|app, event| match event {
        tauri::RunEvent::ExitRequested { api, .. } => {
            if !app.state::<Core>().exit_allowed.load(Ordering::Relaxed) {
                api.prevent_exit();
                request_exit(app.clone());
            }
        }
        tauri::RunEvent::Exit => app.state::<Core>().shutdown(),
        _ => {}
    });
}
