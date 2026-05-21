# Migration for kb-m69.3: ProfileClaim through-model + data migration from Profile.claimed_by FK
#
# Per ADR-014 D1 + ADR-007 D5 (revised 2026-05-21) + ADR-008 D1 (no compat shim).
#
# Operations (in order):
# 1. CreateModel: ProfileClaim through-model
# 2. AddField: Profile.claimants (M2M via ProfileClaim)
# 3. RunPython: backfill — for each Profile with claimed_by IS NOT NULL,
#    create a ProfileClaim(profile, user, verified_method='admin_legacy',
#    verified_at=claimed_at or now(), role='admin', verified_by_admin='migration_admin')
# 4. RemoveField: Profile.claimed_by (ADR-008 D1 no compat shim — drop outright)
# 5. RemoveField: Profile.claimed_at

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone


def backfill_profile_claims(apps, schema_editor):
    """
    For each Profile with claimed_by IS NOT NULL, create a ProfileClaim row
    with verified_method='admin_legacy', verified_at=claimed_at or now(),
    role='admin', verified_by_admin='migration_admin'.

    Per ADR-014 D1 line 137: existing FK rows → ProfileClaim with admin_legacy.
    Per ADR-008 D1: no compat shim; this is the one-way backfill before FK drop.
    """
    Profile = apps.get_model("organizers", "Profile")
    ProfileClaim = apps.get_model("organizers", "ProfileClaim")
    now = timezone.now()

    for profile in Profile.objects.filter(claimed_by__isnull=False).select_related("claimed_by"):
        ProfileClaim.objects.get_or_create(
            profile=profile,
            user=profile.claimed_by,
            defaults={
                "verified_method": "admin_legacy",
                "verified_at": profile.claimed_at or now,
                "role": "admin",
                "verified_by_admin": "migration_admin",
            },
        )


def reverse_backfill(apps, schema_editor):
    """
    Reverse migration: for each ProfileClaim with verified_method='admin_legacy',
    restore claimed_by + claimed_at on the Profile.
    """
    ProfileClaim = apps.get_model("organizers", "ProfileClaim")
    Profile = apps.get_model("organizers", "Profile")

    for claim in ProfileClaim.objects.filter(verified_method="admin_legacy").select_related("profile", "user"):
        Profile.objects.filter(pk=claim.profile_id).update(
            claimed_by=claim.user,
            claimed_at=claim.verified_at,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("organizers", "0009_alter_profile_avatar"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Step 1: Create ProfileClaim through-model
        migrations.CreateModel(
            name="ProfileClaim",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "verified_at",
                    models.DateTimeField(default=timezone.now),
                ),
                (
                    "verified_method",
                    models.CharField(
                        choices=[
                            ("email_domain", "Email domain fast-path"),
                            ("admin_review", "Admin review"),
                            ("admin_legacy", "Admin legacy (migration backfill)"),
                            ("auto_self", "Auto self-claim on signup"),
                        ],
                        max_length=30,
                    ),
                ),
                (
                    "verified_by_admin",
                    models.CharField(blank=True, max_length=150, null=True),
                ),
                (
                    "role",
                    models.CharField(
                        choices=[("admin", "Admin")],
                        default="admin",
                        max_length=30,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("rejected_at", models.DateTimeField(blank=True, null=True)),
                (
                    "rejected_by_admin",
                    models.CharField(blank=True, max_length=150, null=True),
                ),
                (
                    "profile",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="organizers.profile",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "unique_together": {("profile", "user")},
            },
        ),
        # Step 2: Add Profile.claimants M2M via ProfileClaim
        migrations.AddField(
            model_name="profile",
            name="claimants",
            field=models.ManyToManyField(
                blank=True,
                related_name="claimed_profiles",
                through="organizers.ProfileClaim",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        # Step 3: Backfill — convert existing claimed_by FK rows → ProfileClaim rows
        migrations.RunPython(backfill_profile_claims, reverse_backfill),
        # Step 4: Drop Profile.claimed_by FK (ADR-008 D1 no compat shim)
        migrations.RemoveField(
            model_name="profile",
            name="claimed_by",
        ),
        # Step 5: Drop Profile.claimed_at (no longer needed after FK drop)
        migrations.RemoveField(
            model_name="profile",
            name="claimed_at",
        ),
    ]
