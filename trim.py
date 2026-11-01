"""
Trim unwanted ranges out of a video, and remap script timestamps to match.

The point of the remap: the AI picks segment times by reading the script,
and the script describes the ORIGINAL video. Once ranges are removed, every
timestamp after a cut shifts earlier. Without remapping, the AI would pick
moments that no longer line up with the trimmed video.

Ranges are half-open [start, end) in seconds. They must not overlap.
"""

import os
import re
import shutil
import subprocess


# ============================================================
# RANGE HANDLING
# ============================================================

def normalize_ranges(ranges, duration=None):
    """
    Validate and sort cut ranges.

    Accepts a list of dicts with "start" and "end" in seconds, or a list of
    (start, end) tuples. Returns a sorted list of (start, end) tuples with
    overlaps rejected.
    """

    cleaned = []

    for item in ranges or []:

        if isinstance(item, dict):
            pair = (item.get("start"), item.get("end"))
        else:
            try:
                pair = (item[0], item[1])
            except (TypeError, IndexError):
                raise ValueError(
                    "Each cut must have a start and an end."
                )

        try:
            start = float(pair[0])
            end = float(pair[1])

        except (TypeError, ValueError):
            raise ValueError(
                "Each cut must have a numeric start and end."
            )

        if start < 0:
            raise ValueError("Cut start cannot be negative.")

        if end <= start:
            raise ValueError(
                "Cut end must be greater than its start."
            )

        if duration is not None and start >= duration:
            raise ValueError(
                "Cut start is past the end of the video."
            )

        if duration is not None:
            end = min(end, duration)

        cleaned.append((start, end))

    cleaned.sort()

    for i in range(1, len(cleaned)):
        if cleaned[i][0] < cleaned[i - 1][1]:
            raise ValueError(
                "Cuts cannot overlap. Merge them into one."
            )

    return cleaned


def kept_ranges(ranges, duration):
    """
    Invert cut ranges into the ranges that survive.

    Returns a list of (start, end) tuples covering everything not cut.
    """

    cuts = normalize_ranges(ranges, duration)
    kept = []
    cursor = 0.0

    for start, end in cuts:
        if start > cursor:
            kept.append((cursor, start))
        cursor = max(cursor, end)

    if cursor < duration:
        kept.append((cursor, duration))

    return kept


def trim_plan(ranges, duration):
    """
    Describe the result of applying the cuts.

    Returns a dict with the kept ranges, the new total duration, and the
    mapping needed to translate original times into trimmed times.
    """

    cuts = normalize_ranges(ranges, duration)
    kept = kept_ranges(cuts, duration)

    new_duration = sum(end - start for start, end in kept)

    return {
        "cuts": cuts,
        "kept": kept,
        "new_duration": new_duration,
        "removed": duration - new_duration,
    }


# ============================================================
# TIME REMAPPING
# ============================================================

def remap_time(t, kept):
    """
    Translate a time in the original video to the trimmed video.

    Returns None when the time falls inside a removed range, since it has
    no equivalent in the trimmed video.
    """

    offset = 0.0

    for start, end in kept:
        if t < start:
            # Falls in a gap that was cut away.
            return None

        if t <= end:
            return t - start + offset

        offset += end - start

    return None


def remap_timestamp(timestamp, kept):
    """
    Remap an "HH:MM:SS" / "MM:SS" / "SS" timestamp, keeping the format.

    Returns None if the timestamp lands inside a removed range.
    """

    seconds = timestamp_to_seconds(timestamp)
    moved = remap_time(seconds, kept)

    if moved is None:
        return None

    return seconds_to_timestamp(moved)


def timestamp_to_seconds(timestamp):
    """Parse HH:MM:SS, MM:SS or SS into seconds."""

    parts = str(timestamp).strip().split(":")

    if len(parts) > 3:
        raise ValueError(f"Invalid timestamp: {timestamp}")

    try:
        values = [int(p.strip()) for p in parts]

    except ValueError:
        raise ValueError(f"Invalid timestamp: {timestamp}")

    while len(values) < 3:
        values.insert(0, 0)

    hours, minutes, seconds = values

    return hours * 3600 + minutes * 60 + seconds


def seconds_to_timestamp(seconds):
    """Format seconds as HH:MM:SS."""

    total = int(round(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)

    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


# ============================================================
# SCRIPT REMAPPING
# ============================================================

# Matches "[01:12]" or "[1:12:30]" at the start of a line.
MARKER_RE = re.compile(
    r"^\s*\[\s*(\d{1,2}(?::\d{1,2}){1,2})\s*\]"
)


def remap_script(text, kept):
    """
    Rewrite the timestamps in a script so they match the trimmed video.

    Lines whose marker falls inside a removed range are dropped, since that
    part of the video no longer exists. Returns (new_text, dropped_count).
    """

    out = []
    dropped = 0

    for line in text.splitlines():

        match = MARKER_RE.match(line)

        if not match:
            out.append(line)
            continue

        original = match.group(1)
        moved = remap_timestamp(original, kept)

        if moved is None:
            dropped += 1
            continue

        out.append(
            line[: match.start(1)] + moved + line[match.end(1):]
        )

    return "\n".join(out), dropped


# ============================================================
# RENDERING THE TRIM
# ============================================================

def get_ffmpeg():
    """Locate FFmpeg, preferring PATH."""

    ffmpeg = shutil.which("ffmpeg")

    if ffmpeg:
        return ffmpeg

    raise FileNotFoundError(
        "FFmpeg was not found. Please install FFmpeg."
    )


def trim_video(input_path, output_path, ranges, duration=None,
               progress=None):
    """
    Write a copy of the video with the given ranges removed.

    Uses FFmpeg's trim/atrim plus concat, so the result is a single
    continuous file. Re-encodes on the AMD/NVIDIA/CPU encoder when
    available, falling back to libx264.
    """

    if duration is None:
        duration = probe_duration(input_path)

    plan = trim_plan(ranges, duration)

    if not plan["cuts"]:
        shutil.copyfile(input_path, output_path)
        return plan

    ffmpeg = get_ffmpeg()

    # Build "trim each kept range, then concat" in one pass.
    parts = []
    concat_inputs = []

    for i, (start, end) in enumerate(plan["kept"]):
        parts.append(
            f"[0:v]trim=start={start:.3f}:end={end:.3f},"
            f"setpts=PTS-STARTPTS[v{i}];"
            f"[0:a]atrim=start={start:.3f}:end={end:.3f},"
            f"asetpts=PTS-STARTPTS[a{i}]"
        )
        concat_inputs.append(f"[v{i}][a{i}]")

    filter_complex = (
        ";".join(parts)
        + ";"
        + "".join(concat_inputs)
        + f"concat=n={len(plan['kept'])}:v=1:a=1[outv][outa]"
    )

    command = [
        ffmpeg,
        "-y",
        "-i",
        input_path,
        "-filter_complex",
        filter_complex,
        "-map",
        "[outv]",
        "-map",
        "[outa]",
    ]

    command += encoder_args()
    command += [
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        output_path,
    ]

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        bufsize=1,
    )

    for line in process.stdout:
        if progress and line.startswith("frame="):
            progress(line.strip())

    process.wait()

    if process.returncode != 0:
        raise RuntimeError(
            f"FFmpeg failed while trimming (exit {process.returncode})."
        )

    return plan


def encoder_args():
    """Pick the fastest available H.264 encoder."""

    try:
        import shortmakergpu

        gpu = shortmakergpu.detect_gpu()

    except Exception:
        gpu = "cpu"

    if gpu == "nvidia":
        return ["-c:v", "h264_nvenc", "-preset", "p1", "-b:v", "8M"]

    if gpu == "amd":
        return ["-c:v", "h264_amf", "-quality", "speed", "-b:v", "8M"]

    if gpu == "videotoolbox":
        return ["-c:v", "h264_videotoolbox", "-b:v", "8M"]

    return ["-c:v", "libx264", "-preset", "medium", "-crf", "18"]


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
            "Could not read the duration of the selected video."
        )
