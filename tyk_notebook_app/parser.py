"""
Parser for Colab-style @param directives and notebook files.
Extracts cells, parameters, and metadata from .py and .ipynb files.
"""
import re
import json
import os
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class ParsedParameter:
    """Represents a parsed @param directive"""
    name: str
    param_type: str  # 'dropdown', 'string', 'number', 'boolean', 'slider'
    default_value: Any
    options: List[str] = field(default_factory=list)
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    step: Optional[float] = None


@dataclass
class ParsedCell:
    """Represents a parsed notebook cell"""
    title: str = ""
    source_code: str = ""
    description: str = ""
    cell_type: str = "code"  # 'code', 'markdown', 'setup'
    auto_run: bool = False
    is_setup_cell: bool = False
    parameters: List[ParsedParameter] = field(default_factory=list)


class ColabNotebookParser:
    """
    Parses Colab-style Python files and Jupyter notebooks.

    Colab @param syntax:
    - # @param ["option1", "option2"]  -> dropdown
    - # @param {"type":"string"}       -> text input
    - # @param {"type":null}           -> number input
    - # @param {"type":"boolean"}      -> checkbox
    - # @param {"type":"slider", "min":0, "max":100, "step":1}  -> slider

    Colab @title syntax:
    - # @title Cell Title {"run":"auto"}
    """

    # Regex patterns
    TITLE_PATTERN = re.compile(
        r'#\s*@title\s+(.+?)(?:\s*\{(.+?)\})?\s*$',
        re.MULTILINE
    )

    PARAM_PATTERN = re.compile(
        r'^(\w+)\s*=\s*(.+?)\s*#\s*@param\s*(.*)$',
        re.MULTILINE
    )

    MARKDOWN_START = re.compile(r'^"""(.*)$', re.MULTILINE)
    MARKDOWN_END = re.compile(r'^(.*)"""$', re.MULTILINE)

    def __init__(self):
        self.cells: List[ParsedCell] = []
        self.current_cell: Optional[ParsedCell] = None
        self.setup_imports: List[str] = []

    def parse_file(self, filepath: str) -> List[ParsedCell]:
        """Parse a .py or .ipynb file and return list of cells"""
        if filepath.endswith('.ipynb'):
            return self.parse_ipynb(filepath)
        else:
            return self.parse_py(filepath)

    def parse_py(self, filepath: str) -> List[ParsedCell]:
        """Parse a Colab-exported Python file"""
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        return self.parse_py_content(content)

    def parse_py_content(self, content: str) -> List[ParsedCell]:
        """Parse Python content from a Colab export"""
        self.cells = []
        lines = content.split('\n')

        current_cell_lines = []
        current_cell = ParsedCell()
        in_markdown = False
        markdown_content = []
        pending_description = ""

        i = 0
        while i < len(lines):
            line = lines[i]

            # Check for markdown block start
            if line.strip().startswith('"""') and not in_markdown:
                in_markdown = True
                markdown_content = []
                # Check if it's a single-line markdown
                if line.strip().endswith('"""') and len(line.strip()) > 6:
                    md_text = line.strip()[3:-3]
                    pending_description = md_text
                    in_markdown = False
                else:
                    md_start = line.strip()[3:]
                    if md_start:
                        markdown_content.append(md_start)
                i += 1
                continue

            # Inside markdown block
            if in_markdown:
                if line.strip().endswith('"""'):
                    md_end = line.strip()[:-3]
                    if md_end:
                        markdown_content.append(md_end)
                    pending_description = '\n'.join(markdown_content)
                    in_markdown = False
                else:
                    markdown_content.append(line)
                i += 1
                continue

            # Check for @title directive (new cell)
            title_match = self.TITLE_PATTERN.search(line)
            if title_match:
                # Save previous cell if exists
                if current_cell_lines or current_cell.title:
                    current_cell.source_code = '\n'.join(current_cell_lines)
                    if current_cell.source_code.strip() or current_cell.title:
                        self.cells.append(current_cell)

                # Start new cell
                current_cell = ParsedCell()
                current_cell.title = title_match.group(1).strip()
                current_cell.description = pending_description
                pending_description = ""

                # Parse title options
                if title_match.group(2):
                    try:
                        opts = json.loads('{' + title_match.group(2) + '}')
                        current_cell.auto_run = opts.get('run') == 'auto'
                    except json.JSONDecodeError:
                        pass

                current_cell_lines = []
                i += 1
                continue

            # Check for @param directive
            param_match = self.PARAM_PATTERN.search(line)
            if param_match:
                param = self._parse_param_line(param_match)
                if param:
                    current_cell.parameters.append(param)

            # Regular code line
            current_cell_lines.append(line)
            i += 1

        # Don't forget the last cell
        if current_cell_lines or current_cell.title:
            current_cell.source_code = '\n'.join(current_cell_lines)
            if current_cell.source_code.strip() or current_cell.title:
                self.cells.append(current_cell)

        # Mark setup cells
        self._identify_setup_cells()

        return self.cells

    def parse_ipynb(self, filepath: str) -> List[ParsedCell]:
        """Parse a Jupyter notebook file"""
        with open(filepath, 'r', encoding='utf-8') as f:
            nb = json.load(f)

        self.cells = []
        pending_description = ""

        for nb_cell in nb.get('cells', []):
            cell_type = nb_cell.get('cell_type', 'code')
            source = ''.join(nb_cell.get('source', []))

            if cell_type == 'markdown':
                pending_description = source
                continue

            if cell_type == 'code':
                parsed = self._parse_code_cell(source)
                parsed.description = pending_description
                pending_description = ""
                self.cells.append(parsed)

        self._identify_setup_cells()
        return self.cells

    def _parse_code_cell(self, source: str) -> ParsedCell:
        """Parse a single code cell"""
        cell = ParsedCell()
        cell.source_code = source

        # Extract title
        title_match = self.TITLE_PATTERN.search(source)
        if title_match:
            cell.title = title_match.group(1).strip()
            if title_match.group(2):
                try:
                    opts = json.loads('{' + title_match.group(2) + '}')
                    cell.auto_run = opts.get('run') == 'auto'
                except json.JSONDecodeError:
                    pass

        # Extract parameters
        for match in self.PARAM_PATTERN.finditer(source):
            param = self._parse_param_line(match)
            if param:
                cell.parameters.append(param)

        return cell

    def _parse_param_line(self, match: re.Match) -> Optional[ParsedParameter]:
        """Parse a single @param line"""
        var_name = match.group(1)
        default_raw = match.group(2).strip()
        param_spec = match.group(3).strip()

        param = ParsedParameter(
            name=var_name,
            param_type='string',
            default_value=None
        )

        # Parse default value
        param.default_value = self._parse_default_value(default_raw)

        # Parse param specification
        if param_spec:
            # Check if it's a dropdown (list of options)
            if param_spec.startswith('['):
                try:
                    options = json.loads(param_spec)
                    param.param_type = 'dropdown'
                    param.options = options
                except json.JSONDecodeError:
                    pass
            # Check if it's a type specification
            elif param_spec.startswith('{'):
                try:
                    spec = json.loads(param_spec)
                    type_val = spec.get('type')

                    if type_val is None:
                        param.param_type = 'number'
                    elif type_val == 'string':
                        param.param_type = 'string'
                    elif type_val == 'boolean':
                        param.param_type = 'boolean'
                    elif type_val == 'slider':
                        param.param_type = 'slider'
                        param.min_value = spec.get('min', 0)
                        param.max_value = spec.get('max', 100)
                        param.step = spec.get('step', 1)
                    elif type_val == 'integer':
                        param.param_type = 'number'
                except json.JSONDecodeError:
                    pass

        return param

    def _parse_default_value(self, raw: str) -> Any:
        """Parse the default value from Python code"""
        raw = raw.strip()

        # Remove trailing comment if present
        if '#' in raw:
            raw = raw.split('#')[0].strip()

        # Try to evaluate as Python literal
        try:
            import ast
            return ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            # Return as string, stripping quotes if present
            if (raw.startswith('"') and raw.endswith('"')) or \
               (raw.startswith("'") and raw.endswith("'")):
                return raw[1:-1]
            return raw

    def _identify_setup_cells(self):
        """Identify cells that are setup/initialization cells"""
        setup_keywords = [
            'import ', 'from ', 'pip install', '!pip',
            'drive.mount', 'google.colab', 'Inicializando',
            'Estableciendo conexión', 'class TyK'
        ]

        for cell in self.cells:
            source_lower = cell.source_code.lower()
            title_lower = cell.title.lower() if cell.title else ""

            # Check for setup indicators
            is_setup = any(kw.lower() in source_lower or kw.lower() in title_lower
                         for kw in setup_keywords)

            # Also mark as setup if no parameters and appears early
            if is_setup and not cell.parameters:
                cell.is_setup_cell = True
                cell.cell_type = 'setup'


def extract_tyk_class(filepath: str) -> str:
    """
    Extract just the TyK class definition from the file.
    This is useful for the setup cell.
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Find the class definition
    class_pattern = re.compile(
        r'^class TyK:.*?(?=^class |\Z)',
        re.MULTILINE | re.DOTALL
    )

    match = class_pattern.search(content)
    if match:
        return match.group(0)

    return ""


def get_imports_from_file(filepath: str) -> str:
    """Extract all import statements from a file"""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    imports = []
    for line in content.split('\n'):
        stripped = line.strip()
        if stripped.startswith('import ') or stripped.startswith('from '):
            imports.append(line)
        elif stripped.startswith('!pip install'):
            # Convert pip install to comment (handled separately)
            imports.append(f"# {stripped}")

    return '\n'.join(imports)
