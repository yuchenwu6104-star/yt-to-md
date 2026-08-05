# humanizer-zh 護欄精簡與品質提升計畫

**日期：** 2026-08-05  
**狀態：** 提案，待使用者核准  
**目標：** 在不降低任何正確性與發布完整性的前提下，降低 `humanizer-zh` runtime prompt 的重複與形式負擔，把模型注意力移回選材、自然中文、節奏與來源正確性。  
**核心限制：** 新版必須通過 Pareto gate；只要新增一筆重大錯意、數字錯誤、歸屬錯誤、重要利益揭露遺漏或發布不一致，候選變更不得進入正式流程。

---

## 1. 背景

目前 `.claude/skills/humanizer-zh/SKILL.md` 約 1,002 行、86 KB，同時包含：

- `_yt_` 訪談文章的來源核對與編輯流程。
- `_fb_` 與自署名文章的「個性與靈魂」規則。
- 35 種 AI 寫作、翻譯與訪談整理模式。
- 輸入路由、批次 subagent 分工、audit 格式與 HackMD 發布流程。
- 多組歷史事故案例與修復說明。

同一條規則常在編輯權限、模式說明、快速清單、處理流程與 audit 格式重複出現。問題不只是 token 較多，還包含三種品質風險：

1. 編輯注意力被形式自證和重複清單分散。
2. 互相重疊或衝突的規則可能促使模型過度保守、湊引述或過度修改。
3. 機械 gate 的實際能力與 prompt 所聲稱的保障不完全一致。

## 2. 獨立審查後的修正結論

本計畫納入一名 high-reasoning fresh subagent 對原始建議的獨立審查。審查後將建議分為三類。

### 2.1 可以直接進入結構精簡

- 將只適用 `_fb_` 或自署名文章的「個性與靈魂」移出 `_yt_` runtime context。
- 將一般 AI 寫作百科說明與長篇改寫範例移到 references。
- 將 GQG、Tom Lee、股癌、IMEC 等歷史事故移到 regression corpus，主 prompt 只保留錯誤類型、裁決規則與一個最短反例。
- 在建立「規則 → 唯一權威位置 → gate/test」對照表後，刪除重複的快速檢查清單文字。
- 精簡輸入路由與批次分工文字，但不變更「一篇一 producer＋一 fresh reviewer」的角色隔離。

### 2.2 只能在隔離環境 A/B 測試

- 引述章節機械下限由 hard gate 改為 candidate warning。
- 「投資相關全部補回」改為「不可省略核心類＋次要資訊可裁量」。
- 專有名詞全量網路查證改為 transcript/metadata 全查、風險詞才使用外部資料。
- 完整 Q01…QN 六欄表改為程式產生骨架，reviewer 記錄異常與保留理由。
- 流程第 7–12 步的 pass 數調整。文字可濃縮，但第 11 步全文邏輯冷讀、第 12 步重複與贅字專項、第 13 步 fresh review 在未有 A/B 證據前保持獨立。

### 2.3 不得刪除的保障

- 原始草稿不可覆寫，且必須保留對應 `_transcript.txt`。
- transcript 是語意、引述邊界、數字、歸屬與覆蓋的 ground truth。
- 數字、否定、因果、比較、條件、時間順序、利益揭露與立場強度屬高風險回對項目。
- 多人訪談必須核對說話人歸屬與跨講者縫合。
- `_yt_` 每篇必須由一個全新 context 的 fresh reviewer 審查；同一 reviewer 不得在同一任務審多篇。
- 不使用破折號，且保留使用者已明確裁決的報幕詞、語氣打分與 AI 重框句型政策。
- `_audit.md` 必須存在且是已完成的證據，不得含待辦或 provisional 文字。
- `final_gate.py` 低誤報 hard failures 必須為 0。
- HackMD 發布必須經過 remote GET readback，驗證內容、標題、tags 與讀寫權限。

## 3. 當前可執行行為的明確缺口

### 3.1 HackMD 上傳後沒有 remote readback

`upload_hackmd.py` 現在完成 POST 後只使用回傳資料組出網址，沒有用 `/v1/notes/{id}` GET 讀回。因此 HTTP 成功不能證明遠端內容完整。

後續實作要求：

- POST 後 GET 讀回單篇 note。
- 驗證 note ID、完整 content SHA-256、title、tags、readPermission 與 writePermission。
- 處理 eventual consistency 時只允許有限次數、有上限的短重試。
- 讀回不一致時不得宣告發布成功。
- 不驗證 list endpoint 的 content，使用單 note endpoint。

### 3.2 hard gate 使用無語境的 substring

`final_gate.py` 會在引號外任意位置擋截 `補上`、`暗示了`、`透露了`、`坦言`、`直言` 等裸字串，可能誤殺「供應商補上庫存缺口」等正常數述。

後續實作要求：

- 對可疑動詞做引述引導位置或句法感知，不得整行裸字串 hard fail。
- `補刀`、`話鋒一轉`、`她的重點是`、chunk meta leak、破折號與整段重複等低誤報項仍保持 hard。
- 每個樣式必須同時有「應擋截」與「不應擋截」測試。
- `/yt` 與 humanizer 共用規則要有單一來源，不再靠「改一邊記得改另一邊」。

## 4. 基準集與評分方法

### 4.1 基準集

至少選 12 篇已有人工覆核結果的文章，必須覆蓋：

- 英文、中文 ASR、日文或韓文來源。
- 單人訪談與多人對談。
- 投資密集與非投資主題。
- 短篇、長篇、多引述與專名密集文章。
- 曾發生錯意、數字、歸屬、專名、漏段、複述或遠端不一致事故的文章。

基準資料使用相同原始草稿與 transcript。若納入 repo，只能放經去識別、不含使用者私密資料的 fixture；實際 Vault 文件只記錄本機路徑與 hash，不複製進 repo。所有 benchmark 產出必須使用隔離的 output directory 與 state file，不得寫入正式 Vault、HackMD 或 watcher state。

### 4.2 硬性正確性指標

候選版相對 baseline 必須同時滿足：

- 新增語意反轉或重大錯意：0。
- 新增數字、單位、方向或因果錯誤：0。
- 新增說話人歸屬或跨講者縫合錯誤：0。
- 新增重要專名錯誤：0。
- 新增利益揭露、反例、條件或主要論點遺漏：0。
- 無字幕來源支持的新細節：0。
- 原始草稿 hash 不變。
- `final_gate.py` 低誤報 hard failures 為 0。
- 發布測試中的遠端 content/title/tags/permissions parity 為 100%。

### 4.3 編輯品質指標

- 每篇由不知道版本的 reviewer 進行 paired blind review。
- 自然中文、邏輯清晰、節奏、去 AI 痕跡、資訊密度各以 1–5 分評分。
- 候選版的 paired blind preference 至少 70%。
- 五項編輯分數不得任一項明顯低於 baseline，整體平均至少提升 0.25/5，或使用者主觀百分制至少提升 5 分。
- 重複預告、報幕句、引述後再解釋與空洞重框不得高於 baseline。
- 文章長度只做診斷，不作為單獨品質分數。

### 4.4 效率指標

- runtime prompt 大小至少降低 40%；第一階段目標是將主 `SKILL.md` 縮至約 300–400 行。
- 記錄總 token、執行時間、外部查證次數、audit 長度與 reviewer 閱讀時間。
- 效率改善不得抵銷任何正確性或編輯品質退步。

## 5. 分階段實作計畫

### Phase 0：凍結 baseline 與建立回歸評測

1. 選定至少 12 篇 benchmark 文章與對應 transcript。
2. 記錄來源 hash、當前 humanized 成品、audit、gate 輸出與已知事故標籤。
3. 建立語意反轉、數字、歸屬、專名、覆蓋、報幕、複述與 hard-gate 正反例。
4. 建立 blind review 評分表與比較程序。
5. 記錄目前 prompt 大小、平均 token、runtime 與 audit 長度。

**完成條件：** benchmark manifest 完整，每篇都有來源 hash、風險標籤與 baseline 評分，且全程不觸及正式輸出與 watcher state。

### Phase 1：不改變政策的 prompt 結構精簡

1. 建立規則對照表，為每條規則指定唯一權威位置。
2. 主 `SKILL.md` 保留：
   - 場景路由與編輯權限。
   - transcript-first 正確性契約。
   - 覆蓋、引述、歸屬、數字與專名的決策規則。
   - 製作、fresh review、mechanical gate、audit 與發布契約。
3. 將一般風格百科、歷史事故、`_fb_` 專用規則分別移到 references。
4. 快速清單的唯一規則搬完後刪除重複清單。
5. 保留第 11、12、13 步為三個獨立注意力 pass，只縮短說明。
6. 所有決策政策、hard/candidate 分類、audit 必填證據與角色分工保持不變。

**完成條件：** prompt 至少縮小 40%，全部正確性回歸通過，blind review 無明顯退步。此階段不會自動取代正式 skill。

### Phase 2：修復明確的工程缺口

1. 為 `upload_hackmd.py` 增加 POST 後的單 note GET readback 與 parity 驗證。
2. 為 remote readback 增加 mock API 測試，覆蓋成功、空內容、舊內容、權限不符與 eventual consistency。
3. 將 raw substring hard gate 改為語境感知，但明確報幕詞維持 hard。
4. 抽出 `/yt` 與 humanizer 共用樣式的單一來源，降低兩邊漂移。
5. 讓程式產生 Q inventory 與實際 CJK>=6 計數，但此階段仍保留 reviewer 的完整六欄判斷。

**完成條件：** remote parity 測試 100% 通過，hard-gate 誤報下降且無漏報，Q 計數不再依賴人工數數。

### Phase 3：四個爭議護欄分開 A/B

每次只改一項，不得把四項綁在同一個候選版：

1. **引述章節下限**：hard gate 與 candidate warning 比較。
2. **投資覆蓋**：全量補回與重要性分級比較。不可省略類固定包含利益揭露、主要反例、結論條件、核心數字與理解結論所需機制。
3. **專名查證**：全量外部查證與風險分級比較。主持人身分、ASR 近音詞、拼法衝突、標題核心專名與陌生產品仍強制外查。
4. **Q 證據表**：完整六欄與程式骨架＋例外式記錄比較。fresh reviewer 仍必須冷讀每一段引述，只改變證據輸出形式。

**單項採用條件：** 全部硬性正確性指標不退步，且 paired blind preference 與編輯分數達標。任一新增重大錯誤即淘汰該候選政策。

### Phase 4：使用者核准的 shadow period

1. 只在獨立 state file 與獨立 output directory 執行。
2. 不呼叫正式 watcher，不處理 `processed_videos_intl.json` 已有影片，不寫正式 Vault 或 HackMD。
3. 不 unload、kickstart、修改或複製 `com.slking.yt-intl-watcher`。
4. 每一批輸出 baseline/candidate 對比、新增缺陷、修正缺陷、blind preference 與效率數據。
5. 只有連續多批通過 Pareto gate，才向使用者提出正式替換建議。

**完成條件：** 由使用者明確裁決是否進入正式流程，不因技術 gate 通過自動替換。

## 6. 預計檔案與變更邊界

後續實作可能涉及：

- `.claude/skills/humanizer-zh/SKILL.md`
- `.claude/skills/humanizer-zh/references/ai-writing-patterns.md`
- `.claude/skills/humanizer-zh/references/regression-cases.md`
- `.claude/skills/humanizer-zh/references/self-authored-posts.md`
- `.claude/skills/humanizer-zh/scripts/final_gate.py`
- `.claude/skills/humanizer-zh/scripts/upload_hackmd.py`
- `/yt` 與 humanizer 共用的規則模組
- 不含使用者私密內容的 regression tests 與 benchmark manifest

本計畫不授權：

- 修改正式頻道清單。
- 修改或刪除 processed-video state。
- 修改 `.env`、token、Obsidian output directory 或 HackMD 憑證。
- 變更 launchd 排程。
- 在正式輸出目錄進行 benchmark。
- 未經核准將候選版合併或推送到 `master`。

## 7. 回滾設計

- 每個 Phase 使用獨立提交，不將結構精簡、工程修復與爭議政策實驗混在同一 commit。
- 每項 Phase 3 實驗使用獨立 branch 或獨立 commit，可單獨回滾。
- 保留當前 `origin/master` 與 `codex/yt-humanizer-redesign` 作為已知 baseline，不覆寫歷史。
- 只要候選版出現一筆重大正確性回歸，當批立即停止，不以事後平均分數抵銷。
- 若 remote readback 不一致，不宣告發布成功，且不自動建立另一篇重複 note。

## 8. 納入或拒絕變更的最終規則

一項護欄只能在以下條件全部成立時移除或放寬：

1. 它已經在分離的 A/B 實驗中單獨受測。
2. 它在全部高風險基準類型中沒有新增錯誤。
3. 主要論點與利益揭露覆蓋不低於 baseline。
4. blind editorial review 偏好候選版，而不只是 token 更少或 audit 更短。
5. 使用者看過實驗結果並明確核准。

反之，若護欄對應過去的真實重大缺陷，但目前尚無證據顯示更強模型已穩定消除該風險，它預設保留。

---

## 9. 當前版本註記

審查時工作樹位於 `codex/yt-humanizer-redesign`，相對 `origin/master` 多一個提交 `601d661 feat(quality): enforce per-quote audit evidence`。逐引述 Q 表是最新、尚應獨立驗證的實驗性強化，不得與其他精簡項目一次打包移除。
