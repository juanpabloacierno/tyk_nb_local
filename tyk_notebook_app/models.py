"""
Django models for the TyK Notebook Application.
Stores notebooks, cells, parameters, and execution history.
"""
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
import json


class Notebook(models.Model):
    """Represents a notebook (converted from .py or .ipynb)"""
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    source_file = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return self.name

    def get_executable_cells(self):
        """Return cells that can be executed (have parameters or are marked executable)"""
        return self.cells.filter(is_executable=True).order_by('order')


class Cell(models.Model):
    """Represents a single cell in a notebook"""
    CELL_TYPE_CHOICES = [
        ('code', 'Code'),
        ('markdown', 'Markdown'),
        ('setup', 'Setup (runs once)'),
    ]

    notebook = models.ForeignKey(Notebook, on_delete=models.CASCADE, related_name='cells')
    order = models.PositiveIntegerField(default=0)
    title = models.CharField(max_length=255, blank=True)
    cell_type = models.CharField(max_length=20, choices=CELL_TYPE_CHOICES, default='code')
    source_code = models.TextField(blank=True, help_text="Source code (required for code cells, optional for markdown)")
    description = models.TextField(blank=True, help_text="Markdown content shown above the cell")
    is_executable = models.BooleanField(default=True)
    auto_run = models.BooleanField(default=False, help_text="Run automatically when parameters change")
    is_setup_cell = models.BooleanField(default=False, help_text="Run once at notebook initialization")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order']
        unique_together = ['notebook', 'order']

    def __str__(self):
        return f"{self.notebook.name} - Cell {self.order}: {self.title or 'Untitled'}"

    def get_code_with_params(self, param_values: dict) -> str:
        """
        Replace parameter placeholders in source code with actual values.
        """
        code = self.source_code
        for param in self.parameters.all():
            if param.name in param_values:
                value = param_values[param.name]
                # Format value based on type
                if param.param_type == 'string':
                    formatted_value = f'"{value}"'
                elif param.param_type == 'dropdown':
                    formatted_value = f'"{value}"'
                elif param.param_type == 'number':
                    formatted_value = str(value)
                elif param.param_type == 'boolean':
                    formatted_value = 'True' if value else 'False'
                else:
                    formatted_value = repr(value)

                # Replace the parameter assignment line
                import re
                pattern = rf'^({param.name}\s*=\s*).*?(#.*)?$'
                replacement = rf'\1{formatted_value}  \2' if r'\2' else rf'\1{formatted_value}'
                code = re.sub(pattern, replacement, code, flags=re.MULTILINE)

        return code


class Parameter(models.Model):
    """Represents a parameter extracted from @param directives"""
    PARAM_TYPE_CHOICES = [
        ('dropdown', 'Dropdown'),
        ('string', 'Text Input'),
        ('number', 'Number'),
        ('boolean', 'Checkbox'),
        ('slider', 'Slider'),
    ]

    cell = models.ForeignKey(Cell, on_delete=models.CASCADE, related_name='parameters')
    name = models.CharField(max_length=100)
    param_type = models.CharField(max_length=20, choices=PARAM_TYPE_CHOICES, default='string')
    default_value = models.TextField(blank=True)
    options = models.JSONField(default=list, blank=True, help_text="Options for dropdown type")
    min_value = models.FloatField(null=True, blank=True, help_text="Min value for number/slider")
    max_value = models.FloatField(null=True, blank=True, help_text="Max value for number/slider")
    step = models.FloatField(null=True, blank=True, help_text="Step for slider")
    description = models.CharField(max_length=500, blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']
        unique_together = ['cell', 'name']

    def __str__(self):
        return f"{self.cell.title} - {self.name}"

    def get_options_list(self):
        """Return options as a Python list"""
        if isinstance(self.options, list):
            return self.options
        return json.loads(self.options) if self.options else []


class Execution(models.Model):
    """Records each cell execution with parameters and results"""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('success', 'Success'),
        ('error', 'Error'),
    ]

    cell = models.ForeignKey(Cell, on_delete=models.CASCADE, related_name='executions')
    parameters = models.JSONField(default=dict, help_text="Parameter values used")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    output_text = models.TextField(blank=True)
    output_html = models.TextField(blank=True, help_text="HTML output (plots, tables)")
    error_message = models.TextField(blank=True)
    execution_time = models.FloatField(null=True, blank=True, help_text="Execution time in seconds")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.cell} - {self.status} at {self.created_at}"


class ChartType(models.Model):
    """Defines available chart types for dashboards"""
    key = models.CharField(max_length=50, unique=True, help_text="Internal identifier (e.g., 'world_map')")
    name = models.CharField(max_length=255, help_text="Display name (e.g., 'Global Publications Map')")
    description = models.TextField(blank=True, help_text="Description of what this chart shows")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class DashboardChart(models.Model):
    """Configures which charts appear in the dashboard view"""
    notebook = models.ForeignKey(Notebook, on_delete=models.CASCADE, related_name='dashboard_charts')
    chart_type = models.ForeignKey(ChartType, on_delete=models.CASCADE, related_name='dashboard_charts')
    title = models.CharField(max_length=255, blank=True, help_text="Custom title (leave blank for default)")
    order = models.PositiveIntegerField(default=0, help_text="Display order in dashboard")
    is_active = models.BooleanField(default=True)
    default_params = models.JSONField(
        default=dict, blank=True,
        help_text="Default parameters (e.g., colorscale, node_type, max_nodes)"
    )

    class Meta:
        ordering = ['order']
        unique_together = ['notebook', 'chart_type']

    def __str__(self):
        return f"{self.notebook.name} - {self.chart_type.name}"

    def get_title(self):
        """Return custom title or default based on chart type"""
        if self.title:
            return self.title
        return self.chart_type.name


class NotebookSession(models.Model):
    """Tracks a user's session with a notebook (for state persistence)"""
    notebook = models.ForeignKey(Notebook, on_delete=models.CASCADE, related_name='sessions')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notebook_sessions', null=True)
    kernel_state = models.JSONField(default=dict, help_text="Serialized kernel variables")
    parameter_values = models.JSONField(default=dict, help_text="Current parameter values")
    last_executed_cell = models.ForeignKey(Cell, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['notebook', 'user']

    def __str__(self):
        return f"{self.user.username if self.user else 'Anonymous'} - {self.notebook.name}"
