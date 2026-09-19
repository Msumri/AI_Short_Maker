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
    echo
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
# CHECK / INSTALL HOMEBREW
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

    # --------------------------------------------------------
    # Check Homebrew
    # --------------------------------------------------------

    if command -v brew >/dev/null 2>&1; then

        echo "Homebrew found."
        echo
        echo "Installing FFmpeg..."
        echo

        brew install ffmpeg

    else

        echo "Homebrew was not found."
        echo
        read -p "Install Homebrew automatically? [Y/n]: " INSTALL_BREW

        if [[ "$INSTALL_BREW" != "n" && "$INSTALL_BREW" != "N" ]]; then

            echo
            echo "Installing Homebrew..."
            echo

            /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

            # ------------------------------------------------
            # Refresh PATH for Apple Silicon
            # ------------------------------------------------

            if [ -x "/opt/homebrew/bin/brew" ]; then
                eval "$(/opt/homebrew/bin/brew shellenv)"
            fi

            # ------------------------------------------------
            # Refresh PATH for Intel Macs
            # ------------------------------------------------

            if [ -x "/usr/local/bin/brew" ]; then
                eval "$(/usr/local/bin/brew shellenv)"
            fi

            if ! command -v brew >/dev/null 2>&1; then
                echo
                echo "ERROR: Homebrew was installed but could not be found."
                echo
                echo "Please restart Terminal and run this installer again."
                echo
                exit 1
            fi

            echo
            echo "Homebrew installed successfully."
            echo

            brew install ffmpeg

        else

            echo
            echo "FFmpeg installation cancelled."
            echo
            echo "Please install FFmpeg manually."
            echo

            exit 1

        fi

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
echo "    ./run_mac.sh"
echo
echo "Or manually:"
echo
echo "    source .venv/bin/activate"
echo "    python app.py"
echo