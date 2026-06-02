"""No-op replacement for syndication/0005.

State drift (intentional, consequence-free): the real 0005 removes four
PlatformProjection fields (override_data, provenance, generated_by,
last_generated_at). This no-op leaves them in the historical migration state,
so the SQLite table (built by syncdb from the current model, which lacks them)
does not match project_state() here. The only consumer of historical state,
Migration0007BackfillTest, is @skipIf(sqlite)-skipped — so no test reads this
stale state under SQLite. A future test calling project_state() under SQLite
without a skip guard would hit the drift; mirror the real field-removals here
if that day comes.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("syndication", "0004_contentversion_platformprojection_content_version_and_more"),
    ]

    operations = []
