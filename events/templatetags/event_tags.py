"""Custom template tags and filters for the events app."""
from django import template

register = template.Library()


@register.filter
def cents_to_display(value):
    """Convert integer cents to a display string with 2 decimal places.

    Usage: {{ event.price_min_cents|cents_to_display }}
    Returns e.g. "15.00" for 1500 cents.
    """
    if value is None:
        return ""
    try:
        return f"{int(value) / 100:.2f}"
    except (TypeError, ValueError):
        return ""
