# AI Clipper

Makes short clips from a YouTube link or any video file.

## Setup (once)
1. Install Python 3.10+ and ffmpeg (https://ffmpeg.org/download.html; on Windows: `winget install ffmpeg`).
2. `pip install -r requirements.txt`
3. Optional but recommended, for smarter clip picking: set your key
   `ANTHROPIC_API_KEY=your_key` (Mac/Linux: `export ANTHROPIC_API_KEY=...`, Windows: `setx ANTHROPIC_API_KEY ...`).
   Without it the tool still works, using a simpler built-in picker.

## Use it
Web interface:  `streamlit run app.py`   (for files over 200 MB add `--server.maxUploadSize 2000`)

Command line:
```
python clipper.py "https://youtu.be/VIDEO_ID" -n 8 --vertical --captions
python clipper.py my_video.mp4 -n 5 --min 30 --max 75
```
Clips and a `clips.json` (titles and reasons) are saved in `clips/`. You can view, download, or delete past clips directly from the **Video History & Storage** tab in the web interface.

## Notes
- If YouTube says to sign in: add `--cookies-browser chrome`. If downloads fail, run `pip install -U yt-dlp`.
- Only clip content you own or have permission to use. Downloading from YouTube can break its terms of service.
- Speech-based: it works best on talking content (podcasts, streams, interviews). Videos with no speech can't be clipped this way.
