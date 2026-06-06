"""GPU transcription fallback for videos without subtitles.

Downloads a YouTube video's audio (or takes a local audio file) and transcribes
it with faster-whisper large-v3-turbo on the GPU (GTX 1080, CUDA int8).

Usage:
    python transcribe.py <YouTube URL | audio file> [--lang zh|en|...] [--out path.txt]

Notes:
- Defaults to large-v3-turbo (multilingual, fast). ~18x realtime on a GTX 1080.
- Language auto-detected if --lang omitted. For Chinese, output is Simplified by
  Whisper; downstream /humanizer-zh handles 簡轉繁.
- Requires: faster-whisper, yt-dlp, ffmpeg, and pip CUDA libs
  (nvidia-cublas-cu12, nvidia-cudnn-cu12, nvidia-cuda-runtime-cu12).
"""
import os
import sys
import argparse
import subprocess


def _enable_cuda_dlls():
    """Add pip-installed NVIDIA CUDA DLL directories to the loader search path."""
    try:
        import nvidia
    except ImportError:
        return
    for base in nvidia.__path__:
        for root, _dirs, files in os.walk(base):
            if root.endswith("bin") and any(f.endswith(".dll") for f in files):
                os.add_dll_directory(root)
                os.environ["PATH"] = root + os.pathsep + os.environ["PATH"]


def _download_audio(url: str, dest_base: str) -> str:
    out_tmpl = dest_base + ".%(ext)s"
    subprocess.run(
        ["yt-dlp", "-f", "bestaudio", "-x", "--audio-format", "mp3",
         "--audio-quality", "5", "-o", out_tmpl, url],
        check=True,
    )
    return dest_base + ".mp3"


def transcribe(audio_path: str, lang: str | None, model_name: str) -> tuple[str, str]:
    from faster_whisper import WhisperModel
    model = WhisperModel(model_name, device="cuda", compute_type="int8")
    segments, info = model.transcribe(
        audio_path, beam_size=5, vad_filter=True, language=lang
    )
    text = " ".join(s.text.strip() for s in segments)
    return text, info.language


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="YouTube URL or local audio file path")
    ap.add_argument("--lang", default=None, help="force language code (e.g. zh, en)")
    ap.add_argument("--out", default=None, help="output transcript .txt path")
    ap.add_argument("--model", default="large-v3-turbo", help="whisper model")
    args = ap.parse_args()

    _enable_cuda_dlls()

    is_url = args.source.startswith("http")
    audio = _download_audio(args.source, "_transcribe_tmp") if is_url else args.source

    text, detected = transcribe(audio, args.lang, args.model)

    out = args.out or "_transcript_out.txt"
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)

    print(f"LANG={detected} CHARS={len(text)} OUT={out}")
    if is_url and os.path.exists(audio):
        os.remove(audio)


if __name__ == "__main__":
    main()
