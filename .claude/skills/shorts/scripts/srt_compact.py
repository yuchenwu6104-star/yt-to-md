"""Print an SRT as one line per cue: `<cue#> <h:mm:ss> <text>` — compact enough to read a whole episode.

Usage:
    python srt_compact.py <file.srt> [first_cue] [last_cue]
"""
import sys

def main(path, a=None, b=None):
    for blk in open(path, encoding="utf-8-sig").read().replace("\r\n", "\n").strip().split("\n\n"):
        lines = blk.strip().split("\n")
        if len(lines) < 3:
            continue
        n = int(lines[0])
        if (a and n < a) or (b and n > b):
            continue
        print(n, lines[1].split(" --> ")[0].split(",")[0], " ".join(lines[2:]))

if __name__ == "__main__":
    main(sys.argv[1], *(int(x) for x in sys.argv[2:4]))
