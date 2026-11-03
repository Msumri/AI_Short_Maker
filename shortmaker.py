import os
import json
import re
import numpy as np
from moviepy import VideoFileClip,ColorClip, CompositeVideoClip
from moviepy.video.fx import Crop
from openai import OpenAI
from datetime import datetime
import subprocess
import platform

def get_accelerated_codec():
    current_os = platform.system()
    
    # 1. Apple Mac Users (Always works natively out of the box)
    if current_os == "Darwin":
        return "h264_videotoolbox"
        
    # 2. Windows Users (Detect NVIDIA or AMD universally)
    elif current_os == "Windows":
        try:
            # Querying via PowerShell is built into all modern Windows PCs and highly accurate
            cmd = "powershell -Command \"Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name\""
            gpu_info = subprocess.check_output(cmd, shell=True, text=True).lower()
            
            if "nvidia" in gpu_info:
                return "h264_nvenc"
            elif "amd" in gpu_info or "radeon" in gpu_info:
                return "h264_amf"
        except Exception:
            pass
            
    # 3. Linux Users
    elif current_os == "Linux":
        try:
            gpu_info = subprocess.check_output("lspci", shell=True, text=True).lower()
            if "nvidia" in gpu_info:
                return "h264_nvenc"
            elif "amd" in gpu_info or "ati" in gpu_info:
                return "h264_amf"
        except Exception:
            pass
            
    return "libx264" # Universal CPU Fallback
# --------------------------------------------------
# Video cutting
# --------------------------------------------------

# --------------------------------------------------
# Layout constants
# --------------------------------------------------

CAM_BAND_RATIO = 0.30

# Fallback webcam region, in source pixels. Bottom-left corner, which is
# where most gameplay overlays sit.
DEFAULT_CAM = {"x": 20, "y": 520, "w": 320, "h": 180}

# Fallback content region: the whole frame.
DEFAULT_CONTENT = {"x": 0, "y": 0, "w": 1280, "h": 720}


def cut_video_segment(
    input_file,
    output_file,
    start_time,
    end_time,
    layout_style,
    cam_region=None,
    content_region=None,
    band_ratio=None,
    cam_fit=None,
    content_fit=None,
    divisions=None,
    orientation="horizontal",
):
    target_width = 1080
    target_height = 1920
    codec = get_accelerated_codec()
    print(f"[INFO] Auto-detected Hardware Acceleration Codec: {codec}")
    with VideoFileClip(input_file) as video:
        # 1. Slice the clip in time
        cut_clip = video.subclipped(start_time, end_time)
        
        if layout_style =="Center Crop (9:16 Full Screen)":
            # 2. Extract dimensions using the new .size property: (width, height)
            clip_width, clip_height = cut_clip.size
            
            # 3. Calculate portrait width based on video height
            crop_width = int(clip_height * (9 / 16))
            
            # 4. Apply the Crop effect using the layout size attributes
            cropped_clip = cut_clip.with_effects([
                Crop(
                    x_center=clip_width / 2, 
                    y_center=clip_height / 2, 
                    width=crop_width, 
                    height=clip_height
                )
            ])
            # 5. Resize to explicit resolution using .resized()
            final_clip = cropped_clip.resized((target_width, target_height))
        elif layout_style == "Fit with Black Background (Letterbox)":
            resized_clip = cut_clip.resized(width=target_width)
                
            # 3. Create a blank vertical canvas (1080x1920) matching the subclip's exact duration
            background = ColorClip(
                size=(target_width, target_height), 
                color=(0, 0, 0), 
                duration=cut_clip.duration
            )
            
            # 4. Composite them together, telling the video clip to sit dead center
            # In MoviePy 2.0+, positioning is passed directly into the array layout configuration
            final_clip = CompositeVideoClip([
                background, 
                resized_clip.with_position("center")
            ])    
        elif layout_style == "Fit with White Background (Letterbox)":
            resized_clip = cut_clip.resized(width=target_width)
                
            # 3. Create a blank vertical canvas (1080x1920) matching the subclip's exact duration
            background = ColorClip(
                size=(target_width, target_height), 
                color=(255, 255, 255), 
                duration=cut_clip.duration
            )
            
            # 4. Composite them together, telling the video clip to sit dead center
            final_clip = CompositeVideoClip([
                background,
                resized_clip.with_position("center")
            ])
        elif layout_style == "Fit with Blurred Background":
            # Blurred copy of the frame fills the vertical canvas, with the
            # untouched frame centered on top of it.
            #
            # MoviePy 2.x has no GaussianBlur effect (only HeadBlur), so the
            # blur is applied per frame with PIL. image_transform hands the
            # frame over as a numpy array, so convert both ways.
            from PIL import Image, ImageFilter

            def blur_frame(frame):
                return np.asarray(
                    Image.fromarray(frame).filter(
                        ImageFilter.GaussianBlur(25)
                    )
                )

            clip_width, clip_height = cut_clip.size

            # Cover the canvas: scale so the shorter side fills the target.
            scale = max(
                target_width / clip_width,
                target_height / clip_height,
            )

            background = cut_clip.resized(scale).with_effects([
                Crop(
                    x_center=clip_width * scale / 2,
                    y_center=clip_height * scale / 2,
                    width=target_width,
                    height=target_height,
                )
            ]).image_transform(blur_frame)

            foreground = cut_clip.resized(width=target_width)

            final_clip = CompositeVideoClip([
                background,
                foreground.with_position("center"),
            ])
        elif layout_style == "Shorts with Cam (9:16)":
            # Recut the webcam and content regions out of the source and
            # stack them: webcam in the top band, content in the band below.
            # Both are scaled to FILL their band (cover + center crop) so no
            # black bars are left over.
            cam = cam_region or DEFAULT_CAM
            content_box = content_region or DEFAULT_CONTENT

            ratio = CAM_BAND_RATIO if band_ratio is None else band_ratio
            ratio = max(0.10, min(0.70, float(ratio)))

            top_h = int(target_height * ratio)
            top_h -= top_h % 2
            bottom_h = target_height - top_h

            clip_width, clip_height = cut_clip.size

            def cut_region(box):
                """Crop a region, clamped to the frame."""

                x = max(0, min(int(box["x"]), clip_width - 1))
                y = max(0, min(int(box["y"]), clip_height - 1))
                w = max(10, min(int(box["w"]), clip_width - x))
                h = max(10, min(int(box["h"]), clip_height - y))

                return cut_clip.with_effects([
                    Crop(x1=x, y1=y, width=w, height=h)
                ])

            def fit_band(box, band_w, band_h, fit):
                """
                Scale a region into a band.

                "fill" covers the band and crops the overflow (no bars).
                "fit" keeps the whole region inside, padding with black.
                """

                region = cut_region(box)
                rw, rh = region.size

                if (fit or "fill") == "fit":
                    scale = min(band_w / rw, band_h / rh)
                else:
                    scale = max(band_w / rw, band_h / rh)

                region = region.resized(scale)
                rw, rh = region.size

                if (fit or "fill") == "fit":
                    background = ColorClip(
                        size=(band_w, band_h),
                        color=(0, 0, 0),
                        duration=cut_clip.duration,
                    )
                    return CompositeVideoClip([
                        background,
                        region.with_position("center"),
                    ])

                return region.with_effects([
                    Crop(
                        x_center=rw / 2,
                        y_center=rh / 2,
                        width=band_w,
                        height=band_h,
                    )
                ])

            cam_clip = fit_band(cam, target_width, top_h, cam_fit)
            content_clip = fit_band(
                content_box, target_width, bottom_h, content_fit
            )

            background = ColorClip(
                size=(target_width, target_height),
                color=(0, 0, 0),
                duration=cut_clip.duration,
            )

            final_clip = CompositeVideoClip([
                background,
                cam_clip.with_position((0, 0)),
                content_clip.with_position((0, top_h)),
            ])
        elif layout_style == "Multi-Divisão 9:16":
            # Multi-division layout for vertical 9:16 videos
            final_clip = render_multi_division(
                cut_clip, target_width, target_height,
                divisions=divisions, orientation=orientation
            )
        else:
            # "Do Not Crop (Keep Original Aspect Ratio)" and any unknown value:
            # keep the original framing, only scale down if wider than target.
            clip_width, clip_height = cut_clip.size

            if clip_width > target_width:
                scaled = cut_clip.resized(width=target_width)
            else:
                scaled = cut_clip

            # H.264 encoders (h264_amf, h264_nvenc, libx264) reject odd
            # dimensions. Scaling 1920x1080 down to width 1080 yields an odd
            # height (607), so force both sides to be even.
            width, height = scaled.size
            width -= width % 2
            height -= height % 2

            if (width, height) != scaled.size:
                final_clip = scaled.resized((width, height))
            else:
                final_clip = scaled

        # 6. Extract bitrate safely
        # original_bitrate = f"{int(video.reader.bitrate / 1000)}k" if video.reader.bitrate else "5000k"
        
        ffmpeg_extra_params = ["-pix_fmt", "yuv420p"]

        # MoviePy always emits "-preset <preset>" before ffmpeg_params, so the
        # value must be valid for the selected encoder. h264_amf rejects
        # "medium" (it only accepts balanced/speed/quality/high_quality).
        preset = "medium"

        if codec == "h264_nvenc":
            ffmpeg_extra_params += ["-preset", "p4", "-tune", "hq"]
        elif codec == "h264_amf":
            preset = "speed"
            ffmpeg_extra_params += ["-quality", "speed"]
        elif codec == "h264_videotoolbox":
            preset = "medium"
            ffmpeg_extra_params += ["-realtime", "true"]
        # 7. Export the final short using your GooeyLogger
        final_clip.write_videofile(
            output_file,
            fps=video.fps,
            codec=codec,
            audio_codec="aac",
            preset=preset,
            #bitrate=original_bitrate,
            ffmpeg_params=ffmpeg_extra_params,
        )


# --------------------------------------------------
# Multi-Division Layout Rendering (CPU)
# --------------------------------------------------

def render_multi_division(
    clip, target_width, target_height, divisions=None, orientation="horizontal"
):
    """
    Render a multi-division layout for 9:16 vertical videos.
    
    Args:
        clip: Source VideoFileClip
        target_width: Output width (1080)
        target_height: Output height (1920)
        divisions: List of division configs with:
            - region: dict with x, y, w, h in source coordinates
            - fit: 'fill' or 'fit'
            - zoom: float (1.0 = no zoom)
            - pos_x: float (0.0 to 1.0)
            - pos_y: float (0.0 to 1.0)
        orientation: 'horizontal' (stacked vertically), 'vertical' (side by side), 'grid'
    
    Returns:
        CompositeVideoClip with all divisions composed
    """
    from moviepy import ColorClip, CompositeVideoClip
    from moviepy.video.fx import Crop
    
    if not divisions:
        # Fallback - return original clip centered
        bg = ColorClip(size=(target_width, target_height), color=(0, 0, 0), duration=clip.duration)
        return CompositeVideoClip([bg, clip.with_position("center")])
    
    num_divisions = len(divisions)
    if num_divisions == 0:
        bg = ColorClip(size=(target_width, target_height), color=(0, 0, 0), duration=clip.duration)
        return CompositeVideoClip([bg, clip.with_position("center")])
    
    clip_width, clip_height = clip.size
    
    # Calculate division sizes based on orientation
    if orientation == "horizontal":
        # Divisions stacked vertically (one above another)
        div_h = target_height // num_divisions
        div_h -= div_h % 2
        div_w = target_width
        positions = [(0, i * div_h) for i in range(num_divisions)]
        sizes = [(div_w, div_h) for _ in range(num_divisions)]
    elif orientation == "vertical":
        # Divisions side by side horizontally
        div_w = target_width // num_divisions
        div_w -= div_w % 2
        div_h = target_height
        positions = [(i * div_w, 0) for i in range(num_divisions)]
        sizes = [(div_w, div_h) for _ in range(num_divisions)]
    else:  # grid
        # Calculate grid dimensions
        cols = int(num_divisions ** 0.5)
        if cols * cols < num_divisions:
            cols += 1
        rows = (num_divisions + cols - 1) // cols
        
        div_w = target_width // cols
        div_w -= div_w % 2
        div_h = target_height // rows
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
    
    # Create black background
    background = ColorClip(
        size=(target_width, target_height),
        color=(0, 0, 0),
        duration=clip.duration,
    )
    
    clips_to_composite = [background]
    
    def cut_region(box):
        """Crop a region, clamped to the frame."""
        x = max(0, min(int(box["x"]), clip_width - 1))
        y = max(0, min(int(box["y"]), clip_height - 1))
        w = max(10, min(int(box["w"]), clip_width - x))
        h = max(10, min(int(box["h"]), clip_height - y))
        return clip.with_effects([Crop(x1=x, y1=y, width=w, height=h)])
    
    for i, (div, (x, y), (w, h)) in enumerate(zip(divisions, positions, sizes)):
        region = div.get("region", DEFAULT_CONTENT)
        fit = div.get("fit", "fill")
        zoom = div.get("zoom", 1.0)
        pos_x = div.get("pos_x", 0.5)
        pos_y = div.get("pos_y", 0.5)
        
        # Apply zoom by cropping a smaller region
        if zoom != 1.0:
            new_w = int(region['w'] / zoom)
            new_h = int(region['h'] / zoom)
            offset_x = int((region['w'] - new_w) * pos_x)
            offset_y = int((region['h'] - new_h) * pos_y)
            region = {
                'x': region['x'] + offset_x,
                'y': region['y'] + offset_y,
                'w': new_w,
                'h': new_h
            }
        
        # Cut the region from source
        region_clip = cut_region(region)
        rw, rh = region_clip.size
        
        # Scale to fit the division
        if fit == "fit":
            scale = min(w / rw, h / rh)
        else:  # fill
            scale = max(w / rw, h / rh)
        
        region_clip = region_clip.resized(scale)
        rw, rh = region_clip.size
        
        if fit == "fit":
            # Center in the division with black bars
            div_bg = ColorClip(size=(w, h), color=(0, 0, 0), duration=clip.duration)
            positioned = CompositeVideoClip([
                div_bg,
                region_clip.with_position("center"),
            ])
        else:
            # Crop to fill the division (center crop)
            positioned = region_clip.with_effects([
                Crop(
                    x_center=rw / 2,
                    y_center=rh / 2,
                    width=w,
                    height=h,
                )
            ])
        
        clips_to_composite.append(positioned.with_position((x, y)))
    
    return CompositeVideoClip(clips_to_composite)


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
    layout_style,
    cam_region=None,
    content_region=None,
    band_ratio=None,
    cam_fit=None,
    content_fit=None,
    divisions=None,
    orientation="horizontal",
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
            layout_style,
            cam_region=cam_region,
            content_region=content_region,
            band_ratio=band_ratio,
            cam_fit=cam_fit,
            content_fit=content_fit,
            divisions=divisions,
            orientation=orientation,
        )


if __name__ == "__main__":

    print(
        "This script is intended to be "
        "imported and used as a module."
    )