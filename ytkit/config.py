"""共用設定載入器：定位 repo 根、載入 .env、提供取值函式。

各腳本（yt_to_article / transcribe / upload_hackmd）以同一段 bootstrap 把 repo 根
塞進 sys.path，再 `from ytkit import config`，取代各自重複的 .env 載入邏輯。

設計原則：
- 只用 os.environ.setdefault 載入，不覆蓋既有環境變數（不破壞外部 export 的值）。
- repo 根 .env 為主；HACKMD_API_TOKEN 額外回退 ~/.claude/.env（舊機器相容）。
"""
from __future__ import annotations

import os
from pathlib import Path

_MARKERS = (".git", ".env", "ytkit")


def find_repo_root(start: Path | None = None) -> Path:
    """從 start（預設本檔）往上找 repo 根：遇 .git / .env / ytkit 目錄為止。"""
    here = (start or Path(__file__)).resolve()
    for parent in here.parents:
        if any((parent / m).exists() for m in _MARKERS):
            return parent
    return here.parent


def load_env_file(path: Path) -> None:
    """讀 .env 進 os.environ（setdefault，不覆蓋既有環境變數）。"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())


REPO_ROOT = find_repo_root()
# import 時即載入 repo 根 .env（之後各腳本用 os.getenv 取值即可）
load_env_file(REPO_ROOT / ".env")


def get(key: str, default: str | None = None) -> str | None:
    return os.getenv(key, default)


def output_dir() -> Path:
    """YT_OUTPUT_DIR 優先，未設則回退 <repo>/output/（並確保存在）。"""
    d = Path(os.getenv("YT_OUTPUT_DIR") or (REPO_ROOT / "output"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def minimax_base_url() -> str:
    return os.getenv("ANTHROPIC_BASE_URL", "https://api.minimax.io/anthropic")


def minimax_api_key() -> str:
    return os.getenv("ANTHROPIC_API_KEY", "")


def minimax_model() -> str:
    return os.getenv("MINIMAX_MODEL", "MiniMax-M3")


def whisper_device() -> str:
    return os.getenv("WHISPER_DEVICE", "auto")


def hackmd_token() -> str | None:
    """先 repo .env（已載入 os.environ），再回退 ~/.claude/.env。找不到回傳 None。"""
    token = os.getenv("HACKMD_API_TOKEN")
    if token:
        return token
    legacy = Path.home() / ".claude" / ".env"
    if legacy.exists():
        for line in legacy.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("HACKMD_API_TOKEN="):
                val = line.split("=", 1)[1].strip()
                if val:
                    return val
    return None
