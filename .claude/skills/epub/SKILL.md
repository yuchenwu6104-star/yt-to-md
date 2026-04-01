---
name: epub
description: "將 epub 電子書拆解為章節，透過 MiniMax 生成子彈筆記與深度洞察文章，落檔至 Obsidian。當用戶使用 /epub 指令並附上 epub 檔案路徑時觸發。"
---

# /epub — ePub 電子書拆章濃縮至 Obsidian

將 epub 電子書依目錄結構拆解成章節，每章透過 MiniMax M2.7 API 生成兩種知識濃縮文件，落檔至 Obsidian 書籍目錄。

## 使用方式

```
/epub <epub 檔案完整路徑>
```

## 執行流程

收到 epub 路徑後，依序執行以下步驟：

### Step 1: 執行主腳本

```bash
python "<skill-path>/scripts/epub_to_articles.py" "<epub 完整路徑>"
```

腳本會自動：
1. 解析 epub TOC，提取書名與章節清單
2. 合併字數不足的短章，跳過前言/版權等非內容章節
3. 每章呼叫 MiniMax API 兩次：① 子彈式重點筆記 ② 深度洞察文章
4. 在 Obsidian 書籍目錄下建立書名子資料夾，每章存入兩個 MD 檔

### Step 2: 確認結果

腳本執行完畢後，告知用戶：
- 書名與作者
- 處理章節數
- 生成 MD 檔案總數
- 儲存路徑

## 輸出格式

落檔至：`C:\Users\wukee\OneDrive\文件\Obsidian Vault\投資筆記\書籍\{書名}\`

每章生成兩個檔案：
- `{章號}_{章節關鍵字}_bullets.md` — 子彈式重點筆記
- `{章號}_{章節關鍵字}_article.md` — 深度洞察文章

**子彈筆記結構：**
```markdown
---
type: book_bullets
date: YYYY-MM-DD
source: epub
book_title: "書名"
chapter_num: "01"
chapter_title: "章節標題"
tags: [...]
---

# 📌 重點筆記：章節標題

> 來源：書名 | 章節 01

- **概念A**：說明...
- **概念B**：說明...
...

---
*本文由 AI 根據電子書內容生成，僅供參考。*
```

**洞察文章結構：**
```markdown
---
type: book_article
date: YYYY-MM-DD
source: epub
book_title: "書名"
chapter_num: "01"
chapter_title: "章節標題"
tags: [...]
---

# 洞察文章標題

> 來源：書名 | 章節 01

導言...

## 小標題 1
...

## 結語
...

---
*本文由 AI 根據電子書內容生成，僅供參考。*
```

## 環境需求

- Python 3.10+
- 套件：`ebooklib`, `beautifulsoup4`, `lxml`, `httpx`
- 環境變數：`ANTHROPIC_API_KEY`（MiniMax Token Plan key）、`ANTHROPIC_BASE_URL`（預設 https://api.minimax.io/anthropic）

## 錯誤處理

- **無 TOC**：回退到 spine 順序解析
- **章節過長**：自動截斷至 50,000 字元
- **API 失敗**：記錄錯誤並繼續處理下一章，不中斷整本書的處理
