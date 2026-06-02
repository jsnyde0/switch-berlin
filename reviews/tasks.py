"""Async tasks for the reviews app (django-q2)."""

from django.conf import settings
from django.core.mail import send_mail

from a_core.models import EmailFailure


def send_takedown_notification(event_url, reason, body, contact_email):
    """Async task: send email notification for takedown submission."""
    subject = f"[Takedown] {reason}: {event_url[:100]}"
    message = f"URL: {event_url}\nReason: {reason}\nBody: {body}\nContact: {contact_email}"
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[settings.DEFAULT_FROM_EMAIL],
            fail_silently=False,
        )
    except Exception as exc:
        EmailFailure.objects.create(
            recipient=settings.DEFAULT_FROM_EMAIL,
            subject=subject,
            body_preview=message[:500],
            error_message=str(exc),
        )
