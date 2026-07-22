"""
Django views for TyK Notebook Application.
Handles notebook display and cell execution.
"""
import json
import mimetypes
import os
import markdown
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponse, FileResponse, Http404
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.db.models import Q
from django.utils.translation import get_language

from .models import Notebook, Cell, Parameter, Execution, NotebookSession, DashboardChart
from .executor import session_manager
from .importer import export_notebook

# Injected after every venn_interactive.html to enforce the INeS_GPE color scheme.
# Singles are light/pastel; pairwise intersections are mid-saturated; triple is darkest.
# Opacity increases with overlap depth so intersections stand out clearly.
_VENN_STYLE_OVERRIDE = """
<style>
  html, body { padding: 0; margin: 0; }
  .venn-container { max-width: 100%; padding: 10px 10px 0 10px; }
  h1 { font-size: 13px; margin: 0 0 2px 0; }
  .subtitle { font-size: 11px; margin: 0 0 6px 0; }
  #venn { width: 100%; height: auto !important; }
  .stats-table { font-size: 11px; margin: 0; width: 100%; }
  .stats-table th, .stats-table td { padding: 4px 8px; }
  .color-dot { width: 9px; height: 9px; margin-right: 5px; }
</style>
<script>
(function() {
    var TYK_SINGLE_COLORS = ["#c7e9b4", "#7fcdbb", "#1d91c0"];
    var TYK_PAIR_COLORS   = ["#a4dbc0", "#74c6c2", "#41b6c4"];
    var TYK_TRIPLE_COLOR  = "#225ea8";
    var _layoutDone = false;

    function applyTykVennStyle() {
        if (typeof d3 === "undefined" || d3.select("#venn").empty()) {
            setTimeout(applyTykVennStyle, 50);
            return;
        }

        var div = d3.select("#venn");
        var singleIdx = 0, pairIdx = 0;
        var renderedColors = [];
        div.selectAll("g").each(function(d) {
            if (!d || !d.sets) return;
            var g = d3.select(this);
            var path = g.select("path");
            var color;

            if (d.sets.length === 1) {
                color = TYK_SINGLE_COLORS[singleIdx++ % TYK_SINGLE_COLORS.length];
                path.style("fill", color)
                    .style("fill-opacity", 0.45)
                    .style("stroke", "#ffffff")
                    .style("stroke-width", "1.5px");
            } else if (d.sets.length === 2) {
                color = TYK_PAIR_COLORS[pairIdx++ % TYK_PAIR_COLORS.length];
                path.style("fill", color)
                    .style("fill-opacity", 0.72)
                    .style("stroke", "#ffffff")
                    .style("stroke-width", "1.5px");
            } else {
                color = TYK_TRIPLE_COLOR;
                path.style("fill", color)
                    .style("fill-opacity", 0.88)
                    .style("stroke", "#ffffff")
                    .style("stroke-width", "1.5px");
            }
            renderedColors.push(color);

            g.select("text")
                .style("fill", "#f0f4f8")
                .style("stroke", "#1a2e40")
                .style("stroke-width", "2.5px")
                .style("paint-order", "stroke")
                .style("font-size", "13px")
                .style("font-weight", "bold");
        });

        var dots = document.querySelectorAll(".color-dot");
        dots.forEach(function(dot, i) {
            dot.style.background = renderedColors[i] || TYK_TRIPLE_COLOR;
        });
        document.querySelectorAll(".stats-table th").forEach(function(th) {
            th.style.background = "#eef2f7";
        });
        document.querySelectorAll(".stats-table tr").forEach(function(tr) {
            if (tr.style.background && tr.style.background !== "") {
                tr.style.background = "#eef2f7";
            }
        });
    }

    function applyTykVennLayout() {
        var vennEl  = document.getElementById("venn");
        var tableEl = document.querySelector(".stats-table");
        var container = document.querySelector(".venn-container");
        if (!vennEl || !tableEl || !container) { setTimeout(applyTykVennLayout, 50); return; }
        var svg = vennEl.querySelector("svg");
        if (!svg) { setTimeout(applyTykVennLayout, 50); return; }
        if (_layoutDone) return;
        _layoutDone = true;

        // Make SVG responsive at a smaller height
        var origW = parseFloat(svg.getAttribute("width")) || 800;
        var origH = parseFloat(svg.getAttribute("height")) || 500;
        svg.setAttribute("viewBox", "0 0 " + origW + " " + origH);
        svg.setAttribute("width", "100%");
        svg.setAttribute("height", "320");

        // Side-by-side layout: diagram left, table right
        var wrapper = document.createElement("div");
        wrapper.style.cssText = "display:flex; gap:16px; align-items:flex-start;";

        var vennWrap = document.createElement("div");
        vennWrap.style.cssText = "flex:1 1 0; min-width:0;";
        vennWrap.appendChild(vennEl);

        var tableWrap = document.createElement("div");
        tableWrap.style.cssText = "flex:0 0 240px;";
        tableWrap.appendChild(tableEl);

        wrapper.appendChild(vennWrap);
        wrapper.appendChild(tableWrap);
        container.appendChild(wrapper);
    }

    applyTykVennStyle();
    applyTykVennLayout();
})();
</script>
"""


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
        is_active=True
    ).filter(
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
    setup_cells = notebook.cells.filter(is_active=True, is_setup_cell=True).order_by("order")

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
        is_active=True
    ).filter(
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

    # Default chart list (always shown)
    default_chart_types = [
        ('world_map', 'Global Publications Map', {}),
        ('clusters_network', 'TOP Clusters Network', {}),
        ('subclusters_network', 'Subclusters Network', {}),
        ('cooc_network', 'Co-occurrence Network', {'node_type': 'K', 'max_nodes': 80}),
        ('cluster_stats', 'Cluster Details', {}),
        ('venn_diagram', 'Venn Diagram', {}),
    ]

    # Build a lookup of ALL DB-configured charts by chart_type key (active and inactive)
    db_charts = {
        chart.chart_type.key: chart
        for chart in notebook.dashboard_charts.all().prefetch_related('parameters').select_related('chart_type')
    }

    # Build entries with sort key: DB order when configured, else fallback index * 100
    raw_charts = []
    for idx, (ct, default_title, default_params) in enumerate(default_chart_types):
        db_chart = db_charts.get(ct)
        # Skip chart types explicitly disabled in DB
        if db_chart is not None and not db_chart.is_active:
            continue
        sort_key = db_chart.order if db_chart is not None else idx * 100
        entry = {
            'chart_type': ct,
            'title': db_chart.get_title() if db_chart else default_title,
            'default_params': (db_chart.default_params or default_params) if db_chart else default_params,
            'needs_cluster': ct in ('subclusters_network', 'cluster_stats'),
            'param_defs': [
                {
                    'name': p.name,
                    'label': p.get_label(),
                    'type': p.param_type,
                    'value': p.default_value,
                    'options': p.get_options_list(),
                    'min': p.min_value,
                    'max': p.max_value,
                    'step': p.step,
                }
                for p in db_chart.parameters.all()
            ] if db_chart else [],
        }
        raw_charts.append((sort_key, entry))

    charts_data = [entry for _, entry in sorted(raw_charts, key=lambda x: x[0])]

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

    # Handle static file charts
    if chart_type == "venn_diagram":
        tyk_obj = executor.get_variable("tyk")
        if tyk_obj and getattr(tyk_obj, "dat_folder", None):
            path_var = tyk_obj.dat_folder
        elif tyk_obj and getattr(tyk_obj, "path_base", None):
            path_var = tyk_obj.path_base
        else:
            path_var = executor.get_variable("PATH")
        if not path_var:
            return JsonResponse({"success": False, "error": "PATH not set. Please run setup first.", "needs_setup": True})
        venn_path = os.path.join(path_var, "venn_interactive.html")
        if not os.path.isfile(venn_path):
            return JsonResponse({"success": False, "error": f"venn_interactive.html not found at {venn_path}"})
        with open(venn_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        html_content += _VENN_STYLE_OVERRIDE
        return JsonResponse({"success": True, "html": html_content, "stdout": "", "error": "", "execution_time": 0})

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
        _node_type_map = {
            "Keywords": "K",
            "Title Words": "TK",
            "Subject Categories": "S",
            "Subject Sub-Categories": "S2",
            "Journal Sources": "J",
            "Countries": "C",
            "Institutions": "I",
            "References": "R",
            "Reference Sources": "RJ",
            "Authors (Freq)": "A",
        }
        raw_node_type = params.get("node_type", "K")
        node_type = _node_type_map.get(raw_node_type, raw_node_type)
        max_nodes = params.get("max_nodes", 100)
        return f'tyk.plot_cooc_network_interactive(node_type="{node_type}", max_nodes={max_nodes}, height_px=400, mode="inline")'

    elif chart_type == "cluster_stats":
        cluster_id = params.get("cluster_id", "")
        stuff_type = params.get("stuff_type", "K")
        if cluster_id:
            return f'tyk.describe_cluster_params("TOP", "{stuff_type}", cluster_top="{cluster_id}")'
        return '# Select a cluster first'

    return "# Unknown chart type"


@login_required
@require_http_methods(["GET"])
def notebook_dataset_info(request, slug):
    """Return dataset metadata, cluster PDF links, and freq file links for the info panel."""
    import glob

    notebook = get_object_or_404(Notebook, slug=slug, is_active=True)
    session_key = f"user_{request.user.id}"
    executor = session_manager.sessions.get(session_key)
    if not executor:
        return JsonResponse({"ready": False})

    tyk_obj = executor.get_variable("tyk")
    if not tyk_obj:
        return JsonResponse({"ready": False})

    path_base = getattr(tyk_obj, "path_base", None)
    if not path_base or not os.path.isdir(path_base):
        return JsonResponse({"ready": False})

    tyk_data_root = os.path.normpath(getattr(settings, "TYK_DATA_PATH", path_base))

    def _rel_url(abs_path):
        rel = os.path.relpath(abs_path, tyk_data_root).replace(os.sep, "/")
        return f"/pdf/{rel}"

    # --- Article count ---
    article_count = 0
    articles_path = os.path.join(path_base, "articles.dat")
    if os.path.isfile(articles_path):
        with open(articles_path, encoding="utf-8-sig", errors="ignore") as f:
            article_count = sum(1 for ln in f if ln.strip())

    # --- Source databases ---
    databases = []
    db_path = os.path.join(path_base, "database.dat")
    if os.path.isfile(db_path):
        with open(db_path, encoding="utf-8-sig", errors="ignore") as f:
            databases = [ln.strip() for ln in f if ln.strip()]

    # --- General report PDF (dataset root, then clusters/ subfolder) ---
    general_report = None
    for candidate in ["report.pdf", "general_report.pdf"]:
        fp = os.path.join(path_base, candidate)
        if os.path.isfile(fp):
            general_report = {"url": _rel_url(fp), "name": candidate}
            break
    if not general_report:
        # The global overview PDF lives at the dataset root in some datasets and
        # under clusters/ in others — check the root first, then clusters/.
        for pattern in [
            os.path.join(path_base, "global_overview_report*.pdf"),
            os.path.join(path_base, "clusters", "global_overview_report*.pdf"),
        ]:
            matches = sorted(glob.glob(pattern))
            if matches:
                general_report = {"url": _rel_url(matches[0]), "name": os.path.basename(matches[0])}
                break
    if not general_report:
        for fp in sorted(glob.glob(os.path.join(path_base, "*.pdf"))):
            general_report = {"url": _rel_url(fp), "name": os.path.basename(fp)}
            break

    # --- General summary (root-level text, localized) ---
    general_summary = None
    current_lang = (get_language() or "en").split("-")[0]
    summary_candidates = ["executive_abstract.txt", "cluster_overview.txt", "summary.txt"]
    if current_lang == "en":
        summary_candidates = ["global_overview.txt"] + summary_candidates
    else:
        summary_candidates = [f"global_overview_{current_lang}.txt", "global_overview.txt"] + summary_candidates
    for candidate in summary_candidates:
        fp = os.path.join(path_base, candidate)
        if os.path.isfile(fp):
            with open(fp, encoding="utf-8-sig", errors="ignore") as f:
                general_summary = f.read().strip()
            break

    # Render the summary markdown to HTML (full + a collapsed 1000-char preview).
    general_summary_html = None
    general_summary_preview_html = None
    if general_summary:
        md_exts = ['fenced_code', 'tables', 'nl2br']
        general_summary_html = markdown.markdown(general_summary, extensions=md_exts)
        if len(general_summary) > 1000:
            general_summary_preview_html = markdown.markdown(
                general_summary[:1000].rstrip() + " …", extensions=md_exts
            )

    # --- Hierarchical PDF reports ---
    label_map_top = getattr(tyk_obj, "label_map_top", {})
    label_map_sub = getattr(tyk_obj, "label_map_sub", {})

    def _folder_label(folder_name, prefix, label_map):
        parts = folder_name.split("_", 2)
        fid = parts[1] if len(parts) >= 2 else folder_name
        raw = parts[2].replace("-", " ").title() if len(parts) >= 3 else folder_name
        return fid, label_map.get(fid, raw)

    pdf_reports = []
    clusters_dir = os.path.join(path_base, "clusters")
    if os.path.isdir(clusters_dir):
        for top_entry in sorted(os.scandir(clusters_dir), key=lambda e: e.name):
            if not top_entry.is_dir() or not top_entry.name.startswith("top_"):
                continue
            top_id, top_label = _folder_label(top_entry.name, "top_", label_map_top)
            top_pdf_url = None
            for fname in os.listdir(top_entry.path):
                if fname.startswith("cluster_") and fname.endswith("_report.pdf"):
                    top_pdf_url = _rel_url(os.path.join(top_entry.path, fname))
                    break

            subclusters = []
            for sub_entry in sorted(os.scandir(top_entry.path), key=lambda e: e.name):
                if not sub_entry.is_dir() or not sub_entry.name.startswith("subcluster_"):
                    continue
                sub_id, sub_label = _folder_label(sub_entry.name, "subcluster_", label_map_sub)
                for fname in os.listdir(sub_entry.path):
                    if fname.startswith("cluster_") and fname.endswith("_report.pdf"):
                        subclusters.append({
                            "id": sub_id, "name": sub_label,
                            "url": _rel_url(os.path.join(sub_entry.path, fname)),
                        })
                        break

            if top_pdf_url or subclusters:
                pdf_reports.append({
                    "id": top_id, "name": top_label,
                    "url": top_pdf_url, "subclusters": subclusters,
                })

    # --- Freq files ---
    freq_files = []
    freqs_dir = os.path.join(path_base, "freqs")
    if os.path.isdir(freqs_dir):
        for fname in sorted(os.listdir(freqs_dir)):
            if fname.startswith("freq_") and fname.endswith(".dat"):
                fp = os.path.join(freqs_dir, fname)
                display = fname[len("freq_"):-len(".dat")].replace("_", " ").title()
                freq_files.append({"name": display, "filename": fname, "url": _rel_url(fp)})

    # --- Dataset query (DB field first, then query.txt in path_base) ---
    dataset_query = notebook.dataset_query
    if not dataset_query:
        query_txt = os.path.join(path_base, "query.txt")
        if os.path.isfile(query_txt):
            with open(query_txt, encoding="utf-8-sig", errors="ignore") as f:
                dataset_query = f.read().strip()

    # --- Temporal evolution (subnode lineage) interactive HTML ---
    # The filename is prefixed with the dataset name in some datasets
    # (e.g. fermentation_allinone_...), so glob for the suffix.
    temporal_evolution = None
    for pattern in [
        os.path.join(path_base, "allinone_selected_subnodes_lineage.html"),
        os.path.join(path_base, "*allinone_selected_subnodes_lineage.html"),
        os.path.join(path_base, "clusters", "*allinone_selected_subnodes_lineage.html"),
    ]:
        matches = sorted(glob.glob(pattern))
        if matches:
            temporal_evolution = {"url": _rel_url(matches[0]), "name": os.path.basename(matches[0])}
            break

    return JsonResponse({
        "ready": True,
        "dataset_query": dataset_query,
        "article_count": article_count,
        "databases": databases,
        "general_report": general_report,
        "general_summary": general_summary,
        "general_summary_html": general_summary_html,
        "general_summary_preview_html": general_summary_preview_html,
        "pdf_reports": pdf_reports,
        "freq_files": freq_files,
        "temporal_evolution": temporal_evolution,
    })


@login_required
@require_http_methods(["GET"])
def notebook_cluster_options(request, slug):
    """Return top-cluster / subcluster hierarchy for cascading dropdowns."""
    notebook = get_object_or_404(Notebook, slug=slug, is_active=True)
    session_key = f"user_{request.user.id}"
    executor = session_manager.sessions.get(session_key)
    if not executor:
        return JsonResponse({"ready": False})

    tyk_obj = executor.get_variable("tyk")
    if not tyk_obj:
        return JsonResponse({"ready": False})

    path_base = getattr(tyk_obj, "path_base", None)
    if not path_base or not os.path.isdir(path_base):
        return JsonResponse({"ready": False})

    label_map_top = getattr(tyk_obj, "label_map_top", {})
    label_map_sub = getattr(tyk_obj, "label_map_sub", {})

    def _parse_folder(folder_name, prefix, label_map):
        parts = folder_name.split("_", 2)
        fid = parts[1] if len(parts) >= 2 else folder_name
        raw = parts[2].replace("-", " ").title() if len(parts) >= 3 else folder_name
        return fid, label_map.get(fid, raw)

    clusters = []
    clusters_dir = os.path.join(path_base, "clusters")
    if os.path.isdir(clusters_dir):
        for top_entry in sorted(os.scandir(clusters_dir), key=lambda e: e.name):
            if not top_entry.is_dir() or not top_entry.name.startswith("top_"):
                continue
            top_id, top_label = _parse_folder(top_entry.name, "top_", label_map_top)
            subclusters = []
            for sub_entry in sorted(os.scandir(top_entry.path), key=lambda e: e.name):
                if not sub_entry.is_dir() or not sub_entry.name.startswith("subcluster_"):
                    continue
                sub_id, sub_label = _parse_folder(sub_entry.name, "subcluster_", label_map_sub)
                subclusters.append({"id": sub_id, "label": sub_label})
            clusters.append({"id": top_id, "label": top_label, "subclusters": subclusters})

    return JsonResponse({"ready": True, "clusters": clusters})


@login_required
def overview_detail(request, slug):
    """Display the Overview screen for a notebook."""
    notebook = get_object_or_404(Notebook, slug=slug, is_active=True)
    if not notebook.overview_enabled:
        raise Http404("Overview is disabled for this notebook.")
    nb_session, _ = NotebookSession.objects.get_or_create(
        notebook=notebook, user=request.user, defaults={"parameter_values": {}}
    )
    context = {
        "notebook": notebook,
        "setup_complete": nb_session.kernel_state.get("setup_complete", False),
    }
    return render(request, "notebook/overview.html", context)


@login_required
@require_http_methods(["GET"])
def notebook_dynamic_analysis(request, slug):
    """Return cluster hierarchy with sizes for the dynamic Sankey-style view."""
    notebook = get_object_or_404(Notebook, slug=slug, is_active=True)
    session_key = f"user_{request.user.id}"
    executor = session_manager.sessions.get(session_key)
    if not executor:
        return JsonResponse({"ready": False})

    tyk_obj = executor.get_variable("tyk")
    if not tyk_obj:
        return JsonResponse({"ready": False})

    cluster_dict = getattr(tyk_obj, "cluster_dict", {})
    label_map_top = getattr(tyk_obj, "label_map_top", {})
    label_map_sub = getattr(tyk_obj, "label_map_sub", {})
    subclusters_by_top = getattr(tyk_obj, "subclusters_by_top", {})

    nodes = [{"id": "__all__", "label": "All Articles", "level": "root", "size": 0}]
    node_index = {"__all__": 0}

    top_clusters = []
    for cid, node in cluster_dict.items():
        lvl = int(node.get("level", 1))
        size = int(node.get("size", 0) or 0)
        if lvl == 0:
            label = label_map_top.get(cid, node.get("label_real", cid))
            top_clusters.append({"id": cid, "label": label, "size": size})

    top_clusters.sort(key=lambda x: x["id"])
    total_size = sum(tc["size"] for tc in top_clusters)
    nodes[0]["size"] = total_size

    for tc in top_clusters:
        node_index[tc["id"]] = len(nodes)
        nodes.append({"id": tc["id"], "label": tc["label"], "level": "top", "size": tc["size"]})

    sub_clusters_all = []
    for cid, node in cluster_dict.items():
        lvl = int(node.get("level", 1))
        if lvl == 1:
            size = int(node.get("size", 0) or 0)
            label = label_map_sub.get(cid, node.get("label_real", cid))
            sub_clusters_all.append({"id": cid, "label": label, "size": size})

    sub_clusters_all.sort(key=lambda x: x["id"])
    for sc in sub_clusters_all:
        node_index[sc["id"]] = len(nodes)
        nodes.append({"id": sc["id"], "label": sc["label"], "level": "sub", "size": sc["size"]})

    links = []
    for tc in top_clusters:
        if tc["size"] > 0:
            links.append({"source": node_index["__all__"], "target": node_index[tc["id"]], "value": tc["size"]})

    for top_id, sub_ids in subclusters_by_top.items():
        if top_id not in node_index:
            continue
        for sub_id in (sub_ids or []):
            if sub_id not in node_index:
                continue
            sub_node = cluster_dict.get(sub_id, {})
            size = int(sub_node.get("size", 0) or 0)
            if size > 0:
                links.append({"source": node_index[top_id], "target": node_index[sub_id], "value": size})

    # Collect cluster summaries for the info panel
    cluster_summaries = getattr(tyk_obj, "cluster_summaries", {})

    return JsonResponse({
        "ready": True,
        "nodes": nodes,
        "links": links,
        "total_articles": total_size,
        "cluster_summaries": cluster_summaries,
    })


@login_required
@require_http_methods(["POST"])
def notebook_dialog_query(request, slug):
    """Execute a structured dataset query from the dialog section."""
    notebook = get_object_or_404(Notebook, slug=slug, is_active=True)

    try:
        data = json.loads(request.body)
        query_type = data.get("query_type", "")
        params = data.get("params", {})
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    session_key = f"user_{request.user.id}"
    executor = session_manager.sessions.get(session_key)
    if not executor:
        return JsonResponse({"ready": False, "error": "Session not initialized"})

    if "tyk" not in executor.namespace:
        return JsonResponse({"ready": False, "needs_setup": True})

    top = int(params.get("top", 20))
    cluster_id = str(params.get("cluster_id", ""))
    sub_id = str(params.get("sub_id", ""))

    code_map = {
        "top_keywords": f'tyk.describe_cluster_params("GLOBAL", "K") if hasattr(tyk, "describe_cluster_params") else print("Not available")',
        "top_countries": f'tyk.plot_countries_map_global(height=320, method="modern")',
        "cluster_list": 'tyk.list_clusters(top=True)',
        "cluster_detail": f'tyk.describe_cluster_params("TOP", "K", cluster_top="{cluster_id}")' if cluster_id else '# Select a cluster',
        "subcluster_list": f'tyk.list_subclusters("{cluster_id}")' if cluster_id else '# Select a cluster',
        "subcluster_detail": f'tyk.describe_cluster_params("SUB", "K", cluster_top="{cluster_id}", cluster_sub="{sub_id}")' if (cluster_id and sub_id) else '# Select a cluster and subcluster',
    }

    code = code_map.get(query_type, f'# Unknown query type: {query_type}')
    stdout, html, error, exec_time = executor.execute(code)

    return JsonResponse({
        "success": not error,
        "output_text": stdout,
        "output_html": html,
        "error": error,
        "execution_time": exec_time,
    })


@login_required
@xframe_options_sameorigin
def serve_data_file(request, filepath):
    """Serve a file from within the TYK_DATA_PATH directory.

    Marked SAMEORIGIN so served HTML (e.g. the temporal-evolution lineage view)
    can be embedded in a same-origin <iframe>; Django's default is DENY.
    """
    base = os.path.normpath(settings.TYK_DATA_PATH)
    full_path = os.path.normpath(os.path.join(base, filepath))
    if not full_path.startswith(base + os.sep) and full_path != base:
        raise Http404
    if not os.path.isfile(full_path):
        raise Http404
    mime_type, _ = mimetypes.guess_type(full_path)
    return FileResponse(open(full_path, "rb"), content_type=mime_type or "application/octet-stream")


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
