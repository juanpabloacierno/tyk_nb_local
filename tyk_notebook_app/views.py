"""
Django views for TyK Notebook Application.
Handles notebook display and cell execution.
"""
import json
import os
import markdown
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.db.models import Q

from .models import Notebook, Cell, Parameter, Execution, NotebookSession, DashboardChart
from .executor import session_manager
from .importer import export_notebook


@login_required
def notebook_list(request):
    """List all available notebooks"""
    notebooks = Notebook.objects.filter(is_active=True)
    return render(request, "notebook/list.html", {"notebooks": notebooks})


@login_required
def notebook_detail(request, slug):
    """Display a notebook with interactive cells"""
    notebook = get_object_or_404(Notebook, slug=slug, is_active=True)

    # Get notebook session for parameter persistence (per user)
    nb_session, created = NotebookSession.objects.get_or_create(
        notebook=notebook, user=request.user, defaults={"parameter_values": {}}
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

        # Convert description markdown to HTML
        description_html = ""
        if cell.description:
            description_html = markdown.markdown(
                cell.description,
                extensions=['fenced_code', 'tables', 'nl2br']
            )

        cells_data.append(
            {
                "cell": cell,
                "parameters": params_data,
                "has_params": len(params_data) > 0,
                "description_html": description_html,
            }
        )

    context = {
        "notebook": notebook,
        "cells_data": cells_data,
        "setup_complete": nb_session.kernel_state.get("setup_complete", False),
    }

    return render(request, "notebook/detail.html", context)


@login_required
@require_http_methods(["POST"])
def run_setup(request, slug):
    """Initialize the notebook session by running setup cells"""
    notebook = get_object_or_404(Notebook, slug=slug)

    # Get data path from settings or notebook metadata
    base_path = getattr(settings, "TYK_DATA_PATH", None)
    if not base_path:
        # Try to extract from notebook source
        base_path = os.path.dirname(notebook.source_file)

    # Create executor session (use user ID as session key)
    session_key = f"user_{request.user.id}"
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
        notebook=notebook, user=request.user
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


@login_required
@require_http_methods(["POST"])
def run_cell(request, cell_id):
    """Execute a single cell with provided parameters"""
    cell = get_object_or_404(Cell, id=cell_id)

    # Parse parameters from request
    try:
        data = json.loads(request.body)
        params = data.get("parameters", {})
    except json.JSONDecodeError:
        params = {}

    # Get executor (use user ID as session key)
    session_key = f"user_{request.user.id}"
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
        notebook=cell.notebook, user=request.user
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


@login_required
@require_http_methods(["POST"])
def reset_session(request, slug):
    """Reset the notebook session"""
    notebook = get_object_or_404(Notebook, slug=slug)

    # Reset executor session (use user ID as session key)
    session_key = f"user_{request.user.id}"
    session_manager.reset_session(session_key)

    # Reset DB session
    NotebookSession.objects.filter(
        notebook=notebook, user=request.user
    ).delete()

    return JsonResponse({"success": True})


@login_required
def get_cell_parameters(request, cell_id):
    """Get parameter form HTML for a cell"""
    cell = get_object_or_404(Cell, id=cell_id)
    parameters = cell.parameters.all()

    # Get current values from session
    current_values = {}
    try:
        nb_session = NotebookSession.objects.get(
            notebook=cell.notebook, user=request.user
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


@login_required
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


@login_required
def notebook_export(request, slug):
    """Export a notebook as a downloadable .py file"""
    notebook = get_object_or_404(Notebook, slug=slug, is_active=True)

    # Generate export content
    content = export_notebook(notebook)

    # Create response with file download
    response = HttpResponse(content, content_type='text/x-python')
    filename = f"{notebook.slug}.py"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    return response


@login_required
def dashboard_detail(request, slug):
    """Display a notebook with split-screen dashboard + cells layout"""
    notebook = get_object_or_404(Notebook, slug=slug, is_active=True)

    # Get notebook session for parameter persistence (per user)
    nb_session, created = NotebookSession.objects.get_or_create(
        notebook=notebook, user=request.user, defaults={"parameter_values": {}}
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

        description_html = ""
        if cell.description:
            description_html = markdown.markdown(
                cell.description,
                extensions=['fenced_code', 'tables', 'nl2br']
            )

        cells_data.append(
            {
                "cell": cell,
                "parameters": params_data,
                "has_params": len(params_data) > 0,
                "description_html": description_html,
            }
        )

    # Get dashboard charts from database or use defaults
    dashboard_charts = list(notebook.dashboard_charts.filter(is_active=True).order_by('order'))

    # If no charts configured, create default set
    if not dashboard_charts:
        default_chart_types = [
            ('world_map', 'Global Publications Map', {}),
            ('clusters_network', 'TOP Clusters Network', {}),
            ('subclusters_network', 'Subclusters Network', {}),
            ('cooc_network', 'Co-occurrence Network', {'node_type': 'K', 'max_nodes': 80}),
            ('cluster_stats', 'Cluster Details', {}),
        ]
        charts_data = [
            {
                'chart_type': ct,
                'title': title,
                'default_params': params,
                'needs_cluster': ct in ('subclusters_network', 'cluster_stats'),
            }
            for ct, title, params in default_chart_types
        ]
    else:
        charts_data = [
            {
                'chart_type': chart.chart_type.key,
                'title': chart.get_title(),
                'default_params': chart.default_params or {},
                'needs_cluster': chart.chart_type.key in ('subclusters_network', 'cluster_stats'),
            }
            for chart in dashboard_charts
        ]

    context = {
        "notebook": notebook,
        "cells_data": cells_data,
        "charts_data": charts_data,
        "charts_data_json": json.dumps(charts_data),
        "setup_complete": nb_session.kernel_state.get("setup_complete", False),
    }

    return render(request, "notebook/dashboard.html", context)


@login_required
@require_http_methods(["POST"])
def render_dashboard_chart(request, slug):
    """Render a single dashboard chart with given parameters"""
    notebook = get_object_or_404(Notebook, slug=slug)

    try:
        data = json.loads(request.body)
        chart_type = data.get("chart_type")
        params = data.get("params", {})
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    # Get executor session
    session_key = f"user_{request.user.id}"
    base_path = getattr(settings, "TYK_DATA_PATH", None)
    if not base_path:
        base_path = os.path.dirname(notebook.source_file)

    executor = session_manager.get_or_create_session(session_key, base_path=base_path)

    # Check if TyK is initialized in session
    if "tyk" not in executor.namespace:
        return JsonResponse({
            "error": "TyK not initialized. Please run setup first.",
            "needs_setup": True
        }, status=400)

    # Build code to execute based on chart_type
    code = _build_chart_code(chart_type, params)

    # Execute and capture output
    stdout, html, error, exec_time = executor.execute(code)

    return JsonResponse({
        "success": not error,
        "html": html,
        "stdout": stdout,
        "error": error,
        "execution_time": exec_time,
    })


def _build_chart_code(chart_type: str, params: dict) -> str:
    """Build Python code to generate a specific chart type"""

    if chart_type == "world_map":
        colorscale = params.get("colorscale", "Viridis")
        return f'tyk.plot_countries_map_global(colorscale="{colorscale}", height=350, method="modern")'

    elif chart_type == "clusters_network":
        min_weight = params.get("min_edge_weight", 0.0)
        return f'tyk.plot_clusters_graph_interactive(min_edge_weight={min_weight}, mode="inline")'

    elif chart_type == "subclusters_network":
        top_id = params.get("cluster_id", "1")
        min_weight = params.get("min_edge_weight", 0.0)
        return f'tyk.plot_subclusters_graph_interactive("{top_id}", min_edge_weight={min_weight}, mode="inline")'

    elif chart_type == "cooc_network":
        node_type = params.get("node_type", "K")
        max_nodes = params.get("max_nodes", 100)
        return f'tyk.plot_cooc_network_interactive(node_type="{node_type}", max_nodes={max_nodes}, height_px=400, mode="inline")'

    elif chart_type == "cluster_stats":
        cluster_id = params.get("cluster_id", "")
        stuff_type = params.get("stuff_type", "K")
        if cluster_id:
            return f'tyk.describe_cluster_params("TOP", "{stuff_type}", cluster_top="{cluster_id}")'
        return '# Select a cluster first'

    return "# Unknown chart type"


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
