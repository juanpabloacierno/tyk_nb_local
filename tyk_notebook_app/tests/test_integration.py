"""
Integration tests for end-to-end workflows
"""
import json
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from tyk_notebook_app.models import (
    Notebook, Cell, Parameter, Execution, NotebookSession
)


class CompleteNotebookWorkflowTest(TestCase):
    """Test complete notebook execution workflow"""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser",
            password="testpass123"
        )
        self.client.login(username='testuser', password='testpass123')

        # Create a complete notebook
        self.notebook = Notebook.objects.create(
            name="Data Analysis Notebook",
            slug="data-analysis",
            description="Test notebook for data analysis",
            is_active=True
        )

        # Setup cell
        self.setup_cell = Cell.objects.create(
            notebook=self.notebook,
            order=0,
            title="Setup",
            source_code="import pandas as pd\nimport numpy as np\nprint('Setup complete')",
            is_setup_cell=True
        )

        # Code cell with parameters
        self.analysis_cell = Cell.objects.create(
            notebook=self.notebook,
            order=1,
            title="Analysis",
            source_code="""
n = 10
data = list(range(n))
mean = sum(data) / len(data)
print(f"Mean: {mean}")
""",
            is_executable=True
        )

        Parameter.objects.create(
            cell=self.analysis_cell,
            name="n",
            param_type="number",
            default_value="10",
            order=1
        )

        # Visualization cell
        self.viz_cell = Cell.objects.create(
            notebook=self.notebook,
            order=2,
            title="Visualization",
            source_code="""
import matplotlib.pyplot as plt
plt.figure(figsize=(6, 4))
plt.plot([1, 2, 3, 4], [1, 4, 9, 16])
plt.title('Simple Plot')
plt.show()
""",
            is_executable=True
        )

    def test_complete_workflow(self):
        """Test complete notebook workflow from start to finish"""

        # 1. Access notebook list
        response = self.client.get(reverse('notebook:list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Data Analysis Notebook")

        # 2. Open notebook
        response = self.client.get(
            reverse('notebook:detail', args=[self.notebook.slug])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Setup")
        self.assertContains(response, "Analysis")

        # 3. Run setup
        response = self.client.post(
            reverse('notebook:setup', args=[self.notebook.slug])
        )
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('Setup complete', data['output'])

        # 4. Execute analysis cell with parameter
        response = self.client.post(
            reverse('notebook:run_cell', args=[self.analysis_cell.id]),
            data=json.dumps({"parameters": {"n": 20}}),
            content_type='application/json'
        )
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('Mean', data['output_text'])

        # 5. Execute visualization cell
        response = self.client.post(
            reverse('notebook:run_cell', args=[self.viz_cell.id]),
            data=json.dumps({"parameters": {}}),
            content_type='application/json'
        )
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIsNotNone(data.get('output_html'))

        # 6. Verify execution history
        executions = Execution.objects.filter(cell__notebook=self.notebook)
        self.assertGreaterEqual(executions.count(), 2)

        # 7. Verify session state
        session = NotebookSession.objects.get(
            notebook=self.notebook,
            user=self.user
        )
        self.assertTrue(session.kernel_state.get('setup_complete'))
        self.assertEqual(session.parameter_values[f"{self.analysis_cell.id}_n"], 20)


class MultiUserCollaborationTest(TestCase):
    """Test multiple users working on notebooks simultaneously"""

    def setUp(self):
        self.user1 = User.objects.create_user(
            username="analyst1",
            password="pass1"
        )
        self.user2 = User.objects.create_user(
            username="analyst2",
            password="pass2"
        )

        self.notebook = Notebook.objects.create(
            name="Shared Notebook",
            slug="shared-notebook",
            is_active=True
        )

        self.cell = Cell.objects.create(
            notebook=self.notebook,
            order=1,
            title="Shared Cell",
            source_code="""
multiplier = 2
result = multiplier * 10
print(f"Result: {result}")
""",
            is_executable=True
        )

        Parameter.objects.create(
            cell=self.cell,
            name="multiplier",
            param_type="number",
            default_value="2"
        )

    def test_concurrent_user_access(self):
        """Test multiple users can work concurrently"""
        client1 = Client()
        client2 = Client()

        client1.login(username='analyst1', password='pass1')
        client2.login(username='analyst2', password='pass2')

        # Both users access notebook
        response1 = client1.get(
            reverse('notebook:detail', args=[self.notebook.slug])
        )
        response2 = client2.get(
            reverse('notebook:detail', args=[self.notebook.slug])
        )

        self.assertEqual(response1.status_code, 200)
        self.assertEqual(response2.status_code, 200)

        # User 1 executes with multiplier=3
        response1 = client1.post(
            reverse('notebook:run_cell', args=[self.cell.id]),
            data=json.dumps({"parameters": {"multiplier": 3}}),
            content_type='application/json'
        )
        data1 = response1.json()
        self.assertTrue(data1['success'])
        self.assertIn('30', data1['output_text'])

        # User 2 executes with multiplier=5
        response2 = client2.post(
            reverse('notebook:run_cell', args=[self.cell.id]),
            data=json.dumps({"parameters": {"multiplier": 5}}),
            content_type='application/json'
        )
        data2 = response2.json()
        self.assertTrue(data2['success'])
        self.assertIn('50', data2['output_text'])

        # Verify separate sessions
        session1 = NotebookSession.objects.get(
            notebook=self.notebook,
            user=self.user1
        )
        session2 = NotebookSession.objects.get(
            notebook=self.notebook,
            user=self.user2
        )

        self.assertEqual(
            session1.parameter_values[f"{self.cell.id}_multiplier"],
            3
        )
        self.assertEqual(
            session2.parameter_values[f"{self.cell.id}_multiplier"],
            5
        )


class ParameterTypesTest(TestCase):
    """Test all parameter types work correctly"""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser",
            password="testpass123"
        )
        self.client.login(username='testuser', password='testpass123')

        self.notebook = Notebook.objects.create(
            name="Parameter Test",
            slug="param-test"
        )

        self.cell = Cell.objects.create(
            notebook=self.notebook,
            order=1,
            source_code="""
text_val = "default"
num_val = 10
bool_val = True
select_val = "option1"

print(f"Text: {text_val}")
print(f"Number: {num_val}")
print(f"Boolean: {bool_val}")
print(f"Select: {select_val}")
""",
            is_executable=True
        )

        # String parameter
        Parameter.objects.create(
            cell=self.cell,
            name="text_val",
            param_type="string",
            default_value="default",
            order=1
        )

        # Number parameter
        Parameter.objects.create(
            cell=self.cell,
            name="num_val",
            param_type="number",
            default_value="10",
            order=2
        )

        # Boolean parameter
        Parameter.objects.create(
            cell=self.cell,
            name="bool_val",
            param_type="boolean",
            default_value="True",
            order=3
        )

        # Dropdown parameter
        Parameter.objects.create(
            cell=self.cell,
            name="select_val",
            param_type="dropdown",
            default_value="option1",
            options=["option1", "option2", "option3"],
            order=4
        )

    def test_all_parameter_types(self):
        """Test execution with all parameter types"""
        response = self.client.post(
            reverse('notebook:run_cell', args=[self.cell.id]),
            data=json.dumps({
                "parameters": {
                    "text_val": "custom text",
                    "num_val": 42,
                    "bool_val": False,
                    "select_val": "option2"
                }
            }),
            content_type='application/json'
        )

        data = response.json()
        self.assertTrue(data['success'])

        output = data['output_text']
        self.assertIn('custom text', output)
        self.assertIn('42', output)
        self.assertIn('False', output)
        self.assertIn('option2', output)


class ErrorHandlingTest(TestCase):
    """Test error handling in various scenarios"""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser",
            password="testpass123"
        )
        self.client.login(username='testuser', password='testpass123')

        self.notebook = Notebook.objects.create(
            name="Error Test",
            slug="error-test"
        )

    def test_syntax_error_in_cell(self):
        """Test execution with syntax error"""
        cell = Cell.objects.create(
            notebook=self.notebook,
            order=1,
            source_code="print('unclosed string",
            is_executable=True
        )

        response = self.client.post(
            reverse('notebook:run_cell', args=[cell.id]),
            data=json.dumps({"parameters": {}}),
            content_type='application/json'
        )

        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('SyntaxError', data['error'])

    def test_runtime_error_in_cell(self):
        """Test execution with runtime error"""
        cell = Cell.objects.create(
            notebook=self.notebook,
            order=2,
            source_code="x = 1 / 0",
            is_executable=True
        )

        response = self.client.post(
            reverse('notebook:run_cell', args=[cell.id]),
            data=json.dumps({"parameters": {}}),
            content_type='application/json'
        )

        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('ZeroDivisionError', data['error'])

    def test_undefined_variable_error(self):
        """Test execution with undefined variable"""
        cell = Cell.objects.create(
            notebook=self.notebook,
            order=3,
            source_code="print(undefined_variable)",
            is_executable=True
        )

        response = self.client.post(
            reverse('notebook:run_cell', args=[cell.id]),
            data=json.dumps({"parameters": {}}),
            content_type='application/json'
        )

        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('NameError', data['error'])

    def test_execution_creates_error_record(self):
        """Test failed executions are recorded"""
        cell = Cell.objects.create(
            notebook=self.notebook,
            order=4,
            source_code="raise Exception('test')",
            is_executable=True
        )

        self.client.post(
            reverse('notebook:run_cell', args=[cell.id]),
            data=json.dumps({"parameters": {}}),
            content_type='application/json'
        )

        # Check execution record
        execution = Execution.objects.filter(cell=cell).first()
        self.assertIsNotNone(execution)
        self.assertEqual(execution.status, 'error')
        self.assertIn('Exception', execution.error_message)


class SessionPersistenceTest(TestCase):
    """Test session state persistence"""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser",
            password="testpass123"
        )
        self.client.login(username='testuser', password='testpass123')

        self.notebook = Notebook.objects.create(
            name="Session Test",
            slug="session-test"
        )

        self.cell = Cell.objects.create(
            notebook=self.notebook,
            order=1,
            source_code="value = 100",
            is_executable=True
        )

        Parameter.objects.create(
            cell=self.cell,
            name="value",
            param_type="number",
            default_value="100"
        )

    def test_parameter_values_persist(self):
        """Test parameter values persist across page loads"""
        # Execute with custom value
        self.client.post(
            reverse('notebook:run_cell', args=[self.cell.id]),
            data=json.dumps({"parameters": {"value": 250}}),
            content_type='application/json'
        )

        # Reload notebook page
        response = self.client.get(
            reverse('notebook:detail', args=[self.notebook.slug])
        )

        # Check session has saved value
        session = NotebookSession.objects.get(
            notebook=self.notebook,
            user=self.user
        )
        self.assertEqual(session.parameter_values[f"{self.cell.id}_value"], 250)

    def test_session_reset_clears_state(self):
        """Test session reset clears all state"""
        # Execute cell
        self.client.post(
            reverse('notebook:run_cell', args=[self.cell.id]),
            data=json.dumps({"parameters": {"value": 300}}),
            content_type='application/json'
        )

        # Verify session exists
        self.assertTrue(
            NotebookSession.objects.filter(
                notebook=self.notebook,
                user=self.user
            ).exists()
        )

        # Reset session
        self.client.post(
            reverse('notebook:reset', args=[self.notebook.slug])
        )

        # Verify session is deleted
        self.assertFalse(
            NotebookSession.objects.filter(
                notebook=self.notebook,
                user=self.user
            ).exists()
        )


class MarkdownCellTest(TestCase):
    """Test markdown cell rendering"""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser",
            password="testpass123"
        )
        self.client.login(username='testuser', password='testpass123')

        self.notebook = Notebook.objects.create(
            name="Markdown Test",
            slug="markdown-test"
        )

        self.markdown_cell = Cell.objects.create(
            notebook=self.notebook,
            order=1,
            title="Documentation",
            cell_type="markdown",
            description="""
# Title
This is **bold** and this is *italic*.

## Code Block
```python
print("Hello")
```

## List
- Item 1
- Item 2
""",
            is_executable=False
        )

    def test_markdown_rendered_in_page(self):
        """Test markdown cells are rendered as HTML"""
        response = self.client.get(
            reverse('notebook:detail', args=[self.notebook.slug])
        )

        self.assertEqual(response.status_code, 200)
        # Check markdown is converted to HTML (not raw markdown)
        self.assertNotContains(response, '# Title')
        self.assertContains(response, '<strong>bold</strong>')
        self.assertContains(response, '<em>italic</em>')
