# 地圖版三件組（`type: yt_triage`）

另一台機器（Windows，分支 `claude/humanizer-context-rebuild`）的 `/yt` 從 2026-08-06 起
改成「地圖版」：模型不寫文章，只做窄任務（切段、標論點、標專名、標歸屬地雷），文章
一律由 humanizer 寫。產出經 Obsidian 同步進同一個 Vault 目錄，所以**這台會同時收到兩種
`/yt` 產出，同一批裡混著出現**，先讀 frontmatter 的 `type:` 再決定怎麼做。

```
<base>_分流稿.md     type: yt_triage，frontmatter 指向另外兩個檔
<base>_map.json      地圖：論點、引述候選、專名、歸屬地雷、難譯點
<base>_lines.txt     帶行號的英文逐字稿，行號是全流程錨點
<base>_transcript.txt 原始英文字幕（final_gate 用同名規則找它）
```

分流稿檔名可能帶 `(V)`、`v`、`_prototype` 尾綴（使用者自己標記過）；`map:` 與
`transcript_lines:` 兩個 frontmatter 欄位才是權威路徑。**分流稿本身可以不存在**（原型期
那幾集就只有 map／lines／transcript），這時 `read_triage.py` 會用同 base 去找檔名變體，
照樣開得起來——真正缺不得的是 `_map.json` 與 `_lines.txt`。

## 兩條紅線

**分流稿不是寫作素材。** 它是使用者用來決定「這集要不要做」的閱讀稿，規格跟成品相反
（寧可長寧可雜、細節一律保留），而且是機器翻的。不要拿它當底稿，也不要編輯它。寫作
依據是 `_lines.txt` 的英文原文，中文只在你手上產生一次。它唯一的用途是快速掌握這集在
講什麼，以及看使用者標記過的地方。

**地圖是索引不是事實。** 苦力層會編造（實測把 davidad 標成 David Duvenaud），也會把
`strongest` 標成 95 行的巨大跨度。地圖只負責告訴你「該去看第幾行」，任何一條寫進文章
前先回英文原文看過那幾行。

## 用 `scripts/read_triage.py` 讀，不要手動翻 JSON

腳本把 map 的行號還原成 `_lines.txt` 的英文原文，省掉自己數行；跨度大到不可能是單一
論點時會標出來要你自己 `--lines` 看。

```bash
V=/Users/slking/Documents/訪談摘要/.venv/bin/python
S=/Users/slking/Documents/訪談摘要/yt-to-md/.claude/skills/humanizer-zh/scripts/read_triage.py

$V $S --scan "/Users/slking/Documents/Obsidian Vault/投資筆記/每週總結/每日研究"  # 有哪幾集、三件組齊不齊
$V $S <三件組任一檔>                      # 摘要：體檢表、章節導航、各區筆數、成品該叫什麼
$V $S <檔> --section claims               # 論點＋strongest 的英文原文（論點認領表底稿）
$V $S <檔> --section quotes               # 引述候選＋英文原文
$V $S <檔> --section propers              # flag 非「完整」的專名＋出處那幾行
$V $S <檔> --section turns                # 歸屬歧異、低信心輪次＋英文原文
$V $S <檔> --section translate            # 難譯標記、量級疑點
$V $S <檔> --lines 33-47                  # 直接印英文逐字稿某段
$V $S <檔> --json                         # 全部，行號已還原成原文
```

缺 `_map.json` 或 `_lines.txt` 時腳本回傳 exit 2，這一集就不能走這條路：只剩分流稿一個
檔時，它是機器翻譯的閱讀稿，拿它寫文章等於拿翻譯稿再翻一次。分流稿或 `_transcript.txt`
缺席只會標註，不擋（前者本來就只是閱讀稿，後者是 `final_gate.py` 的輸入）。

## 各區怎麼用

| 區 | 用途 | 陷阱 |
|---|---|---|
| `health` | 這集的 ASR 品質與工作量預估 | 歧異多不代表壞，代表該看的地方被標出來了 |
| `segments` | 導航 | **不是章節結構**，照抄成小標就寫成逐字稿了 |
| `claims_confirmed` | 論點認領表的左欄底稿 | `occurrences` 超過一個＝照對話順序寫必然重複，只寫一次，用 `strongest` |
| `claims_single` | 只有一邊標到 | 可靠度低，用之前回英文原文確認 |
| `quote_candidates` | 引述候選 | 候選不是義務；`gist` 是機器摘要，不可當譯文 |
| `propers` | 專名清冊 | `flag` 非「完整」的都要查證；地圖自己也會拼錯 |
| `turn_conflicts`／`turns_low_confidence` | 歸屬地雷 | 回英文自己判；判不出來用不指名寫法，不硬掛 |
| `turns_long` | 超長輪次 | 通常是換手被漏標，不是真的一個人講那麼久 |
| `hard_to_translate` | 最容易翻出「通順但空洞」中文的地方 | 逐一處理，不要略過 |
| `magnitude_suspects` | million／billion／掉位數 | 依 SKILL〈數字的 ASR 重建〉，要第二來源才准改 |
| `skip_spans` | 廣告、寒暄 | 捨棄要在 audit 記一筆 |

`>>` 是自動字幕的換手候選訊號不是判決：實測一集 61 個標記有 7 到 9 個是誤插（同一人續
講被切開）。與講者自稱、互相稱名、接話語氣交叉驗證，打架時不無條件採信 `>>`。

## 與順稿版（`yt_transcript_zh`）的差別

| | 順稿版 | 地圖版 |
|---|---|---|
| 中文哪來 | `/yt` 已經全文翻成中文，humanizer 拿它核對 | 沒有可用的中文，**中文全部由你產生** |
| 核對方向 | 順稿 → 英文字幕（抓幻覺、抓翻錯） | 直接寫，英文原文就是唯一依據 |
| 說話人 | 順稿有前綴行，但**不可預設採信** | 地圖給候選與歧異，一樣回原文自己判 |
| 覆蓋 | 順稿是全文，漏段風險在 humanizer 選材 | 用論點認領表對 `claims_confirmed`＋自己通讀 `_lines.txt` |

**地圖不能取代通讀。** `claims_confirmed` 是兩份標記的交集，本來就會漏；覆蓋對帳仍要自己
從頭讀完 `_lines.txt`，地圖只是讓認領表有個底稿。

## 交付與檔名

成品寫成 `<base>_humanized.md`，**base 不含 `_分流稿` 尾綴**。這不是美觀問題，兩個機械
關卡的失敗形態不一樣，前一個特別危險：

- `final_gate.py` 只剝 `_humanized` 就去找 `<base>_transcript.txt`。尾綴帶錯就找不到字幕，
  **覆蓋率粗檢與英文專名交叉核對整組跳過**，只留一行 [候選] 說找不到字幕，其餘照常
  輸出「通過」。也就是說，稿子看起來過關，實際上兩項最要緊的機械核對根本沒跑。
- `upload_hackmd.py` 找不到對應的 `<base>_audit.md` 會直接 `sys.exit` 拒傳。這個會吵，
  不會漏，但白跑一輪。

`read_triage.py` 的摘要會直接印出這一集該用的成品檔名，照抄就好。
