# v0.1 開發與驗證紀錄

日期：2026-09-29。此版是第一個可執行的開發基線，完成 G0／G1／G2 的部分能力；G0 的雙平台、品質與完整模型評估尚未結案。

## 已實作

| 模組 | 內容 |
|---|---|
| 桌面外殼 | Tauri 2、React／TypeScript、原生選檔及匯出、單一實例、受限媒體 asset scope、Core 子程序及關閉流程。 |
| 本機核心 | JSON Lines IPC；不開 HTTP API；SQLite WAL、單一資料目錄鎖、逐字稿歷史與版本衝突保護。 |
| 影音 | 匯入 WAV／MP3／M4A／MP4／MOV 的可解碼音軌，檢查時長／大小／容量，保存原檔副本與 SHA-256。 |
| 轉錄 | faster-whisper CPU INT8、本機模型 hash 驗證、VAD、詞時間、離線環境設定、原始文字保留。 |
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
3. 播放使用系統 WebView；不支援編碼會顯示錯誤，尚未產生代理檔。音軌相對容器起點偏移 ≥100 ms 暫時拒絕匯入，避免錯誤時間碼。
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
