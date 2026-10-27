#!/usr/bin/env python3
"""AI Clipper: turn a YouTube link or any video file into several short clips.

Pipeline: download (yt-dlp) -> transcribe (faster-whisper) -> pick the best moments
(Claude, or a built-in heuristic if no API key) -> cut with ffmpeg (optional 9:16 + captions).
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def log(cb, msg):
    (cb or print)(msg)


# ---------- 1. Get the video ----------
def download(url, work, cookies_browser=None):
    import yt_dlp
    opts = {
        "format": "bv*[height<=1080]+ba/b[height<=1080]/b",
        "outtmpl": str(work / "source.%(ext)s"),
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
    }
    if cookies_browser:  # use your logged-in browser if YouTube asks you to sign in
        opts["cookiesfrombrowser"] = (cookies_browser,)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
    files = [f for f in work.glob("source.*") if f.suffix in (".mp4", ".mkv", ".webm")]
    if not files:
        raise RuntimeError("Download failed. Update yt-dlp (pip install -U yt-dlp) and try again.")
    return files[0], info.get("title", "video")


# ---------- 2. Transcribe ----------
def transcribe(path, model_size="small"):
    # Ensure compatibility with PyAV if metadata_errors is not supported
    try:
        import av
        _orig_open = av.open
        def _safe_av_open(*args, **kwargs):
            kwargs.pop("metadata_errors", None)
            return _orig_open(*args, **kwargs)
        av.open = _safe_av_open
    except Exception:
        pass

    from faster_whisper import WhisperModel
    model = WhisperModel(model_size, device="auto", compute_type="auto")
    raw, _ = model.transcribe(str(path), word_timestamps=True, vad_filter=True)
    segs = []
    for s in raw:
        segs.append({
            "start": s.start, "end": s.end, "text": s.text.strip(),
            "words": [{"w": w.word.strip(), "start": w.start, "end": w.end} for w in (s.words or [])],
        })
    return segs


# ---------- 3. Pick the best moments ----------
def llm_pick(segs, n, min_len, max_len):
    import anthropic
    transcript = "\n".join(f"[{s['start']:.1f}] {s['text']}" for s in segs)
    prompt = f"""You are an expert short-form video editor. Below is a timestamped transcript (seconds).
Choose up to {n} moments that would make the best standalone clips for TikTok, Shorts and Reels.

Rules:
- Each clip must be between {min_len} and {max_len} seconds long.
- Start on a strong hook (a bold claim, question, surprise or story start) and end on a finished thought.
- A clip must make sense without the rest of the video.
- Clips must not overlap. Spread them across the video where good moments exist.
- Prefer emotion, humor, insight, conflict, strong opinions and punchlines. Avoid filler and intros.

Return ONLY a JSON array, no other text. Each item:
{{"start": seconds, "end": seconds, "title": "short catchy title", "reason": "why it works", "score": 1-10}}

Transcript:
{transcript}"""
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
    msg = client.messages.create(
        model=os.getenv("CLIP_MODEL", "claude-sonnet-5-5"),
        max_tokens=3000, messages=[{"role": "user", "content": prompt}])
    text = msg.content[0].text
    return json.loads(re.search(r"\[.*\]", text, re.S).group(0))


def heuristic_pick(segs, n, min_len, max_len):
    """No-AI fallback: favour fast, punchy speech with questions and exclamations."""
    target = (min_len + max_len) / 2
    cands = []
    for i, s in enumerate(segs):
        j = i
        while j + 1 < len(segs) and segs[j]["end"] - s["start"] < target:
            j += 1
        dur = segs[j]["end"] - s["start"]
        if dur < min_len or dur > max_len:
            continue
        text = " ".join(x["text"] for x in segs[i:j + 1])
        score = len(text.split()) / dur + 0.3 * (text.count("?") + text.count("!"))
        cands.append({"start": s["start"], "end": segs[j]["end"], "score": score,
                      "title": " ".join(text.split()[:7]), "reason": "High-energy stretch of speech"})
    return cands


def snap_and_filter(clips, segs, n, min_len, max_len):
    """Snap to sentence boundaries, enforce length, drop overlaps, keep the top n."""
    starts = [s["start"] for s in segs]
    ends = [s["end"] for s in segs]
    fixed = []
    for c in clips:
        try:
            a, b = float(c["start"]), float(c["end"])
        except (KeyError, TypeError, ValueError):
            continue
        a = max([x for x in starts if x <= a + 0.5] or [starts[0]])
        b = min([x for x in ends if x >= b - 0.5] or [ends[-1]])
        if b - a > max_len:
            b = max([e for e in ends if a < e <= a + max_len] or [a + max_len])
        if b - a < min_len:
            continue
        fixed.append({**c, "start": a, "end": b})
    fixed.sort(key=lambda c: float(c.get("score", 0)), reverse=True)
    chosen = []
    for c in fixed:
        if all(c["end"] <= k["start"] or c["start"] >= k["end"] for k in chosen):
            chosen.append(c)
        if len(chosen) == n:
            break
    return sorted(chosen, key=lambda c: c["start"])


# ---------- 4. Cut clips ----------
def ts(t):
    t = max(t, 0)
    return f"{int(t // 3600):02}:{int(t % 3600 // 60):02}:{int(t % 60):02},{int((t % 1) * 1000):03}"


def write_srt(segs, start, end, path, per_line=4):
    words = [w for s in segs for w in s["words"] if w["start"] >= start and w["end"] <= end + 0.2]
    blocks = []
    for k in range(0, len(words), per_line):
        g = words[k:k + per_line]
        blocks.append(f"{len(blocks) + 1}\n{ts(g[0]['start'] - start)} --> {ts(g[-1]['end'] - start)}\n"
                      f"{' '.join(w['w'] for w in g)}\n")
    path.write_text("\n".join(blocks), encoding="utf-8")
    return bool(words)


def cut(src, c, out_dir, name, segs, vertical, captions):
    filters = []
    if vertical:  # centre-crop to 9:16
        filters.append(r"crop=min(iw\,ih*9/16):ih,scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920")
    if captions and write_srt(segs, c["start"], c["end"], out_dir / f"{name}.srt"):
        style = "FontSize=16,Bold=1,Outline=2,Alignment=2,MarginV=" + ("120" if vertical else "40")
        filters.append(f"subtitles={name}.srt:force_style='{style}'")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{c['start']:.2f}", "-i", str(Path(src).resolve()),
           "-t", f"{c['end'] - c['start']:.2f}"]
    if filters:
        cmd += ["-vf", ",".join(filters)]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-movflags", "+faststart", f"{name}.mp4"]
    subprocess.run(cmd, check=True, cwd=out_dir)  # cwd keeps the subtitle path simple on every OS
    return out_dir / f"{name}.mp4"


# ---------- Main pipeline ----------
def process(source, out_dir="clips", n=5, min_len=20, max_len=60, vertical=False, captions=False,
            whisper_model="small", use_ai=True, cookies_browser=None, progress=None):
    out = Path(out_dir)
    work = out / "_work"
    work.mkdir(parents=True, exist_ok=True)

    if re.match(r"https?://", source):
        log(progress, "Downloading video...")
        src, title = download(source, work, cookies_browser)
    else:
        src = Path(source).expanduser()
        if not src.exists():
            raise FileNotFoundError(f"File not found: {src}")
        title = src.stem

    cache = work / f"transcript_{src.stat().st_size}.json"
    if cache.exists():
        segs = json.loads(cache.read_text(encoding="utf-8"))
    else:
        log(progress, "Transcribing audio (first run downloads the speech model)...")
        segs = transcribe(src, whisper_model)
        cache.write_text(json.dumps(segs), encoding="utf-8")
    if not segs:
        raise RuntimeError("No speech found in this video, so there is nothing to pick clips from.")

    log(progress, "Finding the best moments...")
    cands = []
    if use_ai and os.getenv("ANTHROPIC_API_KEY"):
        try:
            cands = llm_pick(segs, n, min_len, max_len)
        except Exception as e:  # fall back instead of failing the whole run
            log(progress, f"AI step failed ({e}); using the built-in method instead.")
    elif use_ai:
        log(progress, "No ANTHROPIC_API_KEY set; using the built-in method.")
    chosen = snap_and_filter(cands, segs, n, min_len, max_len)
    if len(chosen) < n:  # top up with heuristic picks that don't overlap
        extra = snap_and_filter(chosen + heuristic_pick(segs, n, min_len, max_len), segs, n, min_len, max_len)
        chosen = extra
    if not chosen:
        raise RuntimeError("Could not find clips of the requested length. Try a wider min/max range.")

    results = []
    for k, c in enumerate(chosen, 1):
        log(progress, f"Cutting clip {k} of {len(chosen)}...")
        f = cut(src, c, out, f"clip_{k:02d}", segs, vertical, captions)
        results.append({"file": str(f), "start": round(c["start"], 1), "end": round(c["end"], 1),
                        "title": c.get("title", ""), "reason": c.get("reason", ""), "score": c.get("score")})
    (out / "clips.json").write_text(json.dumps({"source": title, "clips": results}, indent=2), encoding="utf-8")
    return results


def main():
    p = argparse.ArgumentParser(description="Make short clips from a YouTube link or a video file.")
    p.add_argument("source", help="YouTube/video URL or path to a video file")
    p.add_argument("-n", "--clips", type=int, default=5, help="how many clips (default 5)")
    p.add_argument("--min", type=int, default=20, help="shortest clip in seconds")
    p.add_argument("--max", type=int, default=60, help="longest clip in seconds")
    p.add_argument("--vertical", action="store_true", help="9:16 crop for Shorts/TikTok/Reels")
    p.add_argument("--captions", action="store_true", help="burn in captions")
    p.add_argument("--out", default="clips", help="output folder")
    p.add_argument("--whisper", default="small", help="tiny, base, small, medium or large-v3 (bigger = more accurate, slower)")
    p.add_argument("--no-ai", action="store_true", help="skip Claude and use the built-in picker")
    p.add_argument("--cookies-browser", help="e.g. chrome or firefox, if YouTube asks you to sign in")
    a = p.parse_args()
    try:
        res = process(a.source, a.out, a.clips, a.min, a.max, a.vertical, a.captions,
                      a.whisper, not a.no_ai, a.cookies_browser)
    except Exception as e:
        sys.exit(f"Error: {e}")
    print(f"\nDone. {len(res)} clips saved in {a.out}/")
    for r in res:
        print(f"  {Path(r['file']).name}  {r['start']}s-{r['end']}s  {r['title']}")


if __name__ == "__main__":
    main()
