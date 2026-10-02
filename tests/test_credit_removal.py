"""sb-7wzb.23: a credited artist asks, without logging in, for their credit to be removed;
staff act on the request; the removed name is suppressed for the sources of that event."""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from events.models import EventArtist
from ingestion.models import ArtistCreditSuppression, ExtractionAttempt, RawMessage
from organizers.names import name_key
from reviews.models import Flag


@pytest.fixture
def credited_event(published_event):
    raw = RawMessage.objects.create(source_type="website", channel_id="iksk-berlin.de", message_id="m", raw_payload={})
    published_event.raw_message = raw
    published_event.save(update_fields=["raw_message"])
    other = RawMessage.objects.create(
        source_type="telegram_telethon", channel_id="-100", message_id="1", raw_payload={}
    )
    ExtractionAttempt.objects.create(
        raw_message=other, event=published_event, model_name="m", prompt_version="v1", raw_response={}
    )
    EventArtist.objects.create(event=published_event, name="Mareen Scholl", order=0)
    EventArtist.objects.create(event=published_event, name="Lukas Forstmeyer", order=1)
    return published_event


def _event_url(event):
    return "http://testserver" + reverse(
        "event-detail", kwargs={"org_slug": event.organizer.slug, "event_slug": event.slug}
    )


def _post(event, **overrides):
    data = {
        "event_url": _event_url(event),
        "credited": "on",
        "credited_name": "mareen scholl",
        "reason": "other",
        "contact_email": "mareen@example.org",
        "good_faith_confirmed": "on",
    }
    data.update(overrides)
    return Client().post(reverse("takedown"), data)


@pytest.mark.django_db
def test_the_form_files_a_request_and_removes_nothing(credited_event):
    resp = _post(credited_event)
    assert resp.status_code == 200
    flag = Flag.objects.get()
    assert (flag.reason, flag.credited_name, flag.event_id) == ("artist_credit", "mareen scholl", credited_event.id)
    assert credited_event.artist_credits.count() == 2
    assert ArtistCreditSuppression.objects.count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize("missing", ["credited_name", "contact_email"])
def test_credit_mode_needs_the_name_and_a_contact(credited_event, missing):
    _post(credited_event, **{missing: ""})
    assert Flag.objects.count() == 0


@pytest.mark.django_db
def test_credit_mode_needs_an_event_url(credited_event):
    _post(credited_event, event_url="")
    assert Flag.objects.count() == 0


@pytest.fixture
def staff_client(db):
    user = get_user_model().objects.create_superuser(username="staff", password="pw", email="s@example.org")
    client = Client()
    client.force_login(user)
    return client


def _run_action(client, flag):
    return client.post(
        reverse("admin:reviews_flag_changelist"),
        {"action": "remove_credit_and_suppress", "_selected_action": [flag.pk]},
        follow=True,
    )


@pytest.mark.django_db
def test_the_staff_action_removes_the_credit_and_suppresses_it_for_every_source_of_the_event(
    credited_event, staff_client
):
    _post(credited_event)
    flag = Flag.objects.get()
    _run_action(staff_client, flag)
    assert list(credited_event.artist_credits.values_list("name", flat=True)) == ["Lukas Forstmeyer"]
    assert set(ArtistCreditSuppression.objects.values_list("name_key", "channel_id")) == {
        (name_key("Mareen Scholl"), "iksk-berlin.de"),
        (name_key("Mareen Scholl"), "-100"),
    }
    flag.refresh_from_db()
    assert flag.resolved


@pytest.mark.django_db
def test_the_staff_action_ignores_a_flag_that_is_not_a_credit_request(credited_event, staff_client):
    flag = Flag.objects.create(event=credited_event, reason="spam", good_faith_confirmed=True)
    _run_action(staff_client, flag)
    assert credited_event.artist_credits.count() == 2
    assert ArtistCreditSuppression.objects.count() == 0
    flag.refresh_from_db()
    assert not flag.resolved


@pytest.mark.django_db
def test_a_name_that_credits_nobody_is_still_suppressed(credited_event, staff_client):
    _post(credited_event, credited_name="Nobody Here")
    _run_action(staff_client, Flag.objects.get())
    assert credited_event.artist_credits.count() == 2
    assert ArtistCreditSuppression.objects.filter(name_key="nobody here").exists()
