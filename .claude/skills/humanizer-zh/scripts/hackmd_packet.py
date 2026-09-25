#!/usr/bin/env python3
"""組 HackMD 上傳包並上傳（2026-09-26 起 _yt_ 的 HackMD 版本改用這個，不再上傳整份 _humanized.md）。

上傳包 = 成品開頭（frontmatter＋H1＋原始影片行）＋給下游編輯的指令＋精簡說明欄
        ＋plan (c) 命題清單＋_draft.md 全文（去掉 draft 自己的 frontmatter／H1／原始影片行，保留行號錨點）。

用法：
  hackmd_packet.py <base 絕對路徑> <精簡說明欄檔>                 # 只組包 → <base>_hackmd.md
  hackmd_packet.py <base> <desc> --upload                          # 組包＋新建筆記
  hackmd_packet.py <base> <desc> --upload --note-id <id>           # 組包＋原位更新既有筆記

精簡說明欄由 root 手動挑：保留內容簡介、章節時間碼、持股／利益揭露；刪業配、付費推廣、
社群連結、求訂閱、免責聲明、hashtag。保持原文不翻譯。
上傳前會跑 final_gate.py <base>_humanized.md，[硬性] 未清零或缺 audit 一律拒絕。
"""
from __future__ import annotations
import argparse, json, re, subprocess, sys, urllib.request, urllib.error
from pathlib import Path

HERE = Path(__file__).resolve().parent

TEMPLATE = """{head}
接下來這篇訪談稿麻煩你編輯，照我們平常的方式。這是簡介：
{desc}

下面稿件已逐句查核過。段尾的 [L123-130] 是逐字稿行號，只給你看每段話從哪來：找不到行號依據的話不要寫。數字、名字、否定與方向照原文，不補不改。把引述改寫成敘述時講者不能換，主持人舉的例子不要寫成來賓的。有態度的原話（比喻、反問、轉折、帶判斷的句子）留原話用「」，不要改成敘述。輸出時把行號全部拿掉，不用破折號。（如果是單人口播搞就不用太多引述，很需要再引述）

這是這篇的論證骨架，標了限定和反方的句子可以縮短但不能刪、不能換方向：
{claims}

稿件：
{draft}
"""

SRC_LINE = re.compile(r"(?m)^> 原始影片：.*$")


def build(base: str, desc_file: str) -> Path:
    hum = Path(base + "_humanized.md").read_text(encoding="utf-8")
    m = SRC_LINE.search(hum)
    if not m:
        sys.exit("成品找不到「> 原始影片：」行")
    head = hum[: m.end()].rstrip() + "\n"
    plan = Path(base + "_plan.md").read_text(encoding="utf-8")
    c = re.search(r"(?ms)^## \(c\).*?(?=^## \(d\)|\Z)", plan)
    if not c:
        sys.exit("plan 找不到 ## (c) 節")
    draft = Path(base + "_draft.md").read_text(encoding="utf-8")
    dm = SRC_LINE.search(draft)
    if dm:
        draft = draft[dm.end():]
    else:  # 沒有原始影片行就至少剝 frontmatter 與 H1
        draft = re.sub(r"(?s)\A---\n.*?\n---\n", "", draft)
        draft = re.sub(r"(?m)\A\s*^# .*$", "", draft)
    desc = Path(desc_file).read_text(encoding="utf-8").strip()
    body = TEMPLATE.format(head=head, desc=desc, claims=c.group(0).strip(), draft=draft.strip())
    out = Path(base + "_hackmd.md")
    out.write_text(body, encoding="utf-8")
    print(f"{out}（{len(body.encode())} bytes）")
    return out


def gate(base: str) -> None:
    r = subprocess.run([sys.executable, str(HERE / "final_gate.py"), base + "_humanized.md"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("拒絕上傳：final_gate [硬性] 未清零\n" + "\n".join(
            l for l in r.stdout.splitlines() if l.startswith("[硬性]")))
    if not Path(base + "_audit.md").exists():
        sys.exit("拒絕上傳：缺 _audit.md")


def token() -> str:
    for p in HERE.parents:
        if (p / "yt-to-md" / "ytkit" / "config.py").exists():
            sys.path.insert(0, str(p / "yt-to-md"))
            break
        if (p / "ytkit" / "config.py").exists():
            sys.path.insert(0, str(p))
            break
    from ytkit import config
    t = config.hackmd_token()
    if not t:
        sys.exit("找不到 HACKMD_API_TOKEN")
    return t


def upload(pkt: Path, note_id: str | None, tags: list[str]) -> None:
    content = pkt.read_text(encoding="utf-8")
    title = re.search(r"(?m)^# (.+)$", content).group(1).strip()
    tok = token()
    hdr = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
    if note_id:
        url, method, payload = f"https://api.hackmd.io/v1/notes/{note_id}", "PATCH", {"content": content}
    else:
        url, method = "https://api.hackmd.io/v1/notes", "POST"
        payload = {"title": title, "content": content, "readPermission": "guest",
                   "writePermission": "owner", "commentPermission": "everyone", "tags": tags}
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=hdr, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode() or "{}"
    except urllib.error.HTTPError as e:
        sys.exit(f"HackMD API 錯誤 {e.code}: {e.read().decode(errors='replace')[:300]}")
    if note_id:
        g = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
        with urllib.request.urlopen(g, timeout=30) as r:
            d = json.loads(r.read())
        if "稿件：" not in d.get("content", ""):
            sys.exit("PATCH 回傳成功但讀回內容不是上傳包")
        print(d.get("publishLink") or f"https://hackmd.io/{note_id}")
    else:
        d = json.loads(body)
        print(d.get("publishLink") or f"https://hackmd.io/{d.get('id')}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("desc")
    ap.add_argument("--upload", action="store_true")
    ap.add_argument("--note-id", default=None)
    ap.add_argument("--tags", default="YT訪談摘錄")
    a = ap.parse_args()
    if a.upload:
        gate(a.base)
    pkt = build(a.base, a.desc)
    if a.upload:
        upload(pkt, a.note_id, [t for t in a.tags.split(",") if t])


if __name__ == "__main__":
    main()
