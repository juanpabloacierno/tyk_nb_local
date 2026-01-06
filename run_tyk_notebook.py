#!/usr/bin/env python
"""
TyK Notebook - Single Click Launcher

Run this file to start the TyK Notebook application.
The browser will open automatically.

Usage:
    python run_tyk_notebook.py

For more options:
    python run_tyk_notebook.py --help
"""

import os
import sys
from pathlib import Path

# Add the app directory to path
APP_DIR = Path(__file__).parent / 'tyk_notebook_app'
sys.path.insert(0, str(APP_DIR.parent))
sys.path.insert(0, str(APP_DIR))

# Set the data path to current directory
os.environ.setdefault('TYK_DATA_PATH', str(Path(__file__).parent))

if __name__ == '__main__':
    from tyk_notebook_app.launcher import main
    main()
