"""
Django settings for TyK Notebook Application.
Supports both development and packaged (PyInstaller) modes.
"""
import os
import sys
from pathlib import Path

# Handle frozen application (PyInstaller)
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys._MEIPASS)
    RUNTIME_DIR = Path(os.path.dirname(sys.executable))
    DATA_DIR = Path(os.environ.get("TYK_DB_PATH", RUNTIME_DIR / "tyk_data"))
    DATA_DIR.mkdir(parents=True, exist_ok=True)
else:
    BASE_DIR = Path(__file__).resolve().parent.parent  # project root
    RUNTIME_DIR = BASE_DIR
    DATA_DIR = BASE_DIR / 'tyk_notebook_app'  # db lives here, same as before

PROJECT_ROOT = RUNTIME_DIR


def _load_or_create_secret_key():
    key_file = DATA_DIR / '.secret_key'
    try:
        return key_file.read_text().strip()
    except FileNotFoundError:
        key = 'tyk-notebook-dev-key-' + os.urandom(32).hex()
        key_file.write_text(key)
        return key


SECRET_KEY = _load_or_create_secret_key()

DEBUG = True

ALLOWED_HOSTS = ['localhost', '127.0.0.1', '0.0.0.0', 'demo.trackyourknowledge.com']

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
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'
WSGI_APPLICATION = 'config.wsgi.application'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
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

from django.utils.translation import gettext_lazy as _

LANGUAGES = [
    ('en', _('English')),
    ('es', _('Spanish')),
    ('pt', _('Portuguese')),
]

LOCALE_PATHS = [
    BASE_DIR / 'tyk_notebook_app' / 'locale',
]

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [
    BASE_DIR / 'tyk_notebook_app' / 'static'
] if (BASE_DIR / 'tyk_notebook_app' / 'static').exists() else []
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/accounts/login/'

EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

TYK_DATA_PATH = os.environ.get('TYK_DATA_PATH', str(PROJECT_ROOT))
