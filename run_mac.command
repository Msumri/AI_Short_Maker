```bash
#!/bin/bash

# Find the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cd "$SCRIPT_DIR"

if [ ! -f ".venv/bin/activate" ]; then
    echo
    echo "ERROR: Virtual environment was not found."
    echo
    echo "Please run the installer first:"
    echo
    echo "    install_mac.command"
    echo
    read -p "Press Enter to close..."
    exit 1
fi

echo
echo "Starting AI Video Cutter..."
echo

source .venv/bin/activate

python app.py

echo
echo "AI Video Cutter has stopped."
echo

read -p "Press Enter to close..."
```
