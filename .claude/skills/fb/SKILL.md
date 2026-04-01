---
name: fb
description: 將 Obsidian 已落檔的深度文章改寫為 Facebook 貼文格式，存入 FB文章候選目錄。當用戶使用 /fb 指令並附上文章路徑或檔名時觸發。
---

# /fb — 文章轉 Facebook 貼文

將已生成的深度洞察文章，透過 MiniMax M2.7 改寫為適合 Facebook 發文的格式，落檔至 `FB文章候選` 目錄。

## 使用方式

```
/fb <文章路徑或檔名>
```

範例：
```
/fb 2026-03-31_yt_GQ_Taiwan_華爾街交易員_理財真相_財務自由.md
/fb C:\Users\wukee\...\每日研究\2026-03-31_yt_GQ_Taiwan_華爾街交易員.md
```

## 執行流程

收到指令後，執行：

```bash
python "C:\Users\wukee\OneDrive\文件\clon資料\訪談摘要\.claude\skills\yt\scripts\md_to_fb.py" "<文章路徑>"
```

腳本會自動：
1. 解析路徑（支援完整路徑或只傳檔名，自動在 `每日研究` 目錄查找）
2. 讀取文章內容與 frontmatter（youtube_url、channel、video_title）
3. 呼叫 MiniMax M2.7 改寫為 FB 格式
4. 落檔至 `FB文章候選` 目錄

## 輸出格式

**落檔位置：**
`C:\Users\wukee\OneDrive\文件\Obsidian Vault\投資筆記\每週總結\FB文章候選`

**檔名格式：**
`YYYY-MM-DD_fb_<原檔關鍵字>.txt`（純文字，方便直接複製貼上）

**貼文格式規格：**
- 開場 1-2 段純文字，點出講者背景與核心論點
- 正文以 `#標題` 開頭各段，重要概念用 `#詞彙` 嵌入內文
- 純文字，無 markdown 符號、無 emoji
- 總長度 600-900 字
- 結尾自然收束，無 hashtag 列表

## 確認結果

腳本執行完畢後，告知用戶：
- 落檔路徑
- 生成字數

若不滿意可要求重新生成（加入額外指示），或直接在 Obsidian 手動編輯 .txt 檔。
