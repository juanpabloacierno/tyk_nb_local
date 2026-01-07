#!/usr/bin/env python
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
