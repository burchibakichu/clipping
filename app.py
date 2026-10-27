# Web interface. Run with:  streamlit run app.py
import datetime
import json
import os
import shutil
import stat
from pathlib import Path

import streamlit as st

from clipper import process

st.set_page_config(page_title="AI Clipper", page_icon="🎬", layout="wide", initial_sidebar_state="collapsed")

# Mobile-responsive styling
st.markdown("""
<style>
/* ==========================================
   Mobile-Responsive Enhancements
   ========================================== */

/* Touch-friendly buttons & smooth transitions */
.stButton > button, .stDownloadButton > button {
    border-radius: 10px !important;
    font-weight: 500 !important;
    transition: all 0.2s ease !important;
}

/* Mobile Screen Optimizations (phones & small screens) */
@media (max-width: 768px) {
    /* Responsive page container padding */
    .block-container {
        padding-top: 1.5rem !important;
        padding-left: 0.85rem !important;
        padding-right: 0.85rem !important;
        padding-bottom: 2.5rem !important;
    }

    /* Stack form columns comfortably on phone */
    [data-testid="column"] {
        min-width: 100% !important;
        margin-bottom: 0.5rem !important;
    }

    /* Full-width thumb-friendly buttons on phone */
    .stButton > button, .stDownloadButton > button {
        width: 100% !important;
        min-height: 48px !important;
        font-size: 1rem !important;
    }

    /* 2x2 compact grid for metric counters on phone */
    div[data-testid="stHorizontalBlock"]:has(> div [data-testid="stMetric"]) {
        display: grid !important;
        grid-template-columns: 1fr 1fr !important;
        gap: 0.6rem !important;
    }
    div[data-testid="stHorizontalBlock"]:has(> div [data-testid="stMetric"]) > div {
        min-width: 100% !important;
        width: 100% !important;
    }
    [data-testid="stMetric"] {
        background: rgba(128, 128, 128, 0.08);
        padding: 0.6rem 0.8rem !important;
        border-radius: 10px !important;
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.8rem !important;
    }
    [data-testid="stMetricValue"] {
        font-size: 1.25rem !important;
    }

    /* Smooth swipeable tabs on phone */
    .stTabs [data-baseweb="tab-list"] {
        gap: 6px !important;
        overflow-x: auto !important;
        white-space: nowrap !important;
        scrollbar-width: none !important;
        padding-bottom: 4px !important;
    }
    .stTabs [data-baseweb="tab"] {
        padding: 8px 14px !important;
        font-size: 0.9rem !important;
    }

    /* Responsive video player for mobile vertical reels */
    video {
        border-radius: 12px !important;
        max-height: 65vh !important;
        width: 100% !important;
        object-fit: contain !important;
    }
}
</style>
""", unsafe_allow_html=True)

CLIPS_DIR = Path("clips")
CLIPS_DIR.mkdir(parents=True, exist_ok=True)


# ==========================================
# File & Storage Utilities
# ==========================================
def on_rm_error(func, path, exc_info):
    """Handle read-only file removal issues on Windows."""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass


def remove_dir_safely(path: Path):
    """Safely delete a folder and all its contents."""
    if path.exists() and path.is_dir():
        shutil.rmtree(path, onerror=on_rm_error)


def remove_file_safely(path: Path):
    """Safely delete a single file."""
    try:
        if path.exists() and path.is_file():
            os.chmod(path, stat.S_IWRITE)
            path.unlink()
    except Exception:
        pass


def get_path_size(path: Path) -> int:
    """Calculate total size of file or directory in bytes."""
    if not path.exists():
        return 0
    if path.is_file():
        try:
            return path.stat().st_size
        except Exception:
            return 0
    total = 0
    try:
        for p in path.rglob("*"):
            if p.is_file():
                try:
                    total += p.stat().st_size
                except Exception:
                    pass
    except Exception:
        pass
    return total


def format_size(bytes_size: int) -> str:
    """Format bytes into readable units."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_size < 1024.0:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.1f} PB"


def get_all_jobs():
    """Scans CLIPS_DIR for all job folders and returns structured details sorted newest first."""
    if not CLIPS_DIR.exists():
        return []

    jobs = []
    for item in CLIPS_DIR.iterdir():
        if item.is_dir() and not item.name.startswith("."):
            total_size = get_path_size(item)
            work_dir = item / "_work"
            work_size = get_path_size(work_dir) if work_dir.exists() else 0
            clips_size = max(0, total_size - work_size)

            info_json = item / "clips.json"
            title = ""
            clips_meta = {}
            if info_json.exists():
                try:
                    data = json.loads(info_json.read_text(encoding="utf-8"))
                    title = data.get("source", "")
                    for c in data.get("clips", []):
                        f_name = Path(c.get("file", "")).name
                        if f_name:
                            clips_meta[f_name] = c
                except Exception:
                    pass

            mp4_files = sorted([f for f in item.glob("*.mp4") if f.is_file()])

            display_name = item.name
            created_at = None
            if item.name.startswith("job_"):
                raw_time = item.name.replace("job_", "")
                try:
                    dt = datetime.datetime.strptime(raw_time, "%Y%m%d_%H%M%S")
                    created_at = dt
                    display_name = dt.strftime("%b %d, %Y - %I:%M %p")
                except Exception:
                    pass
            if not created_at:
                try:
                    created_at = datetime.datetime.fromtimestamp(item.stat().st_mtime)
                except Exception:
                    created_at = datetime.datetime.min

            jobs.append({
                "path": item,
                "folder_name": item.name,
                "display_name": display_name,
                "created_at": created_at,
                "title": title or item.name,
                "clips_meta": clips_meta,
                "mp4_files": mp4_files,
                "total_size": total_size,
                "work_size": work_size,
                "clips_size": clips_size,
                "has_work": work_dir.exists(),
            })

    jobs.sort(key=lambda j: j["created_at"], reverse=True)
    return jobs


# Initialize session state for persistent storage
if "clips" not in st.session_state:
    st.session_state["clips"] = []
if "clip_bytes" not in st.session_state:
    st.session_state["clip_bytes"] = {}
if "out_folder" not in st.session_state:
    st.session_state["out_folder"] = ""

all_jobs = get_all_jobs()
total_disk_used = sum(j["total_size"] for j in all_jobs)
total_clips_count = sum(len(j["mp4_files"]) for j in all_jobs)

st.title("AI Clipper 🎬")
st.caption("Turn YouTube links or video files into short clips, and manage stored videos directly from your browser.")

tab_create, tab_history = st.tabs([
    "✂️ Make Clips",
    f"📁 Video History & Storage ({len(all_jobs)} jobs • {format_size(total_disk_used)})"
])


# ==========================================
# TAB 1: MAKE CLIPS
# ==========================================
with tab_create:
    st.markdown("### Create New Clips")
    url = st.text_input("YouTube or video link", placeholder="https://www.youtube.com/watch?v=...")
    upload = st.file_uploader("...or upload a video file", type=["mp4", "mov", "mkv", "webm", "avi"])

    c1, c2 = st.columns(2)
    n = c1.slider("Number of clips", 1, 15, 5)
    lo, hi = c2.slider("Clip length (seconds)", 10, 180, (20, 60))
    vertical = c1.checkbox("Vertical 9:16 (Shorts / TikTok / Reels)", value=True)
    captions = c2.checkbox("Burn in captions", value=True)
    model = st.selectbox(
        "Transcription quality",
        ["base", "small", "medium"],
        index=1,
        help="Bigger is more accurate but slower."
    )

    btn_col1, btn_col2, btn_col3 = st.columns([2, 1, 1])
    start_processing = btn_col1.button("Make clips", type="primary", use_container_width=True)

    if btn_col2.button("Clear Results", use_container_width=True, help="Clear the current view from the screen (keeps files on disk)"):
        st.session_state["clips"] = []
        st.session_state["clip_bytes"] = {}
        st.session_state["out_folder"] = ""
        st.rerun()

    if btn_col3.button("🗑️ Delete from Disk", use_container_width=True, help="Permanently delete this newly generated job and its files from disk"):
        current_folder = st.session_state.get("out_folder")
        if current_folder and Path(current_folder).exists():
            remove_dir_safely(Path(current_folder))
            st.session_state["clips"] = []
            st.session_state["clip_bytes"] = {}
            st.session_state["out_folder"] = ""
            st.toast("Current job deleted from disk successfully!")
            st.rerun()
        else:
            st.info("No active job folder to delete.")

    if start_processing:
        if not url and not upload:
            st.error("Please paste a link or upload a video first.")
            st.stop()

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = CLIPS_DIR / f"job_{timestamp}"
        work_dir = out_dir / "_work"
        work_dir.mkdir(parents=True, exist_ok=True)

        source = url.strip()
        if upload:
            uploaded_path = work_dir / upload.name
            uploaded_path.write_bytes(upload.getbuffer())
            source = str(uploaded_path)

        status = st.status("Processing video...", expanded=True)
        try:
            clips = process(
                source=source,
                out_dir=str(out_dir),
                n=n,
                min_len=lo,
                max_len=hi,
                vertical=vertical,
                captions=captions,
                whisper_model=model,
                progress=lambda m: status.write(m),
            )
            status.update(label="Done! Clips created successfully.", state="complete")

            st.session_state["clips"] = clips
            st.session_state["out_folder"] = str(out_dir.resolve())
            clip_bytes = {}
            for c in clips:
                fpath = Path(c["file"])
                if fpath.exists():
                    clip_bytes[c["file"]] = fpath.read_bytes()
            st.session_state["clip_bytes"] = clip_bytes
            st.rerun()

        except Exception as e:
            status.update(label="Processing failed", state="error")
            st.error(f"Error: {e}")
            st.stop()

    # Render generated clips from session_state
    if st.session_state["clips"]:
        st.divider()
        res_hdr_col1, res_hdr_col2 = st.columns([3, 1])
        res_hdr_col1.subheader(f"Generated Clips ({len(st.session_state['clips'])})")

        if st.session_state["out_folder"]:
            st.info(f"📁 Files saved on disk at: `{st.session_state['out_folder']}`")

        for i, c in enumerate(st.session_state["clips"], 1):
            fpath = Path(c["file"])
            st.markdown(f"#### {i}. {c.get('title', f'Clip {i}')}")
            st.caption(f"⏱️ **{c['start']}s to {c['end']}s** • {c.get('reason', '')}")

            video_bytes = st.session_state["clip_bytes"].get(c["file"])
            if not video_bytes and fpath.exists():
                video_bytes = fpath.read_bytes()
                st.session_state["clip_bytes"][c["file"]] = video_bytes

            if video_bytes:
                st.video(video_bytes, format="video/mp4")
                dl_col, del_clip_col = st.columns([3, 1])
                dl_col.download_button(
                    label=f"⬇️ Download {fpath.name}",
                    data=video_bytes,
                    file_name=fpath.name,
                    mime="video/mp4",
                    key=f"dl_clip_{i}_{fpath.name}",
                    use_container_width=True,
                )
                if del_clip_col.button(f"🗑️ Delete", key=f"del_active_{i}_{fpath.name}", use_container_width=True):
                    remove_file_safely(fpath)
                    remove_file_safely(fpath.with_suffix(".srt"))
                    st.session_state["clips"] = [item for item in st.session_state["clips"] if item["file"] != c["file"]]
                    if c["file"] in st.session_state["clip_bytes"]:
                        del st.session_state["clip_bytes"][c["file"]]
                    st.toast(f"Deleted {fpath.name}")
                    st.rerun()
            else:
                st.warning(f"Video file not found at: {c['file']}")


# ==========================================
# TAB 2: VIDEO HISTORY & STORAGE
# ==========================================
with tab_history:
    st.markdown("### 🗄️ Saved Video Library & Storage Manager")
    st.caption("Browse, download, or delete past generated clips and free up disk space without opening folders manually.")

    # Storage Statistics Cards
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Jobs", len(all_jobs))
    m2.metric("Total Clips", total_clips_count)
    m3.metric("Total Disk Space", format_size(total_disk_used))
    total_cache_size = sum(j["work_size"] for j in all_jobs)
    m4.metric("Download Cache Space", format_size(total_cache_size), help="Temporary source videos and audio files in _work directories")

    # Global Quick Actions Toolbar
    st.markdown("#### Quick Cleanup Tools")
    t_col1, t_col2 = st.columns([1, 1])

    if t_col1.button("🧹 Clean All Download Cache (Keep Clips)", use_container_width=True, help="Deletes all raw downloaded videos and audio (_work folders) across all jobs. Your finished short clips remain safe!"):
        cleaned_count = 0
        for j in all_jobs:
            w_dir = j["path"] / "_work"
            if w_dir.exists():
                remove_dir_safely(w_dir)
                cleaned_count += 1
        st.toast(f"Cleaned cache from {cleaned_count} job(s)!")
        st.rerun()

    with t_col2.expander("⚠️ Danger Zone: Delete Everything"):
        st.warning("This will permanently delete ALL clip jobs and videos from your `clips/` folder.")
        confirm_del_all = st.checkbox("I understand this cannot be undone", key="confirm_del_all")
        if st.button("🗑️ Permanently Delete All Video History", type="secondary", use_container_width=True, disabled=not confirm_del_all):
            for j in all_jobs:
                remove_dir_safely(j["path"])
            st.session_state["clips"] = []
            st.session_state["clip_bytes"] = {}
            st.session_state["out_folder"] = ""
            st.toast("All video history and files have been deleted!")
            st.rerun()

    st.divider()

    if not all_jobs:
        st.info("🎉 No saved video jobs found! Your storage is clean.")
    else:
        st.markdown(f"#### Past Jobs ({len(all_jobs)})")

        for idx, job in enumerate(all_jobs):
            with st.expander(
                f"📁 {job['display_name']} — {job['title'][:60]}... ({len(job['mp4_files'])} clips • {format_size(job['total_size'])})",
                expanded=(idx == 0)
            ):
                # Job Header Actions
                hdr_col1, hdr_col2, hdr_col3 = st.columns([3, 1.5, 1.5])
                hdr_col1.markdown(f"**Source / Title:** {job['title']}")
                hdr_col1.caption(f"📁 Folder: `{job['path'].name}` • 💾 Clips: {format_size(job['clips_size'])} • Cache: {format_size(job['work_size'])}")

                # Clean Cache button for this specific job
                if job["has_work"]:
                    if hdr_col2.button("🧹 Free Cache", key=f"free_cache_{job['folder_name']}", use_container_width=True, help="Delete source video to save space"):
                        remove_dir_safely(job["path"] / "_work")
                        st.toast(f"Cache cleared for {job['display_name']}")
                        st.rerun()
                else:
                    hdr_col2.button("🧹 Cache Clean", key=f"cache_clean_{job['folder_name']}", use_container_width=True, disabled=True)

                # Delete Entire Job button
                if hdr_col3.button("🗑️ Delete Job", key=f"del_job_{job['folder_name']}", type="secondary", use_container_width=True, help="Permanently delete this entire job folder and all its videos"):
                    remove_dir_safely(job["path"])
                    if st.session_state.get("out_folder") == str(job["path"].resolve()):
                        st.session_state["clips"] = []
                        st.session_state["clip_bytes"] = {}
                        st.session_state["out_folder"] = ""
                    st.toast(f"Deleted job {job['folder_name']} from disk.")
                    st.rerun()

                st.write("")

                # List individual clips inside this job
                if not job["mp4_files"]:
                    st.write("_No video clips in this folder._")
                else:
                    clip_cols = st.columns(min(len(job["mp4_files"]), 3))
                    for c_idx, mp4_file in enumerate(job["mp4_files"]):
                        meta = job["clips_meta"].get(mp4_file.name, {})
                        col_target = clip_cols[c_idx % len(clip_cols)]

                        with col_target:
                            st.markdown(f"**{meta.get('title', mp4_file.stem)}**")
                            if meta.get("start") is not None and meta.get("end") is not None:
                                st.caption(f"⏱️ {meta['start']}s - {meta['end']}s • {format_size(get_path_size(mp4_file))}")
                            else:
                                st.caption(f"💾 {format_size(get_path_size(mp4_file))}")

                            # Read video bytes for rendering and downloading
                            clip_data = mp4_file.read_bytes()
                            st.video(clip_data, format="video/mp4")

                            d_btn_col, del_btn_col = st.columns([2, 1])
                            d_btn_col.download_button(
                                label="⬇️ Download",
                                data=clip_data,
                                file_name=mp4_file.name,
                                mime="video/mp4",
                                key=f"hist_dl_{job['folder_name']}_{mp4_file.name}",
                                use_container_width=True,
                            )
                            if del_btn_col.button("🗑️", key=f"hist_del_{job['folder_name']}_{mp4_file.name}", help="Delete this clip only", use_container_width=True):
                                remove_file_safely(mp4_file)
                                remove_file_safely(mp4_file.with_suffix(".srt"))
                                st.toast(f"Deleted {mp4_file.name}")
                                st.rerun()

