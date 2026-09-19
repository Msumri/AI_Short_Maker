import os
import json
import re
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

def cut_video_segment(input_file, output_file, start_time, end_time, layout_style):
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
       
    
        
        
        # 6. Extract bitrate safely
        # original_bitrate = f"{int(video.reader.bitrate / 1000)}k" if video.reader.bitrate else "5000k"
        
        ffmpeg_extra_params = ["-pix_fmt", "yuv420p"]
        if codec == "h264_nvenc":
            ffmpeg_extra_params += ["-preset", "p4", "-tune", "hq"]
        elif codec == "h264_amf":
            ffmpeg_extra_params += ["-quality", "speed"]
        elif codec == "h264_videotoolbox":
            ffmpeg_extra_params += ["-realtime", "true"]
        # 7. Export the final short using your GooeyLogger
        final_clip.write_videofile(
            output_file,
            fps=video.fps, 
            codec=codec,
            audio_codec="aac",
            #bitrate=original_bitrate,
            ffmpeg_params=ffmpeg_extra_params,
        )
# --------------------------------------------------
# Timestamp
# --------------------------------------------------

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


# --------------------------------------------------
# Validate segments
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

    if len(segments) != expected_segments:
        raise ValueError(
            f"Expected {expected_segments} segments, "
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

        if duration > max_duration:
            raise ValueError(
                f"Segment {i} is too long: "
                f"{duration}s. "
                f"Maximum is {max_duration}s."
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

def cut_videos(video_segments,video_path, layout_style ):
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
            f"{seg['start_time']} → "
            f"{seg['end_time']}",
            flush=True
        )

        cut_video_segment(
            video_path,
            output_name,
            seg["start_time"],
            seg["end_time"],
            layout_style 
        )


if __name__ == "__main__":

    print(
        "This script is intended to be "
        "imported and used as a module."
    )