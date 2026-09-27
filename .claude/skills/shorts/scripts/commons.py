"""Search Wikimedia Commons and download candidate photos with license/credit metadata.

Usage:
    python commons.py <tag> "<search words>" [--out img] [-n 6]

Writes <out>/<tag>_<i>.jpg (1280px thumbnails) and <out>/<tag>.json (title, license, artist, page).
Commons rate-limits shared IPs hard (HTTP 429); requests retry with backoff, so a run can take minutes.
Pexels / Pixabay block scripted downloads (403), so Commons is the only automatic source.
"""
import argparse, json, os, re, time, urllib.error, urllib.parse, urllib.request

UA = "PodcastShorts/0.1 (https://github.com/yuchenwu6104-star/yt-to-md)"

def get(url):
    for i in range(12):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30).read()
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            time.sleep(int(e.headers.get("retry-after", 5)) + 2 + i * 2)
    raise RuntimeError("rate limited: " + url)

def search(q, n=6):
    p = dict(action="query", generator="search", gsrsearch="filetype:bitmap " + q, gsrnamespace=6, gsrlimit=n,
             prop="imageinfo", iiprop="url|extmetadata|size", iiurlwidth=1280, format="json")
    d = json.loads(get("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(p)))
    out = []
    for pg in sorted(d.get("query", {}).get("pages", {}).values(), key=lambda x: x["index"]):
        ii = pg["imageinfo"][0]
        m = ii["extmetadata"]
        artist = re.sub("<[^>]+>", "", m.get("Artist", {}).get("value", "")).strip()
        out.append(dict(title=pg["title"], w=ii["width"], h=ii["height"], thumb=ii["thumburl"],
                        lic=m.get("LicenseShortName", {}).get("value"), artist=artist, page=ii["descriptionurl"]))
    return out

def credit(meta):
    """One-line on-screen credit for a downloaded photo."""
    return f"Photo: {meta['artist'][:40]} / {meta['lic']} / Wikimedia Commons"

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("query")
    ap.add_argument("--out", default="img")
    ap.add_argument("-n", type=int, default=6)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    res = search(a.query, a.n)
    json.dump(res, open(os.path.join(a.out, f"{a.tag}.json"), "w"), ensure_ascii=False, indent=1)
    for i, r in enumerate(res):
        data = get(r["thumb"])
        open(os.path.join(a.out, f"{a.tag}_{i}.jpg"), "wb").write(data)
        print(a.tag, i, r["title"], r["w"], r["h"], r["lic"], "|", r["artist"][:40], flush=True)
