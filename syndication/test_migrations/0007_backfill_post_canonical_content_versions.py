# Hand-authored data migration for kb-q4u9.2.
# Depends on 0006_contentversion_publishable_scope (which added the post FK
# and mutually-exclusive check constraint on ContentVersion).
#
# Backfill: for every existing Post that has promotion projections whose
# content_version FKs to the event's canonical, mint a canonical ContentVersion
# for the POST and repoint those projections to the post's new canonical.
#
# Safe for ready/published projections: rendered content lives in immutable
# frozen_content (ADR-016 D2). on_delete=PROTECT on projections→ContentVersion
# means the orphaned event-canonical rows are retained, not cascaded — acceptable.
#
# Non-atomic: same reasoning as 0005 — RunPython writes content_version FK
# references which queue deferred FK trigger events; running non-atomically
# commits the backfill first, flushing triggers before any subsequent DDL.
# Harmless on a fresh DB (backfill is a no-op); required against any DB that
# already has Post rows with promotion projections.

from django.db import migrations


def backfill_post_canonical_content_versions(apps, schema_editor):
    """
    For every Post that has promotion projections, ensure the post has its own
    canonical ContentVersion (post FK set, event FK null), then repoint those
    promotion projections from the event's canonical to the post's canonical.

    F4: Use apps.get_model (historical registry) — never live-model imports.
    This keeps the migration correct if those models later change shapes.

    Pattern: mirror-and-invert of migration 0005's backfill helper, which
    routed promotion projections to source_post.event's canonical. This
    migration INVERTS the target: post's own canonical, not event's.
    """
    ContentVersion = apps.get_model("syndication", "ContentVersion")
    Post = apps.get_model("syndication", "Post")
    PlatformProjection = apps.get_model("syndication", "PlatformProjection")

    # Collect all Posts that have at least one promotion projection
    promotion_post_ids = (
        PlatformProjection.objects.filter(
            kind="promotion",
            source_post__isnull=False,
        ).values_list("source_post_id", flat=True).distinct()
    )

    for post_id in promotion_post_ids:
        try:
            post = Post.objects.get(pk=post_id)
        except Post.DoesNotExist:
            # Orphaned projection row — skip rather than block migration.
            continue

        # Get or create a canonical ContentVersion for this post.
        # post FK set, event FK null — exactly-one-publishable invariant.
        post_canonical, _ = ContentVersion.objects.get_or_create(
            post_id=post.pk,
            name="canonical",
            defaults={
                "provenance": "rule_template",
                # event is intentionally not set (null) — post-owned canonical.
            },
        )

        # Repoint all promotion projections for this post to the post's canonical.
        # Only repoint projections that are NOT already pointing at the post's canonical
        # (idempotency: running migration twice must not double-create or thrash).
        PlatformProjection.objects.filter(
            kind="promotion",
            source_post_id=post.pk,
        ).exclude(
            content_version_id=post_canonical.pk,
        ).update(content_version_id=post_canonical.pk)


def reverse_backfill(apps, schema_editor):
    """
    Reverse migration: no-op — we leave the minted post-canonical ContentVersions
    and the repointed FK values in place.

    Cannot undo cleanly without knowing the exact pre-migration state of each
    projection's content_version FK. Acceptable: the check constraint and
    the partial unique constraints added in 0006 mean the event-canonical rows
    are still present (on_delete=PROTECT retains them).
    """
    pass


class Migration(migrations.Migration):

    # Non-atomic: RunPython writes content_version FK references which queue
    # deferred FK trigger events; the subsequent implicit transaction commit
    # flush is required before any later DDL. Harmless on fresh DB.
    atomic = False

    dependencies = [
        ("syndication", "0006_contentversion_publishable_scope"),
    ]

    operations = [
        migrations.RunPython(
            backfill_post_canonical_content_versions,
            reverse_backfill,
        ),
    ]
