"""Tests for a_core.validators — image upload validators.

Uses SimpleTestCase (no DB required).
"""

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.validators import FileExtensionValidator
from django.test import SimpleTestCase

from a_core.validators import MAX_IMAGE_SIZE, validate_image_size


class ValidateImageSizeTest(SimpleTestCase):
    def test_validate_image_size_rejects_oversized(self):
        """File exactly 1 byte over limit raises ValidationError."""
        oversized = SimpleUploadedFile(
            "big.jpg",
            b"x" * (MAX_IMAGE_SIZE + 1),
            content_type="image/jpeg",
        )
        with self.assertRaises(ValidationError):
            validate_image_size(oversized)

    def test_validate_image_size_accepts_under_limit(self):
        """File exactly 1 byte under limit passes without error."""
        ok_file = SimpleUploadedFile(
            "small.jpg",
            b"x" * (MAX_IMAGE_SIZE - 1),
            content_type="image/jpeg",
        )
        # Should not raise
        validate_image_size(ok_file)

    def test_file_extension_validator_rejects_disallowed(self):
        """FileExtensionValidator with jpg/jpeg/png/webp rejects .gif."""
        validator = FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png", "webp"])
        gif_file = SimpleUploadedFile(
            "anim.gif",
            b"GIF89a",
            content_type="image/gif",
        )
        with self.assertRaises(ValidationError):
            validator(gif_file)
