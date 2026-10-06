# Transcript Plus

以逐字稿為核心的本機字幕與會議整理軟體，規劃支援 macOS、Windows 安裝與離線處理。

目前為 **v0.1 開發版**：已實作 Tauri／React 桌面介面、Python 本機轉錄核心、SQLite 儲存、逐字稿校對與字幕匯出。macOS 本機已建置 `.app`；尚非完整 MVP，也尚未完成 Windows 實機與公開發行驗收。

## macOS 安裝與啟動

開啟 `Transcript Plus_0.1.0_aarch64.dmg`，將 `Transcript Plus.app` 拖入「應用程式」，再從「應用程式」啟動。此檔案適用於 Apple Silicon Mac。

**請勿開啟 `build/core/transcript-core/transcript-core.pkg`**：它是 PyInstaller 的內部封裝資料，不是 macOS 安裝套件；交給系統安裝程式會出現 `com.apple.installer.pagecontroller error -1`。

在 macOS 上建立包含最新轉錄核心與介面的 DMG（需先完成下方開發環境安裝）：

```sh
npm run desktop:package:mac
```

產物位於 `apps/desktop/src-tauri/target/release/bundle/dmg/`。若只需直接開啟程式，也可使用 `apps/desktop/src-tauri/target/release/bundle/macos/Transcript Plus.app`。目前為尚未完成 Developer ID 簽章與公證的本機測試版。

## 開發啟動

需要 Node.js 22／24、Rust stable、Python 3.12、uv、FFmpeg／ffprobe。macOS 需要 Xcode Command Line Tools；Windows 需要 Visual Studio C++ Build Tools 與 WebView2。

```sh
uv sync --python 3.12 --extra asr --extra diarization --extra packaging
npm ci
npm run desktop
```

`npm run dev` 僅啟動瀏覽器介面預覽，本機檔案與轉錄操作需使用 `npm run desktop`。初次需從「模型與設定」選擇已有的 Breeze ASR／Whisper 模型資料夾（CTranslate2；Apple Silicon 亦支援 MLX）；程式不會自動下載權重。

```sh
uv run --extra asr --extra diarization --extra packaging pytest -q
npm run test:ui
npm run build
uv run --extra asr --extra diarization --extra packaging python packaging/build_core.py
npm run desktop:build -- --bundles app
```

最後一行為 macOS 內部測試用 `.app`；Windows 改成 `--bundles nsis`。各平台要在該平台建置。模型、測試影音、虛擬環境與編譯產物不進 Git。

目前可用：影音匯入／播放、本機轉錄與詞時間、轉錄方案（品質／平衡／快速）與術語表、工作取消／重試、逐字稿自動儲存／復原／重做、**自動講者分群與聲紋命名**（含手動改名、歸類、合併、註冊聲紋）、字幕生成／同段拆合／時間微調、TXT／SRT／VTT／JSON 匯出。

台灣語音請優先選與 fabo-asr 相同的 Breeze ASR 模型；先前 smoke 測試用的 tiny 不適合作為品質基準。品質模式預設自動語言、延續前文、不切除靜音，詞級時間可另行開啟。M4A 可直接播放；若編碼不相容，按「建立相容音訊供播放」產生本機 WAV 副本，原檔保留。

目前未提供：本機摘要與待辦、影片代理、模型下載／搬移管理、背景系統列、完整長檔驗收及簽章／公證。請參考 [實作與驗證紀錄](docs/IMPLEMENTATION.md)。

## 講者分群與聲紋

從「模型與設定」選擇講者模型資料夾（需含 `segmentation/model.onnx` 與 `nemo_en_titanet_small.onnx`，與 fabo-asr 的 `models/speakers` 相同；不會自動下載）。之後在轉錄設定勾選「分辨講者」，或在「講者」分頁對既有逐字稿按「分析講者」。

- 分群沿用 fabo-asr 的參數（cluster threshold 0.99、window shift 0.25）與長段落內換人偵測；分群後會把過短的小群併入相似的大群，減少同一人被切成多人。知道人數時填「發言人數」可避免過度分群（此時不做自動合併）。
- 講者模型資料夾若另含中文聲紋模型 `3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx`，會自動用它辨認「是誰」（分群仍用 TitaNet）；沒有則退回 TitaNet。換模型後既有聲紋需重新註冊。
- 機器較強（≥4 實體核心、≥12 GB 記憶體）時，講者分群與轉錄同時進行；否則轉錄完成後接著做。CUDA 不可用會自動退回 CPU。
- 「講者」分頁可改名、合併過度分群、把個別段落改歸其他分群，並用已確認身分的分群註冊聲紋；可勾選「強制比對」讓每位聲紋最多對應一個分群，並顯示相似度（不是答對機率）；之後的錄音只在多段語音彼此一致且明顯勝過其他人時才自動命名，不確定就維持「講者 N」。
- 開啟「產生詞級時間」時，同一段落內換人會在詞界自動拆句；字幕已存在的專案重新分析不會拆句，以免破壞字幕。

## 文件

1. [MVP 需求與驗收](docs/MVP.md)：產品定位、首版功能、操作流程、驗收與開發里程碑。
2. [桌面軟體架構](docs/ARCHITECTURE.md)：技術選型、資料契約、編輯與時間戳、工作管理及雙平台發布。
3. [FABO ASR 參考評估](docs/FABO-ASR-REFERENCE.md)：現有程式證據、可移植部分及需新增的能力。
4. [原始需求參考](reference-doc/subtitle_transcription_market_opportunities.md)。
5. [實作與驗證紀錄](docs/IMPLEMENTATION.md)：已完成項目、限制、測試與下一個里程碑。

設計與首次實作日期：2026-09-29。MVP 文件中的效能、品質及工期仍為規劃目標；短檔接線驗證不等於通過產品品質驗收。
