"""Custom template tags and filters for the events app."""
import hashlib

from django import template

register = template.Library()


@register.filter
def slug_hue(value):
    """Map a string deterministically to a 0–360 hue.

    Used to give each event a stable accent color without storing one.
    Returns 0 if input is empty.
    """
    if not value:
        return 0
    digest = hashlib.md5(
        str(value).encode("utf-8"), usedforsecurity=False
    ).hexdigest()
    return int(digest[:6], 16) % 360


@register.filter
def slug_hue_b(value):
    """Companion hue offset by ~50° so we can build a 2-stop gradient."""
    return (slug_hue(value) + 55) % 360


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


@register.filter
def in_set(value, the_set):
    """Return True if value is in the_set.

    Safe when the_set is None, empty string, or empty container.
    Cotton passes unset props as empty string (""), so this guard
    prevents a TypeError when the component is rendered without the prop.

    Usage: {{ event.venue.pk|in_set:going_venue_id_list }}
    """
    if not the_set:
        return False
    return value in the_set
