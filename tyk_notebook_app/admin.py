"""
Django Admin configuration for TyK Notebook Application.
"""
import os
import tempfile
from django.contrib import admin
from django.contrib import messages
from django.utils.html import format_html
from django.urls import reverse, path
from django.shortcuts import render, redirect
from django.http import HttpResponseRedirect
from django import forms
from django.utils.safestring import mark_safe
from .models import Notebook, Cell, Parameter, Execution, NotebookSession
from .importer import import_notebook


class CodeEditorWidget(forms.Textarea):
    """Custom textarea widget with CodeMirror code editor"""

    def __init__(self, attrs=None, mode='python'):
        self.mode = mode
        default_attrs = {
            'class': 'code-editor-textarea',
            'rows': 20,
        }
        if attrs:
            default_attrs.update(attrs)
        super().__init__(attrs=default_attrs)

    class Media:
        css = {
            'all': (
                'https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/codemirror.min.css',
                'https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/theme/monokai.min.css',
            )
        }
        js = (
            'https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/codemirror.min.js',
            'https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/python/python.min.js',
            'https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/markdown/markdown.min.js',
            'https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/addon/edit/matchbrackets.min.js',
            'https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/addon/edit/closebrackets.min.js',
            'https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/addon/selection/active-line.min.js',
        )

    def render(self, name, value, attrs=None, renderer=None):
        # Render the base textarea
        textarea_html = super().render(name, value, attrs, renderer)

        # Add CodeMirror initialization script
        widget_id = attrs.get('id', name) if attrs else name
        script = f'''
        <script>
        (function() {{
            function initCodeMirror() {{
                var textarea = document.getElementById("{widget_id}");
                if (!textarea || textarea.CodeMirror) return;

                var editor = CodeMirror.fromTextArea(textarea, {{
                    mode: "{self.mode}",
                    theme: "monokai",
                    lineNumbers: true,
                    indentUnit: 4,
                    tabSize: 4,
                    indentWithTabs: false,
                    matchBrackets: true,
                    autoCloseBrackets: true,
                    styleActiveLine: true,
                    lineWrapping: true,
                    viewportMargin: Infinity,
                    extraKeys: {{
                        "Tab": function(cm) {{
                            cm.replaceSelection("    ", "end");
                        }}
                    }}
                }});

                editor.setSize("100%", "500px");

                // Store reference
                textarea.CodeMirror = editor;

                // Sync changes back to textarea
                editor.on("change", function() {{
                    editor.save();
                }});
            }}

            // Initialize when DOM is ready
            if (document.readyState === 'loading') {{
                document.addEventListener('DOMContentLoaded', initCodeMirror);
            }} else {{
                // Small delay to ensure textarea is rendered
                setTimeout(initCodeMirror, 100);
            }}
        }})();
        </script>
        <style>
            .CodeMirror {{
                border: 1px solid #ccc;
                border-radius: 4px;
                font-size: 14px;
                font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', 'Consolas', monospace;
            }}
            .code-editor-textarea {{
                display: none;
            }}
        </style>
        '''

        return mark_safe(textarea_html + script)


class CellAdminForm(forms.ModelForm):
    """Custom form for Cell admin with code editor"""

    class Meta:
        model = Cell
        fields = '__all__'
        widgets = {
            'source_code': CodeEditorWidget(mode='python'),
            'description': CodeEditorWidget(mode='markdown'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make source_code not required by default (will validate in clean)
        self.fields['source_code'].required = False

    def clean(self):
        cleaned_data = super().clean()
        cell_type = cleaned_data.get('cell_type')
        source_code = cleaned_data.get('source_code')

        # For code cells, source_code is required
        if cell_type == 'code' and not source_code:
            self.add_error('source_code', 'Source code is required for code cells.')

        # For markdown cells, source_code is optional
        # (no validation needed, it's already optional)

        return cleaned_data


class NotebookImportForm(forms.Form):
    """Form for importing notebooks"""
    notebook_file = forms.FileField(
        label="Notebook File",
        help_text="Upload a .py or .ipynb file"
    )
    name = forms.CharField(
        max_length=200,
        required=False,
        help_text="Optional: Custom name for the notebook (defaults to filename)"
    )
    description = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 3}),
        required=False,
        help_text="Optional: Description of the notebook"
    )
    replace_existing = forms.BooleanField(
        required=False,
        initial=True,
        help_text="Replace notebook if one with the same slug already exists"
    )

    def clean_notebook_file(self):
        file = self.cleaned_data['notebook_file']
        ext = os.path.splitext(file.name)[1].lower()
        if ext not in ['.py', '.ipynb']:
            raise forms.ValidationError(
                "Only .py and .ipynb files are supported"
            )
        return file


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
    change_list_template = 'admin/notebook/notebook_changelist.html'

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

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                'import/',
                self.admin_site.admin_view(self.import_notebook_view),
                name='tyk_notebook_app_notebook_import',
            ),
        ]
        return custom_urls + urls

    def import_notebook_view(self, request):
        """Handle notebook import"""
        if request.method == 'POST':
            form = NotebookImportForm(request.POST, request.FILES)
            if form.is_valid():
                uploaded_file = form.cleaned_data['notebook_file']
                name = form.cleaned_data['name'] or None
                description = form.cleaned_data['description'] or ""
                replace_existing = form.cleaned_data['replace_existing']

                # Save uploaded file to temp location
                ext = os.path.splitext(uploaded_file.name)[1]
                with tempfile.NamedTemporaryFile(
                    mode='wb',
                    suffix=ext,
                    delete=False
                ) as tmp_file:
                    for chunk in uploaded_file.chunks():
                        tmp_file.write(chunk)
                    tmp_path = tmp_file.name

                try:
                    # Check if notebook exists
                    from django.utils.text import slugify
                    check_name = name or os.path.splitext(uploaded_file.name)[0]
                    slug = slugify(check_name)
                    existing = Notebook.objects.filter(slug=slug).first()

                    if existing and not replace_existing:
                        messages.error(
                            request,
                            f'Notebook "{check_name}" already exists. '
                            'Check "Replace existing" to update it.'
                        )
                    else:
                        # Import the notebook
                        notebook = import_notebook(
                            filepath=tmp_path,
                            name=name,
                            description=description
                        )

                        if existing:
                            messages.success(
                                request,
                                f'Successfully updated notebook "{notebook.name}" '
                                f'with {notebook.cells.count()} cells.'
                            )
                        else:
                            messages.success(
                                request,
                                f'Successfully imported notebook "{notebook.name}" '
                                f'with {notebook.cells.count()} cells.'
                            )

                        return HttpResponseRedirect(
                            reverse('admin:tyk_notebook_app_notebook_changelist')
                        )

                except Exception as e:
                    messages.error(request, f'Import failed: {str(e)}')

                finally:
                    # Clean up temp file
                    if os.path.exists(tmp_path):
                        os.unlink(tmp_path)
        else:
            form = NotebookImportForm()

        context = {
            **self.admin_site.each_context(request),
            'form': form,
            'title': 'Import Notebook',
            'opts': self.model._meta,
        }

        return render(request, 'admin/notebook/import_notebook.html', context)


@admin.register(Cell)
class CellAdmin(admin.ModelAdmin):
    """Admin for Cells"""
    form = CellAdminForm
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

    class Media:
        css = {
            'all': (
                'https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/codemirror.min.css',
                'https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/theme/monokai.min.css',
            )
        }
        js = (
            'https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/codemirror.min.js',
            'https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/python/python.min.js',
            'https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/addon/edit/matchbrackets.min.js',
            'https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/addon/edit/closebrackets.min.js',
            'https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/addon/selection/active-line.min.js',
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
    list_display = ['user', 'notebook', 'last_executed_cell', 'updated_at']
    list_filter = ['notebook', 'user', 'created_at']
    readonly_fields = ['user', 'notebook', 'kernel_state', 'parameter_values',
                       'created_at', 'updated_at']

    def has_add_permission(self, request):
        return False
