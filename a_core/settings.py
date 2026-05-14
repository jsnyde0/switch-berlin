"""Django settings for Switch."""

from pathlib import Path

import dj_database_url
from environ import Env

BASE_DIR = Path(__file__).resolve().parent.parent

env = Env()
Env.read_env(env_file=BASE_DIR / ".env")

SECRET_KEY = env.str("SECRET_KEY")

DEBUG = env.bool("DEBUG", default=False)

# Behind Caddy TLS termination: trust X-Forwarded-Proto so request.is_secure()
# returns True. Without this, CsrfViewMiddleware sees an http:// scheme and
# rejects POSTs that arrive with Origin: https://switch.berlin (403).
# Caddy's reverse_proxy sets X-Forwarded-Proto by default.
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    # Production hardening (kb-2e3). Gated on not DEBUG so dev/CI stay HTTP.
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    # Caddy also sets Referrer-Policy at the edge (infra/Caddyfile); Django owns
    # it too so the policy survives any future edge swap. Same value either way.
    SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
    # Isolate the browsing context group from cross-origin openers (Spectre /
    # tabnabbing hardening). Zero downside for a server-rendered site.
    SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
    # HSTS: start short. Bump to 31536000 + preload only after the short
    # window has soaked clean for a few weeks. Sticky once preloaded.
    SECURE_HSTS_SECONDS = 60 * 60  # 1 hour
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
    SECURE_HSTS_PRELOAD = False
    # Django 4+ requires explicit trusted origins for CSRF when proxied (#9).
    CSRF_TRUSTED_ORIGINS = env.list(
        "CSRF_TRUSTED_ORIGINS",
        default=["https://switch.berlin", "https://www.switch.berlin"],
    )

# Explicit SameSite (Django 4.1+ defaults to "Lax" but reads clearer here).
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

# Cap multipart body and individual file uploads. Anything larger should go
# through dedicated object storage (not yet wired). Defaults are 2.5 MiB —
# explicit ceiling avoids relying on framework defaults shifting.
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10 MiB
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10 MiB

if DEBUG:
    import socket

    hostname, _, ips = socket.gethostbyname_ex(socket.gethostname())
    INTERNAL_IPS = ["127.0.0.1", "10.0.2.2"]
    INTERNAL_IPS.extend([ip[:-1] + "1" for ip in ips])

ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])

SITE_URL = env.str("SITE_URL", default="http://localhost:8000")


AUTH_USER_MODEL = "accounts.User"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.sites",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    # 3rd party
    "allauth",
    "allauth.account",
    "debug_toolbar",
    "django_cotton.apps.SimpleAppConfig",
    "django_htmx",
    "django_vite",
    "django_q",
    "template_partials.apps.SimpleAppConfig",
    # local
    "a_core.apps.ACoreConfig",
    "accounts",
    "pages",
    "organizers",
    "venues",
    "events",
    "ingestion",
    "reviews",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "a_core.middleware.TrustedProxyIPMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "debug_toolbar.middleware.DebugToolbarMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "accounts.middleware.LoginWallMiddleware",
    "accounts.middleware.AgeGateMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]

ROOT_URLCONF = "a_core.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "NAME": "myname",
        "DIRS": [BASE_DIR / "templates"],
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "a_core.context_processors.feature_flags",
                "a_core.context_processors.legal_contact_processor",
            ],
            "loaders": [
                (
                    "template_partials.loader.Loader",
                    [
                        (
                            "django.template.loaders.cached.Loader",
                            [
                                "django_cotton.cotton_loader.Loader",
                                "django.template.loaders.filesystem.Loader",
                                "django.template.loaders.app_directories.Loader",
                            ],
                        )
                    ],
                )
            ],
            "builtins": [
                "django_cotton.templatetags.cotton",
                "template_partials.templatetags.partials",
            ],
        },
    },
]

WSGI_APPLICATION = "a_core.wsgi.application"

DATABASE_URL = env.str(
    "DATABASE_URL", default="postgres://postgres:postgres@db:5432/postgres"
)
DATABASES = {"default": dj_database_url.parse(DATABASE_URL)}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": f"django.contrib.auth.password_validation.{v}"}
    for v in [
        "UserAttributeSimilarityValidator",
        "MinimumLengthValidator",
        "CommonPasswordValidator",
        "NumericPasswordValidator",
    ]
]

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

SITE_ID = 1

LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "home"

ACCOUNT_SESSION_REMEMBER = True
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_EMAIL_VERIFICATION = "optional"
ACCOUNT_ADAPTER = "accounts.adapter.NoSignupAdapter"

EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
if EMAIL_HOST and EMAIL_HOST_USER and EMAIL_HOST_PASSWORD:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_PORT = 587
    EMAIL_USE_TLS = True
    DEFAULT_FROM_EMAIL = f"Switch Berlin <{EMAIL_HOST_USER}>"
    ACCOUNT_EMAIL_SUBJECT_PREFIX = "[Switch Berlin] "
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
    DEFAULT_FROM_EMAIL = "Switch Berlin <noreply@localhost>"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Europe/Berlin"
USE_I18N = True
LANGUAGES = [("en", "English"), ("de", "Deutsch")]
LOCALE_PATHS = [BASE_DIR / "locale"]
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Django-Q2: use ORM broker on Postgres (no Redis)
Q_CLUSTER = {
    "name": "switch",
    "workers": 2,
    "recycle": 500,
    "timeout": 300,
    "retry": 600,
    "queue_limit": 50,
    "bulk": 10,
    "orm": "default",
}

# django-vite: React island on /events
# Vite builds to static/dist/, so static_url_prefix="dist" makes generated URLs
# include /dist/ (e.g. /static/dist/assets/app-<hash>.css) — matches the path
# WhiteNoise serves after collectstatic.
DJANGO_VITE = {
    "default": {
        "dev_mode": DEBUG,
        "dev_server_port": 5173,
        "static_url_prefix": "dist",
        "manifest_path": BASE_DIR / "static" / "dist" / ".vite" / "manifest.json",
    }
}

TELEGRAM_BOT_TOKEN = env.str("TELEGRAM_BOT_TOKEN", default="")

LLM_MODEL_NAME = env.str("LLM_MODEL_NAME", default="claude-opus-4-7")

RATELIMIT_ENABLE = env.bool("RATELIMIT_ENABLE", default=True)
# Fail open when the cache backend is unavailable. Narrow risk window is the
# few seconds during a fresh deploy between gunicorn worker boot and the
# 0007_cache_table migration finishing — without this, any rate-limited POST
# in that window would hard-block. Tradeoff: brief "no rate limiting" beats
# brief "no auth at all".
RATELIMIT_FAIL_OPEN = True

# Shared cache for rate-limiting across all gunicorn workers.
# Without this, each worker has its own LocMemCache and the effective
# rate-limit is N × declared (one bucket per worker). DatabaseCache uses
# the same Postgres instance all workers share. The cache_table must be
# created via the 0007_cache_table migration in a_core.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "cache_table",
    }
}

# ---------------------------------------------------------------------------
# Legal contact / Impressum settings (D3: ship structure now, fill at deploy)
# ---------------------------------------------------------------------------
# Required for public deployment (E006 blocks if empty when PUBLIC_READ_ENABLED=True).
IMPRESSUM_NAME = env.str("IMPRESSUM_NAME", default="")
IMPRESSUM_ADDRESS = env.str("IMPRESSUM_ADDRESS", default="")
IMPRESSUM_EMAIL = env.str("IMPRESSUM_EMAIL", default="")

# Optional — second contact channel (renders "contact form" fallback when empty).
IMPRESSUM_PHONE = env.str("IMPRESSUM_PHONE", default="")

# §18 MStV responsible person (defaults to IMPRESSUM_* if unset).
RESPONSIBLE_PERSON_NAME = (
    env.str("RESPONSIBLE_PERSON_NAME", default="") or IMPRESSUM_NAME
)
RESPONSIBLE_PERSON_ADDRESS = (
    env.str("RESPONSIBLE_PERSON_ADDRESS", default="") or IMPRESSUM_ADDRESS
)

# DSA Art. 11/12 contact point (defaults to IMPRESSUM_EMAIL if unset).
DSA_CONTACT_EMAIL = env.str("DSA_CONTACT_EMAIL", default="") or IMPRESSUM_EMAIL

# Assembled dict — used by context processor and templates.
LEGAL_CONTACT = {
    "name": IMPRESSUM_NAME,
    "address": IMPRESSUM_ADDRESS,
    "email": IMPRESSUM_EMAIL,
    "phone": IMPRESSUM_PHONE,
    "responsible_name": RESPONSIBLE_PERSON_NAME,
    "responsible_address": RESPONSIBLE_PERSON_ADDRESS,
    "dsa_email": DSA_CONTACT_EMAIL,
}
