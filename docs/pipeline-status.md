# Pipeline 現況與待辦（最後更新 2026-08-06）

這份是**交接文件**，不是設計文件。任何 session 接手前先讀它。

放在 repo 而不是靠記憶，是因為記憶會過時：2026-08-06 當天就抓到一條錯的
（多份記憶寫「排程實跑的是 yt-insight-bot」，實查已經不是了）。

---

## 現在的樣子

```
23:00  排程 YT Channel Watcher
         └ ytmap/yt_triage.py（每部影片）
             1 normalize_transcript.py  單行字幕 → 一句一行，行號是全流程錨點
             2 build_index.py           數字、拼字變體、廣告、未完成句（純 Python）
             3 map_minimax.py ×2        分段、輪次、論點、引述候選、可疑專名
             4 dedupe_claims.py         跨段合併重複論點 → occurrences/strongest
             5 merge_maps.py            兩份合流 ＋ 體檢表
             6 triage_minimax.py        中文分流稿
             7 strip_markers.py         查證標記抽進 JSON
           產出 <base>_分流稿.md、<base>_map.json、<base>_lines.txt

早上   使用者讀分流稿，挑要做的丟給 humanizer（C 路）

humanizer  SKILL.md ＋ references/ 分檔，各角色只載自己要的
             寫作 → 專名查證(12.5，產 _glossary.json) → fresh eyes(13) → final_gate
```

**設計主張（別再重新發明）**：舊版 `/yt` 一次要模型同時做翻譯、結構、歸屬、
專名、文筆五件事，於是專名就用記憶填了。同一集跑兩次的天然對照顯示，三整段
虛構全部出現在「寫文章」那一步，而分段索引、專名標記這些窄任務它做得對。
把模型的任務縮窄，錯就少了。

---

## 已知缺口（按優先序）

1. **C 路沒有實跑驗證過。** 規則寫在 SKILL 了，但還沒有一篇文章真的走完
   「分流稿 → humanizer C 路 → 成品」。第一批跑出來要抽查。
2. **`>` 引述區塊的格式規則沒進 `final_gate.py`。** SKILL 要求引述內嵌
   「」、`>` 區塊每節至多一段，但機械閘門不擋。實測 B 路曾寫出 52 段 `>`
   區塊、其中 47 段前面掛報幕句。要補：`>` 區塊數硬性上限，以及連續
   「短串接句：引述」的候選計數。
3. **地圖層的輪次比 Claude 版吵。** 同一集 MiniMax 版歸屬歧異 19 處、
   Claude 版 6 處。歧異多不是壞事（該看的地方被標出來了），但下游要花力氣。
4. **`processed_videos.json` 是共用的**，2026-08-06 之前跑過的影片不會重跑。
   要重跑舊影片得手動處理那個檔。
5. **文筆那 30 分**。2026-08-06 三版對照試驗定案：要句子更利、不要砍內容
   （使用者選了「照黃金範本重寫、長度不變」那版）。四條節奏特徵已寫進
   SKILL 的〈語感基準〉。使用者目前打算最後一哩自己交給 ChatGPT 潤，
   所以這條線該優化的是「好素材」而不是「成品」。

---

## 怎麼退回

| 想退什麼 | 怎麼做 |
|---|---|
| `/yt` 退回舊版（模型寫文章） | 環境變數 `YT_MODE=article`。`yt_to_article.py` 一個字沒動 |
| humanizer 退回拆檔前 | `git revert ea850d5`，或取備份 `~/.claude/skill-backups/humanizer-zh.bak-20260806` |
| 排程時間 | `Set-ScheduledTask -TaskName 'YT Channel Watcher' -Trigger (New-ScheduledTaskTrigger -Daily -At '08:00')` |

---

## 幾個容易踩的坑

- **技能載入的是哪一份**：`~/.claude/skills/humanizer-zh` 已改成 junction 指向
  repo 的 `.claude/skills/humanizer-zh`。**副作用：切 git 分支會連 humanizer
  一起換掉**，切到 codex 那條就會拿到他們 15KB 的版本，而且沒有任何提示。
- **備份不要放在 `~/.claude/skills/` 底下**，會被當成一個新技能列進技能清單。
- **排程跑的是工作目錄「當下 checkout 的分支」**。切到一半的分支會直接上線。
- **API key 的環境變數名不一致**：機器上是 `MINIMAX_API_KEY`（使用者環境變數），
  但 `ytkit/config.py` 讀的是 `ANTHROPIC_API_KEY`。手動跑腳本要自己橋接：
  `export ANTHROPIC_API_KEY=$(powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('MINIMAX_API_KEY','User')")`
- **地圖層的 chunk 是 150 行，不要為了省呼叫次數放大。** 實測不是輸出吐不完
  （`max_tokens` 開到 65536 只用了 4000），是**輸入越長它抽得越少**：150 行
  給 25 條論點，500 行給 24 條，800 行給 32 條。放大 chunk 會得到一份看起來
  完整、實際只抓到四分之一的地圖，而且從外觀看不出來。
- **地圖是索引不是事實。** 苦力層會編造（實測把 davidad 標成 David Duvenaud）。
  `map_minimax.py` 已用程式擋掉「name 沒有逐字出現在它引用的行裡」那一類，
  但語意層的編造擋不掉，下游一律回字幕核對。

---

## 分支

```
master                              共同祖先，乾淨
codex/yt-humanizer-redesign         Mac/Codex 那條，/yt 改為中文順稿層
claude/humanizer-context-rebuild    這條（目前 checkout，排程實跑的也是這條）
```

兩條線尚未合併，等實跑效果決定。詳見 memory `project_humanizer_branch_fork_2026_08`。
