"""a_core views — system-level endpoints (e.g. healthz)."""

from django.http import JsonResponse

from events.models import Event


def healthz(request):
    # 200 when events exist, 503 when empty — wipes page (kb-l94).
    has_events = Event.objects.exists()
    payload = {"status": "ok" if has_events else "empty", "has_events": has_events}
    return JsonResponse(payload, status=200 if has_events else 503)
