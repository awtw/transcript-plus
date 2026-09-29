# Transcript Plus

以逐字稿為核心的本機字幕與會議整理軟體，規劃支援 macOS、Windows 安裝與離線處理。

目前為 **v0.1 開發版**：已實作 Tauri／React 桌面介面、Python 本機轉錄核心、SQLite 儲存、逐字稿校對與字幕匯出。macOS 本機已建置 `.app`；尚非完整 MVP，也尚未完成 Windows 實機與公開發行驗收。

## 開發啟動

需要 Node.js 22／24、Rust stable、Python 3.12、uv、FFmpeg／ffprobe。macOS 需要 Xcode Command Line Tools；Windows 需要 Visual Studio C++ Build Tools 與 WebView2。

```sh
uv sync --python 3.12 --extra asr --extra packaging
npm ci
npm run desktop
```

`npm run dev` 僅啟動瀏覽器介面預覽，本機檔案與轉錄操作需使用 `npm run desktop`。初次需從「模型與設定」選擇已有的 faster-whisper／CTranslate2 模型資料夾；程式不會自動下載權重。

```sh
uv run --extra asr --extra packaging pytest -q
npm run test:ui
npm run build
uv run --extra asr --extra packaging python packaging/build_core.py
npm run desktop:build -- --bundles app
```

最後一行為 macOS 內部測試用 `.app`；Windows 改成 `--bundles nsis`。各平台要在該平台建置。模型、測試影音、虛擬環境與編譯產物不進 Git。

目前可用：影音匯入／播放、本機轉錄與詞時間、工作取消／重試、逐字稿自動儲存／復原／重做、手動講者名稱、字幕生成／同段拆合／時間微調、TXT／SRT／VTT／JSON 匯出。

目前未提供：自動講者分離、本機摘要與待辦、影片代理、模型下載／搬移管理、背景系統列、完整長檔驗收及簽章／公證。請參考 [實作與驗證紀錄](docs/IMPLEMENTATION.md)。

## 文件

1. [MVP 需求與驗收](docs/MVP.md)：產品定位、首版功能、操作流程、驗收與開發里程碑。
2. [桌面軟體架構](docs/ARCHITECTURE.md)：技術選型、資料契約、編輯與時間戳、工作管理及雙平台發布。
3. [FABO ASR 參考評估](docs/FABO-ASR-REFERENCE.md)：現有程式證據、可移植部分及需新增的能力。
4. [原始需求參考](reference-doc/subtitle_transcription_market_opportunities.md)。
5. [實作與驗證紀錄](docs/IMPLEMENTATION.md)：已完成項目、限制、測試與下一個里程碑。

設計與首次實作日期：2026-09-29。MVP 文件中的效能、品質及工期仍為規劃目標；短檔接線驗證不等於通過產品品質驗收。
