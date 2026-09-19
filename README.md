# AI Video Cutter

A local Python application for generating and rendering short-form videos using OpenRouter, MoviePy, and FFmpeg.

## Features

* Local NiceGUI interface
* Native file selection dialogs
* OpenRouter AI script and segment generation
* Reuse previously generated JSON scripts
* MoviePy standard rendering
* FFmpeg rendering
* GPU hardware encoding
* Configurable number of shorts
* Configurable video duration range
* Multiple video layout options

---

# Requirements

## Python

Python 3.11 or newer is recommended.

Download Python:

https://www.python.org/downloads/

### Windows

During Python installation, enable:

```text
Add Python to PATH
```

Verify the installation:

```cmd
python --version
```

---

# Installation

## 1. Project Files

Place the project in a folder such as:

```text
AI-Video-Cutter/
```

The project should contain:

```text
AI-Video-Cutter/
├── app.py
├── shortmaker.py
├── shortmakergpu.py
├── style.css
├── requirements.txt
└── INSTALL.md
```

---

## 2. Create a Virtual Environment

Open a terminal inside the project folder.

### Windows

```cmd
python -m venv .venv
```

Activate it:

```cmd
.venv\Scripts\activate
```

You should see something similar to:

```text
(.venv)
```

at the beginning of your terminal prompt.

### macOS / Linux

```bash
python3 -m venv .venv
```

Activate it:

```bash
source .venv/bin/activate
```

---

## 3. Install Python Dependencies

Upgrade pip:

```bash
python -m pip install --upgrade pip
```

Install the project dependencies:

```bash
pip install -r requirements.txt
```

The current requirements are:

```text
nicegui
requests
moviepy
openai
proglog
```

---

# 4. Install Tkinter

Tkinter is used for the native file-selection dialogs.

Test whether Tkinter is installed:

```bash
python -m tkinter
```

A small Tkinter window should appear.

### Windows

Tkinter normally comes with the standard Python installation.

If it is missing, reinstall Python using the official installer:

https://www.python.org/downloads/

### Ubuntu / Debian

```bash
sudo apt install python3-tk
```

### Fedora

```bash
sudo dnf install python3-tkinter
```

---

# 5. Install FFmpeg

FFmpeg is required for video processing.

Check whether FFmpeg is already installed:

```bash
ffmpeg -version
```

If the command works, FFmpeg is available.

## Windows

Download FFmpeg:

https://ffmpeg.org/download.html

Install FFmpeg and add its `bin` directory to your Windows PATH.

For example:

```text
C:\ffmpeg\bin
```

After adding FFmpeg to PATH, close and reopen your terminal.

Then run:

```cmd
ffmpeg -version
```

## macOS

If you use Homebrew:

```bash
brew install ffmpeg
```

Then:

```bash
ffmpeg -version
```

## Ubuntu / Debian

```bash
sudo apt update
sudo apt install ffmpeg
```

Then:

```bash
ffmpeg -version
```

---

# 6. GPU Rendering

GPU rendering is optional.

The application can use the standard renderer without a supported GPU.

For GPU rendering, your hardware, drivers, and FFmpeg installation must support the appropriate hardware encoder.

## NVIDIA

You need:

* An NVIDIA GPU
* NVIDIA drivers
* FFmpeg with NVENC support

Check for NVENC.

### Windows

```cmd
ffmpeg -hide_banner -encoders | findstr nvenc
```

### macOS / Linux

```bash
ffmpeg -hide_banner -encoders | grep nvenc
```

You should see something similar to:

```text
h264_nvenc
hevc_nvenc
```

---

# 7. Test NVIDIA NVENC

You can test NVIDIA hardware encoding with:

```cmd
ffmpeg -hide_banner -f lavfi -i testsrc2=size=1920x1080:rate=30 -t 5 -c:v h264_nvenc -preset p1 test_nvenc.mp4
```

If the command succeeds, FFmpeg should create:

```text
test_nvenc.mp4
```

You can delete the test file afterward.

---

# 8. OpenRouter API Key

AI generation requires an OpenRouter API key.

Create an account at:

https://openrouter.ai/

Create an API key from your OpenRouter account.

The key normally looks similar to:

```text
sk-or-...
```

Enter the key into the **API Key** field in the application.

The API key does not need to be placed inside the Python source code.

---

# 9. Run the Application

Make sure your virtual environment is activated.

### Windows

```cmd
.venv\Scripts\activate
```

### macOS / Linux

```bash
source .venv/bin/activate
```

Start the application:

```bash
python app.py
```

NiceGUI will start a local web server.

Open the address:

```text
http://localhost:8080
```

in your browser.

---

# Using the Application

## Normal AI Workflow

1. Choose a video.
2. Leave **Reuse Existing JSON** disabled.
3. Enter your OpenRouter API key.
4. Select an AI model.
5. Choose your `.txt` script.
6. Set the number of shorts.
7. Set the duration range.
8. Choose the renderer.
9. Choose a layout when using the standard renderer.
10. Click **Process Video**.
11. Confirm the render.

---

# Reusing an Existing JSON Script

If you already generated a JSON script:

1. Enable **Reuse Existing JSON**.
2. Choose the JSON file.
3. The OpenRouter generation step will be skipped.
4. Choose the renderer.
5. Click **Process Video**.
6. Confirm the render.

This allows you to render the same segment data again without making another AI request.

---

# Number of Shorts

The application allows between 1 and 120 shorts.

For example:

```text
25
```

requests 25 video segments from the AI generation process.

---

# Duration

Duration uses the following format:

```text
minimum-maximum
```

For example:

```text
15-60
```

means each generated segment should be between 15 and 60 seconds.

Other examples:

```text
30-60
```

```text
20-45
```

```text
60-90
```

---

# Renderers

## FFmpeg / GPU

When **Use FFmpeg / GPU** is enabled, the application uses:

```python
shortmakergpu.cut_videos(
    videosegmant,
    selected_video,
)
```

The layout setting is not used by this renderer.

---

## Standard Renderer

When FFmpeg/GPU rendering is disabled, the application uses:

```python
shortmaker.cut_videos(
    videosegmant,
    selected_video,
    layout_select.value,
)
```

The standard renderer supports the available layout options.

---

# Layout Options

The standard renderer provides:

```text
Do Not Crop (Keep Original Aspect Ratio)
```

```text
Center Crop (9:16 Full Screen)
```

```text
Fit with Black Background (Letterbox)
```

```text
Fit with Blurred Background
```

The layout setting is disabled when the FFmpeg/GPU renderer is selected.

---

# Project Structure

```text
AI-Video-Cutter/
├── app.py
├── shortmaker.py
├── shortmakergpu.py
├── style.css
├── requirements.txt
├── INSTALL.md
└── .venv/
```

## app.py

The main NiceGUI application.

It handles:

* User interface
* File selection
* OpenRouter settings
* JSON reuse
* Renderer selection
* Progress
* Status messages

## shortmaker.py

Handles the standard video processing and AI-related functionality.

## shortmakergpu.py

Handles FFmpeg/GPU video processing.

## style.css

Controls the application's appearance.

## requirements.txt

Contains the required Python packages.

---

# Troubleshooting

## Python command not found

Try:

```bash
python3 --version
```

If that works, use `python3` instead of `python`.

---

## pip command not found

Use:

```bash
python -m pip install -r requirements.txt
```

instead of:

```bash
pip install -r requirements.txt
```

---

## ModuleNotFoundError

For example:

```text
ModuleNotFoundError: No module named 'nicegui'
```

Make sure the virtual environment is activated.

Then run:

```bash
pip install -r requirements.txt
```

---

## FFmpeg is not recognized

If you see:

```text
ffmpeg is not recognized
```

or:

```text
ffmpeg: command not found
```

FFmpeg is either not installed or is not available through PATH.

Install FFmpeg and restart your terminal.
