#!/usr/bin/env python
"""
TyK Notebook App Builder

Creates a standalone executable that can run on Windows, Linux, or macOS.
Uses PyInstaller to bundle Python and all dependencies.

Usage:
    python build_app.py [--onefile] [--name NAME] [--clean]

Options:
    --onefile    Create a single executable file (slower startup, easier distribution)
    --name       Name for the executable (default: tyk-notebook)
    --clean      Clean build artifacts before building
"""

import os
import sys
import shutil
import subprocess
import argparse
from pathlib import Path

# Directories
BASE_DIR = Path(__file__).resolve().parent
APP_DIR = BASE_DIR / "tyk_notebook_app"
BUILD_DIR = BASE_DIR / "build"
DIST_DIR = BASE_DIR / "dist"


def check_pyinstaller():
    """Check if PyInstaller is installed, install if not"""
    try:
        import PyInstaller
        print(f"PyInstaller {PyInstaller.__version__} found")
    except ImportError:
        print("PyInstaller not found. Installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        print("PyInstaller installed successfully")


def create_entry_point():
    """Create the main entry point script for the packaged app"""
    entry_script = BASE_DIR / "tyk_app_entry.py"

    content = '''#!/usr/bin/env python
"""
TyK Notebook Application - Standalone Entry Point
This is the main entry point for the packaged application.
"""
import os
import sys
import webbrowser
import threading
import time

# Handle frozen application (PyInstaller)
if getattr(sys, 'frozen', False):
    # Running as compiled
    BASE_DIR = sys._MEIPASS
    RUNTIME_DIR = os.path.dirname(sys.executable)
else:
    # Running as script
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    RUNTIME_DIR = BASE_DIR

# Add paths
sys.path.insert(0, BASE_DIR)

# Set up Django settings
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tyk_notebook_app.settings")

# Configure database path to be in runtime directory (writable)
os.environ["TYK_DB_PATH"] = os.path.join(RUNTIME_DIR, "tyk_data")
os.environ["TYK_DATA_PATH"] = RUNTIME_DIR


def ensure_data_dir():
    """Ensure the data directory exists"""
    data_dir = os.environ.get("TYK_DB_PATH", os.path.join(RUNTIME_DIR, "tyk_data"))
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


def setup_django():
    """Initialize Django"""
    import django
    django.setup()


def run_migrations():
    """Run database migrations"""
    from django.core.management import call_command
    print("Setting up database...")
    call_command("migrate", verbosity=0)


def create_admin_user():
    """Create admin user if it doesn't exist"""
    from django.contrib.auth import get_user_model
    User = get_user_model()

    if not User.objects.filter(username="admin").exists():
        User.objects.create_superuser(
            username="admin",
            email="admin@localhost",
            password="admin"
        )
        print("Created admin user (username: admin, password: admin)")


def import_notebooks():
    """Import demo notebooks if not already imported"""
    from tyk_notebook_app.models import Notebook

    if Notebook.objects.exists():
        return

    # Look for notebooks in runtime directory
    from tyk_notebook_app.importer import import_notebook

    notebook_files = [
        "PruebaTYK.ipynb",
        "pruebatyk.py",
        "tyk_demo_20251018.ipynb",
        "tyk_demo_20251018.py",
    ]

    for filename in notebook_files:
        filepath = os.path.join(RUNTIME_DIR, filename)
        if os.path.exists(filepath):
            try:
                notebook = import_notebook(
                    filepath=filepath,
                    name=os.path.splitext(filename)[0],
                    description="Imported notebook"
                )
                print(f"Imported: {notebook.name}")
            except Exception as e:
                print(f"Warning: Could not import {filename}: {e}")
            break


def open_browser(port):
    """Open browser after a short delay"""
    time.sleep(2)
    url = f"http://localhost:{port}/"
    print(f"Opening browser at {url}")
    webbrowser.open(url)


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="TyK Notebook Application")
    parser.add_argument("--port", type=int, default=8000, help="Port to run on")
    parser.add_argument("--no-browser", action="store_true", help="Don't open browser")
    args = parser.parse_args()

    print("=" * 50)
    print("  TyK Notebook Application")
    print("=" * 50)
    print()

    # Setup
    ensure_data_dir()
    setup_django()
    run_migrations()
    create_admin_user()
    import_notebooks()

    # Start browser thread
    if not args.no_browser:
        browser_thread = threading.Thread(target=open_browser, args=(args.port,))
        browser_thread.daemon = True
        browser_thread.start()

    print()
    print("=" * 50)
    print(f"  Server: http://localhost:{args.port}/")
    print(f"  Admin:  http://localhost:{args.port}/admin/")
    print("  Login:  admin / admin")
    print("=" * 50)
    print()
    print("Press Ctrl+C to stop the server")
    print()

    # Run server
    from django.core.management import call_command
    call_command("runserver", f"0.0.0.0:{args.port}", use_reloader=False)


if __name__ == "__main__":
    main()
'''

    with open(entry_script, "w") as f:
        f.write(content)

    print(f"Created entry point: {entry_script}")
    return entry_script


def create_runtime_settings():
    """Create a settings module that works for the packaged app"""
    settings_path = APP_DIR / "settings_packaged.py"

    content = '''"""
Django settings for packaged TyK Notebook Application.
"""
import os
import sys
from pathlib import Path

# Handle frozen application
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys._MEIPASS) / "tyk_notebook_app"
    RUNTIME_DIR = Path(os.path.dirname(sys.executable))
else:
    BASE_DIR = Path(__file__).resolve().parent
    RUNTIME_DIR = BASE_DIR.parent

# Data directory (writable location)
DATA_DIR = Path(os.environ.get("TYK_DB_PATH", RUNTIME_DIR / "tyk_data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

SECRET_KEY = 'tyk-notebook-standalone-key-change-in-production'

DEBUG = True

ALLOWED_HOSTS = ['localhost', '127.0.0.1', '0.0.0.0', '*']

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'tyk_notebook_app',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'tyk_notebook_app.urls_main'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': DATA_DIR / 'db.sqlite3',
    }
}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# TyK specific settings
TYK_DATA_PATH = os.environ.get('TYK_DATA_PATH', str(RUNTIME_DIR))
'''

    with open(settings_path, "w") as f:
        f.write(content)

    print(f"Created packaged settings: {settings_path}")
    return settings_path


def create_spec_file(entry_script, name, onefile):
    """Create PyInstaller spec file"""
    spec_path = BASE_DIR / f"{name}.spec"

    # Collect data files
    datas = [
        (str(APP_DIR / "templates"), "tyk_notebook_app/templates"),
        (str(APP_DIR / "migrations"), "tyk_notebook_app/migrations"),
    ]

    # Add static files if they exist
    static_dir = APP_DIR / "static"
    if static_dir.exists():
        datas.append((str(static_dir), "tyk_notebook_app/static"))

    # Format datas for spec file
    datas_str = ",\n        ".join([f"('{src}', '{dst}')" for src, dst in datas])

    # Hidden imports for Django and dependencies
    hidden_imports = [
        'django.contrib.admin',
        'django.contrib.auth',
        'django.contrib.contenttypes',
        'django.contrib.sessions',
        'django.contrib.messages',
        'django.contrib.staticfiles',
        'django.template.backends.django',
        'django.db.backends.sqlite3',
        'tyk_notebook_app',
        'tyk_notebook_app.models',
        'tyk_notebook_app.views',
        'tyk_notebook_app.admin',
        'tyk_notebook_app.urls',
        'tyk_notebook_app.urls_main',
        'tyk_notebook_app.executor',
        'tyk_notebook_app.importer',
        'tyk_notebook_app.parser',
        'pandas',
        'numpy',
        'plotly',
        'plotly.graph_objs',
        'plotly.io',
        'networkx',
        'matplotlib',
        'matplotlib.pyplot',
    ]

    hidden_imports_str = ",\n        ".join([f"'{imp}'" for imp in hidden_imports])

    spec_content = f'''# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for TyK Notebook Application
Generated by build_app.py
"""

block_cipher = None

a = Analysis(
    ['{entry_script}'],
    pathex=['{BASE_DIR}'],
    binaries=[],
    datas=[
        {datas_str}
    ],
    hiddenimports=[
        {hidden_imports_str}
    ],
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

'''

    if onefile:
        spec_content += f'''exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='{name}',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
'''
    else:
        spec_content += f'''exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='{name}',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='{name}',
)
'''

    with open(spec_path, "w") as f:
        f.write(spec_content)

    print(f"Created spec file: {spec_path}")
    return spec_path


def clean_build():
    """Clean build artifacts"""
    dirs_to_clean = [BUILD_DIR, DIST_DIR]
    files_to_clean = list(BASE_DIR.glob("*.spec"))

    for d in dirs_to_clean:
        if d.exists():
            print(f"Removing {d}")
            shutil.rmtree(d)

    for f in files_to_clean:
        print(f"Removing {f}")
        f.unlink()

    # Clean generated files
    entry_script = BASE_DIR / "tyk_app_entry.py"
    if entry_script.exists():
        entry_script.unlink()

    settings_packaged = APP_DIR / "settings_packaged.py"
    if settings_packaged.exists():
        settings_packaged.unlink()

    print("Build artifacts cleaned")


def build(name, onefile):
    """Build the application"""
    check_pyinstaller()

    # Create necessary files
    entry_script = create_entry_point()
    create_runtime_settings()

    # Update settings to use packaged settings
    settings_file = APP_DIR / "settings.py"
    settings_backup = APP_DIR / "settings.py.backup"

    # Backup original settings
    if settings_file.exists() and not settings_backup.exists():
        shutil.copy(settings_file, settings_backup)

    # Create spec file
    spec_path = create_spec_file(entry_script, name, onefile)

    # Run PyInstaller
    print()
    print("=" * 50)
    print("  Building application with PyInstaller...")
    print("=" * 50)
    print()

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--clean",
        "--noconfirm",
        str(spec_path)
    ]

    try:
        subprocess.check_call(cmd, cwd=str(BASE_DIR))
        print()
        print("=" * 50)
        print("  Build completed successfully!")
        print("=" * 50)
        print()

        if onefile:
            if sys.platform == "win32":
                exe_name = f"{name}.exe"
            else:
                exe_name = name
            exe_path = DIST_DIR / exe_name
            print(f"  Executable: {exe_path}")
        else:
            print(f"  Application folder: {DIST_DIR / name}")
            print(f"  Run: {DIST_DIR / name / name}")

        print()
        print("  To run the application:")
        print(f"    ./{name} --port 8000")
        print()

    except subprocess.CalledProcessError as e:
        print(f"Build failed with error: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Build TyK Notebook as a standalone application"
    )
    parser.add_argument(
        "--onefile",
        action="store_true",
        help="Create a single executable file"
    )
    parser.add_argument(
        "--name",
        default="tyk-notebook",
        help="Name for the executable (default: tyk-notebook)"
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Clean build artifacts before building"
    )
    parser.add_argument(
        "--clean-only",
        action="store_true",
        help="Only clean build artifacts, don't build"
    )

    args = parser.parse_args()

    if args.clean or args.clean_only:
        clean_build()
        if args.clean_only:
            return

    build(args.name, args.onefile)


if __name__ == "__main__":
    main()
