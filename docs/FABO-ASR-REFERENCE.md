# FABO ASR：參考與移植評估

閱讀日期：2026-09-29。參考專案位於 `/Users/augustwang/Documents/github/02-CTBC/fabo-asr`，檢視時 HEAD 為 `3603ba3`，工作目錄乾淨。本次為靜態程式與文件閱讀，未執行模型、測試或重新驗證既有測速。

## 1. 結論

FABO 可提供 Python 推論、版本保護、摘要引用與錯誤處理的參考。Transcript Plus 應另建桌面外殼、共用逐字稿／字幕資料模型與文字拆合流程。移植以函式、adapter 與測試案例為單位，不複製整個企業平台。

參考不等於已取得程式、模型或素材的再散布權；實際搬移程式前記錄來源與授權。此次只建立本專案設計文件，未複製 FABO 程式、帳號、錄音、聲紋、資料庫或模型。

## 2. 現況證據與處理建議

以下路徑均相對於 FABO 專案根目錄，函式名稱供後續定位。

| 範圍 | 觀察到的實作／證據 | Transcript Plus 的處理 |
|---|---|---|
| ASR 引擎 | `backend/asr.py` 的 `configuration`、`transcribe`：Apple Silicon 可走 MLX，其餘 faster-whisper CPU INT8。 | 移為 provider adapter；模型與參數從配置物件注入，不綁 FABO 環境變數。 |
| 字詞時間 | `backend/asr.py` 的 `valid_words`、`normalize`、`transcribe_vad`；`tests/test_word_timestamps.py` 覆蓋時間驗證、VAD 偏移與兩引擎參數。 | 參考驗證及偏移邏輯；保留缺漏狀態，新增穩定 word ID、編輯失效與字幕來源映射。 |
| 背景工作 | `backend/worker.py` 的 `Worker`／`InferenceProcess`：SQLite 排隊、子程序推論與關閉處理。 | 參考序列執行；改為桌面監護、持久化 stage／attempt、明確取消與重試。 |
| 中斷恢復 | `Worker.start()` 將 ASR transcribing 改 failed，分析 running 改 interrupted。ASR 透過 `communicate` 收完整 JSON。 | 現況不能稱為 ASR 續跑；新專案先做階段重用，分塊 checkpoint 延後。 |
| 凍結執行 | `InferenceProcess` 使用 `sys.executable -m backend.worker`／`backend.analysis_runner`；檢視檔案清單未見 `backend/launcher.py`。 | 新增 frozen-safe Core／worker 入口；需用真正封裝產物驗證。 |
| 本機資料 | `backend/storage.py`：SQLite 的 users、sessions、jobs、speakers；逐字稿 JSON 存在 jobs。 | 保留 SQLite 技術，重做領域 schema；單人版不引入登入、管理員與多人所有權資料表。 |
| 修改與版本 | `backend/jobs.py::edit`：revision 更新與衝突處理；特定已分析稿要求相同段數與時間，保留既有 words。 | 參考 revision 保護，不能直接當字幕拆合引擎；需新增 text-to-word 映射、dirty 時間與衍生版本。 |
| 講者分析 | `backend/diarization.py`：sherpa-onnx、segmentation／embedding、群組與聲紋配對；decode_audio 會累積整段陣列。 | 先取匿名講者功能與人工改名；不搬聲紋名冊，長音檔記憶體流程需改造。 |
| 摘要 | `backend/summary.py`：本機端點、長稿分塊、JSON schema、原文引用與承諾驗證；`worker.summary_enabled()` 預設關閉。 | 有實作但非預設就緒；抽離引用驗證，加入模型管理、按需啟停及穩定引用 ID。 |
| 摘要過期 | `backend/jobs.py::edit` 更新 `summary_stale`，分析綁定 revision。 | 沿用原則，將版本依賴擴及字幕、講者與時間修改。 |
| 播放 | `backend/jobs.py` 音訊端點與 `backend/media.py`、`tests/test_audio_playback.py`。 | 參考 range／播放測試；新系統以 Tauri 受控媒體協定取代瀏覽器 API，新增影片代理。 |
| 匯出 | `backend/jobs.py::export` 直接逐 segment 產生 TXT／SRT，其他格式回不支援。 | 重用時間格式概念；新增獨立 cue 規則與 VTT，不能直接把 segment SRT 視為完整字幕引擎。 |
| 前端靜態檔 | `backend/main.py` 已依 `FABO_FRONTEND_DIR` 掛載 `StaticFiles`。 | 證明早期「尚未靜態托管」說法已過時；新前端直接封裝進桌面資源。 |
| 發布狀態 | README 註明 Windows 發布及人工辨識品質尚未驗收；`docs/PACKAGING-EXE-2026-09-13.md` 含方案與待改事項。 | 以現有碼和實際安裝驗收為準，不宣稱已有可重用的完整雙平台 Installer。 |

## 3. 文件差異如何解讀

`docs/ARCHITECTURE.md`、`docs/REQUIREMENTS.md` 明示包含早期草案，其 ASR 模型、API 路徑與功能範圍不等同目前程式。`docs/PACKAGING-EXE-2026-09-13.md` 對 frozen worker 和 Windows 程序樹的分析仍值得參考，但其中未提供靜態前端的敘述已與現行 `main.py` 不同。

`docs/VALIDATION_2026-09-09.md` 記錄特定模型／環境的測試與限制，不能外推成新軟體、另一模型或 Windows 的驗收成績。此次沒有複驗該報告，也沒有將測速數字寫為新產品承諾。

## 4. 建議移植順序

1. 定義與 FABO 無關的 Transcript／Word／Cue schema 與契約測試。
2. 以合成資料移植時間驗證、VAD 時間映射與匯出邊界測試。
3. 將 ASR／講者包成可注入模型配置的 adapter，在雙平台最小安裝包中執行。
4. 新建 Core 的工作狀態機與 revision 交易，補取消、重試、衍生結果失效測試。
5. 移入摘要引用驗證觀念，重新選定可交付模型並完成繁中人工評估。
6. 新建字幕編輯器與桌面 UI，最後完成雙平台發布，而非將企業前端更名後直接交付。

每一項搬移都應附來源版本、移除的耦合、測試結果與授權紀錄。後續實作以 [架構設計](ARCHITECTURE.md) 的新契約為準。
