"""Local transcription fallback for videos without subtitles.

Downloads a YouTube video's audio (or takes a local audio file) and transcribes
it with Whisper large-v3-turbo. The backend is chosen by WHISPER_DEVICE (or
--device): CUDA on Windows/NVIDIA, MLX on Apple Silicon (Mac 晶片), else CPU.

Usage:
    python transcribe.py <YouTube URL | audio file> [--lang zh|en|...] \
        [--out path.txt] [--model large-v3-turbo] [--device auto|cuda|mlx|cpu]

Backends (WHISPER_DEVICE):
- cuda : faster-whisper device="cuda", int8（Windows + NVIDIA，~18x realtime on GTX 1080）
- mlx  : mlx-whisper（Apple Silicon 原生，跑 Mac 的 GPU/NE）
- cpu  : faster-whisper device="cpu", int8（任何平台的退路，慢）
- auto : 偵測到 CUDA → cuda；否則 Apple Silicon 且裝了 mlx-whisper → mlx；否則 cpu

Notes:
- Language auto-detected if --lang omitted. Chinese 由 Whisper 輸出簡體，
  下游 /humanizer-zh 負責簡轉繁。
- 依後端安裝依賴：
    cuda → faster-whisper + nvidia-cublas-cu12 / nvidia-cudnn-cu12 / nvidia-cuda-runtime-cu12
    mlx  → pip install mlx-whisper（首次轉錄自 HuggingFace 下載模型）
    cpu  → faster-whisper
- 共用：yt-dlp、ffmpeg。
"""
import os
import sys
import argparse
import importlib.util
import platform
import subprocess
from pathlib import Path

# 載入 ytkit.config（單一設定來源；import 時即載入 repo 根 .env，讓 WHISPER_DEVICE 等生效）
for _p in Path(__file__).resolve().parents:
    if (_p / "ytkit" / "config.py").exists():
        sys.path.insert(0, str(_p))
        break
from ytkit import config  # noqa: E402,F401


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------


def _enable_cuda_dlls() -> None:
    """Add pip-installed NVIDIA CUDA DLL directories to the loader search path (Windows)."""
    if sys.platform != "win32":
        return
    try:
        import nvidia
    except ImportError:
        return
    for base in nvidia.__path__:
        for root, _dirs, files in os.walk(base):
            if root.endswith("bin") and any(f.endswith(".dll") for f in files):
                os.add_dll_directory(root)
                os.environ["PATH"] = root + os.pathsep + os.environ["PATH"]


def _cuda_available() -> bool:
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def _mlx_available() -> bool:
    return (
        sys.platform == "darwin"
        and platform.machine() in ("arm64", "aarch64")
        and importlib.util.find_spec("mlx_whisper") is not None
    )


def resolve_device(requested: str) -> str:
    """把 auto 解析成具體後端；非 auto 則原樣回傳。"""
    requested = (requested or "auto").lower()
    if requested != "auto":
        return requested
    if _cuda_available():
        return "cuda"
    if _mlx_available():
        return "mlx"
    return "cpu"


# ---------------------------------------------------------------------------
# Audio + transcribe
# ---------------------------------------------------------------------------


def _download_audio(url: str, dest_base: str) -> str:
    audio_path = dest_base + ".mp3"
    # A stale file from an interrupted run makes yt-dlp skip the download and
    # the wrong audio gets transcribed — always start clean.
    if os.path.exists(audio_path):
        os.remove(audio_path)
    out_tmpl = dest_base + ".%(ext)s"
    subprocess.run(
        ["yt-dlp", "-f", "bestaudio", "-x", "--audio-format", "mp3",
         "--audio-quality", "5", "--force-overwrites", "-o", out_tmpl, url],
        check=True,
    )
    return audio_path


def _transcribe_faster_whisper(
    audio_path: str, lang: str | None, model_name: str, device: str
) -> tuple[str, str]:
    from faster_whisper import WhisperModel
    model = WhisperModel(model_name, device=device, compute_type="int8")
    segments, info = model.transcribe(
        audio_path, beam_size=5, vad_filter=True, language=lang
    )
    text = " ".join(s.text.strip() for s in segments)
    return text, info.language


def _transcribe_mlx(
    audio_path: str, lang: str | None, model_name: str
) -> tuple[str, str]:
    import mlx_whisper
    # 裸模型名（large-v3-turbo）→ mlx-community 對應 repo；含 "/" 視為完整 HF repo。
    repo = model_name if "/" in model_name else f"mlx-community/whisper-{model_name}"
    result = mlx_whisper.transcribe(audio_path, path_or_hf_repo=repo, language=lang)
    return result["text"].strip(), result.get("language") or (lang or "")


def transcribe(
    audio_path: str, lang: str | None, model_name: str, device: str = "auto"
) -> tuple[str, str]:
    dev = resolve_device(device)
    if dev == "cuda":
        _enable_cuda_dlls()
        return _transcribe_faster_whisper(audio_path, lang, model_name, "cuda")
    if dev == "mlx":
        return _transcribe_mlx(audio_path, lang, model_name)
    if dev == "cpu":
        return _transcribe_faster_whisper(audio_path, lang, model_name, "cpu")
    raise SystemExit(
        f"未知的 WHISPER_DEVICE/--device：{dev!r}（可用 auto|cuda|mlx|cpu）"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="YouTube URL or local audio file path")
    ap.add_argument("--lang", default=None, help="force language code (e.g. zh, en)")
    ap.add_argument("--out", default=None, help="output transcript .txt path")
    ap.add_argument("--model", default="large-v3-turbo", help="whisper model")
    ap.add_argument(
        "--device",
        default=config.whisper_device(),
        help="auto|cuda|mlx|cpu（預設讀 WHISPER_DEVICE，再不然 auto）",
    )
    args = ap.parse_args()

    dev = resolve_device(args.device)
    print(f"[transcribe] device={dev} model={args.model}", file=sys.stderr)

    is_url = args.source.startswith("http")
    audio = _download_audio(args.source, "_transcribe_tmp") if is_url else args.source

    text, detected = transcribe(audio, args.lang, args.model, dev)

    out = args.out or "_transcript_out.txt"
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)

    print(f"LANG={detected} CHARS={len(text)} OUT={out}")
    if is_url and os.path.exists(audio):
        os.remove(audio)


if __name__ == "__main__":
    main()
