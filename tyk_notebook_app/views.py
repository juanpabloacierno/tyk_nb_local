"""
Django views for TyK Notebook Application.
Handles notebook display and cell execution.
"""
import json
import os
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.db.models import Q

from .models import Notebook, Cell, Parameter, Execution, NotebookSession
from .executor import session_manager


def notebook_list(request):
    """List all available notebooks"""
    notebooks = Notebook.objects.filter(is_active=True)
    return render(request, "notebook/list.html", {"notebooks": notebooks})


def notebook_detail(request, slug):
    """Display a notebook with interactive cells"""
    notebook = get_object_or_404(Notebook, slug=slug, is_active=True)

    # Get or create session
    session_key = request.session.session_key
    if not session_key:
        request.session.create()
        session_key = request.session.session_key

    # Get notebook session for parameter persistence
    nb_session, created = NotebookSession.objects.get_or_create(
        notebook=notebook, session_key=session_key, defaults={"parameter_values": {}}
    )

    # Get cells with their parameters (executable cells + markdown cells)
    cells = notebook.cells.filter(
        Q(is_executable=True) | Q(cell_type='markdown')
    ).prefetch_related("parameters")

    # Build cell data with current parameter values
    cells_data = []
    for cell in cells:
        params_data = []
        for param in cell.parameters.all():
            # Get value from session or use default
            current_value = nb_session.parameter_values.get(
                f"{cell.id}_{param.name}", param.default_value
            )
            params_data.append(
                {
                    "id": param.id,
                    "name": param.name,
                    "type": param.param_type,
                    "value": current_value,
                    "default": param.default_value,
                    "options": param.get_options_list(),
                    "min": param.min_value,
                    "max": param.max_value,
                    "step": param.step,
                }
            )

        cells_data.append(
            {
                "cell": cell,
                "parameters": params_data,
                "has_params": len(params_data) > 0,
            }
        )

    context = {
        "notebook": notebook,
        "cells_data": cells_data,
        "session_key": session_key,
        "setup_complete": nb_session.kernel_state.get("setup_complete", False),
    }

    return render(request, "notebook/detail.html", context)


@require_http_methods(["POST"])
def run_setup(request, slug):
    """Initialize the notebook session by running setup cells"""
    notebook = get_object_or_404(Notebook, slug=slug)

    session_key = request.session.session_key
    if not session_key:
        return JsonResponse({"error": "No session"}, status=400)

    # Get data path from settings or notebook metadata
    base_path = getattr(settings, "TYK_DATA_PATH", None)
    if not base_path:
        # Try to extract from notebook source
        base_path = os.path.dirname(notebook.source_file)

    # Create executor session
    executor = session_manager.get_or_create_session(session_key, base_path=base_path)

    # Run setup cells
    setup_cells = notebook.cells.filter(is_setup_cell=True).order_by("order")

    all_output = []
    errors = []

    for cell in setup_cells:
        stdout, html, error, exec_time = executor.execute(cell.source_code)
        all_output.append(f"=== {cell.title or 'Setup'} ===\n{stdout}")
        if error:
            errors.append(f"{cell.title}: {error}")

    # Update session state
    nb_session, _ = NotebookSession.objects.get_or_create(
        notebook=notebook, session_key=session_key
    )
    nb_session.kernel_state["setup_complete"] = len(errors) == 0
    nb_session.save()

    return JsonResponse(
        {
            "success": len(errors) == 0,
            "output": "\n".join(all_output),
            "errors": errors,
        }
    )


@require_http_methods(["POST"])
def run_cell(request, cell_id):
    """Execute a single cell with provided parameters"""
    cell = get_object_or_404(Cell, id=cell_id)

    session_key = request.session.session_key
    if not session_key:
        return JsonResponse({"error": "No session"}, status=400)

    # Parse parameters from request
    try:
        data = json.loads(request.body)
        params = data.get("parameters", {})
    except json.JSONDecodeError:
        params = {}

    # Get executor
    base_path = getattr(settings, "TYK_DATA_PATH", None)
    if not base_path:
        base_path = os.path.dirname(cell.notebook.source_file)

    executor = session_manager.get_or_create_session(session_key, base_path=base_path)

    # Execute cell
    stdout, html, error, exec_time = executor.execute(cell.source_code, params)

    # Record execution
    execution = Execution.objects.create(
        cell=cell,
        parameters=params,
        status="error" if error else "success",
        output_text=stdout,
        output_html=html,
        error_message=error,
        execution_time=exec_time,
    )

    # Save parameter values to session
    nb_session, _ = NotebookSession.objects.get_or_create(
        notebook=cell.notebook, session_key=session_key
    )
    for param_name, value in params.items():
        nb_session.parameter_values[f"{cell.id}_{param_name}"] = value
    nb_session.last_executed_cell = cell
    nb_session.save()

    return JsonResponse(
        {
            "success": not error,
            "output_text": stdout,
            "output_html": html,
            "error": error,
            "execution_time": exec_time,
            "execution_id": execution.id,
        }
    )


@require_http_methods(["POST"])
def reset_session(request, slug):
    """Reset the notebook session"""
    notebook = get_object_or_404(Notebook, slug=slug)

    session_key = request.session.session_key
    if session_key:
        session_manager.reset_session(session_key)

        # Reset DB session
        NotebookSession.objects.filter(
            notebook=notebook, session_key=session_key
        ).delete()

    return JsonResponse({"success": True})


def get_cell_parameters(request, cell_id):
    """Get parameter form HTML for a cell"""
    cell = get_object_or_404(Cell, id=cell_id)
    parameters = cell.parameters.all()

    # Get current values from session
    session_key = request.session.session_key
    current_values = {}
    if session_key:
        try:
            nb_session = NotebookSession.objects.get(
                notebook=cell.notebook, session_key=session_key
            )
            for param in parameters:
                key = f"{cell.id}_{param.name}"
                if key in nb_session.parameter_values:
                    current_values[param.name] = nb_session.parameter_values[key]
        except NotebookSession.DoesNotExist:
            pass

    params_data = []
    for param in parameters:
        params_data.append(
            {
                "id": param.id,
                "name": param.name,
                "type": param.param_type,
                "value": current_values.get(param.name, param.default_value),
                "options": param.get_options_list(),
                "min": param.min_value,
                "max": param.max_value,
                "step": param.step,
            }
        )

    return render(
        request,
        "notebook/partials/parameter_form.html",
        {
            "cell": cell,
            "parameters": params_data,
        },
    )


def execution_history(request, slug):
    """View execution history for a notebook"""
    notebook = get_object_or_404(Notebook, slug=slug)
    executions = (
        Execution.objects.filter(cell__notebook=notebook)
        .select_related("cell")
        .order_by("-created_at")[:100]
    )

    return render(
        request,
        "notebook/history.html",
        {
            "notebook": notebook,
            "executions": executions,
        },
    )


# API views for programmatic access
@csrf_exempt
@require_http_methods(["POST"])
def api_execute(request):
    """API endpoint for executing code"""
    try:
        data = json.loads(request.body)
        code = data.get("code", "")
        params = data.get("parameters", {})
        session_id = data.get("session_id")

        if not session_id:
            session_id, executor = session_manager.create_session()
        else:
            executor = session_manager.get_or_create_session(session_id)

        stdout, html, error, exec_time = executor.execute(code, params)

        return JsonResponse(
            {
                "success": not error,
                "session_id": session_id,
                "output_text": stdout,
                "output_html": html,
                "error": error,
                "execution_time": exec_time,
            }
        )

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
