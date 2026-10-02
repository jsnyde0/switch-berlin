"""Staff merge of duplicate Profiles or Venues (sb-7wzb.22; sb-x5xh.2 ruling (d), rule 5).

The loser's relations move to the winner, the winner's empty fields are filled
from the loser, the loser is deleted and one MergeRecord is written. Relations
are read from Django's model metadata, so a relation added later is repointed
too; a repoint that would break a constraint and has no rule below refuses
the whole merge (ADR-008 D3), leaving the database untouched.
"""

from decimal import Decimal

from django.contrib import messages
from django.contrib.admin import helpers
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.template.response import TemplateResponse

from .duplicate_names import normalize
from .models import MergeRecord

# Never filled from the loser: slug is the winner's identity; the counters are
# recomputed by ingestion/tasks_flags.py; approval and consent are each one
# record, and filling them field by field would build a state neither side had
# (ADR-008 D3). Venue privacy is settled as a whole by _stricter_privacy.
_NOT_FILLED = {
    "slug",
    "follower_count",
    "avg_rating",
    "rating_count",
    "status",
    "approved_at",
    "approved_by",
    "consent_recorded_at",
    "consent_method",
    "consent_notes",
    "privacy_mode",
    "blur_radius_m",
}
_PRIVACY_ORDER = ["public", "neighborhood_blur", "private"]


class MergeRefused(Exception):
    pass


def _empty(value):
    if value is None:
        return True
    if isinstance(value, bool | int | float | Decimal):
        return False
    return not value


def _keep_one_organizer_row(row, winner):
    # Both profiles organize this event: keep the winner's row, primary if either was.
    twin = row.__class__.objects.filter(event_id=row.event_id, profile=winner).first()
    if twin is None:
        return False
    was_primary = row.is_primary
    row.delete()
    if was_primary and not twin.is_primary:
        twin.is_primary = True
        twin.save(update_fields=["is_primary"])
    return True


def _keep_one_artist_row(row, winner):
    twin = row.__class__.objects.filter(event_id=row.event_id, profile=winner).first()
    if twin is None:
        return False
    if not twin.role and row.role:
        twin.role = row.role
        twin.save(update_fields=["role"])
    row.delete()
    return True


def _keep_one_claim(row, winner):
    # The same account manages both: keep one claim, the active one if either is.
    twin = row.__class__.objects.filter(user_id=row.user_id, profile=winner).first()
    if twin is None:
        return False
    if twin.rejected_at is not None and row.rejected_at is None:
        twin.delete()
        return False  # the loser's active claim now repoints without conflict
    row.delete()
    return True


def _keep_one_follow(row, winner):
    if not row.__class__.objects.filter(user_id=row.user_id, profile=winner).exists():
        return False
    row.delete()
    return True


def _keep_one_connection(row, winner):
    # Postgres treats NULL topic_ids as distinct, so a shared channel would not raise.
    twin = row.__class__.objects.filter(
        organizer=winner, platform=row.platform, destination_id=row.destination_id, topic_id=row.topic_id
    )
    if not twin.exists():
        return False
    row.delete()
    return True


# (model label, field name) -> resolver(row, winner) returning True when it
# disposed of the row itself. Rows without a resolver are repointed as-is.
_RESOLVERS = {
    ("events.EventOrganizer", "profile"): _keep_one_organizer_row,
    ("events.EventArtist", "profile"): _keep_one_artist_row,
    ("organizers.ProfileClaim", "profile"): _keep_one_claim,
    ("organizers.Follow", "profile"): _keep_one_follow,
    ("syndication.PlatformConnection", "organizer"): _keep_one_connection,
}


def _repoint(winner, loser):
    for rel in loser._meta.related_objects:
        if rel.many_to_many:
            if rel.through._meta.auto_created:
                raise MergeRefused(f"no repoint rule for auto-created M2M {rel.related_model._meta.label}")
            continue  # explicit through models are repointed by their own FKs
        label = rel.related_model._meta.label
        resolve = _RESOLVERS.get((label, rel.field.name))
        for row in rel.related_model._base_manager.filter(**{rel.field.name: loser}):
            if resolve and resolve(row, winner):
                continue
            setattr(row, rel.field.name, winner)
            try:
                with transaction.atomic():
                    row.save(update_fields=[rel.field.name])
            except IntegrityError as exc:
                raise MergeRefused(
                    f"{label}.{rel.field.name} row {row.pk} would break a constraint on {winner}: {exc}"
                ) from exc


def _stricter_privacy(winner, loser):
    # The loser's address may fill the winner's, so the stricter privacy wins.
    if _PRIVACY_ORDER.index(loser.privacy_mode) > _PRIVACY_ORDER.index(winner.privacy_mode):
        winner.privacy_mode = loser.privacy_mode
        winner.blur_radius_m = loser.blur_radius_m


def _merge(winner, loser, actor, kind, settle=None):
    if type(winner) is not type(loser):
        raise MergeRefused("winner and loser are different kinds")
    if winner.pk == loser.pk:
        raise MergeRefused(f"cannot merge {winner} with itself")
    with transaction.atomic():
        fills = {
            f.attname: getattr(loser, f.attname)
            for f in winner._meta.concrete_fields
            if not (f.primary_key or f.name in _NOT_FILLED or getattr(f, "auto_now", False))
            and not getattr(f, "auto_now_add", False)
            and _empty(getattr(winner, f.attname))
            and not _empty(getattr(loser, f.attname))
        }
        record = MergeRecord(
            kind=kind,
            winner_id=winner.pk,
            winner_name=winner.name,
            loser_name=loser.name,
            winner_normalized=normalize(winner.name),
            loser_normalized=normalize(loser.name),
            merged_by=actor,
        )
        _repoint(winner, loser)
        for attname, value in fills.items():
            setattr(winner, attname, value)
        if settle:
            settle(winner, loser)
        try:
            with transaction.atomic():
                loser.delete()
                winner.save()
        except (IntegrityError, ProtectedError) as exc:
            raise MergeRefused(f"merging {loser} into {winner} would break a constraint: {exc}") from exc
        record.save()
    return record


def merge_profiles(winner, loser, actor):
    return _merge(winner, loser, actor, "profile")


def merge_venues(winner, loser, actor):
    return _merge(winner, loser, actor, "venue", settle=_stricter_privacy)


def merge_action(modeladmin, request, queryset, merge):
    """Admin action body shared by ProfileAdmin and VenueAdmin: confirm page, then merge."""
    objects = list(queryset)
    if len(objects) != 2:
        modeladmin.message_user(request, "Select exactly two rows to merge.", messages.ERROR)
        return None
    if "apply" not in request.POST:
        return TemplateResponse(
            request,
            "admin/organizers/merge_confirm.html",
            {
                **modeladmin.admin_site.each_context(request),
                "kind": modeladmin.model._meta.verbose_name_plural,
                "objects": objects,
                "action_checkbox_name": helpers.ACTION_CHECKBOX_NAME,
            },
        )
    by_pk = {str(o.pk): o for o in objects}
    winner = by_pk.get(request.POST.get("winner"))
    if winner is None:
        modeladmin.message_user(request, "Pick which of the two to keep.", messages.ERROR)
        return None
    loser = next(o for o in objects if o.pk != winner.pk)
    try:
        record = merge(winner, loser, request.user)
    except MergeRefused as exc:
        modeladmin.message_user(request, f"Merge refused: {exc}", messages.ERROR)
        return None
    modeladmin.message_user(request, f"Merged {record.loser_name!r} into {record.winner_name!r}.", messages.SUCCESS)
    return None
