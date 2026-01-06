"""
Django Admin configuration for TyK Notebook Application.
"""
from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from .models import Notebook, Cell, Parameter, Execution, NotebookSession


class ParameterInline(admin.TabularInline):
    """Inline admin for cell parameters"""
    model = Parameter
    extra = 0
    fields = ['name', 'param_type', 'default_value', 'options', 'order']
    ordering = ['order']


class CellInline(admin.TabularInline):
    """Inline admin for notebook cells"""
    model = Cell
    extra = 0
    fields = ['order', 'title', 'cell_type', 'is_executable', 'is_setup_cell']
    ordering = ['order']
    show_change_link = True


@admin.register(Notebook)
class NotebookAdmin(admin.ModelAdmin):
    """Admin for Notebooks"""
    list_display = ['name', 'slug', 'is_active', 'cell_count', 'updated_at', 'view_link']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'slug', 'description']
    prepopulated_fields = {'slug': ('name',)}
    inlines = [CellInline]

    fieldsets = (
        (None, {
            'fields': ('name', 'slug', 'description', 'is_active')
        }),
        ('Source', {
            'fields': ('source_file',),
            'classes': ('collapse',)
        }),
    )

    def cell_count(self, obj):
        return obj.cells.count()
    cell_count.short_description = 'Cells'

    def view_link(self, obj):
        url = reverse('notebook:detail', args=[obj.slug])
        return format_html('<a href="{}" target="_blank">View</a>', url)
    view_link.short_description = 'View'


@admin.register(Cell)
class CellAdmin(admin.ModelAdmin):
    """Admin for Cells"""
    list_display = ['title', 'notebook', 'order', 'cell_type', 'is_executable',
                    'is_setup_cell', 'param_count']
    list_filter = ['notebook', 'cell_type', 'is_executable', 'is_setup_cell']
    search_fields = ['title', 'description', 'source_code']
    ordering = ['notebook', 'order']
    inlines = [ParameterInline]

    fieldsets = (
        (None, {
            'fields': ('notebook', 'order', 'title', 'cell_type')
        }),
        ('Configuration', {
            'fields': ('is_executable', 'is_setup_cell', 'auto_run')
        }),
        ('Content', {
            'fields': ('description', 'source_code'),
            'classes': ('wide',)
        }),
    )

    def param_count(self, obj):
        return obj.parameters.count()
    param_count.short_description = 'Parameters'


@admin.register(Parameter)
class ParameterAdmin(admin.ModelAdmin):
    """Admin for Parameters"""
    list_display = ['name', 'cell', 'param_type', 'default_value', 'order']
    list_filter = ['param_type', 'cell__notebook']
    search_fields = ['name', 'cell__title']
    ordering = ['cell', 'order']

    fieldsets = (
        (None, {
            'fields': ('cell', 'name', 'param_type', 'order')
        }),
        ('Value Configuration', {
            'fields': ('default_value', 'options', 'description')
        }),
        ('Numeric Options', {
            'fields': ('min_value', 'max_value', 'step'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Execution)
class ExecutionAdmin(admin.ModelAdmin):
    """Admin for Execution history"""
    list_display = ['cell', 'status', 'execution_time', 'created_at', 'output_preview']
    list_filter = ['status', 'cell__notebook', 'created_at']
    search_fields = ['cell__title', 'output_text', 'error_message']
    ordering = ['-created_at']
    readonly_fields = ['cell', 'parameters', 'status', 'output_text', 'output_html',
                       'error_message', 'execution_time', 'created_at']

    def output_preview(self, obj):
        preview = obj.output_text[:100] if obj.output_text else ''
        if len(obj.output_text or '') > 100:
            preview += '...'
        return preview
    output_preview.short_description = 'Output'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(NotebookSession)
class NotebookSessionAdmin(admin.ModelAdmin):
    """Admin for Notebook Sessions"""
    list_display = ['session_key_short', 'notebook', 'last_executed_cell', 'updated_at']
    list_filter = ['notebook', 'created_at']
    readonly_fields = ['session_key', 'kernel_state', 'parameter_values',
                       'created_at', 'updated_at']

    def session_key_short(self, obj):
        return obj.session_key[:16] + '...' if len(obj.session_key) > 16 else obj.session_key
    session_key_short.short_description = 'Session'

    def has_add_permission(self, request):
        return False
