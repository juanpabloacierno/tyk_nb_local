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
        # Determine if this cell is executable
        # Markdown cells are never executable
        if parsed_cell.cell_type == 'markdown':
            is_executable = False
        else:
            is_executable = bool(parsed_cell.parameters) or not parsed_cell.is_setup_cell

        cell = Cell.objects.create(
            notebook=notebook,
            order=order * 5,  # helps to insert some in-between elements if needed
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


def export_notebook(notebook: 'Notebook') -> str:
    """
    Export a notebook to Colab-style Python format.

    This format can be re-imported using import_notebook().

    Args:
        notebook: The Notebook instance to export

    Returns:
        String containing the notebook in .py format
    """
    import json

    lines = []

    # Add header comment
    lines.append(f'# -*- coding: utf-8 -*-')
    lines.append(f'"""')
    lines.append(f'TyK Notebook Export: {notebook.name}')
    if notebook.description:
        lines.append(f'')
        lines.append(notebook.description)
    lines.append(f'"""')
    lines.append('')

    # Export each cell
    cells = notebook.cells.all().order_by('order')

    for cell in cells:
        # Add cell separator
        lines.append('')

        if cell.cell_type == 'markdown':
            # Export markdown cells as triple-quoted strings
            lines.append('"""')
            lines.append(cell.source_code)
            lines.append('"""')
        else:
            # Code cell - add title directive if present
            title_line = ''
            if cell.title:
                title_line = f'# @title {cell.title}'
                if cell.auto_run:
                    title_line += ' {"run":"auto"}'
                lines.append(title_line)

            # Get source code lines
            source_lines = cell.source_code.split('\n')

            # Get parameters for this cell
            params = list(cell.parameters.all().order_by('order'))
            param_names = {p.name for p in params}

            # Process each line, adding @param directives where needed
            for source_line in source_lines:
                # Skip the original @title line if present
                if source_line.strip().startswith('# @title'):
                    continue

                # Check if this line contains a parameter assignment
                param_added = False
                for param in params:
                    # Match: var_name = value (potentially with existing @param)
                    import re
                    pattern = rf'^(\s*)({re.escape(param.name)})\s*=\s*([^#\n]+)'
                    match = re.match(pattern, source_line)

                    if match:
                        indent = match.group(1)
                        var_name = match.group(2)
                        # Use default value from parameter model
                        default_val = _format_default_value(param.default_value, param.param_type)
                        param_spec = _format_param_spec(param)

                        lines.append(f'{indent}{var_name} = {default_val}  # @param {param_spec}')
                        param_added = True
                        break

                if not param_added:
                    # Regular line - skip if it has @param (we've handled params above)
                    if '# @param' not in source_line:
                        lines.append(source_line)

    return '\n'.join(lines)


def _format_default_value(value: str, param_type: str) -> str:
    """Format a default value for export based on parameter type."""
    if param_type == 'boolean':
        return 'True' if value.lower() in ('true', '1', 'yes') else 'False'
    elif param_type == 'number' or param_type == 'slider':
        try:
            # Try to preserve as number
            if '.' in str(value):
                return str(float(value))
            return str(int(value))
        except (ValueError, TypeError):
            return '0'
    elif param_type == 'string':
        # Escape quotes in string
        escaped = str(value).replace('"', '\\"')
        return f'"{escaped}"'
    elif param_type == 'dropdown':
        # For dropdowns, quote if string
        try:
            # Check if it's a number
            float(value)
            return str(value)
        except (ValueError, TypeError):
            escaped = str(value).replace('"', '\\"')
            return f'"{escaped}"'
    else:
        # Default: treat as string
        escaped = str(value).replace('"', '\\"')
        return f'"{escaped}"'


def _format_param_spec(param) -> str:
    """Format the @param specification for a parameter."""
    import json

    if param.param_type == 'dropdown' and param.options:
        # Dropdown: list of options
        return json.dumps(param.options)
    elif param.param_type == 'boolean':
        return '{"type":"boolean"}'
    elif param.param_type == 'string':
        return '{"type":"string"}'
    elif param.param_type == 'slider':
        spec = {
            "type": "slider",
            "min": param.min_value or 0,
            "max": param.max_value or 100,
            "step": param.step or 1
        }
        return json.dumps(spec)
    elif param.param_type == 'number':
        return '{"type":null}'
    else:
        return '{"type":"string"}'
