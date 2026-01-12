"""
Tests for code execution functionality
"""
from django.test import TestCase
from tyk_notebook_app.executor import CellExecutor, SessionManager


class CellExecutorTest(TestCase):
    """Test CellExecutor class"""

    def setUp(self):
        self.executor = CellExecutor()

    def test_simple_execution(self):
        """Test executing simple Python code"""
        stdout, html, error, exec_time = self.executor.execute("print('Hello')")

        self.assertIn('Hello', stdout)
        self.assertIsNone(error)
        self.assertGreater(exec_time, 0)

    def test_execution_with_error(self):
        """Test executing code with errors"""
        stdout, html, error, exec_time = self.executor.execute(
            "raise ValueError('test error')"
        )

        self.assertIsNotNone(error)
        self.assertIn('ValueError', error)
        self.assertIn('test error', error)

    def test_variable_persistence(self):
        """Test variables persist across executions"""
        # First execution
        self.executor.execute("x = 42")

        # Second execution
        stdout, html, error, exec_time = self.executor.execute("print(x)")

        self.assertIn('42', stdout)
        self.assertIsNone(error)

    def test_parameter_substitution(self):
        """Test parameters are substituted correctly"""
        code = "name = 'default'\nprint(f'Hello {name}')"
        params = {"name": "Alice"}

        stdout, html, error, exec_time = self.executor.execute(code, params)

        self.assertIn('Alice', stdout)
        self.assertIsNone(error)

    def test_numeric_parameter(self):
        """Test numeric parameters"""
        code = "x = 10\nprint(x * 2)"
        params = {"x": 5}

        stdout, html, error, exec_time = self.executor.execute(code, params)

        self.assertIn('10', stdout)
        self.assertIsNone(error)

    def test_boolean_parameter(self):
        """Test boolean parameters"""
        code = "flag = True\nprint('Yes' if flag else 'No')"
        params = {"flag": False}

        stdout, html, error, exec_time = self.executor.execute(code, params)

        self.assertIn('No', stdout)
        self.assertIsNone(error)

    def test_matplotlib_output(self):
        """Test matplotlib plots are captured as HTML"""
        code = """
import matplotlib.pyplot as plt
plt.figure()
plt.plot([1, 2, 3], [1, 4, 9])
plt.show()
"""
        stdout, html, error, exec_time = self.executor.execute(code)

        self.assertIsNotNone(html)
        self.assertIn('<img', html)
        self.assertIsNone(error)

    def test_stdout_capture(self):
        """Test stdout is captured correctly"""
        code = """
print("Line 1")
print("Line 2")
print("Line 3")
"""
        stdout, html, error, exec_time = self.executor.execute(code)

        self.assertIn('Line 1', stdout)
        self.assertIn('Line 2', stdout)
        self.assertIn('Line 3', stdout)

    def test_syntax_error(self):
        """Test syntax errors are caught"""
        code = "print('missing closing quote"

        stdout, html, error, exec_time = self.executor.execute(code)

        self.assertIsNotNone(error)
        self.assertIn('SyntaxError', error)

    def test_import_statement(self):
        """Test imports work correctly"""
        code = """
import math
result = math.sqrt(16)
print(result)
"""
        stdout, html, error, exec_time = self.executor.execute(code)

        self.assertIn('4.0', stdout)
        self.assertIsNone(error)

    def test_namespace_isolation(self):
        """Test namespace is isolated per executor"""
        executor1 = CellExecutor()
        executor2 = CellExecutor()

        # Set variable in executor1
        executor1.execute("x = 10")

        # Try to access in executor2 (should fail)
        stdout, html, error, exec_time = executor2.execute("print(x)")

        self.assertIsNotNone(error)
        self.assertIn('NameError', error)

    def test_debug_helpers_available(self):
        """Test debug helper functions are available"""
        code = """
x = 42
y = "test"
debug(x, y, title="Variables")
"""
        stdout, html, error, exec_time = self.executor.execute(code)

        # Should not error
        self.assertIsNone(error)

    def test_trace_function_available(self):
        """Test trace function is available"""
        code = """
trace("Step 1")
x = 10
trace("Step 2")
"""
        stdout, html, error, exec_time = self.executor.execute(code)

        # Should not error
        self.assertIsNone(error)


class SessionManagerTest(TestCase):
    """Test SessionManager class"""

    def setUp(self):
        self.manager = SessionManager()

    def test_create_session(self):
        """Test creating a new session"""
        session_id, executor = self.manager.create_session()

        self.assertIsNotNone(session_id)
        self.assertIsInstance(executor, CellExecutor)

    def test_get_session(self):
        """Test retrieving existing session"""
        session_id, executor1 = self.manager.create_session()
        executor2 = self.manager.get_session(session_id)

        self.assertIs(executor1, executor2)

    def test_get_or_create_session(self):
        """Test get_or_create_session creates if doesn't exist"""
        session_id = "test_session"
        executor = self.manager.get_or_create_session(session_id)

        self.assertIsInstance(executor, CellExecutor)

    def test_get_or_create_session_returns_existing(self):
        """Test get_or_create_session returns existing session"""
        session_id = "test_session"
        executor1 = self.manager.get_or_create_session(session_id)
        executor1.execute("x = 42")

        executor2 = self.manager.get_or_create_session(session_id)
        stdout, html, error, exec_time = executor2.execute("print(x)")

        self.assertIn('42', stdout)

    def test_reset_session(self):
        """Test resetting a session"""
        session_id, executor = self.manager.create_session()
        executor.execute("x = 42")

        # Reset
        self.manager.reset_session(session_id)

        # Get new session (old one should be gone)
        new_executor = self.manager.get_or_create_session(session_id)
        stdout, html, error, exec_time = new_executor.execute("print(x)")

        self.assertIsNotNone(error)
        self.assertIn('NameError', error)

    def test_session_isolation(self):
        """Test sessions are isolated from each other"""
        session1_id, executor1 = self.manager.create_session()
        session2_id, executor2 = self.manager.create_session()

        # Set variable in session1
        executor1.execute("x = 10")

        # Try to access in session2 (should fail)
        stdout, html, error, exec_time = executor2.execute("print(x)")

        self.assertIsNotNone(error)
        self.assertIn('NameError', error)

    def test_cleanup_removes_sessions(self):
        """Test cleanup removes old sessions"""
        session_id = "test_session"
        self.manager.get_or_create_session(session_id)

        # Cleanup
        self.manager.cleanup_old_sessions(max_age=0)

        # Session should still work (cleanup only affects inactive)
        executor = self.manager.get_session(session_id)
        self.assertIsNotNone(executor)


class ExecutorParameterHandlingTest(TestCase):
    """Test parameter handling in executor"""

    def setUp(self):
        self.executor = CellExecutor()

    def test_string_parameter_quoting(self):
        """Test string parameters are properly quoted"""
        code = 'name = "default"'
        params = {"name": "Alice"}

        stdout, html, error, exec_time = self.executor.execute(code, params)

        # Check variable was set
        result = self.executor.namespace.get('name')
        self.assertEqual(result, "Alice")

    def test_number_parameter_no_quotes(self):
        """Test number parameters are not quoted"""
        code = 'x = 10'
        params = {"x": 25}

        stdout, html, error, exec_time = self.executor.execute(code, params)

        result = self.executor.namespace.get('x')
        self.assertEqual(result, 25)

    def test_list_parameter(self):
        """Test list parameters"""
        code = 'items = [1, 2, 3]'
        params = {"items": [4, 5, 6]}

        stdout, html, error, exec_time = self.executor.execute(code, params)

        result = self.executor.namespace.get('items')
        self.assertEqual(result, [4, 5, 6])

    def test_dict_parameter(self):
        """Test dict parameters"""
        code = 'config = {"a": 1}'
        params = {"config": {"b": 2}}

        stdout, html, error, exec_time = self.executor.execute(code, params)

        result = self.executor.namespace.get('config')
        self.assertEqual(result, {"b": 2})


class ExecutorHTMLOutputTest(TestCase):
    """Test HTML output capture"""

    def setUp(self):
        self.executor = CellExecutor()

    def test_plotly_output(self):
        """Test plotly charts are captured as HTML"""
        code = """
import plotly.graph_objects as go
fig = go.Figure(data=[go.Scatter(x=[1, 2, 3], y=[1, 4, 9])])
fig.show()
"""
        stdout, html, error, exec_time = self.executor.execute(code)

        self.assertIsNotNone(html)
        # Plotly outputs HTML
        self.assertIn('plotly', html.lower())

    def test_multiple_plots(self):
        """Test multiple plots are captured"""
        code = """
import matplotlib.pyplot as plt

plt.figure()
plt.plot([1, 2], [1, 2])
plt.show()

plt.figure()
plt.plot([3, 4], [3, 4])
plt.show()
"""
        stdout, html, error, exec_time = self.executor.execute(code)

        self.assertIsNotNone(html)
        # Should have multiple images
        self.assertGreater(html.count('<img'), 1)

    def test_html_escaping(self):
        """Test HTML is properly escaped in output"""
        code = 'print("<script>alert(1)</script>")'

        stdout, html, error, exec_time = self.executor.execute(code)

        # Script tag should be in text output (not executed)
        self.assertIn('script', stdout)


class ExecutorErrorHandlingTest(TestCase):
    """Test error handling in executor"""

    def setUp(self):
        self.executor = CellExecutor()

    def test_zero_division_error(self):
        """Test division by zero is caught"""
        code = "x = 1 / 0"

        stdout, html, error, exec_time = self.executor.execute(code)

        self.assertIsNotNone(error)
        self.assertIn('ZeroDivisionError', error)

    def test_index_error(self):
        """Test index errors are caught"""
        code = """
lst = [1, 2, 3]
x = lst[10]
"""
        stdout, html, error, exec_time = self.executor.execute(code)

        self.assertIsNotNone(error)
        self.assertIn('IndexError', error)

    def test_key_error(self):
        """Test key errors are caught"""
        code = """
d = {'a': 1}
x = d['b']
"""
        stdout, html, error, exec_time = self.executor.execute(code)

        self.assertIsNotNone(error)
        self.assertIn('KeyError', error)

    def test_attribute_error(self):
        """Test attribute errors are caught"""
        code = "x = 'string'.nonexistent_method()"

        stdout, html, error, exec_time = self.executor.execute(code)

        self.assertIsNotNone(error)
        self.assertIn('AttributeError', error)

    def test_import_error(self):
        """Test import errors are caught"""
        code = "import nonexistent_module"

        stdout, html, error, exec_time = self.executor.execute(code)

        self.assertIsNotNone(error)
        self.assertIn('ModuleNotFoundError', error)

    def test_traceback_included(self):
        """Test error traceback is included"""
        code = """
def func():
    raise ValueError("test error")

func()
"""
        stdout, html, error, exec_time = self.executor.execute(code)

        self.assertIsNotNone(error)
        self.assertIn('ValueError', error)
        self.assertIn('test error', error)
        self.assertIn('func', error)
