"""
Notebook import utility.
Imports .py or .ipynb files into Django models.
"""
import os
from django.utils.text import slugify
from typing import List, Optional


def import_notebook(filepath: str, name: Optional[str] = None,
                    description: str = "") -> 'Notebook':
    """
    Import a notebook file (.py or .ipynb) into the database.

    Args:
        filepath: Path to the notebook file
        name: Optional name (defaults to filename)
        description: Optional description

    Returns:
        Created Notebook instance
    """
    from .models import Notebook, Cell, Parameter
    from .parser import ColabNotebookParser

    if not os.path.exists(filepath):
        raise FileNotFoundError(f"File not found: {filepath}")

    # Parse the notebook
    parser = ColabNotebookParser()
    parsed_cells = parser.parse_file(filepath)

    # Create or update notebook
    if name is None:
        name = os.path.splitext(os.path.basename(filepath))[0]

    slug = slugify(name)

    # Check for existing notebook
    notebook, created = Notebook.objects.update_or_create(
        slug=slug,
        defaults={
            'name': name,
            'description': description,
            'source_file': filepath,
            'is_active': True,
        }
    )

    if not created:
        # Clear existing cells if updating
        notebook.cells.all().delete()

    # Create cells and parameters
    for order, parsed_cell in enumerate(parsed_cells):
        # Determine if this cell is executable (has parameters or is not just setup)
        is_executable = bool(parsed_cell.parameters) or not parsed_cell.is_setup_cell

        cell = Cell.objects.create(
            notebook=notebook,
            order=order,
            title=parsed_cell.title,
            cell_type=parsed_cell.cell_type,
            source_code=parsed_cell.source_code,
            description=parsed_cell.description,
            is_executable=is_executable,
            auto_run=parsed_cell.auto_run,
            is_setup_cell=parsed_cell.is_setup_cell,
        )

        # Create parameters
        for param_order, parsed_param in enumerate(parsed_cell.parameters):
            Parameter.objects.create(
                cell=cell,
                name=parsed_param.name,
                param_type=parsed_param.param_type,
                default_value=str(parsed_param.default_value) if parsed_param.default_value is not None else "",
                options=parsed_param.options,
                min_value=parsed_param.min_value,
                max_value=parsed_param.max_value,
                step=parsed_param.step,
                order=param_order,
            )

    return notebook


def import_tyk_demo(base_path: str = None) -> 'Notebook':
    """
    Import the TyK Demo notebook specifically.
    Handles the special structure of the demo notebook.
    """
    if base_path is None:
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # Look for the demo file
    demo_file = None
    for filename in ['tyk_demo_20251018.py', 'tyk_demo_20251018.ipynb']:
        path = os.path.join(base_path, filename)
        if os.path.exists(path):
            demo_file = path
            break

    if demo_file is None:
        raise FileNotFoundError(
            f"TyK demo notebook not found in {base_path}. "
            "Expected tyk_demo_20251018.py or tyk_demo_20251018.ipynb"
        )

    return import_notebook(
        filepath=demo_file,
        name="TyK Demo - October 2025",
        description="Interactive TyK analysis and visualization demo. "
                    "Explore clusters, networks, and bibliometric data."
    )


def list_available_notebooks(directory: str) -> List[str]:
    """List all importable notebooks in a directory"""
    notebooks = []
    for filename in os.listdir(directory):
        if filename.endswith('.py') or filename.endswith('.ipynb'):
            notebooks.append(os.path.join(directory, filename))
    return notebooks


def get_setup_code(notebook: 'Notebook') -> str:
    """
    Get all setup code that needs to run before interactive cells.
    This includes imports and class definitions.
    """
    setup_cells = notebook.cells.filter(is_setup_cell=True).order_by('order')
    return '\n\n'.join(cell.source_code for cell in setup_cells)
