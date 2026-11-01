"""
Split a script into time blocks and generate shorts for each one.

Why blocks: a model given a long transcript and asked for dozens of
segments at once loses track and starts repeating itself. On a 2h42min
transcript the 8B model returned a 340 KB response that was one segment
repeated 861 times, and the JSON did not even parse. The same model, given
a 15-minute slice, answers normally.

Splitting also lets the work be shown as it happens: each block produces
its shorts, which can be reviewed and rendered while the rest run.
"""

import re


# Matches "[01:12]" or "[1:12:30]" at the start of a line.
MARKER_RE = re.compile(
    r"^\s*\[\s*(\d{1,2}(?::\d{1,2}){1,2})\s*\]\s*(.*)$"
)


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

    total = max(0, int(round(seconds)))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)

    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def parse_script(text):
    """
    Read a script into (seconds, line) pairs.

    Lines without a leading marker are kept as context but carry no time,
    so they are attached to the line before them.
    """

    entries = []
    pending = []

    for raw in text.splitlines():

        match = MARKER_RE.match(raw)

        if not match:
            if raw.strip():
                pending.append(raw.strip())
            continue

        try:
            start = timestamp_to_seconds(match.group(1))

        except ValueError:
            continue

        body = match.group(2).strip()

        if pending:
            body = " ".join(pending + [body])
            pending = []

        entries.append((start, f"[{seconds_to_timestamp(start)}] {body}"))

    return entries


def split_into_blocks(text, block_seconds=900):
    """
    Split a script into blocks of roughly `block_seconds`.

    Returns a list of dicts with the block's start, end and text. A block
    boundary falls on the first marker at or past the target time, so no
    line is ever split in half.
    """

    entries = parse_script(text)

    if not entries:
        return []

    blocks = []
    current = []
    block_start = entries[0][0]
    target_end = block_start + block_seconds

    for start, line in entries:

        if current and start >= target_end:
            blocks.append(
                {
                    "start": block_start,
                    "end": start,
                    "text": "\n".join(current),
                }
            )
            current = []
            block_start = start
            target_end = block_start + block_seconds

        current.append(line)

    if current:
        last = entries[-1][0] + 1
        blocks.append(
            {
                "start": block_start,
                "end": last,
                "text": "\n".join(current),
            }
        )

    return blocks


def build_prompt(block, min_shorts, max_shorts,
                 min_duration, max_duration):
    """
    Build the prompt for one block.

    The model is given a range rather than an exact count: it cannot always
    find the requested number of good moments inside one block, and forcing
    an exact count makes it pad with weak segments or repeat itself.
    """

    return f"""You are selecting YouTube Shorts from part of a transcript
of a live stream.

This is ONE BLOCK of a longer video, covering
{seconds_to_timestamp(block['start'])} to
{seconds_to_timestamp(block['end'])}.

Create between {min_shorts} and {max_shorts} short-form video segments
from this block.

Each segment should be interesting, self-contained, and suitable for a
YouTube Short. Prefer the strongest moments; do not pad the list.

IMPORTANT:

Return ONLY valid JSON.

Do NOT use Markdown.

Do NOT use ```json.

Do NOT include explanations.

Do NOT include comments.

Do NOT include text before or after the JSON.

Every segment must have a DIFFERENT title.

Each segment MUST be between {min_duration} and {max_duration} seconds.

Use timestamps in HH:MM:SS format, taken from the block below.

The end_time must be later than start_time.

The script_excerpt must contain the actual portion of the supplied
transcript corresponding to the segment.

Return this structure:

{{
    "segments": [
        {{
            "start_time": "00:00:00",
            "end_time": "00:00:30",
            "title": "Example Title",
            "script_excerpt": "Actual transcript excerpt"
        }}
    ]
}}

TRANSCRIPT BLOCK:

{block['text']}
"""


def looks_repetitive(segments, threshold=0.6):
    """
    True when most segments share the same title.

    A model that has lost track repeats one segment instead of selecting
    several. Catching that here gives a clear message rather than a JSON
    parse error thousands of lines later.
    """

    if len(segments) < 3:
        return False

    titles = [
        str(s.get("title", "")).strip().lower() for s in segments
    ]

    if not titles:
        return False

    most = max(titles.count(t) for t in set(titles))

    return most / len(titles) >= threshold


def clamp_segment(segment, block, min_duration, max_duration):
    """
    Force one segment inside the block and inside the duration limits.

    Returns the adjusted segment, or None when it cannot be made valid.
    """

    try:
        start = timestamp_to_seconds(segment["start_time"])
        end = timestamp_to_seconds(segment["end_time"])

    except (KeyError, ValueError):
        return None

    # Keep the segment inside its block, so a block never claims a moment
    # that belongs to another one.
    start = max(start, int(block["start"]))
    end = min(end, int(block["end"]))

    if end <= start:
        return None

    if end - start > max_duration:
        end = start + max_duration

    if end - start < min_duration:
        return None

    out = dict(segment)
    out["start_time"] = seconds_to_timestamp(start)
    out["end_time"] = seconds_to_timestamp(end)

    return out
