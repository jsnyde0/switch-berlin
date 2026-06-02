"""No-op replacement for syndication/0003."""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("syndication", "0002_agent_credential_identity_token"),
    ]

    operations = []
