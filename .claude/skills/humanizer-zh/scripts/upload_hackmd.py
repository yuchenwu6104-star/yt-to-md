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
