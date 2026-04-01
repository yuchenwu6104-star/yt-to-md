---
name: invest
description: "分析投資備忘錄或文章，透過 River 框架（護城河、估值、EV結構、認知偏差）給出投資評級。當用戶使用 /invest 指令並附上檔案路徑或網址時觸發。支援 MD/TXT、PDF、網址三種輸入。"
---

# /invest — 投資機會分析

將投資備忘錄或文章，透過融合 River 框架與價值投資視角的批判性分析，輸出七維度評估與四級評級，結果直接顯示於終端機。

## 使用方式

```
/invest <檔案路徑 或 URL>
```

範例：
```
/invest C:\Users\wukee\Documents\memo_tsmc.md
/invest C:\Users\wukee\Downloads\report.pdf
/invest https://www.example.com/article
```

## 執行流程

收到輸入後，依序執行：

### Step 1: 執行主腳本

```bash
python "<skill-path>/scripts/invest_analyzer.py" "<路徑或URL>"
```

腳本會自動：
1. 判斷輸入類型（URL / PDF / 文字檔）
2. 萃取文字內容
3. 送入 MiniMax M2.7 進行七維度分析
4. 格式化輸出至終端機

### Step 2: 解讀結果

輸出包含：
- **評級**：強烈關注 / 值得研究 / 中性觀望 / 不符標準
- **護城河評估**：競爭優勢本質與持久性
- **估值安全邊際**：當前價格隱含的風險報酬
- **EV 結構**：牛/基/熊三情境機率加權期望值
- **邊際優勢**：資訊優勢來源分析
- **方差警示**：最壞情況損失評估
- **認知偏差掃描**：可能扭曲判斷的偏見
- **論點失效觸發點**：什麼事件代表論點已錯

## 環境需求

- Python 3.10+
- 套件：`httpx`, `beautifulsoup4`, `lxml`, `pdfplumber`
- 環境變數：`ANTHROPIC_API_KEY`（MiniMax Token Plan key）
