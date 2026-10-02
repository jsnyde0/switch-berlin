from django.contrib import admin, messages
from django.db import transaction
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect
from django.urls import path, reverse
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from a_core.models import ModerationAction
from events.models import Event
from organizers.models import Profile
from organizers.names import name_key

from .models import Flag, Review

# Per-target-type action allowlists (server-side enforcement)
ALLOWED_ACTIONS = {
    "event": {"no_action", "hide", "resolved"},
    "organizer": {"no_action", "hide", "suspend", "resolved"},
    "review": {"no_action", "delete", "resolved"},
}


def _derive_target(flag):
    """Return (target_type, target) from the flag's non-null FK."""
    if flag.event_id is not None:
        return "event", flag.event
    if flag.organizer_id is not None:
        return "organizer", flag.organizer
    if flag.review_id is not None:
        return "review", flag.review
    return None, None


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ["author", "target_display", "rating", "created_at"]

    def target_display(self, obj):
        if obj.organizer:
            return f"Organizer: {obj.organizer}"
        if obj.event:
            return f"Event: {obj.event}"
        return "(none)"

    target_display.short_description = _("Target")


@admin.register(Flag)
class FlagAdmin(admin.ModelAdmin):
    list_display = [
        "reporter",
        "organizer",
        "event",
        "reason",
        "law_reference",
        "resolved",
        "created_at",
    ]
    list_filter = ["resolved", "reason", "good_faith_confirmed"]
    readonly_fields = ["created_at", "good_faith_confirmed"]
    fields = [
        "reporter",
        "organizer",
        "event",
        "review",
        "reason",
        "body",
        "law_reference",
        "contact_email",
        "good_faith_confirmed",
        "resolved",
        "resolution_notes",
        "resolved_by",
        "created_at",
    ]
    change_form_template = "admin/reviews/flag/change_form.html"
    actions = ["resolve_approved", "resolve_rejected", "remove_credit_and_suppress"]

    class Media:
        js = ["admin/js/review_shortcuts.js"]

    def _bulk_resolve(self, request, queryset, *, resolution_notes):
        """Resolve each flag AND write a ModerationAction row per flag.

        Bulk shortcuts must not diverge from process_action's audit surface —
        ModerationAction is the DSA/GDPR audit trail.
        """
        with transaction.atomic():
            for flag in queryset.select_for_update():
                target_type, target = _derive_target(flag)
                if target is None:
                    continue
                ModerationAction.objects.create(
                    moderator=request.user,
                    flag=flag,
                    target_type=target_type,
                    target_id=target.pk,
                    target_repr=str(target),
                    action="resolved",
                )
                flag.resolved = True
                flag.resolved_by = request.user
                flag.resolution_notes = resolution_notes
                flag.save(update_fields=["resolved", "resolved_by", "resolution_notes"])

    @admin.action(description=_("Mark selected flags resolved — approved"))
    def resolve_approved(self, request, queryset):
        self._bulk_resolve(request, queryset, resolution_notes="Bulk approved via admin shortcut")

    @admin.action(description=_("Mark selected flags resolved — rejected"))
    def resolve_rejected(self, request, queryset):
        self._bulk_resolve(request, queryset, resolution_notes="Bulk rejected via admin shortcut")

    @admin.action(description=_("Remove the credited artist's credit and suppress the name for the event's sources"))
    def remove_credit_and_suppress(self, request, queryset):
        """Staff act on an artist-credit request: delete the matching EventArtist rows and suppress
        the name for every source of the event, in one transaction (sb-7wzb.23).

        The anonymous form only files the request; this is the one place a credit is removed.
        """
        from ingestion.models import ArtistCreditSuppression

        done = skipped = 0
        with transaction.atomic():
            for flag in queryset.select_for_update():
                if flag.reason != "artist_credit" or flag.event_id is None or not name_key(flag.credited_name):
                    skipped += 1
                    continue
                key = name_key(flag.credited_name)
                event = flag.event
                for credit in event.artist_credits.all():
                    if name_key(credit.name) == key:
                        credit.delete()
                channels = {a.raw_message.channel_id for a in event.extraction_attempts.select_related("raw_message")}
                if event.raw_message_id is not None:
                    channels.add(event.raw_message.channel_id)
                for channel_id in channels:
                    ArtistCreditSuppression.objects.get_or_create(name_key=key, channel_id=channel_id)
                ModerationAction.objects.create(
                    moderator=request.user,
                    flag=flag,
                    target_type="event",
                    target_id=event.pk,
                    target_repr=str(event),
                    action="resolved",
                    reason=f"credit {flag.credited_name!r} removed and suppressed for {len(channels)} source(s)",
                )
                flag.resolved = True
                flag.resolved_by = request.user
                flag.resolution_notes = "Credit removed and name suppressed via admin action"
                flag.save(update_fields=["resolved", "resolved_by", "resolution_notes"])
                done += 1
        self.message_user(
            request,
            _("%(done)d removed, %(skipped)d skipped (not a credit request).") % {"done": done, "skipped": skipped},
            messages.SUCCESS if done else messages.WARNING,
        )

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<int:flag_id>/action/",
                self.admin_site.admin_view(self.process_action),
                name="reviews_flag_action",
            ),
        ]
        return custom_urls + urls

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        flag = get_object_or_404(Flag, pk=object_id)
        target_type, _target = _derive_target(flag)
        if target_type:
            allowed = ALLOWED_ACTIONS[target_type]
        else:
            allowed = set()
        pre_selected = request.GET.get("action", "")
        flag_action_url = reverse("admin:reviews_flag_action", args=[object_id])
        extra_context["allowed_actions"] = allowed
        extra_context["pre_selected_action"] = pre_selected
        extra_context["flag_action_url"] = flag_action_url
        return super().change_view(request, object_id, form_url=form_url, extra_context=extra_context)

    @method_decorator(require_POST)
    def process_action(self, request, flag_id):
        flag = get_object_or_404(Flag, pk=flag_id)
        action = request.POST.get("action")
        target_type, target = _derive_target(flag)

        allowed = ALLOWED_ACTIONS.get(target_type, set())
        if action not in allowed:
            return HttpResponseBadRequest("Invalid action for target type")

        target_repr = str(target)

        with transaction.atomic():
            # Apply side effect
            if action == "hide" and target_type == "event":
                Event.objects.filter(pk=target.pk).update(hidden=True)
            elif action == "hide" and target_type == "organizer":
                Profile.objects.filter(pk=target.pk).update(hidden=True)
            elif action == "suspend":
                Profile.objects.filter(pk=target.pk).update(status="suspended")
            elif action == "delete":
                Review.objects.filter(pk=target.pk).update(hidden=True)

            ModerationAction.objects.create(
                moderator=request.user,
                flag=flag,
                target_type=target_type,
                target_id=target.pk,
                target_repr=target_repr,
                action=action,
            )

            flag.resolved = True
            flag.save(update_fields=["resolved"])

        return redirect(reverse("admin:reviews_flag_change", args=[flag.pk]))
