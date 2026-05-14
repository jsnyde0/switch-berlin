"""Cross-cutting validators for file uploads.

Place shared Django field validators here — a_core is the natural home for
cross-cutting Django wiring (settings, middleware, etc.).
"""

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

# Maximum allowed image upload size: 5 MiB.
# Increase here if product requirements change.
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5 MiB in bytes


def validate_image_size(image_file):
    """Raise ValidationError if image_file exceeds MAX_IMAGE_SIZE bytes."""
    if image_file.size > MAX_IMAGE_SIZE:
        limit_mb = MAX_IMAGE_SIZE / (1024 * 1024)
        raise ValidationError(
            _("Image file too large. Maximum allowed size is %(limit)s MiB."),
            params={"limit": limit_mb},
        )
