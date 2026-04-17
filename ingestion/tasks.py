import logfire

from .models import HeartbeatLog


def heartbeat(note="scheduled heartbeat"):
    """Inserted every 5 minutes by django-q2 scheduler. Proves worker loop is alive."""
    log = HeartbeatLog.objects.create(note=note)
    logfire.info("heartbeat ok", heartbeat_log_id=log.pk, ran_at=log.ran_at.isoformat())
