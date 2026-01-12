"""
Tests for views and authentication
"""
import json
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from tyk_notebook_app.models import Notebook, Cell, Parameter, NotebookSession


class AuthenticationTest(TestCase):
    """Test authentication requirements"""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser",
            password="testpass123"
        )
        self.notebook = Notebook.objects.create(
            name="Test Notebook",
            slug="test-notebook",
            is_active=True
        )

    def test_login_required_for_notebook_list(self):
        """Test notebook list requires authentication"""
        response = self.client.get(reverse('notebook:list'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_login_required_for_notebook_detail(self):
        """Test notebook detail requires authentication"""
        response = self.client.get(
            reverse('notebook:detail', args=[self.notebook.slug])
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_authenticated_access_to_notebooks(self):
        """Test authenticated user can access notebooks"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('notebook:list'))
        self.assertEqual(response.status_code, 200)

    def test_login_page_loads(self):
        """Test login page loads correctly"""
        response = self.client.get('/accounts/login/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Sign in')

    def test_successful_login(self):
        """Test user can login successfully"""
        response = self.client.post('/accounts/login/', {
            'username': 'testuser',
            'password': 'testpass123'
        })
        # Should redirect after successful login
        self.assertEqual(response.status_code, 302)

    def test_logout(self):
        """Test user can logout"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.post('/accounts/logout/')
        self.assertEqual(response.status_code, 302)

        # Try accessing protected page after logout
        response = self.client.get(reverse('notebook:list'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)


class NotebookListViewTest(TestCase):
    """Test notebook list view"""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser",
            password="testpass123"
        )
        self.client.login(username='testuser', password='testpass123')

        self.notebook1 = Notebook.objects.create(
            name="Notebook 1",
            slug="notebook-1",
            is_active=True
        )
        self.notebook2 = Notebook.objects.create(
            name="Notebook 2",
            slug="notebook-2",
            is_active=True
        )

    def test_notebook_list_displays_notebooks(self):
        """Test notebook list shows all active notebooks"""
        response = self.client.get(reverse('notebook:list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Notebook 1")
        self.assertContains(response, "Notebook 2")

    def test_inactive_notebooks_not_shown(self):
        """Test inactive notebooks are not displayed"""
        inactive = Notebook.objects.create(
            name="Inactive Notebook",
            slug="inactive",
            is_active=False
        )

        response = self.client.get(reverse('notebook:list'))
        self.assertNotContains(response, "Inactive Notebook")

    def test_empty_notebook_list(self):
        """Test message shown when no notebooks available"""
        Notebook.objects.all().delete()
        response = self.client.get(reverse('notebook:list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No notebooks available")


class NotebookDetailViewTest(TestCase):
    """Test notebook detail view"""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser",
            password="testpass123"
        )
        self.client.login(username='testuser', password='testpass123')

        self.notebook = Notebook.objects.create(
            name="Test Notebook",
            slug="test-notebook",
            is_active=True
        )

        self.cell = Cell.objects.create(
            notebook=self.notebook,
            order=1,
            title="Test Cell",
            source_code="print('Hello')",
            is_executable=True
        )

        self.param = Parameter.objects.create(
            cell=self.cell,
            name="test_param",
            param_type="string",
            default_value="test",
            order=1
        )

    def test_notebook_detail_displays_cells(self):
        """Test notebook detail shows cells"""
        response = self.client.get(
            reverse('notebook:detail', args=[self.notebook.slug])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test Cell")

    def test_notebook_detail_displays_parameters(self):
        """Test notebook detail shows parameters"""
        response = self.client.get(
            reverse('notebook:detail', args=[self.notebook.slug])
        )
        self.assertContains(response, "test_param")

    def test_notebook_detail_404_for_invalid_slug(self):
        """Test 404 for non-existent notebook"""
        response = self.client.get(
            reverse('notebook:detail', args=['invalid-slug'])
        )
        self.assertEqual(response.status_code, 404)

    def test_notebook_session_created(self):
        """Test notebook session is created on first visit"""
        self.client.get(
            reverse('notebook:detail', args=[self.notebook.slug])
        )

        session_exists = NotebookSession.objects.filter(
            notebook=self.notebook,
            user=self.user
        ).exists()
        self.assertTrue(session_exists)


class CellExecutionViewTest(TestCase):
    """Test cell execution view"""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser",
            password="testpass123"
        )
        self.client.login(username='testuser', password='testpass123')

        self.notebook = Notebook.objects.create(
            name="Test Notebook",
            slug="test-notebook"
        )

        self.cell = Cell.objects.create(
            notebook=self.notebook,
            order=1,
            title="Test Cell",
            source_code="x = 42\nprint(x)",
            is_executable=True
        )

    def test_cell_execution_requires_authentication(self):
        """Test cell execution requires login"""
        self.client.logout()
        response = self.client.post(
            reverse('notebook:run_cell', args=[self.cell.id]),
            data=json.dumps({"parameters": {}}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 302)

    def test_cell_execution_success(self):
        """Test successful cell execution"""
        response = self.client.post(
            reverse('notebook:run_cell', args=[self.cell.id]),
            data=json.dumps({"parameters": {}}),
            content_type='application/json'
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('42', data['output_text'])

    def test_cell_execution_with_error(self):
        """Test cell execution with error"""
        error_cell = Cell.objects.create(
            notebook=self.notebook,
            order=2,
            source_code="raise ValueError('test error')",
            is_executable=True
        )

        response = self.client.post(
            reverse('notebook:run_cell', args=[error_cell.id]),
            data=json.dumps({"parameters": {}}),
            content_type='application/json'
        )

        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('ValueError', data['error'])

    def test_cell_execution_with_parameters(self):
        """Test cell execution with parameters"""
        param_cell = Cell.objects.create(
            notebook=self.notebook,
            order=3,
            source_code='name = "default"\nprint(f"Hello {name}")',
            is_executable=True
        )

        Parameter.objects.create(
            cell=param_cell,
            name="name",
            param_type="string",
            default_value="default"
        )

        response = self.client.post(
            reverse('notebook:run_cell', args=[param_cell.id]),
            data=json.dumps({"parameters": {"name": "Alice"}}),
            content_type='application/json'
        )

        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('Alice', data['output_text'])

    def test_parameter_values_saved_to_session(self):
        """Test parameter values are saved to user session"""
        param_cell = Cell.objects.create(
            notebook=self.notebook,
            order=4,
            source_code='x = 10',
            is_executable=True
        )

        Parameter.objects.create(
            cell=param_cell,
            name="x",
            param_type="number",
            default_value="10"
        )

        # Execute with parameter
        self.client.post(
            reverse('notebook:run_cell', args=[param_cell.id]),
            data=json.dumps({"parameters": {"x": 25}}),
            content_type='application/json'
        )

        # Check session
        session = NotebookSession.objects.get(
            notebook=self.notebook,
            user=self.user
        )
        self.assertEqual(session.parameter_values[f"{param_cell.id}_x"], 25)


class SetupViewTest(TestCase):
    """Test setup cell execution"""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser",
            password="testpass123"
        )
        self.client.login(username='testuser', password='testpass123')

        self.notebook = Notebook.objects.create(
            name="Test Notebook",
            slug="test-notebook"
        )

        self.setup_cell = Cell.objects.create(
            notebook=self.notebook,
            order=1,
            title="Setup",
            source_code="import sys\nprint('Setup complete')",
            is_setup_cell=True
        )

    def test_setup_execution(self):
        """Test setup cells can be executed"""
        response = self.client.post(
            reverse('notebook:setup', args=[self.notebook.slug])
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('Setup complete', data['output'])

    def test_setup_updates_session_state(self):
        """Test setup completion updates session state"""
        self.client.post(
            reverse('notebook:run_setup', args=[self.notebook.slug])
        )

        session = NotebookSession.objects.get(
            notebook=self.notebook,
            user=self.user
        )
        self.assertTrue(session.kernel_state.get('setup_complete'))


class SessionResetViewTest(TestCase):
    """Test session reset functionality"""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser",
            password="testpass123"
        )
        self.client.login(username='testuser', password='testpass123')

        self.notebook = Notebook.objects.create(
            name="Test Notebook",
            slug="test-notebook"
        )

        # Create a session with data
        self.session = NotebookSession.objects.create(
            notebook=self.notebook,
            user=self.user,
            parameter_values={"x": 1},
            kernel_state={"setup_complete": True}
        )

    def test_session_reset(self):
        """Test session can be reset"""
        response = self.client.post(
            reverse('notebook:reset', args=[self.notebook.slug])
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])

        # Session should be deleted
        session_exists = NotebookSession.objects.filter(
            notebook=self.notebook,
            user=self.user
        ).exists()
        self.assertFalse(session_exists)


class MultiUserIsolationTest(TestCase):
    """Test multi-user session isolation"""

    def setUp(self):
        self.user1 = User.objects.create_user(
            username="user1",
            password="pass1"
        )
        self.user2 = User.objects.create_user(
            username="user2",
            password="pass2"
        )

        self.notebook = Notebook.objects.create(
            name="Test Notebook",
            slug="test-notebook"
        )

        self.cell = Cell.objects.create(
            notebook=self.notebook,
            order=1,
            source_code='x = 1\nprint(x)',
            is_executable=True
        )

        Parameter.objects.create(
            cell=self.cell,
            name="x",
            param_type="number",
            default_value="1"
        )

    def test_users_have_separate_sessions(self):
        """Test each user has their own session"""
        client1 = Client()
        client2 = Client()

        client1.login(username='user1', password='pass1')
        client2.login(username='user2', password='pass2')

        # Both access notebook
        client1.get(reverse('notebook:detail', args=[self.notebook.slug]))
        client2.get(reverse('notebook:detail', args=[self.notebook.slug]))

        # Check separate sessions created
        session1 = NotebookSession.objects.get(
            notebook=self.notebook,
            user=self.user1
        )
        session2 = NotebookSession.objects.get(
            notebook=self.notebook,
            user=self.user2
        )

        self.assertNotEqual(session1.id, session2.id)

    def test_parameter_values_isolated_between_users(self):
        """Test parameter values are isolated per user"""
        client1 = Client()
        client2 = Client()

        client1.login(username='user1', password='pass1')
        client2.login(username='user2', password='pass2')

        # User 1 executes with x=10
        client1.post(
            reverse('notebook:run_cell', args=[self.cell.id]),
            data=json.dumps({"parameters": {"x": 10}}),
            content_type='application/json'
        )

        # User 2 executes with x=20
        client2.post(
            reverse('notebook:run_cell', args=[self.cell.id]),
            data=json.dumps({"parameters": {"x": 20}}),
            content_type='application/json'
        )

        # Check isolated values
        session1 = NotebookSession.objects.get(
            notebook=self.notebook,
            user=self.user1
        )
        session2 = NotebookSession.objects.get(
            notebook=self.notebook,
            user=self.user2
        )

        self.assertEqual(session1.parameter_values[f"{self.cell.id}_x"], 10)
        self.assertEqual(session2.parameter_values[f"{self.cell.id}_x"], 20)
