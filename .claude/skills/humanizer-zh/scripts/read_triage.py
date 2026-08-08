#!/usr/bin/env python3
"""解析 `/yt` 地圖版（`type: yt_triage`）的三件組，供 humanizer C 路使用。

三件組（Windows 那條 `claude/humanizer-context-rebuild` 分支的產出，會同步進 Vault）：

    <base>_分流稿.md    中文分流稿，frontmatter 指向另外兩個檔（機器翻的，不是寫作素材）
    <base>_map.json     地圖：論點、引述候選、專名、歸屬地雷、難譯點
    <base>_lines.txt    帶行號的英文逐字稿，行號是全流程錨點

本腳本只做機械解析：把 map 裡的行號還原成 `lines.txt` 的英文原文，讓下游直接讀到
「論點 → 支撐它的那幾行英文」，而不必自己去數行。**它不做判斷**：地圖是索引不是
事實，苦力層會編造（實測把 davidad 標成 David Duvenaud），任何一條寫進文章前都要
自己回英文原文看過。

用法：
    read_triage.py <三件組任一檔>                 # 摘要（health＋章節＋工作量）
    read_triage.py <檔> --section claims          # 論點清單＋最強那段的英文原文
    read_triage.py <檔> --section quotes          # 引述候選＋英文原文
    read_triage.py <檔> --section propers         # 要查證的專名（flag 非「完整」）
    read_triage.py <檔> --section turns           # 歸屬歧異與低信心輪次＋英文原文
    read_triage.py <檔> --section translate       # 難譯標記
    read_triage.py <檔> --section all             # 全部
    read_triage.py <檔> --lines 33-47             # 直接印英文逐字稿某段
    read_triage.py <檔> --json                    # 解析結果轉 JSON（行號已還原成原文）
    read_triage.py --scan <目錄>                  # 掃目錄裡所有 yt_triage，列三件組是否齊全

<檔> 可以是分流稿、map.json、lines.txt 或 _transcript.txt 任一個，也可以只給 base。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

# 分流稿檔名的尾綴：`_分流稿`、`_分流稿(V)`、`_分流稿v`、`_分流稿_prototype` 都見過
TRIAGE_SUFFIX = re.compile(r"_分流稿[^.]*$")
KNOWN_SUFFIXES = ("_map", "_lines", "_transcript", "_humanized", "_audit")


def resolve_base(path: str) -> str:
    """任一相關檔案 → 這一集的 base（含目錄，不含尾綴與副檔名）。

    反覆剝，不是剝一層就收工：Vault 裡實際存在 `_humanized_map_minimax.json`、
    `_humanized_annotated.md` 這種疊了兩層的實驗檔，只剝一層會得到以
    `_humanized` 結尾的假 base，成品檔名就會算成 `..._humanized_humanized.md`。
    尾綴樣式全部小寫，影片標題裡的 `Lines`、`Roadmap` 不會被誤剝。
    """
    stem, _ = os.path.splitext(path)
    for _ in range(4):
        m = TRIAGE_SUFFIX.search(stem)
        if m:
            stem = stem[: m.start()]
            continue
        for suffix in KNOWN_SUFFIXES:
            # `_map_prototype`、`_audit_baseline` 這種帶後綴的變體也要吃掉
            m2 = re.search(re.escape(suffix) + r"(_[^_]*)?$", stem)
            if m2:
                stem = stem[: m2.start()]
                break
        else:
            break
    return stem


def find_triage_md(base: str) -> str | None:
    directory = os.path.dirname(base) or "."
    name = os.path.basename(base)
    try:
        entries = os.listdir(directory)
    except OSError:
        return None
    hits = [
        e for e in entries
        if e.startswith(name + "_分流稿") and e.endswith(".md")
    ]
    if not hits:
        return None
    hits.sort(key=len)  # 偏好最乾淨的那個（無 (V)／prototype 尾綴）
    return os.path.join(directory, hits[0])


def parse_frontmatter(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    out = {}
    for line in text[3:end].splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


class Episode:
    """一集的三件組。map 的行號一律可還原成英文原文。"""

    def __init__(self, base: str):
        self.base = base
        self.dir = os.path.dirname(base) or "."
        self.triage_path = find_triage_md(base)
        self.front = {}
        if self.triage_path:
            with open(self.triage_path, encoding="utf-8") as f:
                self.front = parse_frontmatter(f.read(4096))

        # frontmatter 指的路徑優先（分流稿被改名成 `(V)` 時 base 推導仍對，但保險）
        self.map_path = self._resolve("map", base + "_map", ".json")
        self.lines_path = self._resolve("transcript_lines", base + "_lines", ".txt")
        self.transcript_path = base + "_transcript.txt"

        self.map = {}
        if os.path.exists(self.map_path):
            with open(self.map_path, encoding="utf-8") as f:
                self.map = json.load(f)

        self.lines: dict[int, str] = {}
        if os.path.exists(self.lines_path):
            with open(self.lines_path, encoding="utf-8") as f:
                for raw in f:
                    m = re.match(r"^\s*(\d+)\s\s?(.*)$", raw.rstrip("\n"))
                    if m:
                        self.lines[int(m.group(1))] = m.group(2)

    def _resolve(self, key: str, stem: str, ext: str) -> str:
        """依序試：分流稿 frontmatter 指的路徑 → 標準檔名 → 同 base 的變體。

        第三層不能省：分流稿本身可能不存在（原型期那幾集就是只有 map／lines／
        transcript，沒有分流稿），這時 frontmatter 讀不到，而檔名又帶著
        `_prototype` 尾綴，只認標準檔名會變成「你把 map 的路徑餵給它，它回報
        map 不存在」。
        """
        val = self.front.get(key)
        if val:
            cand = os.path.join(self.dir, val)
            if os.path.exists(cand):
                return cand
        exact = stem + ext
        if os.path.exists(exact):
            return exact
        import glob as _glob
        hits = sorted(_glob.glob(_glob.escape(stem) + "*" + ext), key=len)
        return hits[0] if hits else exact

    @property
    def complete(self) -> bool:
        return bool(self.map) and bool(self.lines)

    def missing(self) -> list:
        """回傳缺件。帶「非必要」字樣的不擋開工：分流稿只是閱讀稿，
        `_transcript.txt` 是 final_gate 的輸入，兩者都不是寫作依據。"""
        out = []
        if not self.triage_path:
            out.append("分流稿.md（非必要，本來就只是閱讀稿）")
        if not os.path.exists(self.map_path):
            out.append(os.path.basename(self.map_path))
        if not os.path.exists(self.lines_path):
            out.append(os.path.basename(self.lines_path))
        if not os.path.exists(self.transcript_path):
            out.append(os.path.basename(self.transcript_path) + "（非必要，final_gate 會用）")
        return out

    # 跨度超過這個值的 span 原樣印出來會洗掉整個畫面，只印頭尾。
    # 兩種成因要分開看，訊息裡不要替使用者下結論：
    #   claims／quotes 的巨大跨度多半是標壞了（a16z 那集 strongest 標成 L5-99）；
    #   turn_conflicts 的 [1, 150] 則是真訊號——整集歸屬都對不上。
    # 實測 17 份地圖約 3900 個 span 只有 32 個超標，不會吵。
    SPAN_MAX = 24

    @staticmethod
    def _bounds(span):
        if not span:
            return None
        if isinstance(span, int):
            return span, span
        if len(span) == 1:
            return int(span[0]), int(span[0])
        lo, hi = int(span[0]), int(span[1])
        return (hi, lo) if hi < lo else (lo, hi)

    def text(self, span, join: str = " ") -> str:
        """[起, 迄] 或 [單行] → 英文原文。查無的行標成 `[L### 缺行]`。
        跨度大到不可能是單一論點時只印頭尾，並標出來是地圖的問題。"""
        b = self._bounds(span)
        if not b:
            return ""
        lo, hi = b
        def get(n):
            return self.lines.get(n) or "[L%d 缺行]" % n
        if hi - lo + 1 > self.SPAN_MAX:
            head = [get(n) for n in range(lo, lo + 3)]
            tail = [get(n) for n in range(hi - 2, hi + 1)]
            return join.join(
                head
                + ["⚠ 這條標成 L%d-%d 共 %d 行，中間 %d 行未展開，先用 --lines %d-%d 自己看。"
                   "（論點／引述的巨大跨度多半是地圖標壞了；歸屬歧異的巨大跨度則是真訊號，"
                   "代表整段的說話人都對不上。）"
                   % (lo, hi, hi - lo + 1, hi - lo - 5, lo, hi)]
                + tail
            )
        return join.join(get(n) for n in range(lo, hi + 1))

    @staticmethod
    def label(span) -> str:
        if not span:
            return "L?"
        if isinstance(span, int):
            return "L%d" % span
        if len(span) == 1:
            return "L%s" % span[0]
        return "L%s-%s" % (span[0], span[1])


def wrap(text: str, indent: str = "      ", width: int = 110) -> str:
    out, line = [], ""
    for word in text.split(" "):
        if len(line) + len(word) + 1 > width:
            out.append(indent + line)
            line = word
        else:
            line = (line + " " + word).strip()
    if line:
        out.append(indent + line)
    return "\n".join(out)


def print_brief(ep: Episode) -> None:
    print("集數 base：%s" % os.path.basename(ep.base))
    print("分流稿：%s" % (os.path.basename(ep.triage_path) if ep.triage_path else "（缺）"))
    print("地圖：%s｜英文逐字稿：%d 行｜_transcript.txt：%s"
          % (os.path.basename(ep.map_path), len(ep.lines),
             "有" if os.path.exists(ep.transcript_path) else "缺"))
    print("成品應寫成：%s_humanized.md（不要沿用 _分流稿 尾綴，final_gate 與 upload 都靠 base 對檔）"
          % os.path.basename(ep.base))
    health = ep.map.get("health")
    if health:
        print("\n[體檢表]")
        for line in str(health).splitlines():
            print("  " + line)
    print("\n[章節導航 segments]（導航用，不是章節結構，照抄會寫成逐字稿）")
    for seg in ep.map.get("segments", []):
        print("  %-12s %s" % (Episode.label(seg.get("lines")), seg.get("topic", "")))
    counts = [
        ("claims_confirmed 兩邊一致論點", "claims_confirmed"),
        ("claims_single 單邊論點（可靠度低）", "claims_single"),
        ("quote_candidates 引述候選", "quote_candidates"),
        ("propers 專名", "propers"),
        ("turn_conflicts 歸屬歧異", "turn_conflicts"),
        ("turns_low_confidence 低信心輪次", "turns_low_confidence"),
        ("hard_to_translate 難譯", "hard_to_translate"),
        ("magnitude_suspects 量級疑點", "magnitude_suspects"),
        ("skip_spans 可略過", "skip_spans"),
    ]
    print("\n[各區筆數]")
    for label, key in counts:
        print("  %-38s %d" % (label, len(ep.map.get(key, []))))
    need = [p for p in ep.map.get("propers", []) if p.get("flag") and p["flag"] != "完整"]
    print("  %-38s %d" % ("↑ 其中要查證的專名（flag 非「完整」）", len(need)))


def print_claims(ep: Episode) -> None:
    print("\n[claims_confirmed] 論點認領表底稿。occurrences 超過一個＝照對話順序寫必然重複，")
    print("只寫一次，用 strongest 那段。以下附上 strongest 的英文原文。")
    for i, c in enumerate(ep.map.get("claims_confirmed", []), 1):
        print("\n%2d. %s" % (i, c.get("claim", "")))
        if c.get("claim_alt") and c["claim_alt"] != c.get("claim"):
            print("    另一份標成：%s" % c["claim_alt"])
        occ = c.get("occurrences") or []
        print("    strongest %s｜出現 %d 次 %s"
              % (Episode.label(c.get("strongest")), len(occ),
                 " ".join(Episode.label(o) for o in occ)))
        print(wrap(ep.text(c.get("strongest")), "    > "))
    print("\n[claims_single] 只有一邊標到，可靠度低，用之前先回英文原文確認。")
    for i, c in enumerate(ep.map.get("claims_single", []), 1):
        print("\n%2d. [%s] %s" % (i, c.get("來源", "?"), c.get("claim", "")))
        print("    strongest %s" % Episode.label(c.get("strongest")))
        print(wrap(ep.text(c.get("strongest")), "    > "))


def print_quotes(ep: Episode) -> None:
    print("\n[quote_candidates] 候選不是義務，取捨仍是你的工作。「來源 A+B」＝兩邊都標。")
    for i, q in enumerate(ep.map.get("quote_candidates", []), 1):
        print("\n%2d. %s [%s] %s" % (i, Episode.label(q.get("lines")), q.get("來源", "?"), q.get("why", "")))
        if q.get("gist"):
            print("    地圖摘要（不可直接當譯文）：%s" % q["gist"])
        print(wrap(ep.text(q.get("lines")), "    > "))


def print_propers(ep: Episode) -> None:
    print("\n[propers] flag 不是「完整」的都要查證。地圖會編造專名，一律回英文原文那幾行核對。")
    for p in ep.map.get("propers", []):
        flag = p.get("flag", "")
        if flag == "完整":
            continue
        lines = p.get("lines") or []
        print("\n  %-32s [%s] 出現於 %s"
              % (p.get("name", ""), flag, ", ".join("L%s" % n for n in lines[:12])))
        if p.get("note"):
            print(wrap(p["note"], "      "))
        for n in lines[:3]:
            print(wrap("L%s  %s" % (n, ep.text(n)), "      | "))


def print_turns(ep: Episode) -> None:
    print("\n[turn_conflicts] 歸屬地雷：兩份標記打架。回英文原文自己判，判不出來用不指名寫法。")
    for t in ep.map.get("turn_conflicts", []):
        print("\n  %s  A說「%s」｜B說「%s」" % (Episode.label(t.get("lines")), t.get("A說", ""), t.get("B說", "")))
        print(wrap("A依據：%s" % t.get("A依據", ""), "      "))
        print(wrap("B依據：%s" % t.get("B依據", ""), "      "))
        print(wrap(ep.text(t.get("lines")), "      > "))
    print("\n[turns_low_confidence]")
    for t in ep.map.get("turns_low_confidence", []):
        print("\n  %s  判為 %s（信心 %s）" % (Episode.label(t.get("lines")), t.get("speaker", ""), t.get("confidence", "")))
        print(wrap("依據：%s" % t.get("evidence", ""), "      "))
        print(wrap(ep.text(t.get("lines")), "      > "))
    if ep.map.get("turns_long"):
        print("\n[turns_long] 超長輪次，通常是換手被漏標")
        for t in ep.map["turns_long"]:
            print("  %s  %s（%s）" % (Episode.label(t.get("lines")), t.get("speaker", ""), t.get("confidence", "")))


def print_translate(ep: Episode) -> None:
    print("\n[hard_to_translate] 最容易翻出「通順但空洞」中文的地方，逐一處理。")
    for t in ep.map.get("hard_to_translate", []):
        print("\n  %s [%s] %s" % (Episode.label(t.get("lines")), t.get("來源", "?"), t.get("why", "")))
        if t.get("note"):
            print(wrap(t["note"], "      "))
        print(wrap(ep.text(t.get("lines")), "      > "))
    mag = ep.map.get("magnitude_suspects", [])
    if mag:
        print("\n[magnitude_suspects] 量級疑點（million／billion／掉位數）")
        for m in mag:
            print("\n  %s %s" % (Episode.label(m.get("lines")), json.dumps(m, ensure_ascii=False)))
            print(wrap(ep.text(m.get("lines")), "      > "))


def to_json(ep: Episode) -> dict:
    def expand(items, key="lines"):
        out = []
        for it in items:
            d = dict(it)
            d["text"] = ep.text(it.get(key))
            out.append(d)
        return out

    return {
        "base": ep.base,
        "triage": ep.triage_path,
        "map": ep.map_path,
        "lines": ep.lines_path,
        "transcript": ep.transcript_path if os.path.exists(ep.transcript_path) else None,
        "output": ep.base + "_humanized.md",
        "health": ep.map.get("health"),
        "segments": ep.map.get("segments", []),
        "claims_confirmed": expand(ep.map.get("claims_confirmed", []), "strongest"),
        "claims_single": expand(ep.map.get("claims_single", []), "strongest"),
        "quote_candidates": expand(ep.map.get("quote_candidates", [])),
        "propers": ep.map.get("propers", []),
        "turn_conflicts": expand(ep.map.get("turn_conflicts", [])),
        "turns_low_confidence": expand(ep.map.get("turns_low_confidence", [])),
        "hard_to_translate": expand(ep.map.get("hard_to_translate", [])),
        "magnitude_suspects": expand(ep.map.get("magnitude_suspects", [])),
        "skip_spans": ep.map.get("skip_spans", []),
    }


def scan(directory: str) -> int:
    try:
        entries = sorted(os.listdir(directory))
    except OSError as exc:
        print("讀不到目錄：%s" % exc, file=sys.stderr)
        return 2
    # 以 map 檔而非分流稿列舉：分流稿才是可有可無的那一個（原型期那幾集就沒有），
    # 用它當索引會讓「有地圖可做但沒有分流稿」的集數整個消失在清單外。
    bases = sorted({
        resolve_base(os.path.join(directory, e))
        for e in entries
        if (e.endswith(".json") and "_map" in e) or ("_分流稿" in e and e.endswith(".md"))
    })
    if not bases:
        print("這個目錄沒有 yt_triage 三件組。")
        return 0
    incomplete = 0
    for base in bases:
        ep = Episode(base)
        missing = [m for m in ep.missing() if "非必要" not in m]
        done = os.path.exists(ep.base + "_humanized.md")
        status = "缺 " + "、".join(missing) if missing else ("已做" if done else "可做")
        if missing:
            incomplete += 1
        flags = "" if ep.triage_path else "  ← 無分流稿，地圖仍可用"
        print("%-10s %s%s" % (status, os.path.basename(base), flags))
    print("\n共 %d 集，%d 集缺地圖或逐字稿行檔。" % (len(bases), incomplete))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="解析 /yt 地圖版（yt_triage）三件組")
    ap.add_argument("path", nargs="?", help="三件組任一檔案，或 base")
    ap.add_argument("--scan", metavar="DIR", help="掃目錄裡所有 yt_triage，列三件組是否齊全")
    ap.add_argument("--section", default="brief",
                    choices=["brief", "claims", "quotes", "propers", "turns", "translate", "segments", "all"])
    ap.add_argument("--lines", metavar="A-B", help="直接印英文逐字稿某段，例如 33-47")
    ap.add_argument("--json", action="store_true", help="輸出 JSON（行號已還原成英文原文）")
    args = ap.parse_args()

    if args.scan:
        return scan(args.scan)
    if not args.path:
        ap.error("要給一個檔案路徑，或用 --scan <目錄>")

    ep = Episode(resolve_base(args.path))
    if not ep.complete:
        print("三件組不齊，C 路不能開工。缺：%s" % "、".join(ep.missing()), file=sys.stderr)
        print("（分流稿是閱讀稿不是素材，只有它一個檔時不要拿它當寫作依據）", file=sys.stderr)
        return 2

    if args.lines:
        m = re.match(r"^(\d+)(?:\s*[-–~]\s*(\d+))?$", args.lines.strip())
        if not m:
            print("--lines 格式是 33-47 或 33", file=sys.stderr)
            return 2
        lo = int(m.group(1))
        hi = int(m.group(2) or m.group(1))
        for n in range(lo, hi + 1):
            print("%5d  %s" % (n, ep.lines.get(n, "[缺行]")))
        return 0

    if args.json:
        print(json.dumps(to_json(ep), ensure_ascii=False, indent=1))
        return 0

    sec = args.section
    if sec in ("brief", "segments", "all"):
        print_brief(ep)
    if sec in ("claims", "all"):
        print_claims(ep)
    if sec in ("quotes", "all"):
        print_quotes(ep)
    if sec in ("propers", "all"):
        print_propers(ep)
    if sec in ("turns", "all"):
        print_turns(ep)
    if sec in ("translate", "all"):
        print_translate(ep)
    return 0


if __name__ == "__main__":
    sys.exit(main())
