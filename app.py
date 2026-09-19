import os
import json
import asyncio
import tkinter as tk
from tkinter import filedialog

import requests
from nicegui import ui, run

import shortmaker
import shortmakergpu

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
        selected_video = path
        video_file.text = os.path.basename(path)
        video_file.tooltip = path
        update_process_button()

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
    if ffmpeg_toggle.value:
        layout_select.disable()
        layout_help.text = "Layout unavailable with FFmpeg renderer."
        layout_help.classes(
            remove="layout-ok",
            add="layout-disabled",
        )
    else:
        layout_select.enable()
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
                    script_file_path=selected_script,
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
                    selected_video,
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
                    selected_video,
                    layout_select.value,
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
    primary="#6C63FF",
    secondary="#455F76",
    positive="#16A34A",
    negative="#DC2626",
    warning="#D97706",
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

with ui.column().classes("app"):

    # --------------------------------------------------------
    # TITLE
    # --------------------------------------------------------

    with ui.row().classes("title-row"):

        ui.label(
            "AI Shorts Maker"
        ).classes("title")

        ui.label(
            "Local"
        ).classes("local-label")


    # --------------------------------------------------------
    # VIDEO
    # --------------------------------------------------------

    with ui.row().classes("form-row"):

        ui.label(
            "Video"
        ).classes("form-label")

        ui.button(
            "Choose Video...",
            icon="folder_open",
            on_click=choose_video,
        ).props(
            "outline"
        )

        video_file = ui.label(
            "No video selected"
        ).classes("selected-name")


    # --------------------------------------------------------
    # MODE
    # --------------------------------------------------------

    with ui.row().classes("form-row"):

        ui.label(
            "Processing"
        ).classes("form-label")

        reuse_json = ui.switch(
            "Reuse Existing JSON",
            value=False,
            on_change=lambda: toggle_json_mode(),
        )

        mode_status = ui.label(
            "Generate with AI"
        ).classes("inline-help")


    # --------------------------------------------------------
    # AI SETTINGS
    # --------------------------------------------------------

    ai_row = ui.column().classes(
        "form-group"
    )

    with ai_row:

        with ui.row().classes("form-row"):

            ui.label(
                "API Key"
            ).classes("form-label")

            api_key = ui.input(
                value=settings.get("api_key", ""),
                placeholder="sk-or-..."
            ).props(
                "outlined dense type=password"
            ).classes(
                "wide-input"
            )

        with ui.row().classes("form-row"):

            ui.label(
                "AI Model"
            ).classes("form-label")

            ai_model = ui.select(
                OPENROUTER_MODELS,
                value="openrouter/free",
            ).props(
                "outlined dense"
            ).classes(
                "wide-input"
            )


    # --------------------------------------------------------
    # JSON
    # --------------------------------------------------------

    json_row = ui.column().classes(
        "form-group disabled-row"
    )

    with json_row:

        with ui.row().classes("form-row"):

            ui.label(
                "JSON Script"
            ).classes("form-label")

            ui.button(
                "Choose JSON...",
                icon="folder_open",
                on_click=choose_json,
            ).props(
                "outline"
            )

            json_file = ui.label(
                "No JSON selected"
            ).classes("selected-name")


    # --------------------------------------------------------
    # SCRIPT
    # --------------------------------------------------------

    script_row = ui.column().classes(
        "form-group"
    )

    with script_row:

        with ui.row().classes("form-row"):

            ui.label(
                "Script"
            ).classes("form-label")

            ui.button(
                "Choose Script...",
                icon="folder_open",
                on_click=choose_script,
            ).props(
                "outline"
            )

            script_file = ui.label(
                "No script selected"
            ).classes("selected-name")


    # --------------------------------------------------------
    # SHORT SETTINGS
    # --------------------------------------------------------

    short_settings_row = ui.column().classes(
        "form-group"
    )

    with short_settings_row:

        with ui.row().classes("form-row"):

            ui.label(
                "Shorts"
            ).classes("form-label")

            number_of_shorts = ui.number(
                value=25,
                min=1,
                max=120,
                step=1,
            ).props(
                "outlined dense"
            ).classes("small-input")

            ui.label(
                "Duration"
            ).classes("small-label")

            duration_range = ui.input(
                value="15-60"
            ).props(
                "outlined dense"
            ).classes("small-input")


    # --------------------------------------------------------
    # RENDERER
    # --------------------------------------------------------

    with ui.row().classes("form-row"):

        ui.label(
            "Renderer"
        ).classes("form-label")

        ffmpeg_toggle = ui.switch(
            "Use FFmpeg / GPU",
            value=True,
            on_change=lambda: toggle_ffmpeg(),
        )

        ui.label(
            "Fast hardware rendering"
        ).classes("inline-help")


    # --------------------------------------------------------
    # LAYOUT
    # --------------------------------------------------------

    with ui.row().classes("form-row"):

        ui.label(
            "Layout"
        ).classes("form-label")

        layout_select = ui.select(
            [
                "Do Not Crop (Keep Original Aspect Ratio)",
                "Center Crop (9:16 Full Screen)",
                "Fit with Black Background (Letterbox)",
                "Fit with White Background (Letterbox)",
            ],
            value="Center Crop (9:16 Full Screen)",
        ).props(
            "outlined dense"
        ).classes(
            "layout-input"
        )

        layout_help = ui.label(
            "Layout unavailable with FFmpeg renderer."
        ).classes(
            "inline-help layout-disabled"
        )


    # --------------------------------------------------------
    # PROCESS BUTTON
    # --------------------------------------------------------

    ui.separator().classes("form-separator")

    process_button = ui.button(
        "Process Video",
        icon="play_arrow",
        on_click=process_video,
    ).props(
        "unelevated"
    ).classes(
        "process-button"
    )


    # --------------------------------------------------------
    # PROGRESS
    # --------------------------------------------------------

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


    # --------------------------------------------------------
    # STATUS
    # --------------------------------------------------------

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

# Initial state
toggle_json_mode()
toggle_ffmpeg()
update_process_button()


# ============================================================
# RUN
# ============================================================

ui.run(
    title="AI Video Cutter",
    reload=False,
    port=8080,
)