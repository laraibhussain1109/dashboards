"""Portable defaults: a Python venv and SQLite are sufficient to run Prism."""
import os
from pathlib import Path
from urllib.parse import unquote, urlsplit
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BASE_DIR.parent
LOCAL_DIR = Path(os.environ.get('PRISM_DATA_DIR', PROJECT_DIR / '.local'))
LOCAL_DIR.mkdir(parents=True, exist_ok=True)
DEBUG = os.environ.get('DJANGO_DEBUG', '1') == '1'
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY')
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured('Set DJANGO_SECRET_KEY when DJANGO_DEBUG=0.')
    secret_path = LOCAL_DIR / 'django-secret'
    if not secret_path.exists():
        import secrets
        try:
            with secret_path.open('x', encoding='utf8') as handle:
                handle.write(secrets.token_urlsafe(64))
            secret_path.chmod(0o600)
        except FileExistsError:
            pass
    SECRET_KEY = secret_path.read_text(encoding='utf8').strip()
ALLOWED_HOSTS = [h.strip() for h in os.environ.get('DJANGO_ALLOWED_HOSTS', '*' if DEBUG else 'localhost,127.0.0.1').split(',') if h.strip()]
CSRF_TRUSTED_ORIGINS = [h.strip() for h in os.environ.get('DJANGO_CSRF_TRUSTED_ORIGINS', '').split(',') if h.strip()]
INSTALLED_APPS = ['django.contrib.contenttypes', 'django.contrib.sessions', 'django.contrib.staticfiles', 'studio']
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
ROOT_URLCONF = 'config.urls'
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'DIRS': [], 'APP_DIRS': True, 'OPTIONS': {}}]
WSGI_APPLICATION = 'config.wsgi.application'
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': os.environ.get('SQLITE_PATH', str(LOCAL_DIR / 'db.sqlite3')), 'OPTIONS': {'timeout': 20}}}
if os.environ.get('DATABASE_URL'):
    url = urlsplit(os.environ['DATABASE_URL'])
    engines = {'postgres': 'django.db.backends.postgresql', 'postgresql': 'django.db.backends.postgresql', 'mysql': 'django.db.backends.mysql'}
    if url.scheme in engines:
        DATABASES = {'default': {'ENGINE': engines[url.scheme], 'NAME': unquote(url.path.lstrip('/')), 'USER': unquote(url.username or ''), 'PASSWORD': unquote(url.password or ''), 'HOST': url.hostname or '', 'PORT': url.port or '', 'CONN_MAX_AGE': 60}}
    elif url.scheme == 'sqlite':
        DATABASES['default']['NAME'] = unquote(url.path)
    else:
        raise ImproperlyConfigured('DATABASE_URL must use sqlite, postgres/postgresql, or mysql. Install the chosen database driver separately.')
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
SESSION_ENGINE = 'django.contrib.sessions.backends.db'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_AGE = 60 * 60 * 24 * 90
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SECURE = not DEBUG
CSRF_FAILURE_VIEW = 'studio.views.csrf_failure'
DATA_UPLOAD_MAX_MEMORY_SIZE = 30 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
PRISM_MAX_UPLOAD_BYTES = 25 * 1024 * 1024
PRISM_MAX_ROWS = 100000
MEDIA_ROOT = LOCAL_DIR / 'uploads'
MEDIA_URL = '/private-media/'  # Intentionally never routed or publicly served.
STATIC_URL = '/static/'
STATIC_ROOT = LOCAL_DIR / 'static'
FRONTEND_DIST = PROJECT_DIR / 'frontend' / 'dist'
WHITENOISE_ROOT = FRONTEND_DIST
WHITENOISE_AUTOREFRESH = DEBUG
WHITENOISE_MAX_AGE = 3600
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'
if not DEBUG:
    SECURE_SSL_REDIRECT = os.environ.get('DJANGO_SECURE_SSL_REDIRECT', '1') == '1'
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    # Only enable when the deployment proxy strips untrusted forwarding headers.
    if os.environ.get('DJANGO_TRUST_PROXY', '0') == '1':
        SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'prism-local'}}
LOGGING = {'version': 1, 'disable_existing_loggers': False, 'handlers': {'console': {'class': 'logging.StreamHandler'}}, 'root': {'handlers': ['console'], 'level': 'INFO'}}
