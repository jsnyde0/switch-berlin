"""
Seed dev data for the destination picker (kb-sbhs.2 browser verification).

Run via:
  docker compose exec app python manage.py shell < scripts/seed_picker_dev.py

Creates:
  - User: pickerdev / $SEED_PICKER_PASSWORD (default: dev-only-change-me, status=vouched)
  - Profile + ProfileClaim (mirrors connections_list ownership seam)
  - PlatformConnection rows:
    1. Telegram channel (bot-tier, theme_tags)
    2. Telegram group (plain, no forum topics)
    3. Forum group/supergroup cluster + 2 forum_topic leaves (same chat_id)
    4. One flagged_missing=True channel
    5. One agent-tier group (postability=agent, no AgentCredential for user)
  - NO AgentCredential (so agent-tier row renders LOCKED)

Safe to re-run: uses get_or_create on user/profile/connections.
"""
import django
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "a_core.settings")

from django.contrib.auth import get_user_model
from organizers.models import Profile, ProfileClaim
from syndication.models import PlatformConnection, TelegramDialogType, TelegramPostability, AgentCredential

User = get_user_model()

# --- User ---
user, created = User.objects.get_or_create(
    username="pickerdev",
    defaults={
        "email": "pickerdev@dev.local",
        "status": "vouched",
    }
)
if created:
    seed_password = os.environ.get("SEED_PICKER_PASSWORD", "dev-only-change-me")
    user.set_password(seed_password)
    user.save()
    print(f"Created user: pickerdev (pk={user.pk})")
else:
    print(f"User already exists: pickerdev (pk={user.pk})")

# --- Profile + ProfileClaim ---
profile, pcreated = Profile.objects.get_or_create(
    slug="pickerdev-profile",
    defaults={"name": "Picker Dev Profile"}
)
if pcreated:
    print(f"Created profile: {profile.slug} (pk={profile.pk})")
else:
    print(f"Profile already exists: {profile.slug} (pk={profile.pk})")

claim, claim_created = ProfileClaim.objects.get_or_create(
    profile=profile,
    user=user,
    defaults={"verified_method": "auto_self"}
)
if claim_created:
    print(f"Created ProfileClaim for user {user.username} -> profile {profile.slug}")
else:
    print(f"ProfileClaim already exists")

# --- Connections ---

# 1. Channel (bot-tier, with theme_tags)
ch, _ = PlatformConnection.objects.get_or_create(
    organizer=profile,
    platform="telegram",
    destination_id="-1009000001",
    topic_id=None,
    defaults={
        "type": TelegramDialogType.CHANNEL,
        "title": "Dev Channel Alpha",
        "postability": TelegramPostability.BOT,
        "flagged_missing": False,
        "kinds": ["promotion"],
        "theme_tags": ["kink", "berlin"],
        "friendly_name": None,
    }
)
print(f"Channel: pk={ch.pk} title={ch.title}")

# 2. Plain group (agent-tier, no forum topics, with theme_tags)
grp, _ = PlatformConnection.objects.get_or_create(
    organizer=profile,
    platform="telegram",
    destination_id="-1009000002",
    topic_id=None,
    defaults={
        "type": TelegramDialogType.GROUP,
        "title": "Dev Regulars Group",
        "postability": TelegramPostability.AGENT,
        "flagged_missing": False,
        "kinds": ["promotion"],
        "theme_tags": ["queer"],
        "friendly_name": None,
    }
)
print(f"Group: pk={grp.pk} title={grp.title}")

# 3. Forum cluster: one GROUP row as the cluster parent + 2 forum_topic leaves
FORUM_DEST_ID = "-1009000003"

forum_cluster, _ = PlatformConnection.objects.get_or_create(
    organizer=profile,
    platform="telegram",
    destination_id=FORUM_DEST_ID,
    topic_id=None,
    defaults={
        "type": TelegramDialogType.GROUP,
        "title": "Dev Forum Group",
        "postability": TelegramPostability.AGENT,
        "flagged_missing": False,
        "kinds": ["promotion"],
        "theme_tags": ["events", "berlin"],
        "friendly_name": "Dev Forum Hub",
    }
)
print(f"Forum cluster: pk={forum_cluster.pk} title={forum_cluster.title}")

topic1, _ = PlatformConnection.objects.get_or_create(
    organizer=profile,
    platform="telegram",
    destination_id=FORUM_DEST_ID,
    topic_id=101,
    defaults={
        "type": TelegramDialogType.FORUM_TOPIC,
        "title": "Dev Forum Group",
        "postability": TelegramPostability.AGENT,
        "flagged_missing": False,
        "kinds": ["promotion"],
        "theme_tags": ["events"],
        "friendly_name": "General Announcements",
    }
)
print(f"Forum topic 1: pk={topic1.pk} friendly_name={topic1.friendly_name}")

topic2, _ = PlatformConnection.objects.get_or_create(
    organizer=profile,
    platform="telegram",
    destination_id=FORUM_DEST_ID,
    topic_id=102,
    defaults={
        "type": TelegramDialogType.FORUM_TOPIC,
        "title": "Dev Forum Group",
        "postability": TelegramPostability.AGENT,
        "flagged_missing": False,
        "kinds": ["promotion"],
        "theme_tags": ["berlin"],
        "friendly_name": "Party Listings",
    }
)
print(f"Forum topic 2: pk={topic2.pk} friendly_name={topic2.friendly_name}")

# 4. Vanished channel (flagged_missing=True)
vanished, _ = PlatformConnection.objects.get_or_create(
    organizer=profile,
    platform="telegram",
    destination_id="-1009000099",
    topic_id=None,
    defaults={
        "type": TelegramDialogType.CHANNEL,
        "title": "Vanished Channel",
        "postability": TelegramPostability.BOT,
        "flagged_missing": True,
        "kinds": ["promotion"],
        "theme_tags": [],
        "friendly_name": None,
    }
)
print(f"Vanished channel: pk={vanished.pk} flagged_missing={vanished.flagged_missing}")

# 5. Agent-tier group (postability=agent, LOCKED because no AgentCredential)
agent_grp, _ = PlatformConnection.objects.get_or_create(
    organizer=profile,
    platform="telegram",
    destination_id="-1009000010",
    topic_id=None,
    defaults={
        "type": TelegramDialogType.GROUP,
        "title": "Agent-Only Private Group",
        "postability": TelegramPostability.AGENT,
        "flagged_missing": False,
        "kinds": ["promotion"],
        "theme_tags": ["kink"],
        "friendly_name": None,
    }
)
print(f"Agent-tier group: pk={agent_grp.pk} postability={agent_grp.postability}")

# Ensure NO AgentCredential for this user (delete if exists)
deleted_count, _ = AgentCredential.objects.filter(user=user).delete()
if deleted_count:
    print(f"Deleted {deleted_count} existing AgentCredential(s) for pickerdev")
else:
    print("No AgentCredential for pickerdev (correct — agent-tier rows will render LOCKED)")

print("\n=== Seed complete ===")
print(f"Login at: /accounts/login/ with username=pickerdev password=<SEED_PICKER_PASSWORD env var, default: dev-only-change-me>")
print(f"Picker URL: /syndication/destinations/")
print(f"PKs: channel={ch.pk} group={grp.pk} forum_cluster={forum_cluster.pk} topic1={topic1.pk} topic2={topic2.pk} vanished={vanished.pk} agent_grp={agent_grp.pk}")
