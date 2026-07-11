#!/usr/bin/env python3
"""上傳 markdown 檔案到 HackMD，回傳網址。

用法：
    python upload_hackmd.py <markdown_file> [--title TITLE] [--permission guest|signed_in|owner]

預設 readPermission=guest（連結可看），writePermission=owner，commentPermission=everyone。
HACKMD_API_TOKEN 讀取順序：先找 repo 根 .env，再回退 ~/.claude/.env（維持舊行為相容）。
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path


# 載入 ytkit.config（單一設定來源：repo 根 .env，回退 ~/.claude/.env）
for _p in Path(__file__).resolve().parents:
    if (_p / "ytkit" / "config.py").exists():
        sys.path.insert(0, str(_p))
        break
from ytkit import config  # noqa: E402


def load_env_token() -> str:
    token = config.hackmd_token()
    if not token:
        sys.exit(
            "找不到 HACKMD_API_TOKEN（已找 repo 根 .env 與 ~/.claude/.env）。"
            "請在 .env 設定 HACKMD_API_TOKEN=... 或去 HackMD Settings → API & Webhooks 產生"
        )
    return token


def _quality_gate(file_path: Path) -> None:
    """_yt_ 成品上傳前的品質關卡（無 bypass，這是設計）。

    兩個條件缺一不可，否則直接拒絕上傳：
    1. final_gate.py [硬性] 清零（機械規則：破折號、報幕詞、外語殘留、meta 洩漏…）
    2. 同名 `_audit.md` 交付證據檔存在（覆蓋對帳表、引述回對、專名核對等七項——
       證據落檔才能區分「查過沒漏」與「沒查」；2026-07-11 停損王篇教訓：
       humanizer 表層修完就交件，意思反轉與 10 條漏段全靠事後盲審才撈回來）

    只擋 `_yt_*_humanized.md`；其他檔案（fb/invest/epub）維持原行為。
    """
    if "_yt_" not in file_path.name or not file_path.name.endswith("_humanized.md"):
        return
    import subprocess

    gate = Path(__file__).resolve().parent / "final_gate.py"
    r = subprocess.run(
        [sys.executable, str(gate), str(file_path)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        hard = "\n".join(l for l in r.stdout.splitlines() if l.startswith("[硬性]"))
        sys.exit(
            "拒絕上傳：final_gate [硬性] 未清零。回去修到重跑無輸出，不要嘗試繞過。\n"
            + (hard or r.stdout[-500:])
        )
    audit = file_path.with_name(
        file_path.name[: -len("_humanized.md")] + "_audit.md"
    )
    if not audit.exists() or len(audit.read_text(encoding="utf-8").strip()) < 200:
        sys.exit(
            f"拒絕上傳：交付證據檔不存在或過短（{audit.name}）。\n"
            "依 humanizer-zh SKILL.md「交付清單」，七項證據（修改清單、引述回對表、"
            "專名核對表、數字對帳、歸屬核對、朗讀證據、串接複述掃描）加覆蓋對帳表"
            "必須先落檔為 _audit.md 才可上傳。沒有清單＝沒查，回去補做。"
        )


def extract_title(content: str, fallback: str) -> str:
    for line in content.splitlines():
        m = re.match(r"^#\s+(.+)$", line.strip())
        if m:
            return m.group(1).strip()
    return fallback


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("file")
    parser.add_argument("--title", default=None)
    parser.add_argument("--permission", default="guest", choices=["guest", "signed_in", "owner"])
    parser.add_argument("--team", default=None, help="Team path（例如 slking）。省略則上傳到個人")
    parser.add_argument("--tags", default=None, help="逗號分隔的 tag 列表，例如 'YT訪談摘錄,投資'")
    args = parser.parse_args()

    file_path = Path(args.file)
    if not file_path.exists():
        sys.exit(f"檔案不存在：{file_path}")

    _quality_gate(file_path)

    content = file_path.read_text(encoding="utf-8")
    title = args.title or extract_title(content, file_path.stem)
    token = load_env_token()

    payload = {
        "title": title,
        "content": content,
        "readPermission": args.permission,
        "writePermission": "owner",
        "commentPermission": "everyone",
    }
    if args.tags:
        payload["tags"] = [t.strip() for t in args.tags.split(",") if t.strip()]

    url = (
        f"https://api.hackmd.io/v1/teams/{args.team}/notes"
        if args.team
        else "https://api.hackmd.io/v1/notes"
    )
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        sys.exit(f"HackMD API 錯誤 {e.code}: {body}")
    except urllib.error.URLError as e:
        sys.exit(f"網路錯誤：{e.reason}")

    note_id = data.get("id")
    publish_link = data.get("publishLink") or f"https://hackmd.io/{note_id}"
    print(publish_link)


if __name__ == "__main__":
    main()
