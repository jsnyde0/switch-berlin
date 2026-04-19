from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("ingestion", "0003_approvedsender_extractionattempt_and_more"),
    ]

    operations = [
        migrations.RunSQL(
            "CREATE EXTENSION IF NOT EXISTS pg_trgm;",
            reverse_sql="SELECT 1;",
        ),
    ]
