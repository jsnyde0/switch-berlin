from django.contrib import admin
from django.db import transaction
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect
from django.urls import path, reverse
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from a_core.models import ModerationAction
from events.models import Event
from organizers.models import Organizer

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
        "reporter", "organizer", "event", "reason",
        "law_reference", "resolved", "created_at",
    ]
    list_filter = ["resolved", "reason", "good_faith_confirmed"]
    readonly_fields = ["created_at", "good_faith_confirmed"]
    fields = [
        "reporter", "organizer", "event", "review",
        "reason", "body", "law_reference", "contact_email",
        "good_faith_confirmed",
        "resolved", "resolution_notes", "resolved_by",
        "created_at",
    ]
    change_form_template = "admin/reviews/flag/change_form.html"
    actions = ["resolve_approved", "resolve_rejected"]

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
                flag.save(
                    update_fields=["resolved", "resolved_by", "resolution_notes"]
                )

    @admin.action(description=_("Mark selected flags resolved — approved"))
    def resolve_approved(self, request, queryset):
        self._bulk_resolve(
            request, queryset, resolution_notes="Bulk approved via admin shortcut"
        )

    @admin.action(description=_("Mark selected flags resolved — rejected"))
    def resolve_rejected(self, request, queryset):
        self._bulk_resolve(
            request, queryset, resolution_notes="Bulk rejected via admin shortcut"
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
        return super().change_view(
            request, object_id, form_url=form_url, extra_context=extra_context
        )

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
                Organizer.objects.filter(pk=target.pk).update(hidden=True)
            elif action == "suspend":
                Organizer.objects.filter(pk=target.pk).update(status="suspended")
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
