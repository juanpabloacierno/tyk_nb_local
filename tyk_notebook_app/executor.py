"""
Cell execution engine for TyK Notebook Application.
Handles Python code execution with parameter substitution.
"""
import sys
import io
import time
import traceback
import re
import json
from types import ModuleType
from typing import Dict, Any, Optional, Tuple
from contextlib import redirect_stdout, redirect_stderr
import uuid

# Global container for HTML outputs - uses a mutable container so mocks can find current outputs
class OutputContainer:
    """Mutable container for HTML outputs that allows dynamic lookup"""
    def __init__(self):
        self.html_outputs = []

    def append(self, item):
        self.html_outputs.append(item)

    def clear(self):
        self.html_outputs.clear()

    def get_outputs(self):
        return self.html_outputs


# Singleton container - all mocks will use this
_output_container = OutputContainer()


def create_mock_ipython_display(html_outputs=None):
    """
    Create a mock IPython.display module that captures HTML output.
    This allows code using display(HTML(...)) to work in our executor.

    If html_outputs is None, uses the global _output_container.
    """
    # Use global container if no specific list provided
    use_container = html_outputs is None
    if use_container:
        output_target = _output_container
    else:
        # Wrap the list in a simple object with append/clear methods
        class ListWrapper:
            def __init__(self, lst):
                self.html_outputs = lst
            def append(self, item):
                self.html_outputs.append(item)
            def clear(self):
                self.html_outputs.clear()
        output_target = ListWrapper(html_outputs)

    class MockDisplayObject:
        """Base class for display objects"""
        def __init__(self, data=None):
            self.data = data

        def __repr__(self):
            return f"<{self.__class__.__name__} object>"

        def _repr_html_(self):
            return None

    class MockHTML(MockDisplayObject):
        """Mock HTML display object that stores HTML content"""
        def __init__(self, data=None, url=None, filename=None):
            if data is not None:
                self.data = data
            elif url is not None:
                self.data = f'<iframe src="{url}" width="100%" height="400"></iframe>'
            elif filename is not None:
                try:
                    with open(filename, 'r') as f:
                        self.data = f.read()
                except:
                    self.data = f'<p>Could not load file: {filename}</p>'
            else:
                self.data = ''

        def _repr_html_(self):
            return self.data

        def __repr__(self):
            # Return empty string to avoid printing object representation
            return ''

    class MockMarkdown(MockDisplayObject):
        """Mock Markdown display object"""
        def __init__(self, data=None):
            self.data = data or ''

        def _repr_html_(self):
            # Return markdown wrapped in a div for frontend rendering
            return f'<div class="markdown-content">{self.data}</div>'

        def __repr__(self):
            return ''

    class MockImage(MockDisplayObject):
        """Mock Image display object"""
        def __init__(self, data=None, url=None, filename=None, format=None,
                     embed=None, width=None, height=None):
            self.width = width
            self.height = height
            self.format = format

            if url is not None:
                self.data = url
                self._is_url = True
            elif filename is not None:
                self.data = filename
                self._is_url = False
            elif data is not None:
                import base64
                if isinstance(data, bytes):
                    self.data = base64.b64encode(data).decode('utf-8')
                else:
                    self.data = data
                self._is_url = False
            else:
                self.data = ''
                self._is_url = False

        def _repr_html_(self):
            style = ''
            if self.width:
                style += f'width:{self.width}px;'
            if self.height:
                style += f'height:{self.height}px;'
            style_attr = f' style="{style}"' if style else ''

            if self._is_url:
                return f'<img src="{self.data}"{style_attr}/>'
            elif hasattr(self, 'format') and self.format:
                return f'<img src="data:image/{self.format};base64,{self.data}"{style_attr}/>'
            else:
                return f'<img src="data:image/png;base64,{self.data}"{style_attr}/>'

        def __repr__(self):
            return ''

    class MockJSON(MockDisplayObject):
        """Mock JSON display object"""
        def __init__(self, data=None, root='root', expanded=False):
            self.data = data
            self.root = root
            self.expanded = expanded

        def _repr_html_(self):
            import json as json_module
            json_str = json_module.dumps(self.data, indent=2, default=str)
            return f'<pre class="json-output">{json_str}</pre>'

        def __repr__(self):
            return ''

    class MockIFrame(MockDisplayObject):
        """Mock IFrame display object"""
        def __init__(self, src=None, width='100%', height='400', **kwargs):
            self.src = src
            self.width = width
            self.height = height

        def _repr_html_(self):
            width = self.width if isinstance(self.width, str) else f'{self.width}px'
            height = self.height if isinstance(self.height, str) else f'{self.height}px'
            return f'<iframe src="{self.src}" width="{width}" height="{height}" frameborder="0"></iframe>'

        def __repr__(self):
            return ''

    class MockAudio(MockDisplayObject):
        """Mock Audio display object"""
        def __init__(self, data=None, filename=None, url=None, embed=False, rate=None, autoplay=False):
            self.url = url
            self.filename = filename
            self.autoplay = autoplay

        def _repr_html_(self):
            src = self.url or self.filename or ''
            autoplay = ' autoplay' if self.autoplay else ''
            return f'<audio controls{autoplay}><source src="{src}">Your browser does not support audio.</audio>'

        def __repr__(self):
            return ''

    class MockVideo(MockDisplayObject):
        """Mock Video display object"""
        def __init__(self, data=None, filename=None, url=None, embed=False, width=None, height=None, mimetype=None):
            self.url = url
            self.filename = filename
            self.width = width
            self.height = height

        def _repr_html_(self):
            src = self.url or self.filename or ''
            style = ''
            if self.width:
                style += f'width:{self.width}px;'
            if self.height:
                style += f'height:{self.height}px;'
            style_attr = f' style="{style}"' if style else ''
            return f'<video controls{style_attr}><source src="{src}">Your browser does not support video.</video>'

        def __repr__(self):
            return ''

    def mock_display(*objs, **kwargs):
        """
        Mock display function that captures HTML output from display objects.
        """
        for obj in objs:
            html_content = None

            # Check if object has _repr_html_ method (IPython display protocol)
            if hasattr(obj, '_repr_html_'):
                html_content = obj._repr_html_()

            # Handle pandas DataFrames
            elif hasattr(obj, 'to_html'):
                try:
                    html_content = obj.to_html(classes='dataframe', escape=False)
                except:
                    html_content = f'<pre>{str(obj)}</pre>'

            # Handle plotly figures
            elif hasattr(obj, 'to_html'):
                try:
                    html_content = obj.to_html(full_html=False, include_plotlyjs='cdn')
                except:
                    pass

            # Check for plotly Figure type
            elif type(obj).__name__ == 'Figure' and hasattr(obj, 'to_html'):
                try:
                    import plotly.io as pio
                    html_content = pio.to_html(obj, full_html=False, include_plotlyjs='cdn')
                except:
                    pass

            # Handle matplotlib figures
            elif type(obj).__name__ == 'Figure' and hasattr(obj, 'savefig'):
                try:
                    import base64
                    buf = io.BytesIO()
                    obj.savefig(buf, format='png', bbox_inches='tight')
                    buf.seek(0)
                    img_base64 = base64.b64encode(buf.read()).decode('utf-8')
                    html_content = f'<img src="data:image/png;base64,{img_base64}"/>'
                    buf.close()
                except:
                    pass

            if html_content:
                output_target.append(html_content)
            elif obj is not None:
                # For non-HTML objects, create a text representation
                obj_str = str(obj)
                if obj_str and obj_str != '' and not obj_str.startswith('<') or not obj_str.endswith('object>'):
                    # Only output if it's not an empty string or object repr
                    if obj_str.strip():
                        print(obj_str)

    def mock_clear_output(wait=False):
        """Mock clear_output that clears the html_outputs list"""
        output_target.clear()

    # Create the mock module
    mock_module = ModuleType('IPython.display')
    mock_module.display = mock_display
    mock_module.HTML = MockHTML
    mock_module.Markdown = MockMarkdown
    mock_module.Image = MockImage
    mock_module.JSON = MockJSON
    mock_module.IFrame = MockIFrame
    mock_module.Audio = MockAudio
    mock_module.Video = MockVideo
    mock_module.clear_output = mock_clear_output
    mock_module.DisplayObject = MockDisplayObject

    # Also create parent IPython module if needed
    mock_ipython = ModuleType('IPython')
    mock_ipython.display = mock_module

    # Create IPython.core.display for direct imports
    mock_core = ModuleType('IPython.core')
    mock_core_display = ModuleType('IPython.core.display')
    mock_core_display.display = mock_display
    mock_core_display.HTML = MockHTML
    mock_core_display.Markdown = MockMarkdown
    mock_core_display.Image = MockImage
    mock_core_display.JSON = MockJSON
    mock_core_display.IFrame = MockIFrame
    mock_core_display.Audio = MockAudio
    mock_core_display.Video = MockVideo
    mock_core_display.clear_output = mock_clear_output
    mock_core_display.DisplayObject = MockDisplayObject
    mock_core.display = mock_core_display
    mock_ipython.core = mock_core

    return {
        'IPython': mock_ipython,
        'IPython.display': mock_module,
        'IPython.core': mock_core,
        'IPython.core.display': mock_core_display,
    }


def install_global_ipython_mocks():
    """
    Install IPython mocks globally at module load time.
    This ensures any module imported later gets our mocks.
    Uses the global _output_container for output capture.
    """
    # Create mocks with no list - they'll use _output_container
    mocks = create_mock_ipython_display(None)
    for mod_name, mock_mod in mocks.items():
        sys.modules[mod_name] = mock_mod
    return mocks


# Install mocks early - before any other code might import IPython
_early_mocks = install_global_ipython_mocks()


def set_output_target(html_outputs_list):
    """Redirect the global output container to a specific list"""
    _output_container.html_outputs = html_outputs_list


def get_current_outputs():
    """Get the current outputs from the global container"""
    return _output_container.html_outputs


class CellExecutor:
    """
    Executes notebook cells in an isolated namespace with parameter substitution.
    Maintains state between cell executions within a session.
    """

    def __init__(self, base_path: str = None):
        """
        Initialize executor with optional base path for data files.
        """
        self.namespace: Dict[str, Any] = {}
        self.base_path = base_path

        self._html_outputs: list = []
        self._plot_outputs: list = []

        self._setup_namespace()

    def _setup_namespace(self):
        """Set up the initial namespace with common imports and utilities"""
        # Use the global mocks that are already installed
        self._mock_ipython_modules = _early_mocks

        # Patch any modules that were imported before we created this executor
        self._patch_imported_modules()

        # Basic builtins
        self.namespace["__builtins__"] = __builtins__

        # Pre-import common modules (lazy - won't fail if not installed)
        try:
            import pandas as pd

            self.namespace["pd"] = pd
        except ImportError:
            pass

        try:
            import numpy as np

            self.namespace["np"] = np
        except ImportError:
            pass

        # Add base path to namespace
        if self.base_path:
            self.namespace["BASE_PATH"] = self.base_path
            self.namespace["PATH"] = self.base_path

        # Custom display function that captures HTML
        self.namespace["_html_outputs"] = self._html_outputs
        self.namespace["_plot_outputs"] = self._plot_outputs

        # Pre-add display and HTML to namespace for convenience
        self.namespace["display"] = self._mock_ipython_modules['IPython.display'].display
        self.namespace["HTML"] = self._mock_ipython_modules['IPython.display'].HTML
        self.namespace["clear_output"] = self._mock_ipython_modules['IPython.display'].clear_output

    def _patch_imported_modules(self):
        """Patch any already-imported modules that cached IPython display functions"""
        mock_display = self._mock_ipython_modules['IPython.display'].display
        mock_html = self._mock_ipython_modules['IPython.display'].HTML
        mock_clear = self._mock_ipython_modules['IPython.display'].clear_output
        mock_iframe = self._mock_ipython_modules['IPython.display'].IFrame

        # Patch modules that might have imported IPython.display
        for mod_name, mod in list(sys.modules.items()):
            if mod is None:
                continue
            try:
                # Skip our mock modules
                if mod_name.startswith('IPython'):
                    continue

                # Check if module has display/HTML from IPython
                if hasattr(mod, 'display'):
                    display_func = getattr(mod, 'display', None)
                    if display_func is not None and display_func is not mock_display:
                        # Check if it's from IPython (not our mock)
                        display_module = getattr(display_func, '__module__', '')
                        if 'IPython' in str(display_module) or 'ipython' in str(display_module):
                            setattr(mod, 'display', mock_display)

                if hasattr(mod, 'HTML'):
                    html_class = getattr(mod, 'HTML', None)
                    if html_class is not None and html_class is not mock_html:
                        html_module = getattr(html_class, '__module__', '')
                        if 'IPython' in str(html_module) or 'ipython' in str(html_module):
                            setattr(mod, 'HTML', mock_html)

                if hasattr(mod, 'clear_output'):
                    clear_func = getattr(mod, 'clear_output', None)
                    if clear_func is not None and clear_func is not mock_clear:
                        clear_module = getattr(clear_func, '__module__', '')
                        if 'IPython' in str(clear_module) or 'ipython' in str(clear_module):
                            setattr(mod, 'clear_output', mock_clear)

                if hasattr(mod, 'IFrame'):
                    iframe_class = getattr(mod, 'IFrame', None)
                    if iframe_class is not None and iframe_class is not mock_iframe:
                        iframe_module = getattr(iframe_class, '__module__', '')
                        if 'IPython' in str(iframe_module) or 'ipython' in str(iframe_module):
                            setattr(mod, 'IFrame', mock_iframe)

            except Exception:
                pass  # Skip modules that cause issues

    def _patch_namespace_modules(self):
        """Patch modules and objects in the execution namespace"""
        mock_display = self._mock_ipython_modules['IPython.display'].display
        mock_html = self._mock_ipython_modules['IPython.display'].HTML
        mock_clear = self._mock_ipython_modules['IPython.display'].clear_output

        # Update namespace with our mocks
        self.namespace['display'] = mock_display
        self.namespace['HTML'] = mock_html
        self.namespace['clear_output'] = mock_clear

        # Patch any module objects in namespace
        for name, obj in list(self.namespace.items()):
            if obj is None or name.startswith('_'):
                continue
            try:
                # Check if it's a module with IPython display functions
                if hasattr(obj, '__module__') or hasattr(obj, '__file__'):
                    if hasattr(obj, 'display'):
                        display_func = getattr(obj, 'display', None)
                        if display_func is not None and display_func is not mock_display:
                            display_module = getattr(display_func, '__module__', '')
                            if 'IPython' in str(display_module):
                                setattr(obj, 'display', mock_display)
                    if hasattr(obj, 'HTML'):
                        html_class = getattr(obj, 'HTML', None)
                        if html_class is not None and html_class is not mock_html:
                            html_module = getattr(html_class, '__module__', '')
                            if 'IPython' in str(html_module):
                                setattr(obj, 'HTML', mock_html)
                    if hasattr(obj, 'clear_output'):
                        clear_func = getattr(obj, 'clear_output', None)
                        if clear_func is not None and clear_func is not mock_clear:
                            clear_module = getattr(clear_func, '__module__', '')
                            if 'IPython' in str(clear_module):
                                setattr(obj, 'clear_output', mock_clear)
            except Exception:
                pass

    def substitute_parameters(self, code: str, params: Dict[str, Any]) -> str:
        """
        Replace parameter values in code.

        Args:
            code: The source code with parameter assignments
            params: Dict of parameter_name -> value

        Returns:
            Code with parameter values substituted
        """
        result = code

        for name, value in params.items():
            # Format value appropriately for Python
            if isinstance(value, str):
                formatted = f'"{value}"'
            elif isinstance(value, bool):
                formatted = "True" if value else "False"
            elif value is None:
                formatted = "None"
            else:
                formatted = str(value)

            # Pattern to match variable assignment with @param comment
            pattern = rf"^({name}\s*=\s*).*?(#\s*@param.*)$"
            replacement = rf"\1{formatted}  \2"
            result = re.sub(pattern, replacement, result, flags=re.MULTILINE)

            # Also handle assignments without @param (for direct substitution)
            pattern_simple = (
                rf'^({name}\s*=\s*)("[^"]*"|\'[^\']*\'|\d+|True|False|None)(\s*)$'
            )
            replacement_simple = rf"\1{formatted}\3"
            result = re.sub(
                pattern_simple, replacement_simple, result, flags=re.MULTILINE
            )

        return result

    def execute(
        self, code: str, params: Optional[Dict[str, Any]] = None, timeout: float = 60.0
    ) -> Tuple[str, str, str, float]:
        """
        Execute code with optional parameter substitution.

        Args:
            code: Python code to execute
            params: Optional dict of parameters to substitute
            timeout: Maximum execution time in seconds

        Returns:
            Tuple of (stdout, html_output, error, execution_time)
        """
        # Clear previous outputs
        self._html_outputs.clear()
        self._plot_outputs.clear()

        # Substitute parameters
        if params:
            code = self.substitute_parameters(code, params)

        # Remove problematic Colab-specific code
        code = self._sanitize_code(code)

        # Capture output
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()

        start_time = time.time()
        error_msg = ""
        html_output = ""

        # Redirect global output container to our list
        # This ensures all display() calls (even from cached imports) go to our list
        old_outputs = get_current_outputs()
        set_output_target(self._html_outputs)

        try:
            # Patch any already-imported modules that have cached IPython functions
            self._patch_imported_modules()

            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                exec(code, self.namespace)

            # After execution, patch any newly imported modules (like tyk.py)
            self._patch_imported_modules()
            self._patch_namespace_modules()

            # Collect HTML outputs
            html_output = "\n".join(self._html_outputs)

            # Check for plotly figures in namespace
            html_output += self._extract_plotly_figures()

        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"

        finally:
            # Keep mocks installed - don't restore original modules
            # This ensures subsequent cells also use our mocks
            pass

        execution_time = time.time() - start_time

        stdout_text = stdout_capture.getvalue()
        stderr_text = stderr_capture.getvalue()

        # Combine stdout and stderr
        combined_output = stdout_text
        if stderr_text:
            combined_output += f"\n[stderr]\n{stderr_text}"

        return combined_output, html_output, error_msg, execution_time

    def _sanitize_code(self, code: str) -> str:
        """Remove or modify Colab-specific code that won't work locally"""
        # Remove Google Drive mount
        code = re.sub(
            r"^from google\.colab import drive\s*\n?.*drive\.mount.*$",
            "# [Removed: Google Drive mount]",
            code,
            flags=re.MULTILINE,
        )

        # Remove !pip install (handled separately)
        code = re.sub(
            r"^!pip install.*$",
            "# [Removed: pip install - dependencies should be pre-installed]",
            code,
            flags=re.MULTILINE,
        )

        # Remove @title comments (they're metadata, not code)
        code = re.sub(r"^#\s*@title.*$", "", code, flags=re.MULTILINE)

        # Replace Colab file path with local path if BASE_PATH is set
        if self.base_path:
            code = re.sub(r'/content/drive/MyDrive/[^"\']+/', self.base_path, code)

        return code

    def _extract_plotly_figures(self) -> str:
        """Extract plotly figures from namespace and convert to HTML"""
        html_parts = []

        try:
            import plotly.graph_objs as go
            import plotly.io as pio

            for name, obj in list(self.namespace.items()):
                if isinstance(obj, go.Figure):
                    try:
                        html = pio.to_html(obj, full_html=False, include_plotlyjs="cdn")
                        html_parts.append(html)
                    except Exception:
                        pass
        except ImportError:
            pass

        return "\n".join(html_parts)

    def set_variable(self, name: str, value: Any):
        """Set a variable in the execution namespace"""
        self.namespace[name] = value

    def get_variable(self, name: str) -> Any:
        """Get a variable from the execution namespace"""
        return self.namespace.get(name)

    def reset(self):
        """Reset the execution namespace"""
        self.namespace.clear()
        self._html_outputs.clear()
        self._plot_outputs.clear()
        self._setup_namespace()


class SessionManager:
    """Manages execution sessions for multiple users/notebooks"""

    def __init__(self):
        self.sessions: Dict[str, CellExecutor] = {}

    def get_or_create_session(
        self, session_key: str, base_path: str = None
    ) -> CellExecutor:
        """Get existing session or create new one"""
        if session_key not in self.sessions:
            self.sessions[session_key] = CellExecutor(base_path=base_path)
        return self.sessions[session_key]

    def create_session(self, base_path: str = None) -> Tuple[str, CellExecutor]:
        """Create a new session with a unique key"""
        session_key = str(uuid.uuid4())
        executor = CellExecutor(base_path=base_path)
        self.sessions[session_key] = executor
        return session_key, executor

    def destroy_session(self, session_key: str):
        """Destroy a session and free resources"""
        if session_key in self.sessions:
            del self.sessions[session_key]

    def reset_session(self, session_key: str):
        """Reset a session's namespace"""
        if session_key in self.sessions:
            self.sessions[session_key].reset()


# Global session manager
session_manager = SessionManager()
