---
name: shorts
description: "把 Podcast 單集（音檔＋校正過的 SRT 字幕）剪成 YouTube Shorts：讀完整集挑出內容型候選片段、可跳接、上字幕，沒有影片畫面就配自製圖卡與 Wikimedia Commons 開源圖。當用戶給音檔連結（Vocaroo、YouTube、檔案）與字幕檔、要剪 Shorts / 短影音 / 精華片段，或使用 /shorts 指令時觸發。"
---

# /shorts — Podcast 單集 → YouTube Shorts

輸入一集的**音檔**和**校正過的 SRT**，產出直式 1080×1920 的 mp4：講者原音跳接、逐句字幕（重點詞標黃）、跟著講話時間跳出的圖卡或開源照片，另附 YouTube 說明欄文字（含圖片出處）。

## 使用方式

```
/shorts <音檔網址或路徑> <字幕.srt>
```

分兩個回合：先**挑候選片段**給用戶選，選完才**製作**。不要沒問就直接全做。

## 準備環境

```bash
# 系統：ffmpeg、Noto Sans CJK（Linux: apt-get install -y ffmpeg fonts-noto-cjk；
#        macOS: brew install ffmpeg && brew install --cask font-noto-sans-cjk）
pip install -r "<skill-path>/scripts/requirements.txt"
```

雲端 session 的網路要允許：`voca.ro`、`vocaroo.com`、`*.vocaroo.com`（音檔）、`commons.wikimedia.org`、
`upload.wikimedia.org`（配圖）、`huggingface.co`（第一次下載 Whisper small 模型）。Pexels、Pixabay 會對腳本回 403，不要浪費時間。

**工作目錄**：本機用 `output/shorts/<集數>/`（已被 .gitignore 的 `output/` 蓋到）；雲端用 scratchpad。音檔、圖、成品都放這裡，不進 git。以下指令都在工作目錄執行。

```bash
python "<skill-path>/scripts/fetch_audio.py" "<音檔網址>" ep.mp3
```

## 第一回合：挑候選片段

1. `python "<skill-path>/scripts/srt_compact.py" <字幕.srt>` 把整集印成「編號 時間 文字」一行一句。**整集讀完**再挑，好段落常在後半（說故事、投資主題）。
2. 挑 6–8 段**內容取向**的候選（知識點、反直覺結論、有具體數字、有比喻），閒聊與抖內回覆除非用戶要娛樂向否則略過。每段給：
   - 標題（放在畫面上方的兩行，第二行是鉤子）
   - 用到的 **cue 編號範圍**與時間碼，可以跳接（不相鄰的範圍依序接起來）
   - 開場鉤子句、推薦理由、畫面構想（哪些用自製圖卡、哪些找照片）
3. 標出推薦的前 2–3 支，請用戶挑。

## 第二回合：製作

每支 Short 是工作目錄裡的一個 Python spec，以 `examples/ep171_ipo_lottery.py`、`examples/ep171_el_farol.py` 為範本：

```python
import os, sys
sys.path.insert(0, "<skill-path>/scripts")
from shortslib import *
from commons import credit
configure("ep.mp3", "<字幕.srt>", "停損王 EP171")      # 音檔、字幕、左上角標籤

S = Short("short_name", "標題第一行", "黃色鉤子第二行",
          [(2180, 2186, "hook"), (2189, 2192, "idle"), ...],   # (第一句, 最後一句, 場景名)，含頭尾
          highlights=["3%", "7萬5", ...])                      # 字幕裡要標黃的詞

def visual(S, fr, t):            # 每一格畫面：依場景畫進 PANEL 區（y 470–1310）
    c = S.clip_at(t)             # c["scene"], c["t0"]
    ...                          # S.cue_time(n) = 第 n 句在成片中開始的秒數，用來讓圖卡跟著講話出現
S.render(visual)
```

引擎自動處理：剪接點、音量正規化到 -14 LUFS、逐句字幕（直接用 SRT 的校正文字）、標題列、進度條。
相鄰的 cue 範圍會合併成同一段連續音訊，只切換畫面，不會重播。

### 步驟

1. **寫 spec**：片段以 cue 範圍表示；畫面用 `card()`、`chip()`、`check()`、`xmark()`、`arrow()`、`text_c()`、`rich()` 畫圖卡（範例裡的 `row()` 可直接抄），
   照片用 `load_cover()` + `photo()`（自動加 Ken Burns 與角落出處）。
2. **找照片**（需要時）：`python "<skill-path>/scripts/commons.py" <tag> "<英文關鍵字>"`，
   再把 `img/<tag>_*.jpg` 拼成一張縮圖總表用 Read 看過再挑。Commons 對共用 IP 限流很兇，一次查詢可能要好幾分鐘，放背景跑，同時先做不需要照片的部分。搜不到合適的就改畫圖卡，不要硬塞不相干的圖。
3. **預覽**：`PREVIEW=5,30,60 python spec.py` 輸出 `preview_<name>.jpg`（多個時間點並排），用 Read 看：文字有沒有超出邊界、圖卡有沒有空白太久、元素有沒有重疊。修到沒問題才渲染。
4. **渲染**：`python spec.py` → `<name>.mp4`（約 1 分鐘成片 / 1 分鐘運算）。
5. **驗證剪接點**：`python "<skill-path>/scripts/verify_cuts.py" <name>`，確認每段開頭與結尾都是完整的字。
   句尾出現下一段第一個字（因為／可是／我們）通常只是 Whisper 的歸屬誤差，對照下一行開頭確認。
6. **說明欄**：寫 `<name>_description.txt`：鉤子、兩三句重點、「完整內容：<節目> <集數>」、hashtag、圖片出處（標題／作者／授權）。有模擬或示意的圖要註明。
7. 用 SendUserFile 傳 mp4 與說明欄。

## 用戶偏好（停損王）

- **保留推論細節**：第一版剪太精簡被說「細節去掉太多」。寧可 1.5–2.5 分鐘講完整，也不要只剩結論（Shorts 上限 3 分鐘）。
- **開場就要有東西**：第一秒就出現鉤子字卡，不要空白等講到重點才跳。
- 口頭禪、字幕跟原音的小差異（如省略「那個」）用戶不在意，不用逐一確認。
- 視覺：深色底、黃色重點、字幕在下方安全區（避開 Shorts 底部介面），數字與結論用自製動態圖卡。

## 踩過的坑（引擎已處理，改引擎時別退回去）

- **SRT 時間碼會偏 0.3–0.5 秒**：直接照 cue 切，會把上一句尾巴帶進來（實例：「舉例」被切進「假如說抽籤要 250 萬」）。
  引擎在每個剪接點附近跑 Whisper 找句首句尾的實際字，再對到最安靜的 10 ms。
- **Whisper 的字尾時間偏早**：照它切，句尾會被吃掉（實例：「metadata」的「ta」）。
  結尾一律往後走到聲音真的降到靜音，再留約 0.1 秒，但不碰到下一個字、最多延長 0.45 秒；淡出 60 ms。
- **mp3 用 `-ss` 跳轉時開頭幾毫秒解碼成靜音**：做能量分析會誤判成「最安靜的點」。`load_mono` 會多解 0.5 秒再丟掉。
- **相鄰片段各自加緩衝會重疊重播**：相鄰 cue 範圍要合併成一段音訊（引擎已做）。
- `pkill -f <pattern>` 會連同跑這條指令的 shell 一起殺掉，停背景工作改用 PID。
