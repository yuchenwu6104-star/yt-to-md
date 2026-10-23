# podcast-video — Podcast 音檔＋字幕 → YouTube 影片

把 podcast 的 mp3 和 SRT 字幕做成 1920×1080 的 mp4，畫面是卷軸式逐字稿：

- 正在講的那句是墨黑色，前後句淡灰，換句時平滑往上捲
- 畫面一次露出 5～6 句，觀眾截一張圖就是一大段內容
- 左上角封面＋節目名＋集數，右下角進度條＋時間
- 自動把過短的字幕併成一句（≤34 字），連續重複的字幕會併掉

## 需求

```bash
sudo apt install ffmpeg
pip install pillow numpy
```

字型建議用思源宋體繁中 Bold（`NotoSerifTC-Bold.otf`）：
<https://cdn.jsdelivr.net/gh/notofonts/noto-cjk@Serif2.003/Serif/SubsetOTF/TC/NotoSerifTC-Bold.otf>

## 用法

```bash
# 先試一小段（從 23:15 開始 60 秒）
python3 podcast_to_video.py ep173.srt ep173.mp3 cover.png NotoSerifTC-Bold.otf test.mp4 \
  --ep "第 173 集" --start 1395 --dur 60

# 整集
python3 podcast_to_video.py ep173.srt ep173.mp3 cover.png NotoSerifTC-Bold.otf 停損王_EP173.mp4 --ep "第 173 集"
```

| 參數 | 說明 |
|---|---|
| `--title` | 節目名，預設「停損王」 |
| `--ep` | 集數文字，例如「第 173 集」 |
| `--start` / `--dur` | 只輸出某一段（秒），試排版用 |
| `--fps` | 預設 30 |

75 分鐘的音檔大約要 30 分鐘轉完。顏色、字級、版面位置都在腳本開頭的常數。
