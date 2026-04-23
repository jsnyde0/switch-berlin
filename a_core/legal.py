"""Legal contact settings module.

Exposes ``get_legal_contact()`` which returns the ``settings.LEGAL_CONTACT``
dict assembled from IMPRESSUM_* and related env vars.
"""

from django.conf import settings


def get_legal_contact() -> dict:
    """Return the LEGAL_CONTACT dict from Django settings."""
    return settings.LEGAL_CONTACT
