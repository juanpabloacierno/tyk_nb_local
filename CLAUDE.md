# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TyK Notebook is a Django web application that converts Python notebooks (Jupyter/Colab-style) into interactive web interfaces with parameter controls. It allows users to execute data analysis code through a web UI without modifying source code.

## Common Commands

### Development Server
```bash
python tyk_app_entry.py [--port PORT] [--no-browser]
```
- Runs Django dev server on port 8000 by default
- Auto-opens browser and creates admin user (admin/admin)
- Access at http://localhost:8000/, admin at http://localhost:8000/admin/

### Build Standalone Executable
```bash
python build_app.py [--onefile] [--name NAME] [--clean]
```
- Creates standalone executable using PyInstaller
- Output in `dist/` folder

### Django Management
```bash
python -c "import os; os.environ['DJANGO_SETTINGS_MODULE']='tyk_notebook_app.settings'; import django; django.setup(); from django.core.management import call_command; call_command('migrate')"
```

## Architecture

### Data Flow
```
Notebook File (.py/.ipynb)
    → Parser (ColabNotebookParser)
    → Django Models (Notebook, Cell, Parameter)
    → Executor (isolated code execution)
    → Web Frontend (Django templates)
```

### Core Components

**Parser** (`tyk_notebook_app/parser.py`): Parses .py and .ipynb files, extracts cells and `@param`/`@title` directives (Colab-style). Supports parameter types: dropdown, string, number, boolean, slider.

**Executor** (`tyk_notebook_app/executor.py`): Runs Python code in isolated environments, captures stdout and HTML output (matplotlib, plotly), provides mock IPython.display module for Colab compatibility.

**Models** (`tyk_notebook_app/models.py`):
- `Notebook`: Container with name, slug, description
- `Cell`: Code/markdown cells with order, title, source_code
- `Parameter`: Cell inputs with type, default_value, options
- `Execution`: Execution history with output/errors
- `NotebookSession`: User session state, parameter values (JSON)

**Views** (`tyk_notebook_app/views.py`): Key endpoints:
- `/` - notebook list
- `/notebook/<slug>/` - interactive notebook interface
- `/notebook/<slug>/export/` - export notebook as .py file
- `/cell/<id>/run/` - execute single cell
- `/api/execute/` - REST API for programmatic access

**Importer/Exporter** (`tyk_notebook_app/importer.py`):
- `import_notebook(filepath, name, description)` - imports .py/.ipynb files into database
- `export_notebook(notebook)` - exports a Notebook model to Colab-style .py format

**TyK Class** (`tyk.py`): Specialized data analysis class for bibliometric/cluster analysis, works with networkx graphs, geolocation, JSON clusters. Used by demo notebooks.

### URL Routing
Main config in `tyk_notebook_app/urls_main.py` → `tyk_notebook_app/urls.py`

### Session Management
Per-user session state stored in `NotebookSession.parameter_values` (JSON field). Execution results persisted in `Execution` table.

## Tech Stack

- **Python 3.12+**, **Django 5.0+**, **SQLite**
- **Data**: pandas, numpy, networkx, plotly, matplotlib, pyvis, pycountry
- **Packaging**: PyInstaller for standalone executables
- **Frontend**: Django templates, CodeMirror (CDN)

## Key Patterns

- Uses Colab-compatible `@param` and `@title` directives for cell metadata
- Mock IPython.display module allows Colab code to run outside Jupyter
- Database stored in `tyk_notebook_app/db.sqlite3` (dev) or `tyk_data/db.sqlite3` (packaged)
- Demo data in `data/HVOA/` directory (bibliometric cluster data)

## Import/Export

### Importing Notebooks
```bash
python manage.py import_notebook path/to/notebook.py --name "My Notebook"
```
Or programmatically:
```python
from tyk_notebook_app.importer import import_notebook
notebook = import_notebook("path/to/file.py", name="My Notebook")
```

### Exporting Notebooks
- **UI**: Click the download icon on the notebook list page
- **URL**: GET `/notebook/<slug>/export/` returns a downloadable .py file
- **Programmatic**:
```python
from tyk_notebook_app.importer import export_notebook
from tyk_notebook_app.models import Notebook
nb = Notebook.objects.get(slug="my-notebook")
content = export_notebook(nb)  # Returns Colab-style Python string
```

Export format preserves all cells, parameters (`@param`), titles (`@title`), and markdown blocks. Exported files can be re-imported into any TyK Notebook instance.
