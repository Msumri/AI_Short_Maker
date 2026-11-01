import os
import io
import json
import asyncio
import hashlib
import shutil
import subprocess
import tkinter as tk
from tkinter import filedialog

import requests
from nicegui import ui, run, app, core
from fastapi import Response
from fastapi.responses import FileResponse

import shortmaker
import shortmakergpu
import trim

# Shared with the renderers so the picker and the renderers agree on the
# webcam defaults and the height of the webcam band.
DEFAULT_CAM = shortmakergpu.DEFAULT_CAM
DEFAULT_CONTENT = shortmakergpu.DEFAULT_CONTENT
CAM_BAND_RATIO = shortmakergpu.CAM_BAND_RATIO
OUTPUT_WIDTH = shortmakergpu.OUTPUT_WIDTH
OUTPUT_HEIGHT = shortmakergpu.OUTPUT_HEIGHT

# Height of the content band in the Shorts-with-Cam layout. The content
# region keeps this aspect ratio so it fills the band with no black bars.
CONTENT_BAND_HEIGHT = OUTPUT_HEIGHT - int(
    OUTPUT_HEIGHT * CAM_BAND_RATIO
)


# ============================================================
# PERSISTED CONFIG (kept in the browser, survives restarts)
# ============================================================

CONFIG_KEY = "shortmaker_config"

CONFIG_DEFAULTS = {
    "cam": dict(DEFAULT_CAM),
    "content": dict(DEFAULT_CONTENT),
    "cam_band_ratio": CAM_BAND_RATIO,
    "cam_fit": "fill",
    "content_fit": "fill",
    "layout": "Center Crop (9:16 Full Screen)",
    "use_ffmpeg": True,
    "shorts": 25,
    "duration": "15-60",
    "model": "openrouter/free",
}

# Regions and layout settings come from the persisted config. The dicts are
# mutated in place (never rebound) so every closure sees the same object.
# Assigned right after load_config() is defined, further down.


def load_config():
    """
    Read the saved configuration from the browser storage.

    Falls back to the defaults for anything missing, so a config saved by
    an older version keeps working after new keys are added.
    """

    # NiceGUI runs this module once at import, before the server (and
    # therefore the storage) exists. Stay quiet during that pass.
    if core.is_script_mode_preflight() or not app.is_started:
        return {
            key: (dict(value) if isinstance(value, dict) else value)
            for key, value in CONFIG_DEFAULTS.items()
        }

    saved = {}

    try:
        saved = app.storage.user.get(CONFIG_KEY, {}) or {}

    except Exception as e:
        print(f"[WARNING] Could not read browser storage: {e}")

    merged = {}

    for key, default in CONFIG_DEFAULTS.items():
        value = saved.get(key, default)

        if isinstance(default, dict):
            box = dict(default)
            if isinstance(value, dict):
                box.update(
                    {
                        k: v
                        for k, v in value.items()
                        if k in default
                    }
                )
            merged[key] = box
        else:
            merged[key] = value

    return merged


def save_config():
    """Write the current configuration to the browser storage."""

    if core.is_script_mode_preflight() or not app.is_started:
        return

    try:
        app.storage.user[CONFIG_KEY] = json.loads(
            json.dumps(config)
        )

    except Exception as e:
        print(f"[WARNING] Could not save browser storage: {e}")


# Load the persisted configuration now that load_config() exists.
config = load_config()

# ============================================================
# SETTINGS
# ============================================================

SETTINGS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "settings.json",
)


def load_settings():
    if not os.path.exists(SETTINGS_FILE):
        return {}

    try:
        with open(
            SETTINGS_FILE,
            "r",
            encoding="utf-8",
        ) as file:
            return json.load(file)

    except Exception as e:
        print(f"[WARNING] Could not load settings: {e}")
        return {}


def save_settings(settings):
    try:
        with open(
            SETTINGS_FILE,
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                settings,
                file,
                indent=4,
            )

    except Exception as e:
        print(f"[WARNING] Could not save settings: {e}")


settings = load_settings()
# ============================================================
# OPENROUTER MODELS
# ============================================================

def get_openrouter_models():
    try:
        response = requests.get(
            "https://openrouter.ai/api/v1/models",
            timeout=10,
        )
        response.raise_for_status()

        data = response.json()

        models = sorted(
            model["id"]
            for model in data.get("data", [])
            if "id" in model
        )

        if models:
            return models

    except Exception as e:
        print(f"[WARNING] Could not load OpenRouter models: {e}")

    return [
        "openrouter/free",
        "google/gemini-flash-1.5",
        "meta-llama/llama-3.1-8b-instruct",
        "openai/gpt-4o-mini",
        "anthropic/claude-3.5-sonnet",
    ]


OPENROUTER_MODELS = get_openrouter_models()


# ============================================================
# FILE STATE
# ============================================================

selected_video = ""
selected_script = ""
selected_json = ""

# Set once the user trims the source video. Everything downstream (AI
# generation, rendering) then works on this file instead of the original.
trimmed_video = ""
trim_plan = None

cam_region = config["cam"]
content_region = config["content"]


# ============================================================
# VIDEO TRIMMING
# ============================================================

def active_video():
    """
    The video everything downstream should use.

    Once the user trims, that file replaces the original for AI generation
    and rendering.
    """

    return trimmed_video or selected_video


def active_script():
    """
    The script the AI should read.

    After a trim the timestamps in the original script no longer match the
    video, so a remapped copy is produced on demand. This covers the case
    where the script is chosen after the trim was applied.
    """

    if not trim_plan or not selected_script:
        return selected_script

    if not os.path.exists(selected_script):
        return selected_script

    base = os.path.splitext(
        os.path.basename(selected_video)
    )[0]

    out_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "trimmed"
    )
    remapped = os.path.join(out_dir, f"{base}_trimmed_script.txt")

    # Rebuild whenever the source script is newer than the remapped copy.
    try:
        if (
            os.path.exists(remapped)
            and os.path.getmtime(remapped)
            >= os.path.getmtime(selected_script)
        ):
            return remapped

    except OSError:
        pass

    try:
        with open(selected_script, "r", encoding="utf-8") as f:
            text = f.read()

        new_text, dropped = trim.remap_script(text, trim_plan["kept"])

        os.makedirs(out_dir, exist_ok=True)

        with open(remapped, "w", encoding="utf-8") as f:
            f.write(new_text)

        print(
            f"[TRIM] Remapped script written to {remapped} "
            f"({dropped} line(s) dropped)",
            flush=True,
        )

        return remapped

    except Exception as e:
        print(f"[WARNING] Could not remap the script: {e}")
        return selected_script


def reset_trim():
    """Drop a previous trim, e.g. when a different video is chosen."""

    global trimmed_video, trim_plan

    if trimmed_video and os.path.exists(trimmed_video):
        try:
            os.remove(trimmed_video)
        except OSError:
            pass

    trimmed_video = ""
    trim_plan = None


def parse_timecode(text):
    """Parse HH:MM:SS, MM:SS or SS into seconds."""

    return trim.timestamp_to_seconds(text)


def format_timecode(seconds):
    """Format seconds as HH:MM:SS."""

    return trim.seconds_to_timestamp(seconds)


async def apply_trim(ranges, script_path=None):
    """
    Cut the selected ranges out of the video.

    Returns (ok, message). On success the trimmed file becomes the active
    video, and the script is rewritten so its timestamps still line up.
    """

    global trimmed_video, trim_plan

    source = selected_video

    if not source or not os.path.exists(source):
        return False, "Choose a video first."

    try:
        duration = await run.io_bound(trim.probe_duration, source)

    except Exception as e:
        return False, f"Could not read the video duration: {e}"

    try:
        plan = trim.trim_plan(ranges, duration)

    except ValueError as e:
        return False, str(e)

    if not plan["cuts"]:
        return False, "No cuts to apply."

    out_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "trimmed"
    )
    os.makedirs(out_dir, exist_ok=True)

    base = os.path.splitext(os.path.basename(source))[0]
    out_path = os.path.join(out_dir, f"{base}_trimmed.mp4")

    try:
        await run.io_bound(
            trim.trim_video, source, out_path, ranges, duration
        )

    except Exception as e:
        return False, f"Trimming failed: {e}"

    trimmed_video = out_path
    trim_plan = plan

    # Rewrite the script so its timestamps match the trimmed video.
    note = ""

    if script_path and os.path.exists(script_path):
        try:
            with open(script_path, "r", encoding="utf-8") as f:
                text = f.read()

            new_text, dropped = trim.remap_script(text, plan["kept"])

            trimmed_script = os.path.join(
                out_dir, f"{base}_trimmed_script.txt"
            )

            with open(trimmed_script, "w", encoding="utf-8") as f:
                f.write(new_text)

            note = (
                f" Script timestamps remapped"
                f"{f', {dropped} line(s) dropped' if dropped else ''}."
            )

        except Exception as e:
            note = f" (script remap failed: {e})"

    return True, (
        f"Trimmed: removed {plan['removed']:.1f}s, "
        f"new length {plan['new_duration']:.1f}s.{note}"
    )


# ============================================================
# MEDIA STREAMING (so the browser can play the local video)
# ============================================================

# NiceGUI re-executes this module for every client in script mode, so the
# token map and the route must live outside the module namespace or they
# would be rebuilt (and the route re-registered) on each connection.
if not hasattr(app, "_media_tokens"):
    app._media_tokens = {}

    @app.get("/media/{token}")
    def serve_media(token: str):
        """Stream a registered media file, with range support."""

        path = app._media_tokens.get(token)

        if not path or not os.path.exists(path):
            return Response(status_code=404)

        return FileResponse(path, media_type="video/mp4")


def media_url(path):
    """
    Register a local media file and return a URL the browser can play.

    Returns an empty string when there is nothing to serve.
    """

    if not path or not os.path.exists(path):
        return ""

    token = hashlib.sha1(
        os.path.abspath(path).encode("utf-8")
    ).hexdigest()[:16]

    app._media_tokens[token] = os.path.abspath(path)

    return f"/media/{token}"


# ============================================================
# FRAME EXTRACTION (for the webcam picker)
# ============================================================

def extract_frame(video_path, at_seconds=5):
    """
    Grab a single frame from the video and return it as a PIL image.

    Used by the webcam picker so the user chooses the region on a real
    frame instead of typing pixel numbers.
    """

    from PIL import Image

    ffmpeg = shutil.which("ffmpeg")

    if not ffmpeg:
        raise FileNotFoundError(
            "FFmpeg was not found. Please install FFmpeg."
        )

    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        str(at_seconds),
        "-i",
        video_path,
        "-frames:v",
        "1",
        "-f",
        "image2pipe",
        "-vcodec",
        "png",
        "-",
    ]

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    if result.returncode != 0 or not result.stdout:
        raise RuntimeError(
            "Could not read a frame from the selected video."
        )

    import io

    return Image.open(io.BytesIO(result.stdout)).convert("RGB")


# ============================================================
# NATIVE FILE PICKER
# ============================================================

def native_file_picker(title, filetypes):
    root = tk.Tk()
    root.withdraw()

    try:
        root.attributes("-topmost", True)

        return filedialog.askopenfilename(
            title=title,
            filetypes=filetypes,
        )

    finally:
        root.destroy()


# ============================================================
# FILE PICKERS
# ============================================================

def choose_video():
    global selected_video

    path = native_file_picker(
        "Choose Video",
        [
            (
                "Video Files",
                "*.mp4 *.avi *.mov *.mkv *.webm",
            ),
            ("All Files", "*.*"),
        ],
    )

    if path:
        # A new source video invalidates any previous trim.
        reset_trim()

        selected_video = path
        video_file.text = os.path.basename(path)
        video_file.tooltip = path
        update_process_button()

        try:
            refresh_trim_status()
        except NameError:
            pass

        set_status("Video selected.")


def choose_script():
    global selected_script

    path = native_file_picker(
        "Choose Script",
        [
            ("Text Files", "*.txt"),
            ("All Files", "*.*"),
        ],
    )

    if path:
        selected_script = path
        script_file.text = os.path.basename(path)
        script_file.tooltip = path
        update_process_button()


def choose_json():
    global selected_json

    path = native_file_picker(
        "Choose JSON Script",
        [
            ("JSON Files", "*.json"),
            ("All Files", "*.*"),
        ],
    )

    if path:
        selected_json = path
        json_file.text = os.path.basename(path)
        json_file.tooltip = path
        update_process_button()


# ============================================================
# UI STATE
# ============================================================

def toggle_json_mode():
    reuse = reuse_json.value

    if reuse:
        json_row.classes(remove="disabled-row")
        ai_row.classes(add="disabled-row")
        script_row.classes(add="disabled-row")
        short_settings_row.classes(add="disabled-row")

        mode_status.text = "Using existing JSON"

    else:
        json_row.classes(add="disabled-row")
        ai_row.classes(remove="disabled-row")
        script_row.classes(remove="disabled-row")
        short_settings_row.classes(remove="disabled-row")

        mode_status.text = "Generate with AI"

    update_process_button()


def toggle_ffmpeg():
    # Both renderers support the layout options now, so the selector stays
    # enabled either way. Only the help text changes.
    layout_select.enable()

    if ffmpeg_toggle.value:
        layout_help.text = "Layout is applied by the FFmpeg / GPU renderer."
        layout_help.classes(
            remove="layout-disabled",
            add="layout-ok",
        )
    else:
        layout_help.text = "Layout is available with the standard renderer."
        layout_help.classes(
            remove="layout-disabled",
            add="layout-ok",
        )


def update_process_button():
    if not selected_video:
        process_button.disable()
        return

    if reuse_json.value:
        if selected_json:
            process_button.enable()
        else:
            process_button.disable()
        return

    if (
        api_key.value.strip()
        and selected_script
    ):
        process_button.enable()
    else:
        process_button.disable()


def set_status(message, error=False):
    status_label.text = message

    if error:
        status_label.classes(
            remove="status-normal status-success",
            add="status-error",
        )
    else:
        status_label.classes(
            remove="status-error status-success",
            add="status-normal",
        )


def update_progress(percent, message=None):
    """
    NiceGUI expects progress as 0.0 - 1.0.
    The displayed value remains 0 - 100%.
    """

    percent = max(0, min(100, int(percent)))

    progress_bar.value = percent / 100.0
    progress_percent.text = f"{percent}%"

    if message:
        progress_status.text = message


# ============================================================
# DURATION
# ============================================================

def parse_duration(value):
    try:
        minimum, maximum = value.split("-")

        minimum = int(minimum.strip())
        maximum = int(maximum.strip())

        if minimum <= 0:
            raise ValueError()

        if maximum <= 0:
            raise ValueError()

        if minimum > maximum:
            raise ValueError()

        return minimum, maximum

    except Exception:
        raise ValueError(
            "Duration must be written as min-max, for example 15-60."
        )


def render_preview_image(frame, cam_box, content_box, band_ratio,
                         cam_fit=None, content_fit=None):
    """
    Compose a real preview of the output from a source frame.

    Crops the webcam and content regions out of the frame and fits them into
    their bands exactly like the renderers do, so what you see here is what
    the render will produce.
    """

    from PIL import Image

    out_w, out_h = OUTPUT_WIDTH, OUTPUT_HEIGHT

    top_h = int(out_h * band_ratio)
    top_h -= top_h % 2
    bottom_h = out_h - top_h

    src_w, src_h = frame.size

    def crop(box):
        x = max(0, min(int(box["x"]), src_w - 1))
        y = max(0, min(int(box["y"]), src_h - 1))
        w = max(10, min(int(box["w"]), src_w - x))
        h = max(10, min(int(box["h"]), src_h - y))
        return frame.crop((x, y, x + w, y + h))

    def fit(region, band_w, band_h, mode):
        rw, rh = region.size

        if (mode or "fill") == "fit":
            scale = min(band_w / rw, band_h / rh)
        else:
            scale = max(band_w / rw, band_h / rh)

        new_w = max(1, int(round(rw * scale)))
        new_h = max(1, int(round(rh * scale)))
        region = region.resize((new_w, new_h), Image.LANCZOS)

        band = Image.new("RGB", (band_w, band_h), (0, 0, 0))

        if (mode or "fill") == "fit":
            band.paste(
                region,
                ((band_w - new_w) // 2, (band_h - new_h) // 2),
            )
        else:
            left = (new_w - band_w) // 2
            top = (new_h - band_h) // 2
            band.paste(region.crop((
                left, top, left + band_w, top + band_h
            )), (0, 0))

        return band

    canvas = Image.new("RGB", (out_w, out_h), (0, 0, 0))

    canvas.paste(
        fit(crop(cam_box), out_w, top_h, cam_fit), (0, 0)
    )
    canvas.paste(
        fit(crop(content_box), out_w, bottom_h, content_fit),
        (0, top_h),
    )

    # Downscale for display; the browser does not need 1080x1920.
    return canvas.resize((270, 480), Image.LANCZOS)


# ============================================================
# REGION PICKER (webcam / content)
# ============================================================

async def pick_region(which):
    """
    Let the user position a region rectangle on a frame of the video.

    `which` is "cam" or "content".

    Webcam: the size is free, dragging draws a new rectangle.
    Content: the size is fixed (it must fill the band below the webcam), so
    dragging moves the rectangle instead of resizing it.

    Both offer alignment buttons and arrow-key nudging, like an image editor.
    """

    target = cam_region if which == "cam" else content_region
    label = "webcam" if which == "cam" else "content"
    fixed_size = which == "content"

    if not selected_video or not os.path.exists(selected_video):
        set_status(
            "Choose a video before selecting an area.",
            error=True,
        )
        return False

    try:
        frame = await run.io_bound(
            extract_frame, selected_video, 5
        )

    except Exception as e:
        set_status(
            f"Could not read a frame from the video: {e}",
            error=True,
        )
        return False

    img_w, img_h = frame.size

    # Work on a copy so cancelling leaves the saved region untouched.
    draft = {
        "x": max(0, min(target["x"], img_w - 1)),
        "y": max(0, min(target["y"], img_h - 1)),
        "w": max(10, min(target["w"], img_w)),
        "h": max(10, min(target["h"], img_h)),
    }

    if fixed_size:
        # The content band has a fixed aspect ratio, so the region must too.
        # Fit it to the full frame height (or width, whichever binds first).
        band_aspect = OUTPUT_WIDTH / CONTENT_BAND_HEIGHT

        w = int(round(img_h * band_aspect))
        h = img_h

        if w > img_w:
            w = img_w
            h = int(round(w / band_aspect))

        draft["w"] = w - (w % 2)
        draft["h"] = h - (h % 2)

    result = {"confirmed": False}
    drag = {"active": False, "dx": 0, "dy": 0}
    syncing = {"on": False}

    def clamp():
        draft["w"] = max(10, min(draft["w"], img_w))
        draft["h"] = max(10, min(draft["h"], img_h))
        draft["x"] = max(0, min(draft["x"], img_w - draft["w"]))
        draft["y"] = max(0, min(draft["y"], img_h - draft["h"]))

    def svg_content():
        x, y, w, h = (
            draft["x"],
            draft["y"],
            draft["w"],
            draft["h"],
        )
        return (
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" '
            f'fill="rgba(108,99,255,0.25)" '
            f'stroke="#6C63FF" stroke-width="3"/>'
        )

    def redraw():
        clamp()
        preview.content = svg_content()

        # Guard against the number inputs re-triggering on_manual_change.
        syncing["on"] = True
        x_in.value = draft["x"]
        y_in.value = draft["y"]
        w_in.value = draft["w"]
        h_in.value = draft["h"]
        syncing["on"] = False

    def on_drag(e):
        if e.type == "pointerdown" and e.button == 0:
            drag["active"] = True

            if fixed_size:
                # Move: remember the offset from the pointer to the corner.
                drag["dx"] = e.image_x - draft["x"]
                drag["dy"] = e.image_y - draft["y"]
            else:
                # Draw: start a new rectangle at the pointer.
                drag["dx"] = 0
                drag["dy"] = 0
                draft["x"] = int(e.image_x)
                draft["y"] = int(e.image_y)
                draft["w"] = 10
                draft["h"] = 10

        elif e.type == "pointermove" and drag["active"]:

            if fixed_size:
                draft["x"] = int(e.image_x - drag["dx"])
                draft["y"] = int(e.image_y - drag["dy"])
            else:
                x0, y0 = drag["dx"], drag["dy"]
                draft["x"] = int(min(x0, e.image_x))
                draft["y"] = int(min(y0, e.image_y))
                draft["w"] = int(abs(e.image_x - x0))
                draft["h"] = int(abs(e.image_y - y0))

        elif e.type == "pointerup":
            drag["active"] = False

        else:
            return

        redraw()

    def on_manual_change():
        if syncing["on"]:
            return

        draft["x"] = int(x_in.value or 0)
        draft["y"] = int(y_in.value or 0)

        if not fixed_size:
            draft["w"] = int(w_in.value or 10)
            draft["h"] = int(h_in.value or 10)

        redraw()

    def nudge(dx, dy):
        draft["x"] += dx
        draft["y"] += dy
        redraw()

    def align(where):
        if where == "left":
            draft["x"] = 0
        elif where == "hcenter":
            draft["x"] = (img_w - draft["w"]) // 2
        elif where == "right":
            draft["x"] = img_w - draft["w"]
        elif where == "top":
            draft["y"] = 0
        elif where == "vcenter":
            draft["y"] = (img_h - draft["h"]) // 2
        elif where == "bottom":
            draft["y"] = img_h - draft["h"]

        redraw()

    def reset():
        draft["x"] = (img_w - draft["w"]) // 2
        draft["y"] = (img_h - draft["h"]) // 2
        redraw()

    with ui.dialog() as dialog, ui.card().classes(
        "confirm-dialog"
    ):

        ui.label(f"Select the {label} area").classes(
            "confirm-title"
        )

        if fixed_size:
            hint = (
                "Drag to move the content area. Its size is fixed so it "
                "always fills the band below the webcam."
            )
        else:
            hint = "Drag on the image to draw the webcam region."

        ui.label(
            f"{hint} Source resolution: {img_w} x {img_h} px."
        ).classes("confirm-text")

        preview = ui.interactive_image(
            source=frame,
            events=["pointerdown", "pointermove", "pointerup"],
            on_mouse=on_drag,
            cross=False,
        ).classes("cam-preview")
        preview.content = svg_content()

        # ----------------------------------------------------
        # Alignment (Photoshop-style)
        # ----------------------------------------------------

        with ui.row().classes("cam-tools"):

            ui.label("Align").classes("small-label")

            for icon, where, tip in (
                ("align_horizontal_left", "left", "Left"),
                ("align_horizontal_center", "hcenter", "Center"),
                ("align_horizontal_right", "right", "Right"),
                ("align_vertical_top", "top", "Top"),
                ("align_vertical_center", "vcenter", "Middle"),
                ("align_vertical_bottom", "bottom", "Bottom"),
            ):
                ui.button(
                    icon=icon,
                    on_click=lambda w=where: align(w),
                ).props("flat dense round size=sm").tooltip(tip)

            ui.button(
                "Center",
                icon="center_focus_strong",
                on_click=reset,
            ).props("flat dense size=sm").tooltip(
                "Center in the frame"
            )

        # ----------------------------------------------------
        # Nudge
        # ----------------------------------------------------

        with ui.row().classes("cam-tools"):

            ui.label("Nudge").classes("small-label")

            for icon, dx, dy, tip in (
                ("keyboard_arrow_left", -10, 0, "Left 10px"),
                ("keyboard_arrow_right", 10, 0, "Right 10px"),
                ("keyboard_arrow_up", 0, -10, "Up 10px"),
                ("keyboard_arrow_down", 0, 10, "Down 10px"),
            ):
                ui.button(
                    icon=icon,
                    on_click=lambda a=dx, b=dy: nudge(a, b),
                ).props("flat dense round size=sm").tooltip(tip)

            ui.label("10 px").classes("inline-help")

        # ----------------------------------------------------
        # Numeric fields
        # ----------------------------------------------------

        with ui.row().classes("cam-inputs"):

            x_in = ui.number(
                "X", value=draft["x"], min=0, max=img_w, step=1,
                on_change=on_manual_change,
            ).props("outlined dense").classes("small-input")

            y_in = ui.number(
                "Y", value=draft["y"], min=0, max=img_h, step=1,
                on_change=on_manual_change,
            ).props("outlined dense").classes("small-input")

            w_in = ui.number(
                "Width", value=draft["w"], min=10, max=img_w, step=1,
                on_change=on_manual_change,
            ).props("outlined dense").classes("small-input")

            h_in = ui.number(
                "Height", value=draft["h"], min=10, max=img_h, step=1,
                on_change=on_manual_change,
            ).props("outlined dense").classes("small-input")

            if fixed_size:
                w_in.props("readonly")
                h_in.props("readonly")

        with ui.row().classes("confirm-buttons"):

            ui.button(
                "Cancel",
                on_click=dialog.close,
            ).props("flat")

            ui.button(
                "Use This Area",
                on_click=lambda: (
                    result.update(confirmed=True),
                    dialog.close(),
                ),
            ).props("unelevated color=primary")

    dialog.open()

    while dialog.value:
        await asyncio.sleep(0.05)

    if result["confirmed"]:
        # Mutate in place so every closure keeps seeing the same dict.
        target = cam_region if which == "cam" else content_region
        target.clear()
        target.update(draft)

        save_config()

        set_status(
            f"{label.capitalize()} area set to "
            f"{draft['w']}x{draft['h']} "
            f"at ({draft['x']}, {draft['y']}). Saved."
        )

        try:
            refresh_region_summaries()
            update_preview()
        except NameError:
            pass

    return result["confirmed"]


# ============================================================
# CONFIRMATION
# ============================================================

async def confirm_render():
    result = {"confirmed": False}

    with ui.dialog() as dialog:
        with ui.card().classes("confirm-dialog"):

            ui.label("Ready to render?").classes(
                "confirm-title"
            )

            ui.label(
                "The video segments are ready. "
                "Start cutting and rendering the videos?"
            ).classes(
                "confirm-text"
            )

            with ui.row().classes("confirm-buttons"):

                ui.button(
                    "Cancel",
                    on_click=dialog.close,
                ).props("flat")

                ui.button(
                    "Start Rendering",
                    on_click=lambda: (
                        result.update(confirmed=True),
                        dialog.close(),
                    ),
                ).props(
                    "unelevated color=primary"
                )

    dialog.open()

    while dialog.value:
        await asyncio.sleep(0.05)

    return result["confirmed"]


# ============================================================
# PROCESS
# ============================================================

async def process_video():

    process_button.disable()

    update_progress(0, "Starting...")
    set_status("Processing...")

    try:

        # ----------------------------------------------------
        # VIDEO
        # ----------------------------------------------------

        if not selected_video:
            set_status(
                "Please choose a video.",
                error=True,
            )
            return

        if not os.path.exists(selected_video):
            set_status(
                "The selected video no longer exists.",
                error=True,
            )
            return

        update_progress(
            5,
            "Video found.",
        )

        videosegmant = None

        # ----------------------------------------------------
        # EXISTING JSON
        # ----------------------------------------------------

        if reuse_json.value:

            if not selected_json:
                set_status(
                    "Please choose an existing JSON file.",
                    error=True,
                )
                return

            if not os.path.exists(selected_json):
                set_status(
                    "The selected JSON file no longer exists.",
                    error=True,
                )
                return

            update_progress(
                15,
                "Loading JSON script...",
            )

            def load_json():
                with open(
                    selected_json,
                    "r",
                    encoding="utf-8",
                ) as file:
                    return json.load(file)

            videosegmant = await run.io_bound(
                load_json
            )

            update_progress(
                35,
                "JSON script loaded.",
            )

        # ----------------------------------------------------
        # AI GENERATION
        # ----------------------------------------------------

        else:

            if not api_key.value.strip():
                set_status(
                    "Please enter your OpenRouter API key.",
                    error=True,
                )
                return

            if not selected_script:
                set_status(
                    "Please choose a script.",
                    error=True,
                )
                return

            if not os.path.exists(selected_script):
                set_status(
                    "The selected script no longer exists.",
                    error=True,
                )
                return

            try:
                minimum, maximum = parse_duration(
                    duration_range.value
                )

            except ValueError as e:
                set_status(
                    str(e),
                    error=True,
                )
                return

            try:
                number = int(
                    number_of_shorts.value
                )

                if number < 1 or number > 120:
                    raise ValueError()

            except Exception:
                set_status(
                    "Number of shorts must be between 1 and 120.",
                    error=True,
                )
                return

            update_progress(
                10,
                "Generating segments with AI...",
            )

            model = ai_model.value

            def generate():

                return shortmaker.get_script(
                    script_file_path=active_script(),
                    num_segments=number,
                    model=model,
                    API_KEY=api_key.value.strip(),
                    min_duration=minimum,
                    max_duration=maximum,
                )

            videosegmant = await run.io_bound(
                generate
            )

            update_progress(
                35,
                "AI generation complete.",
            )

        # ----------------------------------------------------
        # VALIDATE AGAINST THE ACTUAL VIDEO
        # ----------------------------------------------------

        # The AI works from the script, which can disagree with the video
        # (a stale script, or a trim applied after the script was written).
        # Segments past the end would render as black frames, so drop them
        # here and say so.
        try:
            video_duration = await run.io_bound(
                trim.probe_duration, active_video()
            )

        except Exception:
            video_duration = None

        if video_duration:
            kept_segments = []
            dropped = []

            for seg in videosegmant:
                try:
                    start = trim.timestamp_to_seconds(seg["start_time"])
                    end = trim.timestamp_to_seconds(seg["end_time"])

                except Exception:
                    dropped.append(seg.get("title", "?"))
                    continue

                if start >= video_duration - 0.5:
                    dropped.append(seg.get("title", "?"))
                    continue

                # Clamp a segment that runs past the end.
                if end > video_duration:
                    seg = dict(seg)
                    seg["end_time"] = trim.seconds_to_timestamp(
                        video_duration
                    )

                kept_segments.append(seg)

            if dropped:
                print(
                    f"[WARNING] Dropped {len(dropped)} segment(s) past "
                    f"the end of the video "
                    f"({video_duration:.1f}s): {dropped}",
                    flush=True,
                )

            if not kept_segments:
                set_status(
                    f"None of the generated segments fit inside the "
                    f"video ({video_duration:.1f}s). The script's "
                    f"timestamps do not match the video — if you trimmed "
                    f"it, re-select the script and apply the trim again "
                    f"so the timestamps are remapped.",
                    error=True,
                )
                update_progress(0, "Nothing to render.")
                return

            if dropped:
                set_status(
                    f"{len(dropped)} segment(s) skipped: they fall past "
                    f"the end of the video ({video_duration:.1f}s)."
                )

            videosegmant = kept_segments

        # ----------------------------------------------------
        # CONFIRM
        # ----------------------------------------------------

        set_status(
            "Segments are ready."
        )

        update_progress(
            40,
            "Waiting for confirmation..."
        )

        if not await confirm_render():

            update_progress(
                0,
                "Rendering cancelled."
            )

            set_status(
                "Rendering cancelled."
            )

            return

        # ----------------------------------------------------
        # RENDER
        # ----------------------------------------------------

        update_progress(
            45,
            "Starting renderer..."
        )

        if ffmpeg_toggle.value:

            set_status(
                "Rendering with FFmpeg / GPU..."
            )

            update_progress(
                50,
                "Rendering with FFmpeg / GPU..."
            )

            await run.io_bound(
                lambda: shortmakergpu.cut_videos(
                    videosegmant,
                    active_video(),
                    layout_select.value,
                    cam_region,
                    content_region,
                    config['cam_band_ratio'],
                    config['cam_fit'],
                    config['content_fit'],
                )
            )

        else:

            set_status(
                "Rendering with standard renderer..."
            )

            update_progress(
                50,
                "Rendering with standard renderer..."
            )

            await run.io_bound(
                lambda: shortmaker.cut_videos(
                    videosegmant,
                    active_video(),
                    layout_select.value,
                    cam_region,
                    content_region,
                    config['cam_band_ratio'],
                    config['cam_fit'],
                    config['content_fit'],
                )
            )

        # ----------------------------------------------------
        # DONE
        # ----------------------------------------------------

        update_progress(
            100,
            "Finished!"
        )

        set_status(
            "All video shorts generated successfully."
        )

    except Exception as e:

        print(
            f"[ERROR] {repr(e)}"
        )

        update_progress(
            0,
            "Processing failed."
        )

        set_status(
            f"Error: {e}",
            error=True,
        )

    finally:
        update_process_button()


# ============================================================
# COLORS
# ============================================================

ui.colors(
    primary="#FF8C3F",
    secondary="#26282E",
    positive="#4ADE80",
    negative="#F87171",
    warning="#FFC480",
)


# ============================================================
# CSS
# ============================================================

css_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "style.css",
)

ui.add_css(css_path)

# ============================================================
# FORM
# ============================================================

def section(number, title, hint=""):
    """Numbered section header, in the design system's mono style."""

    with ui.row().classes("section-head"):

        ui.label(number).classes("section-num")

        with ui.column().classes("section-titles"):

            ui.label(title).classes("section-title")

            if hint:
                ui.label(hint).classes("section-hint")


with ui.column().classes("app"):

    # --------------------------------------------------------
    # TITLE
    # --------------------------------------------------------

    with ui.column().classes("title-row"):

        with ui.row().classes("title-line"):

            ui.label(
                "AI Shorts Maker"
            ).classes("title")

            ui.label(
                "Local"
            ).classes("local-label")

        ui.label(
            "Turn one long video into vertical shorts. "
            "Runs on your machine."
        ).classes("title-sub")


    # --------------------------------------------------------
    # 01 — SOURCE
    # --------------------------------------------------------

    with ui.column().classes("panel"):

        section(
            "01",
            "Source",
            "Pick the long video and the script the AI should read.",
        )

        with ui.row().classes("form-row"):

            ui.label("Video").classes("form-label")

            ui.button(
                "Choose Video...",
                icon="folder_open",
                on_click=choose_video,
            ).props("outline")

            video_file = ui.label(
                "No video selected"
            ).classes("selected-name")

        # --- trim ------------------------------------------

        with ui.expansion(
            "Trim video (remove unwanted parts)", icon="content_cut"
        ).classes("trim-panel"):

            trim_status = ui.label(
                "Choose a video to trim it."
            ).classes("inline-help")

            trim_duration = ui.label("").classes("inline-help")

            # --- player + timeline -----------------------------

            with ui.row().classes("trim-player-row"):

                trim_video_el = ui.video(
                    "", controls=True
                ).classes("trim-video")

                with ui.column().classes("trim-side"):

                    ui.label("Playhead").classes("small-label")

                    trim_playhead = ui.label(
                        "00:00:00"
                    ).classes("trim-playhead")

                    with ui.row().classes("trim-row"):

                        ui.button(
                            "Set start",
                            icon="first_page",
                            on_click=lambda: use_playhead("start"),
                        ).props("outline dense")

                        ui.button(
                            "Set end",
                            icon="last_page",
                            on_click=lambda: use_playhead("end"),
                        ).props("outline dense")

                    ui.label(
                        "Play the video, pause where the unwanted part "
                        "begins, then Set start. Pause where it ends and "
                        "Set end. Add cut."
                    ).classes("inline-help")

            # --- timeline with cut markers ---------------------

            ui.label("Timeline").classes("small-label")

            timeline = ui.html("").classes("trim-timeline")

            timeline_legend = ui.label("").classes("inline-help")

            # --- add a cut -------------------------------------

            with ui.row().classes("trim-row"):

                ui.label("Remove from").classes("small-label")

                trim_start = ui.input(
                    value="00:00:00"
                ).props("outlined dense").classes("tc-input")

                ui.label("to").classes("small-label")

                trim_end = ui.input(
                    value="00:00:00"
                ).props("outlined dense").classes("tc-input")

                ui.button(
                    "Add cut",
                    icon="add",
                    on_click=lambda: add_cut(),
                ).props("outline dense")

            # --- list of cuts ----------------------------------

            trim_list = ui.column().classes("trim-list")

            with ui.row().classes("trim-row"):

                ui.button(
                    "Apply Trim",
                    icon="content_cut",
                    on_click=lambda: run_trim(),
                ).props("unelevated color=primary dense")

                ui.button(
                    "Clear",
                    icon="undo",
                    on_click=lambda: clear_cuts(),
                ).props("flat dense")

                ui.button(
                    "Reset to original",
                    icon="restart_alt",
                    on_click=lambda: do_reset_trim(),
                ).props("flat dense")

        # Pending cuts, in seconds. Persisted so a reload keeps them.
        cuts = []

        # Which timecode field the "Set start/end" buttons fill.
        async def use_playhead(which):
            """Copy the player's current time into a timecode field."""

            try:
                raw = await ui.run_javascript(
                    "(document.querySelector('video.trim-video') || {})"
                    ".currentTime ?? null",
                    timeout=3,
                )

            except Exception as e:
                print(f"[WARNING] Could not read playhead: {e}")
                raw = None

            if raw is None:
                set_status(
                    "Could not read the player position. "
                    "Load a video and press play first.",
                    error=True,
                )
                return

            seconds = float(raw)

            if which == "start":
                trim_start.value = format_timecode(seconds)
            else:
                trim_end.value = format_timecode(seconds)

            set_status(
                f"{'Start' if which == 'start' else 'End'} set to "
                f"{format_timecode(seconds)}."
            )

        def render_timeline(duration):
            """Draw the timeline bar with the pending cuts marked."""

            if not duration or duration <= 0:
                timeline.content = ""
                timeline_legend.text = ""
                return

            bars = []

            for a, b in cuts:
                left = max(0.0, min(100.0, a / duration * 100))
                width = max(0.4, min(100.0 - left, (b - a) / duration * 100))
                bars.append(
                    f'<div class="tl-cut" style="left:{left:.3f}%;'
                    f'width:{width:.3f}%" title="{format_timecode(a)}'
                    f' - {format_timecode(b)}"></div>'
                )

            ticks = []
            for i in range(11):
                pos = i * 10
                ticks.append(
                    f'<div class="tl-tick" style="left:{pos}%"></div>'
                )

            timeline.content = (
                '<div class="tl-wrap">'
                '<div class="tl-track">'
                + "".join(ticks)
                + "".join(bars)
                + "</div></div>"
            )

            total = sum(b - a for a, b in cuts)
            timeline_legend.text = (
                f"0s {'':>4} {format_timecode(duration/2)} "
                f"{'':>4} {format_timecode(duration)}"
                + (f"   |   removing {total:.1f}s" if cuts else "")
            )

        def refresh_trim_status():
            """Redraw the cut list and the current trim state."""

            trim_list.clear()

            if not selected_video:
                trim_status.text = "Choose a video to trim it."
                trim_duration.text = ""
                render_timeline(0)
                return

            try:
                dur = trim.probe_duration(selected_video)
                trim_duration.text = (
                    f"Source: {os.path.basename(selected_video)} "
                    f"({format_timecode(dur)})"
                )

                # Point the player at the source (or the trimmed file, if the
                # trim is already applied) so the user can watch it.
                media_src = media_url(active_video())
                if media_src:
                    trim_video_el.set_source(media_src)

            except Exception:
                trim_duration.text = ""
                dur = 0

            render_timeline(dur)

            if trimmed_video and trim_plan:
                trim_status.text = (
                    f"Trimmed video active: "
                    f"{format_timecode(trim_plan['new_duration'])} "
                    f"(removed {trim_plan['removed']:.1f}s)"
                )
            elif cuts:
                total = sum(b - a for a, b in cuts)
                trim_status.text = (
                    f"{len(cuts)} cut(s) pending, "
                    f"{total:.1f}s to remove. Click Apply Trim."
                )
            else:
                trim_status.text = "No cuts. The full video will be used."

            with trim_list:

                if not cuts:
                    ui.label("No cuts added.").classes("inline-help")
                    return

                for i, (a, b) in enumerate(cuts):
                    with ui.row().classes("trim-item"):

                        ui.label(
                            f"{format_timecode(a)} - {format_timecode(b)}"
                        ).classes("trim-item-label")

                        ui.label(
                            f"({b - a:.1f}s)"
                        ).classes("inline-help")

                        ui.button(
                            icon="close",
                            on_click=lambda idx=i: remove_cut(idx),
                        ).props("flat dense round size=sm")

        def add_cut():
            """Add a pending cut from the two timecode fields."""

            try:
                start = parse_timecode(trim_start.value)
                end = parse_timecode(trim_end.value)

            except ValueError:
                set_status(
                    "Use HH:MM:SS for the cut times, for example 00:01:30.",
                    error=True,
                )
                return

            if end <= start:
                set_status(
                    "The cut end must be after its start.",
                    error=True,
                )
                return

            cuts.append((start, end))
            cuts.sort()

            # Reject overlaps early, so the list stays valid.
            for i in range(1, len(cuts)):
                if cuts[i][0] < cuts[i - 1][1]:
                    cuts.pop(i)
                    set_status(
                        "That cut overlaps an existing one.",
                        error=True,
                    )
                    refresh_trim_status()
                    return

            set_status(
                f"Cut added: {format_timecode(start)} - "
                f"{format_timecode(end)}."
            )
            refresh_trim_status()

        def remove_cut(index):
            if 0 <= index < len(cuts):
                cuts.pop(index)
                refresh_trim_status()

        def clear_cuts():
            cuts.clear()
            refresh_trim_status()
            set_status("Pending cuts cleared.")

        def do_reset_trim():
            reset_trim()
            refresh_trim_status()

            try:
                update_preview()
            except NameError:
                pass

            set_status("Back to the original video.")

        async def run_trim():
            """Apply the pending cuts."""

            if not cuts:
                set_status("Add at least one cut first.", error=True)
                return

            set_status("Trimming video...")

            ok, message = await apply_trim(
                [{"start": a, "end": b} for a, b in cuts],
                selected_script or None,
            )

            set_status(message, error=not ok)

            if ok:
                cuts.clear()
                refresh_trim_status()

                # The active video changed, so the preview must be rebuilt.
                try:
                    update_preview()
                except NameError:
                    pass

    refresh_trim_status()

    # --------------------------------------------------------
    # 02 — OUTPUT
    # --------------------------------------------------------

    with ui.column().classes("panel"):

        section(
            "02",
            "Output",
            "How many shorts to cut, and how long each one should be.",
        )

        # Wrapped so "Reuse Existing JSON" can disable these: a JSON
        # already carries its own segment count and durations.
        short_settings_row = ui.column().classes("form-group")

        with short_settings_row:

            with ui.row().classes("form-row"):

                ui.label("Shorts").classes("form-label")

                number_of_shorts = ui.number(
                    value=config["shorts"],
                    min=1,
                    max=120,
                    step=1,
                ).props("outlined dense").classes("small-input")

                ui.label("Duration").classes("small-label")

                duration_range = ui.input(
                    value=config["duration"]
                ).props("outlined dense").classes("small-input")

        with ui.row().classes("form-row"):

            ui.label("Renderer").classes("form-label")

            ffmpeg_toggle = ui.switch(
                "Use FFmpeg / GPU",
                value=config["use_ffmpeg"],
                on_change=lambda: toggle_ffmpeg(),
            )

            ui.label(
                "Fast hardware rendering"
            ).classes("inline-help")

    # --------------------------------------------------------
    # 03 — LAYOUT
    # --------------------------------------------------------

    with ui.column().classes("panel"):

        section(
            "03",
            "Layout",
            "How the frame is fitted into the vertical canvas.",
        )

        with ui.row().classes("form-row"):

            ui.label("Layout").classes("form-label")

            layout_select = ui.select(
                [
                    "Do Not Crop (Keep Original Aspect Ratio)",
                    "Center Crop (9:16 Full Screen)",
                    "Fit with Black Background (Letterbox)",
                    "Fit with White Background (Letterbox)",
                    "Fit with Blurred Background",
                    "Shorts with Cam (9:16)",
                ],
                value=config["layout"],
            ).props("outlined dense").classes("layout-input")

        with ui.row().classes("form-row"):

            ui.label("").classes("form-label")

            layout_help = ui.label(
                "Layout is applied by the FFmpeg / GPU renderer."
            ).classes("inline-help layout-ok")

        # --- regions ---------------------------------------

        with ui.row().classes("form-row"):

            ui.label("Webcam").classes("form-label")

            ui.button(
                "Select Webcam Area...",
                icon="crop_free",
                on_click=lambda: pick_region("cam"),
            ).props("outline")

            cam_summary = ui.label("").classes("selected-name")

        with ui.row().classes("form-row"):

            ui.label("Content").classes("form-label")

            ui.button(
                "Select Content Area...",
                icon="crop_free",
                on_click=lambda: pick_region("content"),
            ).props("outline")

            content_summary = ui.label("").classes("selected-name")

        with ui.row().classes("form-row"):

            ui.label("Cam height").classes("form-label")

            band_slider = ui.slider(
                min=10,
                max=70,
                step=1,
                value=int(config["cam_band_ratio"] * 100),
                on_change=lambda: on_band_change(),
            ).props("label-always").classes("band-slider")

        with ui.row().classes("form-row"):

            ui.label("Cam fit").classes("form-label")

            cam_fit_select = ui.select(
                ["Fill (may crop)", "Fit (may add bars)"],
                value=(
                    "Fit (may add bars)"
                    if config["cam_fit"] == "fit"
                    else "Fill (may crop)"
                ),
                on_change=lambda: on_fit_change(),
            ).props("outlined dense").classes("layout-input")

        with ui.row().classes("form-row"):

            ui.label("Content fit").classes("form-label")

            content_fit_select = ui.select(
                ["Fill (may crop)", "Fit (may add bars)"],
                value=(
                    "Fit (may add bars)"
                    if config["content_fit"] == "fit"
                    else "Fill (may crop)"
                ),
                on_change=lambda: on_fit_change(),
            ).props("outlined dense").classes("layout-input")

    def on_band_change():
        config["cam_band_ratio"] = band_slider.value / 100.0
        save_config()
        refresh_region_summaries()
        update_preview()

    def refresh_region_summaries():
        cam_summary.text = (
            f"{cam_region['w']}x{cam_region['h']} "
            f"at ({cam_region['x']}, {cam_region['y']})"
        )
        content_summary.text = (
            f"{content_region['w']}x{content_region['h']} "
            f"at ({content_region['x']}, {content_region['y']})"
        )

    def on_fit_change():
        config["cam_fit"] = (
            "fit" if cam_fit_select.value.startswith("Fit") else "fill"
        )
        config["content_fit"] = (
            "fit"
            if content_fit_select.value.startswith("Fit")
            else "fill"
        )
        save_config()
        update_preview()

    refresh_region_summaries()

    # --------------------------------------------------------
    # 04 — AI
    # --------------------------------------------------------

    with ui.column().classes("panel"):

        section(
            "04",
            "AI",
            "Where the segments come from. Reuse a JSON to skip the AI.",
        )

        with ui.row().classes("form-row"):

            ui.label("Source").classes("form-label")

            reuse_json = ui.switch(
                "Reuse Existing JSON",
                value=False,
                on_change=lambda: toggle_json_mode(),
            )

            mode_status = ui.label(
                "Generate with AI"
            ).classes("inline-help")

        ai_row = ui.column().classes("form-group")

        with ai_row:

            with ui.row().classes("form-row"):

                ui.label("API Key").classes("form-label")

                api_key = ui.input(
                    value=settings.get("api_key", ""),
                    placeholder="sk-or-...",
                ).props(
                    "outlined dense type=password"
                ).classes("wide-input")

            with ui.row().classes("form-row"):

                ui.label("AI Model").classes("form-label")

                ai_model = ui.select(
                    OPENROUTER_MODELS,
                    value=config["model"],
                ).props("outlined dense").classes("wide-input")

        json_row = ui.column().classes("form-group disabled-row")

        with json_row:

            with ui.row().classes("form-row"):

                ui.label("JSON Script").classes("form-label")

                ui.button(
                    "Choose JSON...",
                    icon="folder_open",
                    on_click=choose_json,
                ).props("outline")

                json_file = ui.label(
                    "No JSON selected"
                ).classes("selected-name")

        script_row = ui.column().classes("form-group")

        with script_row:

            with ui.row().classes("form-row"):

                ui.label("Script").classes("form-label")

                ui.button(
                    "Choose Script...",
                    icon="folder_open",
                    on_click=choose_script,
                ).props("outline")

                script_file = ui.label(
                    "No script selected"
                ).classes("selected-name")


    # --------------------------------------------------------
    # 05 — PREVIEW
    # --------------------------------------------------------

    with ui.column().classes("panel"):

        section(
            "05",
            "Preview",
            "What the rendered short will look like.",
        )

        with ui.expansion(
            "Show preview", icon="preview"
        ).classes("preview-panel"):

            preview_row = ui.row().classes("preview-row")

        preview_note = ui.label(
            "Choose a video to see a real preview."
        ).classes("inline-help")

    def update_preview():
        """
        Show what the output will look like.

        For the Shorts-with-Cam layout this renders an actual preview from a
        frame of the selected video, using the same fitting rules as the
        renderers. The other layouts get a schematic.
        """

        preview_row.clear()

        layout = layout_select.value
        band = config["cam_band_ratio"]

        # Output canvas, drawn small. 9:16.
        out_w, out_h = 216, 384

        # Keep the note in step with what the preview can show.
        if layout == "Shorts with Cam (9:16)":
            source = active_video()
            if source and os.path.exists(source):
                preview_note.text = (
                    "Rendered from a real frame of the video, using the "
                    "same fitting rules as the renderer."
                )
            else:
                preview_note.text = (
                    "Choose a video to see a real preview."
                )
        else:
            preview_note.text = (
                "Schematic. The Shorts-with-Cam layout shows a real frame."
            )

        with preview_row:

            if layout == "Shorts with Cam (9:16)":

                # Use the active video: after a trim, the preview must
                # reflect the trimmed file, not the original.
                source = active_video()

                if source and os.path.exists(source):
                    try:
                        frame = extract_frame(source, 5)

                        image = render_preview_image(
                            frame,
                            cam_region,
                            content_region,
                            band,
                            config.get("cam_fit"),
                            config.get("content_fit"),
                        )

                        ui.image(image).classes("preview-image")

                    except Exception as e:
                        print(f"[WARNING] Preview failed: {e}")
                        ui.label(
                            "Could not build the preview."
                        ).classes("inline-help")

                else:
                    ui.label(
                        "Choose a video to see a real preview."
                    ).classes("inline-help")

            else:

                with ui.element("div").classes(
                    "preview-canvas"
                ).style(f"width:{out_w}px;height:{out_h}px"):

                    if layout == (
                        "Do Not Crop (Keep Original Aspect Ratio)"
                    ):
                        ui.label(
                            "Original framing, no vertical canvas."
                        ).classes("inline-help")

                    else:
                        ui.element("div").classes(
                            "preview-content"
                        ).style(
                            f"left:0;top:0;"
                            f"width:{out_w}px;height:{out_h}px"
                        )

                        ui.label(
                            layout.split("(")[0].strip()
                        ).classes("preview-tag").style(
                            "left:6px;top:6px"
                        )

            with ui.column().classes("preview-info"):

                ui.label(
                    f"Output: {OUTPUT_WIDTH} x {OUTPUT_HEIGHT}"
                ).classes("inline-help")

                top_h = int(OUTPUT_HEIGHT * band)
                top_h -= top_h % 2

                ui.label(
                    f"Cam band: {int(band * 100)}% ({top_h} px)"
                ).classes("inline-help")

                ui.label(
                    f"Content band: "
                    f"{100 - int(band * 100)}% "
                    f"({OUTPUT_HEIGHT - top_h} px)"
                ).classes("inline-help")

                ui.label(
                    f"Cam source: {cam_region['w']}x{cam_region['h']} "
                    f"at ({cam_region['x']}, {cam_region['y']})"
                ).classes("inline-help")

                ui.label(
                    f"Content source: "
                    f"{content_region['w']}x{content_region['h']} "
                    f"at ({content_region['x']}, {content_region['y']})"
                ).classes("inline-help")

    layout_select.on_value_change(
        lambda: (config.update(layout=layout_select.value),
                 save_config(),
                 update_preview())
    )

    update_preview()


    # --------------------------------------------------------
    # RUN
    # --------------------------------------------------------

    with ui.column().classes("panel run-panel"):

        section("06", "Run", "Render the shorts.")

        process_button = ui.button(
            "Process Video",
            icon="play_arrow",
            on_click=process_video,
        ).props("unelevated").classes("process-button")

        with ui.row().classes("progress-info"):

            progress_status = ui.label(
                "Ready"
            ).classes("progress-text")

            progress_percent = ui.label(
                "0%"
            ).classes("progress-text")

        progress_bar = ui.linear_progress(
            value=0
        ).classes("progress-bar")

        status_label = ui.label(
            "Choose a video to get started."
        ).classes("status-normal")


# ============================================================
# EVENTS
# ============================================================

def api_key_changed():
    settings["api_key"] = api_key.value.strip()
    save_settings(settings)
    update_process_button()


api_key.on_value_change(
    lambda: api_key_changed()
)


def persist_settings():
    """Keep the persisted config in step with the controls."""

    config["layout"] = layout_select.value
    config["use_ffmpeg"] = bool(ffmpeg_toggle.value)
    config["shorts"] = int(number_of_shorts.value or 25)
    config["duration"] = duration_range.value
    config["model"] = ai_model.value
    save_config()


number_of_shorts.on_value_change(lambda: persist_settings())
duration_range.on_value_change(lambda: persist_settings())
ai_model.on_value_change(lambda: persist_settings())
ffmpeg_toggle.on_value_change(lambda: persist_settings())

# Initial state
toggle_json_mode()
toggle_ffmpeg()
update_process_button()


# ============================================================
# RUN
# ============================================================

# Port 8080 is commonly taken by other local services (Docker containers,
# WhatsApp/Evolution API, dev servers). Allow an override so the app can
# always be started:
#     set AI_SHORT_MAKER_PORT=8081
PORT = int(os.environ.get("AI_SHORT_MAKER_PORT", "8081"))

ui.run(
    title="AI Video Cutter",
    reload=False,
    port=PORT,
    # Required for app.storage.user, which holds the saved regions and
    # layout settings.
    storage_secret=os.environ.get(
        "AI_SHORT_MAKER_SECRET",
        "ai-short-maker-local-storage",
    ),
)