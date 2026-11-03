import os
import json
import re
from openai import OpenAI
from datetime import datetime
import subprocess
import shutil

import platform




def get_ffmpeg_path():
    """
    Find FFmpeg regardless of whether it is in PATH.
    """

    # First try PATH
    ffmpeg = shutil.which("ffmpeg")

    if ffmpeg:
        print(f"[FFMPEG] Found in PATH: {ffmpeg}", flush=True)
        return ffmpeg

    # Windows WinGet installation
    if platform.system() == "Windows":
        winget_path = os.path.expandvars(
            r"%LOCALAPPDATA%\Microsoft\WinGet\Packages"
        )

        print(f"[FFMPEG] Searching: {winget_path}", flush=True)

        if os.path.exists(winget_path):
            for root, dirs, files in os.walk(winget_path):
                if "ffmpeg.exe" in files:
                    ffmpeg = os.path.join(root, "ffmpeg.exe")

                    print(
                        f"[FFMPEG] Found: {ffmpeg}",
                        flush=True
                    )

                    return ffmpeg

    raise FileNotFoundError(
        "FFmpeg was not found. Please install FFmpeg."
    )


def detect_gpu():
    """
    Detect the available GPU/platform and return a pipeline name.
    """

    system = platform.system()

    print(f"[GPU] Operating System: {system}", flush=True)

    # ---------------------------------------------------------
    # MAC
    # ---------------------------------------------------------

    if system == "Darwin":
        print(
            "[GPU] Using Apple VideoToolbox",
            flush=True
        )

        return "videotoolbox"

    # ---------------------------------------------------------
    # WINDOWS
    # ---------------------------------------------------------

    if system == "Windows":

        try:
            command = [
                "powershell",
                "-Command",
                "Get-CimInstance Win32_VideoController | "
                "Select-Object -ExpandProperty Name"
            ]

            gpu_info = subprocess.check_output(
                command,
                text=True,
                stderr=subprocess.DEVNULL
            ).lower()

            print(
                f"[GPU] Detected GPU:\n{gpu_info}",
                flush=True
            )

            # NVIDIA
            if "nvidia" in gpu_info:

                print(
                    "[GPU] NVIDIA detected -> CUDA/NVENC",
                    flush=True
                )

                return "nvidia"

            # AMD
            if "amd" in gpu_info or "radeon" in gpu_info:

                print(
                    "[GPU] AMD detected -> AMF",
                    flush=True
                )

                return "amd"

        except Exception as e:

            print(
                f"[GPU] Detection failed: {e}",
                flush=True
            )

    # ---------------------------------------------------------
    # LINUX
    # ---------------------------------------------------------

    if system == "Linux":

        try:

            gpu_info = subprocess.check_output(
                ["lspci"],
                text=True,
                stderr=subprocess.DEVNULL
            ).lower()

            print(
                f"[GPU] Detected GPU:\n{gpu_info}",
                flush=True
            )

            if "nvidia" in gpu_info:

                print(
                    "[GPU] NVIDIA detected -> CUDA/NVENC",
                    flush=True
                )

                return "nvidia"

            if "amd" in gpu_info or "ati" in gpu_info:

                print(
                    "[GPU] AMD detected",
                    flush=True
                )

                return "amd"

        except Exception as e:

            print(
                f"[GPU] Detection failed: {e}",
                flush=True
            )

    # ---------------------------------------------------------
    # CPU FALLBACK
    # ---------------------------------------------------------

    print(
        "[GPU] No supported GPU detected -> CPU",
        flush=True
    )

    return "cpu"


def timestamp_to_seconds(timestamp):

    parts = timestamp.split(":")

    if len(parts) != 3:
        raise ValueError(
            f"Invalid timestamp: {timestamp}"
        )

    hours, minutes, seconds = map(int, parts)

    if minutes >= 60 or seconds >= 60:
        raise ValueError(
            f"Invalid timestamp: {timestamp}"
        )

    return (
        hours * 3600
        + minutes * 60
        + seconds
    )


# ---------------------------------------------------------
# Layouts
# ---------------------------------------------------------

OUTPUT_WIDTH = 1080
OUTPUT_HEIGHT = 1920

LAYOUT_ORIGINAL = "original"
LAYOUT_CROP = "crop"
LAYOUT_BLUR = "blur"
LAYOUT_CAM = "cam"
LAYOUT_LETTERBOX_BLACK = "letterbox_black"
LAYOUT_LETTERBOX_WHITE = "letterbox_white"

# Fraction of the output height used by the webcam band.
CAM_BAND_RATIO = 0.30

# Fallback webcam region, in source pixels, used when the caller does not
# supply one. Bottom-left corner, which is where most gameplay overlays sit.
DEFAULT_CAM = {"x": 20, "y": 520, "w": 320, "h": 180}

# Fallback content region: the whole frame.
DEFAULT_CONTENT = {"x": 0, "y": 0, "w": 1280, "h": 720}

# Colour handling. The source is bt709 limited-range; without these the
# filter graph emits yuvj420p full-range and the output looks washed out
# and blue-tinted.
COLOR_PARAMS = [
    "-pix_fmt", "yuv420p",
    "-color_range", "tv",
    "-colorspace", "bt709",
    "-color_primaries", "bt709",
    "-color_trc", "bt709",
]

LAYOUT_MULTI = "multi"

# Maps the labels shown in the UI to the internal layout names.
LAYOUT_MAP = {
    "Do Not Crop (Keep Original Aspect Ratio)": LAYOUT_ORIGINAL,
    "Center Crop (9:16 Full Screen)": LAYOUT_CROP,
    "Shorts with Cam (9:16)": LAYOUT_CAM,
    "Multi-Divisão 9:16": LAYOUT_MULTI,
}


def normalize_layout(layout):
    """Accept a UI label or an internal name; return an internal name."""

    if not layout:
        return LAYOUT_ORIGINAL

    if layout in LAYOUT_MAP:
        return LAYOUT_MAP[layout]

    if layout in (
        LAYOUT_ORIGINAL,
        LAYOUT_CROP,
        LAYOUT_CAM,
        LAYOUT_MULTI,
    ):
        return layout

    raise ValueError(f"Unknown layout: {layout}")


# How a region is fitted into its band.
#   fill -> scale to cover the band, cropping the overflow (no black bars)
#   fit  -> scale to fit inside the band, adding black bars (nothing cropped)
FIT_FILL = "fill"
FIT_CONTAIN = "fit"

FIT_MAP = {
    "Fill (may crop)": FIT_FILL,
    "Fit (may add bars)": FIT_CONTAIN,
}


def normalize_fit(fit):
    """Accept a UI label or an internal name; return an internal name."""

    if not fit:
        return FIT_FILL

    if fit in FIT_MAP:
        return FIT_MAP[fit]

    if fit in (FIT_FILL, FIT_CONTAIN):
        return fit

    return FIT_FILL


def _fit_chain(dst_w, dst_h, fit):
    """FFmpeg chain that scales a stream into a dst_w x dst_h box."""

    if normalize_fit(fit) == FIT_CONTAIN:
        return (
            f"scale={dst_w}:{dst_h}"
            f":force_original_aspect_ratio=decrease,"
            f"pad={dst_w}:{dst_h}:(ow-iw)/2:(oh-ih)/2:color=black"
        )

    return (
        f"scale={dst_w}:{dst_h}"
        f":force_original_aspect_ratio=increase,"
        f"crop={dst_w}:{dst_h}"
    )


def _merge_box(default, override):
    """Overlay a user-supplied region on top of the default one."""

    box = dict(default)

    if override:
        box.update(
            {
                key: value
                for key, value in override.items()
                if value is not None
            }
        )

    return box


def build_video_filter(
    layout,
    cam=None,
    content=None,
    band_ratio=None,
    cam_fit=None,
    content_fit=None,
    divisions=None,
    orientation="horizontal",
):
    """
    Build the FFmpeg filter graph for a layout.

    Returns (filter_complex, output_label). For the passthrough layout both
    are None, meaning the input stream is mapped straight through, which is
    the fastest path and keeps the original resolution.
    """

    layout = normalize_layout(layout)

    if band_ratio is None:
        band_ratio = CAM_BAND_RATIO

    # Keep the band within sane limits and even, so the encoder accepts it.
    band_ratio = max(0.10, min(0.70, float(band_ratio)))

    if layout == LAYOUT_ORIGINAL:
        return None, None

    if layout == LAYOUT_CROP:
        return (
            f"[0:v]scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}"
            f":force_original_aspect_ratio=increase,"
            f"crop={OUTPUT_WIDTH}:{OUTPUT_HEIGHT},"
            f"setsar=1[out]",
            "[out]",
        )

    if layout == LAYOUT_LETTERBOX_BLACK:
        return (
            f"[0:v]scale={OUTPUT_WIDTH}:-2,setsar=1[fg];"
            f"color=c=black:s={OUTPUT_WIDTH}x{OUTPUT_HEIGHT}:r=30,format=yuv420p[bg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2[out]",
            "[out]",
        )

    if layout == LAYOUT_LETTERBOX_WHITE:
        return (
            f"[0:v]scale={OUTPUT_WIDTH}:-2,setsar=1[fg];"
            f"color=c=white:s={OUTPUT_WIDTH}x{OUTPUT_HEIGHT}:r=30,format=yuv420p[bg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2[out]",
            "[out]",
        )

    if layout == LAYOUT_BLUR:
        return (
            f"[0:v]scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}"
            f":force_original_aspect_ratio=increase,"
            f"crop={OUTPUT_WIDTH}:{OUTPUT_HEIGHT},"
            f"gblur=sigma=25,eq=brightness=-0.15,setsar=1[bg];"
            f"[0:v]scale={OUTPUT_WIDTH}:-2,setsar=1[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2[out]",
            "[out]",
        )

    if layout == LAYOUT_CAM:

        cam_box = _merge_box(DEFAULT_CAM, cam)
        content_box = _merge_box(DEFAULT_CONTENT, content)

        top_h = int(OUTPUT_HEIGHT * band_ratio)
        top_h -= top_h % 2
        bottom_h = OUTPUT_HEIGHT - top_h

        return (
            # Webcam: cut the region out, then fit it into the top band.
            f"[0:v]crop={cam_box['w']}:{cam_box['h']}"
            f":{cam_box['x']}:{cam_box['y']},"
            f"{_fit_chain(OUTPUT_WIDTH, top_h, cam_fit)},setsar=1[cam];"
            # Content: cut its region out, then fit it into the bottom band.
            f"[0:v]crop={content_box['w']}:{content_box['h']}"
            f":{content_box['x']}:{content_box['y']},"
            f"{_fit_chain(OUTPUT_WIDTH, bottom_h, content_fit)},setsar=1[content];"
            # Compose onto a vertical canvas.
            f"color=c=black:s={OUTPUT_WIDTH}x{OUTPUT_HEIGHT}"
            f":r=30,format=yuv420p[bg];"
            f"[bg][cam]overlay=0:0:format=auto[t1];"
            f"[t1][content]overlay=0:{top_h}:format=auto,"
            f"format=yuv420p[out]",
            "[out]",
        )

    if layout == LAYOUT_MULTI:
        return build_multi_division_filter(
            cam, content, band_ratio, cam_fit, content_fit, divisions, orientation
        )

    raise ValueError(f"Unknown layout: {layout}")


def build_multi_division_filter(
    cam=None,
    content=None,
    band_ratio=None,
    cam_fit=None,
    content_fit=None,
    divisions=None,
    orientation="horizontal",
):
    """
    Build FFmpeg filter graph for Multi-Divisão 9:16 layout.
    
    Args:
        divisions: List of division configs, each containing:
            - source: 'cam', 'content', or a video file path
            - region: dict with x, y, w, h in source coordinates
            - fit: 'fill' or 'fit'
            - zoom: float (1.0 = no zoom)
            - pos_x: float (0.0 to 1.0) for horizontal offset within division
            - pos_y: float (0.0 to 1.0) for vertical offset within division
        orientation: 'horizontal' (stacked vertically), 'vertical' (side by side), 'grid'
    
    Returns:
        (filter_complex, output_label) tuple
    """
    if not divisions:
        # Fallback to simple cam layout if no divisions
        return build_video_filter(
            LAYOUT_CAM, cam, content, band_ratio, cam_fit, content_fit
        )
    
    num_divisions = len(divisions)
    if num_divisions == 0:
        return build_video_filter(
            LAYOUT_CAM, cam, content, band_ratio, cam_fit, content_fit
        )
    
    # Calculate division sizes based on orientation
    if orientation == "horizontal":
        # Divisions stacked vertically (one above another)
        div_h = OUTPUT_HEIGHT // num_divisions
        div_h -= div_h % 2  # Ensure even
        div_w = OUTPUT_WIDTH
        positions = [(0, i * div_h) for i in range(num_divisions)]
        sizes = [(div_w, div_h) for _ in range(num_divisions)]
    elif orientation == "vertical":
        # Divisions side by side horizontally
        div_w = OUTPUT_WIDTH // num_divisions
        div_w -= div_w % 2  # Ensure even
        div_h = OUTPUT_HEIGHT
        positions = [(i * div_w, 0) for i in range(num_divisions)]
        sizes = [(div_w, div_h) for _ in range(num_divisions)]
    else:  # grid
        # Calculate grid dimensions
        cols = int(num_divisions ** 0.5)
        if cols * cols < num_divisions:
            cols += 1
        rows = (num_divisions + cols - 1) // cols
        
        div_w = OUTPUT_WIDTH // cols
        div_w -= div_w % 2
        div_h = OUTPUT_HEIGHT // rows
        div_h -= div_h % 2
        
        positions = []
        sizes = []
        for i in range(num_divisions):
            row = i // cols
            col = i % cols
            x = col * div_w
            y = row * div_h
            positions.append((x, y))
            sizes.append((div_w, div_h))
    
    # Build filter complex
    filter_parts = []
    overlay_chain = []
    
    # Create black background
    filter_parts.append(
        f"color=c=black:s={OUTPUT_WIDTH}x{OUTPUT_HEIGHT}:r=30,format=yuv420p[bg]"
    )
    last_overlay = "[bg]"
    
    for i, (div, (x, y), (w, h)) in enumerate(zip(divisions, positions, sizes)):
        source_type = div.get("source", "content")
        region = div.get("region", DEFAULT_CONTENT if source_type == "content" else DEFAULT_CAM)
        fit = div.get("fit", "fill")
        zoom = div.get("zoom", 1.0)
        pos_x = div.get("pos_x", 0.5)  # Center by default
        pos_y = div.get("pos_y", 0.5)
        
        # Build crop and scale for this division
        crop_str = f"crop={region['w']}:{region['h']}:{region['x']}:{region['y']}"
        
        # Apply zoom by scaling the crop region
        if zoom != 1.0:
            # Zoom by cropping a smaller region from the center
            new_w = int(region['w'] / zoom)
            new_h = int(region['h'] / zoom)
            offset_x = int((region['w'] - new_w) * pos_x)
            offset_y = int((region['h'] - new_h) * pos_y)
            crop_str = f"crop={new_w}:{new_h}:{region['x'] + offset_x}:{region['y'] + offset_y}"
        
        # Build fit chain
        fit_chain = _fit_chain(w, h, fit)
        
        # Input stream label
        input_label = f"[0:v]"
        
        # Division output label
        div_label = f"[div{i}]"
        
        filter_parts.append(
            f"{input_label}{crop_str},{fit_chain},setsar=1{div_label}"
        )
        
        # Overlay onto canvas
        overlay_label = f"[ov{i}]"
        filter_parts.append(
            f"{last_overlay}{div_label}overlay={x}:{y}:format=auto{overlay_label}"
        )
        last_overlay = overlay_label
    
    # Final output
    filter_parts.append(f"{last_overlay}format=yuv420p[out]")
    
    filter_complex = ";".join(filter_parts)
    return filter_complex, "[out]"


def cut_video_segment(
    input_file,
    output_file,
    start_time,
    end_time,
    layout=None,
    cam=None,
    content=None,
    band_ratio=None,
    cam_fit=None,
    content_fit=None,
    divisions=None,
    orientation="horizontal",
    preview_mode=False,
    preview_duration=None,
):
    ffmpeg = get_ffmpeg_path()
    gpu_type = detect_gpu()

    start_seconds = timestamp_to_seconds(start_time)
    end_seconds = timestamp_to_seconds(end_time)
    duration = end_seconds - start_seconds

    # Preview mode: use shorter duration, lower quality, smaller resolution
    if preview_mode and preview_duration:
        duration = min(preview_duration, duration)
        target_width = 480
        target_height = 854
        video_bitrate = "1M"
        preset = "p1"  # Fastest for NVIDIA
        cpu_preset = "ultrafast"
        crf = "28"
    else:
        target_width = 1080
        target_height = 1920
        video_bitrate = "8M"
        preset = "p1"
        cpu_preset = "medium"
        crf = "18"

    if duration <= 0:
        raise ValueError(
            f"Invalid segment duration: "
            f"{start_time} -> {end_time}"
        )

    print(
        f"\n[GPU] Selected pipeline: {gpu_type}" + (" (PREVIEW MODE)" if preview_mode else ""),
        flush=True
    )

    # ---------------------------------------------------------
    # Build command
    # ---------------------------------------------------------

    command = [
        ffmpeg,
        "-y",
    ]

    # NVIDIA
    if gpu_type == "nvidia":
        command += [
            "-hwaccel",
            "cuda",
            "-hwaccel_output_format",
            "cuda",
        ]

    # Mac
    elif gpu_type == "videotoolbox":
        command += [
            "-hwaccel",
            "videotoolbox",
        ]

    # ---------------------------------------------------------
    # Input / cutting
    # ---------------------------------------------------------

    command += [
        "-ss",
        start_time,

        "-i",
        input_file,

        "-t",
        str(duration),
    ]

    # ---------------------------------------------------------
    # Video filter (layout)
    # ---------------------------------------------------------

    filter_complex, output_label = build_video_filter(
        layout, cam, content, band_ratio, cam_fit, content_fit,
        divisions=divisions, orientation=orientation
    )

    # Add scale filter for preview mode to reduce resolution
    if preview_mode and filter_complex:
        # Append scale to the filter complex
        filter_complex = filter_complex.replace(
            "[out]",
            f"scale={target_width}:{target_height}:flags=lanczos[out]"
        )

    if filter_complex:

        print(
            f"[GPU] Layout: {normalize_layout(layout)}" + (" (PREVIEW MODE)" if preview_mode else ""),
            flush=True
        )

        command += [
            "-filter_complex",
            filter_complex,
            "-map",
            output_label,
            "-map",
            "0:a?",
        ]

    else:

        # -----------------------------------------------------
        # NO VIDEO FILTER (original resolution passthrough)
        # -----------------------------------------------------

        if preview_mode:
            # Add scale filter for preview mode
            command += [
                "-vf",
                f"scale={target_width}:{target_height}:flags=lanczos",
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
            ]
        else:
            command += [
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
            ]

    # ---------------------------------------------------------
    # Video encoder
    # ---------------------------------------------------------

    if gpu_type == "nvidia":

        command += [
            "-c:v",
            "h264_nvenc",
            "-preset",
            preset,  # p1 for preview, p1 for normal (fastest)
            "-b:v",
            video_bitrate,
        ]

    elif gpu_type == "videotoolbox":

        command += [
            "-c:v",
            "h264_videotoolbox",
            "-b:v",
            video_bitrate,
        ]

    elif gpu_type == "amd":

        command += [
            "-c:v",
            "h264_amf",
            "-quality",
            "speed",
            "-b:v",
            video_bitrate,
        ]

    else:

        command += [
            "-c:v",
            "libx264",
            "-preset",
            cpu_preset,  # ultrafast for preview, medium for normal
            "-crf",
            crf,  # 28 for preview, 18 for normal
        ]

    # ---------------------------------------------------------
    # Colour metadata
    # ---------------------------------------------------------

    # Only needed when a filter graph ran; the passthrough path already
    # carries the source's own colour metadata.
    if filter_complex:
        command += COLOR_PARAMS

    # ---------------------------------------------------------
    # Audio + progress
    # ---------------------------------------------------------

    command += [
        "-c:a",
        "aac",
        "-b:a",
        "192k",

        "-progress",
        "pipe:1",
        "-nostats",

        output_file,
    ]

    # ---------------------------------------------------------
    # Print command
    # ---------------------------------------------------------

    print("\n[FFMPEG] Starting:", flush=True)

    print(
        " ".join(
            f'"{x}"' if " " in x else x
            for x in command
        ),
        flush=True
    )

    # ---------------------------------------------------------
    # Run FFmpeg
    # ---------------------------------------------------------

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        bufsize=1,
    )

    last_percent = -1
    ffmpeg_output = []

    for line in process.stdout:

        line = line.strip()

        if not line:
            continue

        ffmpeg_output.append(line)

        if len(ffmpeg_output) > 100:
            ffmpeg_output.pop(0)

        # ---------------------------------------------
        # FFmpeg progress
        # ---------------------------------------------

        if line.startswith("out_time_ms="):

            try:
                out_time_us = int(
                    line.split("=", 1)[1]
                )

                current_seconds = (
                    out_time_us / 1_000_000
                )

                percent = int(
                    min(
                        100,
                        (
                            current_seconds
                            / duration
                        ) * 100
                    )
                )

                if percent != last_percent:

                    print(
                        f"chunk: {percent}%",
                        flush=True
                    )

                    last_percent = percent

            except ValueError:
                pass

    process.wait()

    # ---------------------------------------------------------
    # Error handling
    # ---------------------------------------------------------

    if process.returncode != 0:

        print(
            "\n[FFMPEG ERROR]",
            flush=True
        )

        print(
            "\n".join(ffmpeg_output),
            flush=True
        )

        raise RuntimeError(
            f"FFmpeg failed with exit code "
            f"{process.returncode}"
        )

    print(
        "chunk: 100%",
        flush=True
    )

    print(
        f"[FFMPEG] Finished: {output_file}",
        flush=True
    ) 
# --------------------------------------------------
# Timestamp
# --------------------------------------------------

def timestamp_to_seconds(timestamp):
    """
    Convert a timestamp to seconds.

    Accepts HH:MM:SS, MM:SS and SS. AI models frequently answer with the
    shorter MM:SS form, especially when the source script is written that
    way (e.g. "[01:12] ..."), so all three forms are accepted.
    """

    if isinstance(timestamp, (int, float)):
        return int(timestamp)

    parts = str(timestamp).strip().split(":")

    if len(parts) > 3:
        raise ValueError(
            f"Invalid timestamp: {timestamp}"
        )

    try:
        values = [int(part.strip()) for part in parts]

    except ValueError:
        raise ValueError(
            f"Invalid timestamp: {timestamp}"
        )

    if any(value < 0 for value in values):
        raise ValueError(
            f"Invalid timestamp: {timestamp}"
        )

    # Left-pad so that "SS" -> [0, 0, s] and "MM:SS" -> [0, m, s]
    while len(values) < 3:
        values.insert(0, 0)

    hours, minutes, seconds = values

    if minutes >= 60 or seconds >= 60:
        raise ValueError(
            f"Invalid timestamp: {timestamp}"
        )

    return (
        hours * 3600
        + minutes * 60
        + seconds
    )


# --------------------------------------------------
# Validate segments
def seconds_to_timestamp(seconds):
    """Format seconds as HH:MM:SS."""

    total = max(0, int(round(seconds)))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)

    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


# --------------------------------------------------

def validate_segments(
    data,
    expected_segments,
    min_duration,
    max_duration
):

    if not isinstance(data, dict):
        raise ValueError(
            "Response is not a JSON object."
        )

    if "segments" not in data:
        raise ValueError(
            "Missing 'segments'."
        )

    segments = data["segments"]

    if not isinstance(segments, list):
        raise ValueError(
            "'segments' must be an array."
        )

    # Models rarely hit an exact count. Rejecting a good batch over one
    # extra segment wastes a whole request, so allow a margin and use
    # whatever came back.
    if not segments:
        raise ValueError("The response contained no segments.")

    lower = max(1, int(expected_segments * 0.8))
    upper = max(lower, int(expected_segments * 1.2) + 1)

    if not (lower <= len(segments) <= upper):
        raise ValueError(
            f"Expected around {expected_segments} segments, "
            f"got {len(segments)}."
        )

    for i, segment in enumerate(segments):

        if not isinstance(segment, dict):
            raise ValueError(
                f"Segment {i} is not an object."
            )

        required = [
            "start_time",
            "end_time",
            "title",
            "script_excerpt"
        ]

        for field in required:

            if field not in segment:
                raise ValueError(
                    f"Segment {i} is missing "
                    f"'{field}'."
                )

        start = timestamp_to_seconds(
            segment["start_time"]
        )

        end = timestamp_to_seconds(
            segment["end_time"]
        )

        duration = end - start

        if duration < min_duration:
            raise ValueError(
                f"Segment {i} is too short: "
                f"{duration}s. "
                f"Minimum is {min_duration}s."
            )

        # A model that ignores the upper bound is common when the script
        # has sparse markers. Trim the segment instead of failing the run.
        if duration > max_duration:
            print(
                f"[AI] Segment {i} is {duration}s, over the "
                f"{max_duration}s limit; trimming it.",
                flush=True,
            )
            segment["end_time"] = seconds_to_timestamp(
                start + max_duration
            )

        if not segment["title"].strip():
            raise ValueError(
                f"Segment {i}: title is empty."
            )

        if not segment["script_excerpt"].strip():
            raise ValueError(
                f"Segment {i}: script_excerpt "
                f"is empty."
            )

    return segments


# --------------------------------------------------
# Extract JSON
# --------------------------------------------------

def clean_json(content):

    content = content.strip()

    if content.startswith("```"):

        content = re.sub(
            r"^```(?:json)?\s*",
            "",
            content,
            flags=re.IGNORECASE
        )

        content = re.sub(
            r"\s*```$",
            "",
            content
        )

    return content.strip()


# --------------------------------------------------
# Generate script cuts
# --------------------------------------------------

def get_script(
    script_file_path,
    num_segments=10,
    model="openrouter/free",
    API_KEY=None,
    min_duration=15,
    max_duration=60
):

    print(
        "\n[AI] Generating script cuts...",
        flush=True
    )

    print(
        f"[AI] Model: {model}",
        flush=True
    )

    print(
        f"[AI] Number of shorts: {num_segments}",
        flush=True
    )

    print(
        f"[AI] Duration: "
        f"{min_duration}-{max_duration}s",
        flush=True
    )

    # --------------------------------------------------
    # Client
    # --------------------------------------------------

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=API_KEY
    )

    # --------------------------------------------------
    # Read script
    # --------------------------------------------------

    with open(
        script_file_path,
        "r",
        encoding="utf-8"
    ) as file:

        script_content = file.read()

    print(
        f"[AI] Script loaded: "
        f"{len(script_content)} characters",
        flush=True
    )

    # --------------------------------------------------
    # Prompt
    # --------------------------------------------------

    prompt = f"""
You are selecting YouTube Shorts from a
long-form YouTube video script.

Create exactly {num_segments} short-form
video segments.

Each segment should be interesting,
self-contained, and suitable for a
YouTube Short.

IMPORTANT:

Return ONLY valid JSON.

Do NOT use Markdown.

Do NOT use ```json.

Do NOT include explanations.

Do NOT include comments.

Do NOT include text before or after
the JSON.

Return exactly {num_segments} segments.

Each segment MUST be between
{min_duration} and {max_duration} seconds.

Use timestamps in HH:MM:SS format.

The end_time must be later than start_time.

The title should be short and compelling.

The script_excerpt must contain the
actual portion of the supplied script
corresponding to the segment.

Return this structure:

{{
    "segments": [
        {{
            "start_time": "00:00:00",
            "end_time": "00:00:30",
            "title": "Example Title",
            "script_excerpt": "Actual script excerpt"
        }}
    ]
}}

SCRIPT:

{script_content}
"""

    # --------------------------------------------------
    # OpenRouter request
    # --------------------------------------------------

    print(
        "\n[AI] Sending request to OpenRouter...",
        flush=True
    )

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0.2
    )

    print(
        "[AI] OpenRouter response received!",
        flush=True
    )

    # --------------------------------------------------
    # Get content
    # --------------------------------------------------

    content = response.choices[0].message.content

    if not content:
        raise RuntimeError(
            "OpenRouter returned an empty response."
        )

    print(
        f"[AI] Response length: "
        f"{len(content)} characters",
        flush=True
    )

    # --------------------------------------------------
    # Clean JSON
    # --------------------------------------------------

    content = clean_json(content)

    # --------------------------------------------------
    # Parse
    # --------------------------------------------------

    try:

        data = json.loads(content)

    except json.JSONDecodeError as e:

        print(
            "\nAI returned invalid JSON:"
        )

        print(content)

        raise RuntimeError(
            f"Could not parse AI response: {e}"
        )

    # --------------------------------------------------
    # Validate
    # --------------------------------------------------

    video_segments = validate_segments(
        data,
        expected_segments=num_segments,
        min_duration=min_duration,
        max_duration=max_duration
    )

    # --------------------------------------------------
    # Print
    # --------------------------------------------------

    print(
        "\n[AI] Generated segments:",
        flush=True
    )

    print(
        json.dumps(
            video_segments,
            indent=2,
            ensure_ascii=False
        ),
        flush=True
    )

    # --------------------------------------------------
    # Save
    # --------------------------------------------------

    os.makedirs(
        "scripts",
        exist_ok=True
    )
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    with open(
        f"scripts/output_script_{timestamp}.json",
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            video_segments,
            file,
            indent=2,
            ensure_ascii=False
        )

    print(
        f"\n[AI] Saved scripts/output_script_{timestamp}.json",
        flush=True
    )

    return video_segments


# --------------------------------------------------
# Cut videos
# --------------------------------------------------

def cut_videos(
    video_segments,
    video_path,
    layout=None,
    cam=None,
    content=None,
    band_ratio=None,
    cam_fit=None,
    content_fit=None,
):
    os.makedirs(
            "output",
            exist_ok=True
        )
    total = len(video_segments)

    for index, seg in enumerate(video_segments):

        clean_title = re.sub(
            r"[^a-zA-Z0-9_-]+",
            "_",
            seg["title"]
        ).strip("_").lower()

        output_name = (
            f"output/{clean_title}.mp4"
        )

        print(
            f"\n[{index + 1}/{total}] "
            f"Cutting '{seg['title']}'",
            flush=True
        )

        print(
            f"{seg['start_time']} -> "
            f"{seg['end_time']}",
            flush=True
        )

        cut_video_segment(
            video_path,
            output_name,
            seg["start_time"],
            seg["end_time"],
            layout=layout,
            cam=cam,
            content=content,
            band_ratio=band_ratio,
            cam_fit=cam_fit,
            content_fit=content_fit,
        )


if __name__ == "__main__":

    print(
        "This script is intended to be "
        "imported and used as a module."
    )