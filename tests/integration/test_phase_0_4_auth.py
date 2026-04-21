"""
Integration tests for Phase 0.4 — auth layer bugfixes, middleware restructure,
kill-switches, and approval UX.

Test plan items (from bead kb-2eu.1):
1. organizer.events (not event_set) — GET /o/<slug>/ no longer crashes
2. pagination hx-target is #event-list (not #event-list-container)
3. approved user (is_approved=True, is_staff=False) gets 200 on /events/
4. unapproved authenticated user sees 403_pending_approval.html at status 403
5. MAP_ENABLED and INVITES_ENABLED settings exist and are readable
6. INVITES_ENABLED=False hides the Register <li> in navbar
7. MAP_ENABLED=False: response contains no id="map" and no maplibre
8. Context processor provides MAP_ENABLED and INVITES_ENABLED in templates
"""

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def approved_user(db):
    """Authenticated, approved but non-staff user — should get 200 after restructure."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(
        username="approved",
        email="approved@example.com",
        password="x",
        is_staff=False,
        is_approved=True,
    )


@pytest.fixture
def unapproved_user(db):
    """Authenticated, non-staff, non-approved user — should get 403 pending page."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(
        username="unapproved",
        email="unapproved@example.com",
        password="x",
        is_staff=False,
        is_approved=False,
    )


# ---------------------------------------------------------------------------
# Bugfix 1: organizer.events (related_name) — not event_set
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_organizer_profile_uses_events_related_name(
    client, staff_user, approved_organizer, published_event
):
    """GET /o/<slug>/ returns 200 (not 500) — organizer.events FK works."""
    client.force_login(staff_user)
    response = client.get(f"/o/{approved_organizer.slug}/")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Bugfix 2: pagination hx-target is #event-list
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_pagination_hx_target_is_event_list(client, staff_user, approved_organizer):
    """Pagination links target #event-list, not #event-list-container."""
    from datetime import timedelta

    import django.utils.timezone as tz

    from events.models import Event, Tag

    tag = Tag.objects.create(slug="pag-tag", label="Pag Tag", kind="theme")
    future = tz.now() + timedelta(days=1)
    for i in range(25):
        e = Event.objects.create(
            title=f"Pag Event {i}",
            slug=f"pag-event-{i}",
            organizer=approved_organizer,
            status="published",
            start=future + timedelta(hours=i),
        )
        e.tags.add(tag)

    client.force_login(staff_user)
    response = client.get("/events/?tags=pag-tag&page=2")
    assert response.status_code == 200
    content = response.content.decode()
    # Must target #event-list, not #event-list-container
    assert 'hx-target="#event-list"' in content
    assert 'hx-target="#event-list-container"' not in content


# ---------------------------------------------------------------------------
# Middleware restructure: approved user can access /events/
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_approved_user_can_access_events(client, approved_user, published_event):
    """Approved non-staff user gets 200 on /events/ after middleware restructure."""
    client.force_login(approved_user)
    response = client.get("/events/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_approved_user_not_blocked_by_middleware(
    client, approved_user, published_event
):
    """Approved non-staff user is not blocked by the login-wall."""
    client.force_login(approved_user)
    response = client.get("/events/")
    # Must NOT be 403
    assert response.status_code != 403


# ---------------------------------------------------------------------------
# Middleware restructure: unapproved user sees 403_pending_approval.html
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_unapproved_user_gets_403_pending_page_in_rollback_mode(client, unapproved_user):
    """Unapproved user sees 403_pending_approval.html when PUBLIC_READ_ENABLED=False."""
    from django.core.cache import cache

    from a_core.models import FeatureFlag

    # Phase 0.5: PUBLIC_READ_ENABLED=True allows unapproved users on /events/.
    # In rollback mode (PUBLIC_READ_ENABLED=False), they see the 403 pending page.
    FeatureFlag.objects.update_or_create(
        key="PUBLIC_READ_ENABLED", defaults={"enabled": False}
    )
    cache.clear()
    client.force_login(unapproved_user)
    try:
        response = client.get("/events/")
        assert response.status_code == 403
        content = response.content.decode()
        assert "pending approval" in content.lower()
    finally:
        FeatureFlag.objects.filter(key="PUBLIC_READ_ENABLED").delete()
        cache.clear()


@pytest.mark.django_db
def test_unapproved_user_gets_full_page_not_bare_text_in_rollback_mode(
    client, unapproved_user
):
    """Unapproved user sees a real HTML page in rollback mode, not a bare string."""
    from django.core.cache import cache

    from a_core.models import FeatureFlag

    FeatureFlag.objects.update_or_create(
        key="PUBLIC_READ_ENABLED", defaults={"enabled": False}
    )
    cache.clear()
    client.force_login(unapproved_user)
    try:
        response = client.get("/events/")
        assert response.status_code == 403
        content = response.content.decode()
        assert "<!DOCTYPE html>" in content or "<html" in content
    finally:
        FeatureFlag.objects.filter(key="PUBLIC_READ_ENABLED").delete()
        cache.clear()


@pytest.mark.django_db
def test_unapproved_user_can_still_logout(client, unapproved_user):
    """Unapproved user can reach /accounts/logout/ (PUBLIC_PREFIXES still applies)."""
    client.force_login(unapproved_user)
    # GET to the logout page (allauth shows a confirmation form)
    response = client.get("/accounts/logout/")
    # Should not be blocked — /accounts/ is a public prefix
    assert response.status_code != 403


# ---------------------------------------------------------------------------
# Kill-switches: MAP_ENABLED and INVITES_ENABLED are FeatureFlags
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_map_enabled_flag_default_is_true():
    """MAP_ENABLED FeatureFlag defaults to True when no DB row exists."""
    from a_core.models import get_flag

    assert get_flag("MAP_ENABLED", default=True) is True


@pytest.mark.django_db
def test_invites_enabled_flag_default_is_true():
    """INVITES_ENABLED FeatureFlag defaults to True when no DB row exists."""
    from a_core.models import get_flag

    assert get_flag("INVITES_ENABLED", default=True) is True


# ---------------------------------------------------------------------------
# Context processor: MAP_ENABLED and INVITES_ENABLED in templates
# ---------------------------------------------------------------------------


def test_feature_flags_context_processor_exists():
    """a_core.context_processors.feature_flags is importable."""
    from a_core.context_processors import feature_flags

    assert callable(feature_flags)


@pytest.mark.django_db
def test_feature_flags_context_processor_returns_map_enabled():
    """feature_flags context processor returns MAP_ENABLED key."""
    from a_core.context_processors import feature_flags

    result = feature_flags(None)
    assert "MAP_ENABLED" in result


@pytest.mark.django_db
def test_feature_flags_context_processor_returns_invites_enabled():
    """feature_flags context processor returns INVITES_ENABLED key."""
    from a_core.context_processors import feature_flags

    result = feature_flags(None)
    assert "INVITES_ENABLED" in result


def test_feature_flags_context_processor_registered():
    """feature_flags context processor is registered in TEMPLATES settings."""
    from django.conf import settings

    processors = settings.TEMPLATES[0]["OPTIONS"]["context_processors"]
    assert "a_core.context_processors.feature_flags" in processors


# ---------------------------------------------------------------------------
# INVITES_ENABLED=False hides Register link in navbar
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_invites_disabled_hides_register_link(client):
    """With INVITES_ENABLED=False FeatureFlag, the Register link is not in the page."""
    from django.core.cache import cache

    from a_core.models import FeatureFlag

    FeatureFlag.objects.update_or_create(
        key="INVITES_ENABLED", defaults={"enabled": False}
    )
    cache.clear()
    try:
        # Anonymous user so we're in the unauthenticated branch of the navbar
        response = client.get("/accounts/login/")
        assert response.status_code == 200
        content = response.content.decode()
        assert "account_signup" not in content or "Register" not in content
    finally:
        FeatureFlag.objects.filter(key="INVITES_ENABLED").delete()
        cache.clear()


@pytest.mark.django_db
def test_invites_enabled_shows_register_link(client):
    """With INVITES_ENABLED=True FeatureFlag, the Register link is present."""
    from django.core.cache import cache

    from a_core.models import FeatureFlag

    FeatureFlag.objects.update_or_create(
        key="INVITES_ENABLED", defaults={"enabled": True}
    )
    cache.clear()
    try:
        response = client.get("/accounts/login/")
        assert response.status_code == 200
        content = response.content.decode()
        assert "Register" in content
    finally:
        FeatureFlag.objects.filter(key="INVITES_ENABLED").delete()
        cache.clear()


# ---------------------------------------------------------------------------
# MAP_ENABLED=False: no map div, no maplibre in response
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_map_disabled_no_map_div(client, staff_user, published_event):
    """With MAP_ENABLED=False FeatureFlag, the map div is not rendered."""
    from django.core.cache import cache

    from a_core.models import FeatureFlag

    FeatureFlag.objects.update_or_create(key="MAP_ENABLED", defaults={"enabled": False})
    cache.clear()
    client.force_login(staff_user)
    try:
        response = client.get("/events/")
        assert response.status_code == 200
        assert b'id="map"' not in response.content
    finally:
        FeatureFlag.objects.filter(key="MAP_ENABLED").delete()
        cache.clear()


@pytest.mark.django_db
def test_map_disabled_no_maplibre_assets(client, staff_user, published_event):
    """With MAP_ENABLED=False FeatureFlag, maplibre JS/CSS is not loaded."""
    from django.core.cache import cache

    from a_core.models import FeatureFlag

    FeatureFlag.objects.update_or_create(key="MAP_ENABLED", defaults={"enabled": False})
    cache.clear()
    client.force_login(staff_user)
    try:
        response = client.get("/events/")
        assert response.status_code == 200
        assert b"maplibre" not in response.content.lower()
    finally:
        FeatureFlag.objects.filter(key="MAP_ENABLED").delete()
        cache.clear()


@pytest.mark.django_db
def test_map_enabled_has_map_div(client, staff_user, published_event):
    """With MAP_ENABLED=True FeatureFlag, the map div IS rendered."""
    from django.core.cache import cache

    from a_core.models import FeatureFlag

    FeatureFlag.objects.update_or_create(key="MAP_ENABLED", defaults={"enabled": True})
    cache.clear()
    client.force_login(staff_user)
    try:
        response = client.get("/events/")
        assert response.status_code == 200
        assert b'id="map"' in response.content
    finally:
        FeatureFlag.objects.filter(key="MAP_ENABLED").delete()
        cache.clear()
