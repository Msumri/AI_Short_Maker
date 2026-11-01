"""
Transcribe a video's audio into a timestamped script.

The point: the AI picks segment times by reading a script, and a script
written by hand can only describe what is visible. A transcript records
what is actually said, with real timestamps, which is what the model needs
to place cuts accurately.

Uses whisper.cpp through pywhispercpp. It runs on the CPU and works on
older chips: faster-whisper's CTranslate2 backend requires AVX-512
instructions that Broadwell-era Xeons (E5 v4) do not have, and fails at
load time with "HW capability found ... but HW capability requested".
"""

import os
import re
import shutil
import subprocess


# Model sizes, smallest first. Larger is more accurate and slower.
MODELS = ["tiny", "base", "small", "medium", "large-v3"]

# Rough guide, so the caller can warn before a long job.
SPEED_HINT = {
    "tiny": "fastest, least accurate",
    "base": "fast, okay for clear speech",
    "small": "balanced",
    "medium": "slow, better on accents",
    "large-v3": "slowest, best quality",
}


def get_ffmpeg():
    """Locate FFmpeg, preferring PATH."""

    ffmpeg = shutil.which("ffmpeg")

    if ffmpeg:
        return ffmpeg

    raise FileNotFoundError(
        "FFmpeg was not found. Please install FFmpeg."
    )


def extract_audio(video_path, audio_path, sample_rate=16000):
    """
    Pull the audio track out as mono 16 kHz WAV.

    Whisper works at 16 kHz internally, so resampling here avoids doing it
    again per chunk and keeps the temporary file small.
    """

    ffmpeg = get_ffmpeg()

    command = [
        ffmpeg,
        "-y",
        "-i",
        video_path,
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-c:a",
        "pcm_s16le",
        audio_path,
    ]

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Could not extract audio from the video. "
            "Does it have an audio track?\n"
            + result.stderr[-500:]
        )

    return audio_path


def load_model(size="base", threads=None):
    """
    Load a whisper.cpp model.

    Returns (model, thread_count). The model is downloaded on first use
    and cached by pywhispercpp.
    """

    from pywhispercpp.model import Model

    if size not in MODELS:
        raise ValueError(
            f"Unknown model '{size}'. Choose one of: "
            + ", ".join(MODELS)
        )

    n_threads = threads or max(4, (os.cpu_count() or 4) // 2)

    model = Model(
        size,
        n_threads=n_threads,
        print_realtime=False,
        print_progress=False,
    )

    return model, n_threads


def format_timestamp(seconds):
    """Format seconds as HH:MM:SS."""

    total = max(0, int(round(seconds)))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)

    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def probe_duration(path):
    """Return the duration of a media file in seconds."""

    ffmpeg = get_ffmpeg()
    ffprobe = shutil.which("ffprobe")

    if not ffprobe:
        candidate = os.path.join(
            os.path.dirname(ffmpeg), "ffprobe.exe"
        )
        ffprobe = candidate if os.path.exists(candidate) else ffmpeg

    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        return float(result.stdout.strip())

    except ValueError:
        raise RuntimeError(
            "Could not read the duration of the audio."
        )


def slice_audio(audio_path, start, duration, out_path):
    """Write a slice of a WAV file, without re-encoding."""

    ffmpeg = get_ffmpeg()

    result = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-ss",
            str(start),
            "-t",
            str(duration),
            "-i",
            audio_path,
            "-c",
            "copy",
            out_path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Could not slice the audio.\n" + result.stderr[-400:]
        )

    return out_path


def transcribe(
    video_path,
    model_size="base",
    language=None,
    on_progress=None,
    keep_audio=False,
    chunk_seconds=300,
):
    """
    Transcribe a video and return a list of segments.

    Each segment is a dict with start, end and text. `language=None` lets
    Whisper detect it, which is right for a mixed-language stream.

    The audio is transcribed in chunks rather than in one pass. Over a long
    recording Whisper accumulates error and eventually loops, repeating the
    last phrase it managed to process and never recovering, which corrupts
    everything after that point. Chunks of a few minutes keep each pass
    short enough that this does not happen.

    `on_progress(count, end_seconds)` is called as segments arrive.
    """

    if not os.path.exists(video_path):
        raise FileNotFoundError(video_path)

    work_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "transcripts"
    )
    os.makedirs(work_dir, exist_ok=True)

    base = os.path.splitext(os.path.basename(video_path))[0]
    audio_path = os.path.join(work_dir, f"{base}.wav")

    if not os.path.exists(audio_path):
        print("[WHISPER] extracting audio...", flush=True)
        extract_audio(video_path, audio_path)

    total = probe_duration(audio_path)

    model, threads = load_model(model_size)

    print(
        f"[WHISPER] model={model_size} device=cpu threads={threads} "
        f"audio={format_timestamp(total)} "
        f"chunks of {chunk_seconds}s",
        flush=True,
    )

    out = []
    offset = 0.0
    chunk_index = 0
    chunk_path = os.path.join(work_dir, f"{base}_chunk.wav")

    while offset < total:

        length = min(chunk_seconds, total - offset)

        if length < 1:
            break

        chunk_index += 1

        print(
            f"[WHISPER] chunk {chunk_index} "
            f"({format_timestamp(offset)} +{length:.0f}s)",
            flush=True,
        )

        slice_audio(audio_path, offset, length, chunk_path)

        raw = model.transcribe(
            chunk_path,
            language=language or "pt",
            translate=False,
        )

        for seg in raw:
            text = seg.text.strip()

            if not text:
                continue

            out.append(
                {
                    "start": offset + seg.t0 / 100.0,
                    "end": offset + seg.t1 / 100.0,
                    "text": text,
                }
            )

            if on_progress:
                on_progress(len(out), offset + seg.t1 / 100.0)

        offset += length

    try:
        os.remove(chunk_path)
    except OSError:
        pass

    if not keep_audio:
        try:
            os.remove(audio_path)
        except OSError:
            pass

    return out, None


def _normalize(text):
    """Lowercase and strip punctuation, for comparison only."""

    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def collapse_repeats(text, min_repeat=3):
    """
    Collapse a phrase repeated back to back inside one line.

    Whisper loops on music, silence and noise, producing lines such as
    "Olha o bot, mano. Olha o bot, mano. Olha o bot, mano." The repeated
    phrase carries no extra meaning, so one copy is kept.

    Two shapes are handled: plain sentences separated by punctuation, and
    quoted phrases, which Whisper also emits when it loops ("a." "a." "a.").

    Returns (cleaned_text, removed_count).
    """

    text = text.strip()

    if not text:
        return text, 0

    # Quoted repeats: '"x." "x." "x."' -> '"x."'
    quoted = re.findall(r'"([^"]*)"', text)

    if len(quoted) >= min_repeat:
        keys = [_normalize(q) for q in quoted]
        keys = [k for k in keys if k]

        if keys and len(set(keys)) == 1:
            # Everything inside quotes is the same phrase.
            outside = re.sub(r'"[^"]*"', "", text).strip()
            kept = f'"{quoted[0]}"'
            return (
                (outside + " " + kept).strip() if outside else kept,
                len(quoted) - 1,
            )

    # Plain repeats: split on sentence punctuation.
    parts = re.split(r"(?<=[.!?])\s+", text)

    if len(parts) < min_repeat:
        return text, 0

    kept = []
    removed = 0
    i = 0

    while i < len(parts):

        run = 1
        key = _normalize(parts[i])

        while (
            i + run < len(parts)
            and key
            and _normalize(parts[i + run]) == key
        ):
            run += 1

        kept.append(parts[i])

        if run >= min_repeat:
            removed += run - 1

        i += run

    return " ".join(kept), removed


def dedupe_segments(segments):
    """
    Drop segments whose text repeats the previous one.

    Returns (kept_segments, dropped_count).
    """

    kept = []
    dropped = 0

    for seg in segments:
        key = _normalize(seg["text"])

        if not key:
            dropped += 1
            continue

        if kept and _normalize(kept[-1]["text"]) == key:
            # Same content again; extend the previous span instead.
            kept[-1]["end"] = seg["end"]
            dropped += 1
            continue

        kept.append(dict(seg))

    return kept, dropped


def clean_segments(segments, min_repeat=3):
    """
    Remove Whisper's repetition loops from a transcript.

    Two passes: collapse phrases repeated inside a single segment, then
    drop whole segments that repeat the one before. Returns the cleaned
    list plus a summary of what was removed.
    """

    stats = {"inner": 0, "segments": 0}

    collapsed = []

    for seg in segments:
        text, removed = collapse_repeats(seg["text"], min_repeat)

        if removed:
            stats["inner"] += removed

        if not _normalize(text):
            stats["segments"] += 1
            continue

        item = dict(seg)
        item["text"] = text
        collapsed.append(item)

    kept, dropped = dedupe_segments(collapsed)
    stats["segments"] += dropped

    return kept, stats


def build_script(segments, title="", max_chars=180, gap=2.0, clean=True):
    """
    Turn transcript segments into a script the AI can read.

    Consecutive lines are merged while they stay short and close together,
    so the script is a readable list of moments rather than one line per
    Whisper segment.

    With `clean`, the repetition loops Whisper produces on music and noise
    are removed first. Returns (text, line_count, stats).
    """

    stats = {"inner": 0, "segments": 0}

    if clean:
        segments, stats = clean_segments(segments)

    lines = []
    buffer = None

    for seg in segments:

        if buffer is None:
            buffer = dict(seg)
            continue

        close = seg["start"] - buffer["end"] <= gap
        short = len(buffer["text"]) + len(seg["text"]) <= max_chars

        if close and short:
            buffer["text"] = buffer["text"] + " " + seg["text"]
            buffer["end"] = seg["end"]
        else:
            lines.append(buffer)
            buffer = dict(seg)

    if buffer is not None:
        lines.append(buffer)

    out = []

    if title:
        out.append(title.strip())
        out.append("")

    for line in lines:
        stamp = format_timestamp(line["start"])
        out.append(f"[{stamp}] {line['text']}")

    return "\n".join(out) + "\n", len(lines), stats


def save_script(text, video_path, suffix="_transcript"):
    """Write the script next to the project and return its path."""

    base = os.path.splitext(os.path.basename(video_path))[0]
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", base).strip("_")[:60]

    path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        f"script_{safe}{suffix}.txt",
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write(text)

    return path


def transcribe_to_script(
    video_path,
    model_size="base",
    language=None,
    title="",
    on_progress=None,
    keep_audio=False,
    clean=True,
):
    """
    Convenience wrapper: transcribe a video and write a script file.

    Returns (script_path, line_count, stats).
    """

    segments, _ = transcribe(
        video_path,
        model_size=model_size,
        language=language,
        on_progress=on_progress,
        keep_audio=keep_audio,
    )

    text, count, stats = build_script(
        segments, title=title, clean=clean
    )

    path = save_script(text, video_path)

    return path, count, stats
