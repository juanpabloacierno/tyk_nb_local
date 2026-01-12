"""
Tests for Django models
"""
from django.test import TestCase
from django.contrib.auth.models import User
from tyk_notebook_app.models import Notebook, Cell, Parameter, Execution, NotebookSession


class NotebookModelTest(TestCase):
    """Test Notebook model"""

    def setUp(self):
        self.notebook = Notebook.objects.create(
            name="Test Notebook",
            slug="test-notebook",
            description="Test description",
            is_active=True
        )

    def test_notebook_creation(self):
        """Test notebook can be created"""
        self.assertEqual(self.notebook.name, "Test Notebook")
        self.assertEqual(self.notebook.slug, "test-notebook")
        self.assertTrue(self.notebook.is_active)

    def test_notebook_str(self):
        """Test notebook string representation"""
        self.assertEqual(str(self.notebook), "Test Notebook")

    def test_notebook_ordering(self):
        """Test notebooks are ordered by updated_at"""
        nb1 = Notebook.objects.create(name="NB1", slug="nb1")
        nb2 = Notebook.objects.create(name="NB2", slug="nb2")

        notebooks = list(Notebook.objects.all())
        # Most recent should be first
        self.assertEqual(notebooks[0].name, "NB2")

    def test_get_executable_cells(self):
        """Test getting executable cells"""
        Cell.objects.create(
            notebook=self.notebook,
            order=1,
            title="Cell 1",
            source_code="print('test')",
            is_executable=True
        )
        Cell.objects.create(
            notebook=self.notebook,
            order=2,
            title="Cell 2",
            source_code="# markdown",
            cell_type="markdown",
            is_executable=False
        )

        executable = self.notebook.get_executable_cells()
        self.assertEqual(executable.count(), 1)
        self.assertEqual(executable.first().title, "Cell 1")


class CellModelTest(TestCase):
    """Test Cell model"""

    def setUp(self):
        self.notebook = Notebook.objects.create(
            name="Test Notebook",
            slug="test-notebook"
        )
        self.cell = Cell.objects.create(
            notebook=self.notebook,
            order=1,
            title="Test Cell",
            source_code="x = 42",
            cell_type="code",
            is_executable=True
        )

    def test_cell_creation(self):
        """Test cell can be created"""
        self.assertEqual(self.cell.title, "Test Cell")
        self.assertEqual(self.cell.order, 1)
        self.assertEqual(self.cell.cell_type, "code")

    def test_cell_str(self):
        """Test cell string representation"""
        expected = f"{self.notebook.name} - Cell 1: Test Cell"
        self.assertEqual(str(self.cell), expected)

    def test_cell_ordering(self):
        """Test cells are ordered by order field"""
        cell2 = Cell.objects.create(
            notebook=self.notebook,
            order=2,
            title="Cell 2",
            source_code="y = 43"
        )

        cells = list(self.notebook.cells.all())
        self.assertEqual(cells[0].order, 1)
        self.assertEqual(cells[1].order, 2)

    def test_markdown_cell_optional_source_code(self):
        """Test markdown cells can have empty source_code"""
        markdown_cell = Cell.objects.create(
            notebook=self.notebook,
            order=3,
            title="Markdown Cell",
            cell_type="markdown",
            source_code="",
            is_executable=False
        )
        self.assertEqual(markdown_cell.source_code, "")

    def test_get_code_with_params(self):
        """Test parameter substitution in code"""
        cell = Cell.objects.create(
            notebook=self.notebook,
            order=10,
            title="Param Cell",
            source_code='name = "default"\nage = 25'
        )

        # Create parameters
        Parameter.objects.create(
            cell=cell,
            name="name",
            param_type="string",
            default_value="default"
        )
        Parameter.objects.create(
            cell=cell,
            name="age",
            param_type="number",
            default_value="25"
        )

        # Test substitution
        param_values = {"name": "Alice", "age": 30}
        code = cell.get_code_with_params(param_values)

        self.assertIn('name = "Alice"', code)
        self.assertIn('age = 30', code)


class ParameterModelTest(TestCase):
    """Test Parameter model"""

    def setUp(self):
        self.notebook = Notebook.objects.create(name="NB", slug="nb")
        self.cell = Cell.objects.create(
            notebook=self.notebook,
            order=1,
            source_code="x = 1"
        )
        self.param = Parameter.objects.create(
            cell=self.cell,
            name="test_param",
            param_type="string",
            default_value="test",
            order=1
        )

    def test_parameter_creation(self):
        """Test parameter can be created"""
        self.assertEqual(self.param.name, "test_param")
        self.assertEqual(self.param.param_type, "string")
        self.assertEqual(self.param.default_value, "test")

    def test_parameter_str(self):
        """Test parameter string representation"""
        self.assertIn("test_param", str(self.param))

    def test_parameter_types(self):
        """Test all parameter types can be created"""
        types = ['dropdown', 'string', 'number', 'boolean', 'slider']

        for i, ptype in enumerate(types):
            param = Parameter.objects.create(
                cell=self.cell,
                name=f"param_{ptype}",
                param_type=ptype,
                default_value="default",
                order=i + 2
            )
            self.assertEqual(param.param_type, ptype)

    def test_get_options_list(self):
        """Test getting options as list"""
        param = Parameter.objects.create(
            cell=self.cell,
            name="dropdown_param",
            param_type="dropdown",
            options=["opt1", "opt2", "opt3"],
            order=10
        )

        options = param.get_options_list()
        self.assertEqual(options, ["opt1", "opt2", "opt3"])


class ExecutionModelTest(TestCase):
    """Test Execution model"""

    def setUp(self):
        self.notebook = Notebook.objects.create(name="NB", slug="nb")
        self.cell = Cell.objects.create(
            notebook=self.notebook,
            order=1,
            source_code="print('test')"
        )

    def test_execution_creation(self):
        """Test execution record can be created"""
        execution = Execution.objects.create(
            cell=self.cell,
            parameters={"x": 1},
            status="success",
            output_text="test output",
            execution_time=0.5
        )

        self.assertEqual(execution.status, "success")
        self.assertEqual(execution.output_text, "test output")
        self.assertEqual(execution.execution_time, 0.5)

    def test_execution_ordering(self):
        """Test executions ordered by created_at descending"""
        exec1 = Execution.objects.create(cell=self.cell, status="success")
        exec2 = Execution.objects.create(cell=self.cell, status="success")

        executions = list(Execution.objects.all())
        # Most recent first
        self.assertEqual(executions[0].id, exec2.id)

    def test_execution_statuses(self):
        """Test all execution statuses"""
        statuses = ['pending', 'running', 'success', 'error']

        for status in statuses:
            execution = Execution.objects.create(
                cell=self.cell,
                status=status
            )
            self.assertEqual(execution.status, status)


class NotebookSessionModelTest(TestCase):
    """Test NotebookSession model"""

    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser",
            password="testpass"
        )
        self.notebook = Notebook.objects.create(name="NB", slug="nb")

    def test_session_creation(self):
        """Test notebook session can be created"""
        session = NotebookSession.objects.create(
            notebook=self.notebook,
            user=self.user,
            parameter_values={"x": 1},
            kernel_state={"setup_complete": True}
        )

        self.assertEqual(session.user, self.user)
        self.assertEqual(session.parameter_values, {"x": 1})
        self.assertTrue(session.kernel_state["setup_complete"])

    def test_session_unique_constraint(self):
        """Test unique_together constraint on notebook and user"""
        NotebookSession.objects.create(
            notebook=self.notebook,
            user=self.user
        )

        # Try to create duplicate - should raise IntegrityError
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            NotebookSession.objects.create(
                notebook=self.notebook,
                user=self.user
            )

    def test_session_str(self):
        """Test session string representation"""
        session = NotebookSession.objects.create(
            notebook=self.notebook,
            user=self.user
        )

        expected = f"{self.user.username} - {self.notebook.name}"
        self.assertEqual(str(session), expected)

    def test_multiple_users_same_notebook(self):
        """Test multiple users can have sessions for same notebook"""
        user2 = User.objects.create_user(username="user2", password="pass")

        session1 = NotebookSession.objects.create(
            notebook=self.notebook,
            user=self.user
        )
        session2 = NotebookSession.objects.create(
            notebook=self.notebook,
            user=user2
        )

        self.assertNotEqual(session1.id, session2.id)
        self.assertEqual(
            NotebookSession.objects.filter(notebook=self.notebook).count(),
            2
        )
