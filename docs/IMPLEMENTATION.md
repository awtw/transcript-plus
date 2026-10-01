# v0.1 開發與驗證紀錄

日期：2026-09-29。此版是第一個可執行的開發基線，完成 G0／G1／G2 的部分能力；G0 的雙平台、品質與完整模型評估尚未結案。

## 已實作

| 模組 | 內容 |
|---|---|
| 桌面外殼 | Tauri 2、React／TypeScript、原生選檔及匯出、單一實例、受限媒體 asset scope、Core 子程序及關閉流程。 |
| 本機核心 | JSON Lines IPC；不開 HTTP API；SQLite WAL、單一資料目錄鎖、逐字稿歷史與版本衝突保護。 |
| 影音 | 匯入 WAV／MP3／M4A／MP4／MOV 的可解碼音軌，檢查時長／大小／容量，保存原檔副本與 SHA-256。 |
| 轉錄 | faster-whisper CPU INT8／Apple Silicon MLX、本機模型 hash 驗證、品質模式（延續前文、VAD 關閉）、選用詞時間、離線環境設定、原始文字保留。 |
| 工作 | 持久化排隊、子程序隔離、進度、取消、重試、開機恢復中斷狀態、重用已校驗的 PCM 前處理產物。 |
| 校對 | 點段落跳播、播放倍速、全文篩選、虛擬清單、800 ms 防抖自動儲存、手動講者、當次編輯復原／重做。 |
| 字幕 | 詞界／停頓／標點切分、同段字幕拆合、手動時間、品質警示、失效版本處理。 |
| 匯出 | TXT、SRT、VTT、JSON；禁止過期或時間重疊字幕匯出，保留修訂版本。 |
| 打包 | PyInstaller onedir，含 Python、ASR runtime、FFmpeg／ffprobe；Tauri 使用資源目錄啟動封裝核心。 |

模型及服務程式重新撰寫，未複製 FABO 程式、錄音、聲紋或資料庫。參考既有設計中的時間映射、版本與中斷處理原則。

## 本機驗證

- 26 項 Python 核心測試通過，涵蓋真實 WAV 匯入、時間邊界、字詞修改失效、字幕拆合、SRT／VTT 時鐘、版本衝突、歷史恢復、中斷狀態、資料鎖及 stdio 協定。
- 6 項前端測試通過，涵蓋防抖儲存、保存失敗不丟草稿、空白文字拒絕、保存途中繼續輸入、失敗後停止自動重試，以及改回原文清除未儲存狀態。TypeScript 與正式前端 build 通過。
- Rust `cargo check` 與本機 macOS `.app` 建置通過。
- 使用 macOS 系統合成的 8.35 秒英文語音，搭配公開 `Systran/faster-whisper-tiny` 測試模型，開發核心實際辨識出 2 段、22 個詞時間，匯出 TXT／SRT／VTT／JSON。第一次測得整個 smoke 流程約 3.81 秒，包含初始化等操作；這不是產品效能基準。
- 封裝核心使用僅含 `/usr/bin:/bin` 的 PATH，仍能匯入、轉錄、匯出 VTT 並正常退出；證實該路徑不需使用開發環境的 Python／FFmpeg。
- `.app` 已實際透過原生對話框匯入 WAV、選擇本機模型並完成轉錄；播放控制讀取到 8 秒音訊。已驗證手動講者及文字修改會自動保存並增加修訂版本；字幕隨即標示過期。重新產生後已透過原生儲存對話框匯出 SRT，並讀回檔案確認內容與時間。重新產生字幕與重新轉錄改用應用程式內的明確確認對話框；已在最終 `.app` 確認重新轉錄對話框可取消，且取消不建立新工作。重啟後仍可讀取修訂版本 4、校正文字與手動講者。原生檔案對話框已設定主視窗 parent，修正初次操作時選擇按鈕狀態不正常的問題。
- Windows 建置及測試工作流程已配置，**尚未在本次本機環境執行，也未發布或上傳安裝包**。

短檔測試不代表繁中／中英混用準確率、120 分鐘穩定性、Windows 支援或原始 MVP 的品質門檻已通過。測試音檔／模型／SQLite 與匯出成果放 `.local-data/`，均已忽略。

## 開發與打包細節

Core 開發模式由專案 `.venv` 啟動；release 使用 `.app`／安裝目錄內的 `core/transcript-core`。`packaging/build_core.py` 需在目標平台執行，先建立 onedir，再放入 Tauri 資源目錄。不得只複製入口執行檔而丟掉 `_internal`。

目前資料位置使用 Tauri 的 app-local-data API，而非硬編碼名稱：macOS 為 `~/Library/Application Support/com.transcriptplus.desktop/`；Windows 預期為 `%LOCALAPPDATA%\com.transcriptplus.desktop\`，待 Windows 實機確認。此處是相對架構草案 `TranscriptPlus/` 的實作差異，避免手動依平台猜路徑。

目前僅驗證此開發機的 macOS／Apple Silicon 環境；設定中的 macOS 14 下限尚未以該版本實機測試。Homebrew FFmpeg 等原生依賴仍需檢查部署版本並在發行環境重新建置，不能以本機可啟動推定較舊 macOS 可用。

本機 macOS 產物位於 `apps/desktop/src-tauri/target/release/bundle/macos/Transcript Plus.app`。另以 `dist/TranscriptPlus-0.1.0-macos-arm64-dev.zip` 保存測試包，不含模型或使用者資料。這是本機開發用產物，未完成 Developer ID 簽章與公證；不代表可直接公開散布。

CI 使用 `macos-15` 與 `windows-2022`，僅 build／test，不上傳或發布。runner 平台標籤依 [GitHub 官方說明](https://docs.github.com/en/actions/reference/runners/github-hosted-runners) 選定；未執行的流程不能當成跨平台驗收證據。

## 限制與下一步

1. 講者分離與本機 LLM 尚未接入；UI 已明示。下個功能里程碑建立匿名 diarization adapter，再接摘要引用／待辦與過期處理。
2. 模型目前選擇外部本機資料夾，記錄 hash，不會複製、下載或管理授權 manifest。下一步建立可搬移的模型包、版本及空間管理。
3. 播放使用系統 WebView；M4A 或不支援編碼可按「建立相容音訊供播放」，生成 16 kHz 單聲道 PCM WAV，保留原檔；播放副本會驗證來源與快取校驗碼。封面圖片不再視為影片。音軌相對容器起點偏移 ≥100 ms 暫時拒絕匯入，避免錯誤時間碼。
4. 首版字幕文字從逐字稿修正；字幕頁先提供拆合與時間，不提供獨立文字副本。合併限制同一逐字稿段落；跨段／跨講者合併待設計。
5. 字詞跳播與字幕疊圖預覽尚未接入；目前可點片段／字幕跳播。
6. 工作重試目前重用前處理音訊；尚無 ASR 中途 checkpoint，未完成 ASR 仍需重跑。POSIX worker 有父程序監視，Windows Job Object 已寫入但未實機驗證。
7. 未實作系統列背景運作、專案刪除／空間管理、schema 升級備份流程。關閉視窗會退出；有工作或未存草稿時提示。
8. 需追加手動儲存衝突解決介面、字幕編輯長清單最佳化、讀取區段 API、無障礙與全長壓力測試。目前詳情 RPC 讀取完整稿件，並非架構草案的分頁契約。
9. 正式交付前要鎖定可散布的模型及 FFmpeg build、完成 notices／SBOM、雙平台乾淨機安裝／升級／移除與簽章。開發機 Homebrew FFmpeg 包含哪些第三方元件不能視為已完成發行授權審核。

## 重現短檔驗證

準備可合法使用的本機短語音檔及 CTranslate2 模型，執行：

```sh
uv run --extra asr python scripts/smoke_asr.py \
  --model /absolute/path/to/model \
  --audio /absolute/path/to/test.wav \
  --data-dir .local-data/smoke-workspace \
  --language en
```

腳本只讀指定模型、複製指定影音至測試資料目錄，並在該目錄產生匯出檔。請勿以機密企業錄音取代可公開的測試素材。

## 台灣語音與 M4A 修正（2026-09-29）

- 發現桌面設定仍使用首次接線驗證的 faster-whisper-tiny；新增 MLX 模型辨識及引擎選擇，可直接使用 FABO 的 Breeze ASR 25 模型資料夾。Windows／Intel Mac 仍使用 CTranslate2，不會自動下載或退回小模型。
- 新工作預設 auto 語言、temperature 0、transcribe、延續前文，VAD 與詞時間關閉，對齊 FABO quality。可勾選詞級時間供字幕細分；關閉時僅用實際段落時間，不虛構詞對齊。工作和 JSON 匯出保存推論參數。
- MLX 以 faster-whisper 的 PyAV decoder 讀取原始錄音，與 FABO 使用相同取樣流程。UI 的逐字稿時間以毫秒表示，超過容器長度的末段時間會限制在專案範圍。
- 使用使用者已匯入錄音的 30 秒片段、本機 Breeze ASR 25 MLX，與 FABO 的 resolve_parameters quality／transcribe 實際比對：11 段文字（去除頭尾空白）全部一致；無人工真值，這不是準確率評估，也不是整段約 95 分鐘的驗收。原始專案及逐字稿未重跑。
- 修正後 32 項 Python 測試與 7 項前端測試通過，TypeScript／Vite 建置通過。新增測試涵蓋 CT2／MLX 解碼參數、模型校驗、工作參數快照、真實 AAC M4A 匯入、PCM 跳讀、播放快取重用與毀損重建，以及前端從 M4A 切換播放副本。

- 最終 PyInstaller 核心在 PATH=/usr/bin:/bin 下成功以 Breeze ASR 25 MLX 轉錄，同樣 11 段文字與 FABO 一致；M4A 播放副本建立成功。打包明確使用 MLX wheel 的 libjaccl，避免混入 Homebrew 的不相容版本。
- 最終 macOS .app 建置成功並重新開啟；使用者設定已由 tiny 切換 Breeze ASR 25 MLX，舊模型設定另存於忽略的本機測試目錄。於實際 95:34 M4A 專案建立播放副本，原生播放器顯示完整時長、播放計時前進，點 00:21 段落可跳播；驗證後已暫停。原始逐字稿仍為版本 1，未自動重跑整份錄音。

## 最終 .app 的 MLX 載入修正

使用者回報「尚未安裝所選模型的本機轉錄引擎」後，worker.log 顯示真正原因是找不到 default metallib。前輪只在 PyInstaller dist 中驗證推論，雖然最終 .app 的播放通過，未涵蓋最終資源複製後的模型載入。資源複製將根目錄的 libmlx 符號連結解參照，使 Metal shader 不再與實際載入的函式庫相鄰。

封裝現在將 wheel 的 mlx.metallib 同時放在根目錄與 mlx/lib，適應最終 .app 的複製布局；原生函式庫載入錯誤改回報 RUNTIME_LOAD_FAILED，避免誤稱引擎未安裝。入口呼叫 multiprocessing.freeze_support，避免 resource tracker 子程序被一般 CLI parser 誤判。

新增 scripts/smoke_packaged.py，必須將 --core 指向最終 .app/Contents/Resources/core/transcript-core，使用獨立 --data-dir、短語音 --audio 與本機 --model；以系統 PATH、不同工作目錄驗證匯入、播放副本與實際轉錄。

修正後驗證：33 項 Python 測試通過；最終 .app 內的核心在隔離工作目錄及系統 PATH 下成功完成 30 秒 M4A 的 MLX 轉錄（11 段）與播放副本建立，worker.log 為空。已重新開啟新版並從 UI 重試使用者新匯入、先前因 metallib 載入失敗的 95 分鐘工作；此處僅記錄已啟動，不代表全長轉錄驗收完成。

## MLX 中途進度回報

MLX 的 transcribe 原先整份完成才回傳 segments，造成 UI 一直顯示 00:00。新增工作子程序限定的進度轉接器，觀察 mlx-whisper 0.4.x 的影格更新，即使 verbose=None 關閉 tqdm 顯示也會透過 JSONL 回報；不分割原音訊、不修改解碼與前文設定，退出或例外均還原模組狀態。引擎略過靜音時未必逐段回報，進度可能停頓後跳動，不能視為線性剩餘時間估計。

模型驗證／載入、ASR、結果儲存分別呈現，推論完成後整理段落不再讓進度倒退。UI 顯示處理時間、百分比與已執行時間；第一段完成前明示等待原因，未完成的工作不宣稱 100%。scripts/smoke_packaged.py 新增 --require-progress，使用 60–90 秒短檔檢查最終 .app 在 running/asr 階段已有非零進度。

本次 35 項 Python 與 10 項 UI 測試、前端建置通過。30 秒實際錄音的回報為 0、28700、30010 毫秒（工作層限制至檔案時長），辨識文字仍與 FABO 比對基準相同。原先重試的 95:34 錄音已完成，耗時約 14 分 53 秒，逐字稿已儲存，worker.log 無錯誤。

最終 .app 以 90 秒錄音執行 --require-progress 驗證通過：running/asr 階段確實收到非零中途進度，最後完成 33 段文字與播放副本。新版已重新開啟，使用者完整錄音的既有完成結果保留，未再次重跑。

## 對照 fabo-asr 後的更新（2026-10-01）

比對 fabo-asr HEAD `c59c082` 後移植並調整：

**轉錄**
- `hardware.py`：實體核心／記憶體偵測、CUDA 偵測；CT2 在有 NVIDIA GPU 時用 float16，載入或解碼失敗自動退回 CPU；CPU 執行緒依是否與講者分析並行分配（`TP_DEVICE`、`TP_CPU_THREADS`、`TP_CONCURRENT_STAGES` 可覆寫）。
- 轉錄方案：品質（預設，與 FABO 相同）／平衡（CT2 beam 3；MLX 快速注意力）／快速（beam 1、不延續前文）。MLX 快速注意力與詞級時間互斥，後端會拒絕組合。
- 術語表（`initial_prompt`，上限 4000 字元）、低信心段落標記（avg_logprob／no_speech／重複壓縮率）、重疊段落合併、Windows `\\?\` 路徑前綴清除（Rust 與 Python 兩端）。

**講者**
- `diarization.py` 移植 sherpa-onnx pyannote 分段 + TitaNet 聲紋：分群、長段落換人偵測 `refine_turns`、時間重疊與聲紋證據指派、保守聲紋比對（門檻 0.72、差距 0.12、至少兩段一致）、由會議乾淨語音註冊聲紋。音訊改用專案已前處理的 16 kHz PCM16，以 int16 保存，記憶體約為 float32 的一半。
- `speakers.py`：講者命名（手動 > 聲紋 > 講者 N）、改名、段落歸類、合併分群（保留註冊用快取有效）、重新比對、詞界拆句。手動輸入的講者名稱永遠優先。
- 分群在獨立子程序執行（與轉錄並行時各用不同硬體；結束即釋放記憶體）。分群失敗不會丟失已完成的逐字稿，工作以完成狀態保留並顯示原因。
- 僅講者的改動（改名、歸類、合併、註冊）不使字幕過期。
- SQLite 結構升至 v2（`projects.speakers`、`people`、`voiceprints`），舊資料庫以 ALTER 補欄位。

**驗證（本機 macOS／Apple Silicon）**
- 52 項 Python 測試與 12 項 UI 測試通過；`cargo check` 通過。
- 以 fabo-asr 測試錄音「胖寶進度報告0609_5min」、Breeze ASR 25 MLX 與 fabo 講者模型實跑：5 分鐘錄音約 100 秒完成轉錄 + 分群；開啟詞級時間時，換人處會拆成獨立段落。這是接線與行為驗證，沒有人工標註真值，不是 DER／CER 評估。
- 6 場 holdout 的 DER 0.739 → 0.309 是 fabo-asr 以其資料得到的數字（見其 `quality-parameters.md`），本專案沿用參數但未重新評估。

**未移植（尚待決定）**
- fabo 的 Windows 可攜版交叉編譯（cargo-xwin、內嵌 CPython、離線 WebView2／VC runtime、`Diagnose.cmd`、啟動診斷報告）與暫時管理員／多帳號：本專案是單人桌面版，沿用 PyInstaller 與 CI 建置，未建立同等流程，Windows 仍待實機驗收。
- 以錄音檔直接註冊聲紋、台語候選、摘要。
