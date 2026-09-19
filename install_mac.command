```bash
#!/bin/bash

set -e

# ============================================================
# AI VIDEO CUTTER - MAC INSTALLER
# Double-click this file to install
# ============================================================

echo
echo "=========================================="
echo "       AI Video Cutter Installer"
echo "=========================================="
echo

# ============================================================
# FIND INSTALL LOCATION
# ============================================================

INSTALL_DIR="$HOME/AI_Short_Maker"
REPO_URL="https://github.com/Msumri/AI_Short_Maker.git"

echo "Install location:"
echo "$INSTALL_DIR"
echo


# ============================================================
# CHECK GIT
# ============================================================

echo "[1/6] Checking Git..."
echo

if ! command -v git >/dev/null 2>&1; then
    echo "Git was not found."
    echo
    echo "Installing Xcode Command Line Tools..."
    echo

    xcode-select --install

    echo
    echo "Please complete the Xcode Command Line Tools installation,"
    echo "then run this installer again."
    echo

    read -p "Press Enter to close..."
    exit 1
fi

echo "Git found."
echo


# ============================================================
# CHECK PYTHON
# ============================================================

echo "[2/6] Checking Python..."
echo

if command -v python3 >/dev/null 2>&1; then
    PYTHON=python3
else
    echo
    echo "ERROR: Python 3 was not found."
    echo
    echo "Please install Python 3.11 or newer."
    echo
    read -p "Press Enter to close..."
    exit 1
fi

$PYTHON --version

echo
echo "Python found."
echo


# ============================================================
# DOWNLOAD / UPDATE PROJECT
# ============================================================

echo "[3/6] Getting AI Video Cutter..."
echo

if [ -d "$INSTALL_DIR/.git" ]; then

    echo "Existing installation found."
    echo "Updating..."
    echo

    cd "$INSTALL_DIR"
    git pull

else

    echo "Downloading AI Video Cutter..."
    echo

    rm -rf "$INSTALL_DIR"

    git clone "$REPO_URL" "$INSTALL_DIR"

    cd "$INSTALL_DIR"

fi

echo
echo "Project ready."
echo


# ============================================================
# CREATE VIRTUAL ENVIRONMENT
# ============================================================

echo "[4/6] Creating virtual environment..."
echo

if [ ! -d ".venv" ]; then

    $PYTHON -m venv .venv

    echo "Virtual environment created."

else

    echo "Virtual environment already exists."

fi

echo


# ============================================================
# ACTIVATE VIRTUAL ENVIRONMENT
# ============================================================

echo "Activating virtual environment..."
echo

source .venv/bin/activate

echo "Virtual environment activated."
echo


# ============================================================
# INSTALL PYTHON DEPENDENCIES
# ============================================================

echo "Installing Python dependencies..."
echo

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo
echo "Python dependencies installed."
echo


# ============================================================
# CHECK / INSTALL FFMPEG
# ============================================================

echo "[5/6] Checking FFmpeg..."
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
            # Apple Silicon
            # ------------------------------------------------

            if [ -x "/opt/homebrew/bin/brew" ]; then
                eval "$(/opt/homebrew/bin/brew shellenv)"
            fi

            # ------------------------------------------------
            # Intel Mac
            # ------------------------------------------------

            if [ -x "/usr/local/bin/brew" ]; then
                eval "$(/usr/local/bin/brew shellenv)"
            fi

            if ! command -v brew >/dev/null 2>&1; then

                echo
                echo "ERROR: Homebrew was installed but could not"
                echo "be found by this installer."
                echo
                echo "Please restart Terminal and run the installer again."
                echo

                read -p "Press Enter to close..."
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

            read -p "Press Enter to close..."
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

    read -p "Press Enter to close..."
    exit 1

fi


# ============================================================
# MAKE RUN SCRIPT EXECUTABLE
# ============================================================

echo
echo "[6/6] Finalizing installation..."
echo

if [ -f "$INSTALL_DIR/run_mac.sh" ]; then
    chmod +x "$INSTALL_DIR/run_mac.sh"
fi

echo
echo "=========================================="
echo "       Installation Complete!"
echo "=========================================="
echo
echo "AI Video Cutter has been installed to:"
echo
echo "    $INSTALL_DIR"
echo
echo "To start the application:"
echo
echo "    cd \"$INSTALL_DIR\""
echo "    ./run_mac.sh"
echo
echo "=========================================="
echo

read -p "Press Enter to close..."
```
