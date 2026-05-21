# kb-m69.12 — ADR-008 D1: delete NoSignupAdapter compat shim.
# Drops InviteCode.redeemed_by and InviteCode.redeemed_at — legacy fields
# that existed only to support the dead NoSignupAdapter (phase 0.4).
# The canonical V0 fields are used_by / used_at (added in 0007).

import django.db.models.deletion
from django.conf import settings
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0007_vouch_invitecode_invitegrant"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveField(
            model_name="invitecode",
            name="redeemed_by",
        ),
        migrations.RemoveField(
            model_name="invitecode",
            name="redeemed_at",
        ),
    ]
