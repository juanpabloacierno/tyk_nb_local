"""
Django settings for TyK Notebook Application.
Supports both development and packaged (PyInstaller) modes.
"""
import os
import sys
from pathlib import Path

# Handle frozen application (PyInstaller)
if getattr(sys, 'frozen', False):
    # Running as compiled executable
    BASE_DIR = Path(sys._MEIPASS) / "tyk_notebook_app"
    RUNTIME_DIR = Path(os.path.dirname(sys.executable))
    # Data directory for database and user files (writable location)
    DATA_DIR = Path(os.environ.get("TYK_DB_PATH", RUNTIME_DIR / "tyk_data"))
    DATA_DIR.mkdir(parents=True, exist_ok=True)
else:
    # Running as script (development mode)
    BASE_DIR = Path(__file__).resolve().parent
    RUNTIME_DIR = BASE_DIR.parent
    DATA_DIR = BASE_DIR  # In dev mode, use app directory

PROJECT_ROOT = RUNTIME_DIR

SECRET_KEY = 'tyk-notebook-dev-key-change-in-production-' + os.urandom(16).hex()

DEBUG = True

ALLOWED_HOSTS = ['localhost', '127.0.0.1', '0.0.0.0', '*']

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'tyk_notebook_app',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'tyk_notebook_app.urls_main'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': DATA_DIR / 'db.sqlite3',
    }
}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_L10N = True
USE_TZ = True

# Internationalization
from django.utils.translation import gettext_lazy as _

LANGUAGES = [
    ('en', _('English')),
    ('es', _('Spanish')),
]

LOCALE_PATHS = [
    BASE_DIR / 'locale',
]

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static'] if (BASE_DIR / 'static').exists() else []

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Authentication settings
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/accounts/login/'

# Email settings for password reset (console backend for development)
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
# For production, configure these:
# EMAIL_HOST = 'smtp.gmail.com'
# EMAIL_PORT = 587
# EMAIL_USE_TLS = True
# EMAIL_HOST_USER = 'your-email@example.com'
# EMAIL_HOST_PASSWORD = 'your-password'

# TyK specific settings
TYK_DATA_PATH = os.environ.get('TYK_DATA_PATH', str(PROJECT_ROOT))
