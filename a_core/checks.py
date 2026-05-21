"""Django system checks for legal-contact env vars and Turnstile keys.

W006 — WARNING: required legal vars are empty when DEBUG=True (internal only).
E006 — ERROR: required legal vars are empty when PUBLIC_READ_ENABLED=True.
E007 — ERROR: Turnstile keys missing when PUBLIC_READ_ENABLED=True (ADR-014 D4).

Registered via ACoreConfig.ready() in a_core/apps.py.
"""

from django.conf import settings
from django.core.checks import Error, Warning, register
from django.db.utils import OperationalError, ProgrammingError

REQUIRED_LEGAL_VARS = ["IMPRESSUM_NAME", "IMPRESSUM_ADDRESS", "IMPRESSUM_EMAIL"]


@register()
def check_legal_contact(app_configs, **kwargs):
    """Check that required legal env vars are populated.

    - E006 if PUBLIC_READ_ENABLED=True and any required var is missing.
    - W006 if DEBUG=True (and PUBLIC_READ_ENABLED=False) and any required var missing.
    - Silent if neither condition applies (internal cohort, neither flag set).

    On a fresh DB (pre-migrate), FeatureFlag table does not exist yet.
    In that case we return no errors — the check will re-run after migrations.
    """
    from a_core.models import get_flag

    errors = []
    try:
        public_read = get_flag("PUBLIC_READ_ENABLED", default=False)
    except (ProgrammingError, OperationalError):
        # Pre-migrate state: DB table doesn't exist yet. Not a deploy violation.
        return []
    missing = [v for v in REQUIRED_LEGAL_VARS if not getattr(settings, v, "")]

    if not missing:
        return errors

    if public_read:
        errors.append(
            Error(
                "PUBLIC_READ_ENABLED=True but required legal env vars are empty: "
                + ", ".join(missing),
                hint=(
                    "Set IMPRESSUM_NAME, IMPRESSUM_ADDRESS, IMPRESSUM_EMAIL "
                    "in your environment before enabling public read access."
                ),
                obj=settings,
                id="a_core.E006",
            )
        )
    elif settings.DEBUG:
        errors.append(
            Warning(
                "Legal env vars are empty (OK for DEBUG=True internal use): "
                + ", ".join(missing),
                hint=(
                    "Fill IMPRESSUM_NAME, IMPRESSUM_ADDRESS, IMPRESSUM_EMAIL "
                    "before setting PUBLIC_READ_ENABLED=True."
                ),
                obj=settings,
                id="a_core.W006",
            )
        )

    return errors


@register()
def check_turnstile_keys(app_configs, **kwargs):
    """E007: Turnstile site/secret keys must be set when PUBLIC_READ_ENABLED=True.

    Per ADR-014 D4 (Turnstile on public-facing forms) + ADR-008 D3 (fail loud).
    On a fresh DB (pre-migrate), returns [] — check re-runs after migrations.
    """
    from a_core.models import get_flag

    errors = []
    try:
        public_read = get_flag("PUBLIC_READ_ENABLED", default=False)
    except (ProgrammingError, OperationalError):
        return []

    if not public_read:
        return []

    site_key = getattr(settings, "TURNSTILE_SITE_KEY", "")
    secret_key = getattr(settings, "TURNSTILE_SECRET_KEY", "")
    missing = []
    if not site_key:
        missing.append("TURNSTILE_SITE_KEY")
    if not secret_key:
        missing.append("TURNSTILE_SECRET_KEY")

    if missing:
        errors.append(
            Error(
                "PUBLIC_READ_ENABLED=True but Turnstile env vars are missing: "
                + ", ".join(missing),
                hint=(
                    "Set TURNSTILE_SITE_KEY and TURNSTILE_SECRET_KEY "
                    "before enabling public read access. "
                    "Use Cloudflare test keys for non-production environments."
                ),
                obj=settings,
                id="a_core.E007",
            )
        )

    return errors
