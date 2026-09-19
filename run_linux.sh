#!/bin/bash

if [ ! -f ".venv/bin/activate" ]; then
    echo
    echo "ERROR: Virtual environment was not found."
    echo
    echo "Please run:"
    echo
    echo "    ./install_linux.sh"
    echo
    exit 1
fi

source .venv/bin/activate

python app.py