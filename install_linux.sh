#!/bin/bash

set -e

echo
echo "=========================================="
echo "       AI Video Cutter Installer"
echo "=========================================="
echo

# ============================================================
# CHECK PYTHON
# ============================================================

echo "[1/5] Checking Python..."
echo

if command -v python3 >/dev/null 2>&1; then
    PYTHON=python3
else
    echo "ERROR: Python 3 was not found."
    echo
    echo "Please install Python 3.11 or newer."
    echo
    exit 1
fi

$PYTHON --version

echo
echo "Python found."
echo


# ============================================================
# CREATE VIRTUAL ENVIRONMENT
# ============================================================

echo "[2/5] Creating virtual environment..."
echo

if [ ! -d ".venv" ]; then
    $PYTHON -m venv .venv

    if [ $? -ne 0 ]; then
        echo
        echo "ERROR: Could not create the virtual environment."
        echo
        echo "On Debian/Ubuntu, you may need:"
        echo
        echo "    sudo apt install python3-venv"
        echo
        exit 1
    fi

    echo "Virtual environment created."
else
    echo "Virtual environment already exists."
fi

echo


# ============================================================
# ACTIVATE VIRTUAL ENVIRONMENT
# ============================================================

echo "[3/5] Activating virtual environment..."
echo

source .venv/bin/activate

echo "Virtual environment activated."
echo


# ============================================================
# INSTALL PYTHON DEPENDENCIES
# ============================================================

echo "[4/5] Installing Python dependencies..."
echo

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo
echo "Python dependencies installed."
echo


# ============================================================
# CHECK / INSTALL FFMPEG
# ============================================================

echo "[5/5] Checking FFmpeg..."
echo

if command -v ffmpeg >/dev/null 2>&1; then

    echo "FFmpeg is already installed."
    echo
    ffmpeg -version | head -n 1

else

    echo "FFmpeg was not found."
    echo
    echo "Attempting to install FFmpeg..."
    echo

    # --------------------------------------------------------
    # Debian / Ubuntu
    # --------------------------------------------------------

    if command -v apt-get >/dev/null 2>&1; then

        echo "Detected Debian/Ubuntu-based Linux."
        echo

        sudo apt-get update
        sudo apt-get install -y ffmpeg

    # --------------------------------------------------------
    # Fedora / RHEL
    # --------------------------------------------------------

    elif command -v dnf >/dev/null 2>&1; then

        echo "Detected Fedora/RHEL-based Linux."
        echo

        sudo dnf install -y ffmpeg

    # --------------------------------------------------------
    # Arch Linux
    # --------------------------------------------------------

    elif command -v pacman >/dev/null 2>&1; then

        echo "Detected Arch Linux."
        echo

        sudo pacman -Sy --noconfirm ffmpeg

    # --------------------------------------------------------
    # openSUSE
    # --------------------------------------------------------

    elif command -v zypper >/dev/null 2>&1; then

        echo "Detected openSUSE."
        echo

        sudo zypper install -y ffmpeg

    else

        echo
        echo "ERROR: Could not determine your Linux package manager."
        echo
        echo "Please install FFmpeg manually."
        echo

        exit 1

    fi

fi


# ============================================================
# VERIFY FFMPEG
# ============================================================

echo
echo "Verifying FFmpeg..."
echo

if command -v ffmpeg >/dev/null 2>&1; then
    echo "FFmpeg installed successfully."
    ffmpeg -version | head -n 1
else
    echo
    echo "ERROR: FFmpeg could not be installed."
    echo
    exit 1
fi


# ============================================================
# FINISHED
# ============================================================

echo
echo "=========================================="
echo "       Installation Complete!"
echo "=========================================="
echo
echo "The AI Video Cutter is ready."
echo
echo "To start the application:"
echo
echo "    ./run_linux.sh"
echo
echo "Or manually:"
echo
echo "    source .venv/bin/activate"
echo "    python app.py"
echo