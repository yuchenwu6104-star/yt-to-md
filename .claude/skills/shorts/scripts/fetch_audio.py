"""Download episode audio to a local file.

Usage:
    python fetch_audio.py <url-or-path> <out.mp3>

Handles Vocaroo share links (voca.ro/<id>, vocaroo.com/<id>), YouTube links (via yt-dlp),
direct file URLs, and local paths (copied).
"""
import os, re, shutil, subprocess, sys, urllib.request

def main(src, out):
    if os.path.exists(src):
        shutil.copyfile(src, out)
        return
    m = re.search(r"(?:voca\.ro|vocaroo\.com)/(?:i/)?([A-Za-z0-9]+)", src)
    if m:
        url = f"https://media1.vocaroo.com/mp3/{m.group(1)}"
        req = urllib.request.Request(url, headers={"Referer": "https://vocaroo.com/", "User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120) as r, open(out, "wb") as f:
            shutil.copyfileobj(r, f)
        return
    if re.search(r"youtube\.com|youtu\.be", src):
        base = os.path.splitext(out)[0]
        subprocess.run(["yt-dlp", "-x", "--audio-format", "mp3", "-o", base + ".%(ext)s", src], check=True)
        return
    with urllib.request.urlopen(urllib.request.Request(src, headers={"User-Agent": "Mozilla/5.0"}), timeout=120) as r, \
            open(out, "wb") as f:
        shutil.copyfileobj(r, f)

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
    size = os.path.getsize(sys.argv[2])
    dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", sys.argv[2]],
                         capture_output=True, text=True).stdout.strip()
    print(f"{sys.argv[2]}  {size / 1e6:.1f} MB  {float(dur or 0) / 60:.1f} min")
