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
from typing import Dict, Any, Optional, Tuple
from contextlib import redirect_stdout, redirect_stderr
import uuid


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

        try:
            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                exec(code, self.namespace)

            # Collect HTML outputs
            html_output = "\n".join(self._html_outputs)

            # Check for plotly figures in namespace
            html_output += self._extract_plotly_figures()

        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"

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
