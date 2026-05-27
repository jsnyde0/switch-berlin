from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.db.models import F
from django.http import (
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponsePermanentRedirect,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from a_core.models import get_flag, get_numeric
from events.models import Attendance, Event
from reviews.models import Review

from .forms import ClaimForm
from .models import ClaimIntent, Follow, MagicLinkToken, Profile, ProfileClaim

# Valid sort options and their corresponding ORM orderings.
_SORT_ORDERINGS = {
    "recent": ("-created_at",),
    "highest": ("-rating", "-created_at"),
    "lowest": ("rating", "-created_at"),
}

# Valid event sort options for the organizer profile event lists.
_EVENT_SORT_OPTIONS = {"date", "lowest_rated", "most_reviewed"}
_EVENT_RATING_SORT_OPTIONS = {"lowest_rated", "most_reviewed"}


def organizer_profile(request, slug):
    organizer = get_object_or_404(
        Profile.objects.visible(), slug=slug, status="approved"
    )
    now = timezone.now()

    # Parse ?event_sort query param; fall back to 'date' for unknown values.
    # Rating-based sorts gated by EVENT_REVIEWS_DISPLAYED (ADR-002/005).
    event_sort = request.GET.get("event_sort", "date")
    if event_sort not in _EVENT_SORT_OPTIONS:
        event_sort = "date"
    event_reviews_displayed = get_flag("EVENT_REVIEWS_DISPLAYED", default=False)
    if event_sort in _EVENT_RATING_SORT_OPTIONS and not event_reviews_displayed:
        event_sort = "date"

    upcoming_events_qs = (
        Event.objects.visible_to(request.user)
        .filter(
            hidden=False,
            event_organizer_set__profile=organizer,
            event_organizer_set__is_primary=True,
            status="published",
            start__gte=now,
        )
        .select_related("venue")
        .prefetch_related("tags", "event_organizer_set__profile")
        .distinct()
    )
    if event_sort == "lowest_rated":
        upcoming_events_qs = upcoming_events_qs.order_by(
            F("avg_rating").asc(nulls_last=True), "start"
        )
    elif event_sort == "most_reviewed":
        upcoming_events_qs = upcoming_events_qs.order_by(
            F("rating_count").desc(), "start"
        )
    else:
        upcoming_events_qs = upcoming_events_qs.order_by("start")
    upcoming_events = upcoming_events_qs[:50]

    past_events = (
        Event.objects.visible_to(request.user)
        .filter(
            hidden=False,
            event_organizer_set__profile=organizer,
            event_organizer_set__is_primary=True,
            status="published",
            start__lt=now,
        )
        .select_related("venue")
        .prefetch_related("tags", "event_organizer_set__profile")
        .distinct()
        .order_by("-start")[:20]
    )

    if request.user.is_authenticated:
        following = Follow.objects.filter(user=request.user, profile=organizer).exists()
        going_venue_ids = list(
            Attendance.objects.filter(
                user=request.user, status="going", event__venue__isnull=False
            ).values_list("event__venue_id", flat=True)
        )
        # CTA state: viewer-IS-claimant → explicit "you manage" (ADR-014 D2, ADR-008 D3)
        viewer_is_claimant = organizer.active_claimants.filter(
            pk=request.user.pk
        ).exists()
        # CTA state: viewer has a pending ClaimIntent (unresolved, not rejected)
        viewer_claim_is_pending = (
            not viewer_is_claimant
            and ClaimIntent.objects.filter(
                user=request.user,
                profile=organizer,
                resolved_at__isnull=True,
                rejected_at__isnull=True,
            ).exists()
        )
    else:
        following = False
        going_venue_ids = []
        viewer_is_claimant = False
        viewer_claim_is_pending = False

    rating_count = organizer.rating_count
    avg_rating = organizer.avg_rating
    threshold = get_numeric("threshold.organizer_ratings_display", default=3)
    show_rating = rating_count >= threshold

    # Parse ?sort query param; fall back to 'recent' for unknown values.
    sort = request.GET.get("sort", "recent")
    if sort not in _SORT_ORDERINGS:
        sort = "recent"
    ordering = _SORT_ORDERINGS[sort]
    reviews = (
        Review.objects.filter(organizer=organizer, hidden=False)
        .select_related("author")
        .order_by(*ordering)
    )

    user_review = None
    if request.user.is_authenticated:
        try:
            user_review = organizer.reviews.get(author=request.user)
        except Review.DoesNotExist:
            user_review = None

    context = {
        "organizer": organizer,
        "upcoming_events": upcoming_events,
        "past_events": past_events,
        "following": following,
        "going_venue_id_list": going_venue_ids,
        "rating_count": rating_count,
        "avg_rating": avg_rating,
        "show_rating": show_rating,
        "reviews": reviews,
        "sort": sort,
        "event_sort": event_sort,
        "user_review": user_review,
        "EVENT_REVIEWS_DISPLAYED": event_reviews_displayed,
        "MIN_RATINGS_FOR_DISPLAY": threshold,
        # Claim CTA state (ADR-014 D2, ADR-008 D3)
        "viewer_is_claimant": viewer_is_claimant,
        "viewer_claim_is_pending": viewer_claim_is_pending,
    }
    return render(request, "organizers/profile.html", context)


@require_POST
@login_required
def organizer_follow(request, slug):
    # Following is a private subscription powering the personalized feed, open
    # to any logged-in user — NOT a vouched-gated capability. ADR-013 scopes
    # `vouched` to restricted-event reads, rating signals, and invite grants;
    # follow is none of those. If follow is ever re-gated to vouched, the gate
    # must fail loud (visible error) and the button must be hidden for
    # non-vouched users — never a silent 403 (ADR-008 D3). See kb follow-gate bead.
    organizer = get_object_or_404(Profile, slug=slug, status="approved")
    follow, created = Follow.objects.get_or_create(user=request.user, profile=organizer)
    if not created:
        follow.delete()
        following = False
    else:
        following = True
    return render(
        request,
        "organizers/_follow_button.html",
        {
            "organizer": organizer,
            "following": following,
        },
    )


def profile_legacy_redirect(request, slug):
    """301 permanent redirect from /o/<slug>/ to /p/<slug>/, preserving query string."""
    target = reverse("organizer-profile", kwargs={"slug": slug})
    qs = request.GET.urlencode()
    url = f"{target}?{qs}" if qs else target
    return HttpResponsePermanentRedirect(url)


@login_required
def claim_entry(request, slug):
    """
    Claim entry view for profile /p/<slug>/claim/.

    Auth-required (ADR-014 D2 — auth-before-claim; user_target NEVER NULL per D3).

    GET:  Render the claim form (with Turnstile per ADR-014 D3).
    POST: Both tracks ALWAYS pass through magic-link confirmation (ADR-014 D2):
        - email_domain fast-path: submitted email domain == Profile.verified_domain
          → MagicLinkToken(intended_method='email_domain') created, magic-link
            email sent.
        - admin-review path: no domain match or verified_domain not set
          → ClaimIntent + MagicLinkToken(intended_method='admin_review') created,
            email sent.
        Both tracks redirect to check-email page; ProfileClaim is NOT created at
        POST time.

    Explicit branch for user-IS-claimant (ADR-008 D3 — not silent).
    """
    profile = get_object_or_404(Profile, slug=slug)

    # ADR-008 D3: explicit branch — not silent omission
    if profile.active_claimants.filter(pk=request.user.pk).exists():
        return render(
            request,
            "organizers/claim_start.html",
            {"organizer": profile, "already_claimant": True},
        )

    # Pre-fill with the logged-in user's email (the common case: claiming with
    # your own address). Editable so org-domain users can swap in a matching
    # address for the email_domain fast-path. initial only applies on GET (unbound).
    form = ClaimForm(request.POST or None, initial={"email": request.user.email})

    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"]
        submitted_domain = email.split("@")[1].lower()

        is_fast_path = (
            profile.verified_domain
            and submitted_domain == profile.verified_domain.lower()
        )

        if is_fast_path:
            # ---- Email-domain fast-path (ADR-014 D2) ----
            # Both tracks go through magic-link; fast-path differs only in
            # post-confirmation routing (auto-claim vs admin queue).
            intended_method = "email_domain"
        else:
            # ---- Admin-review path (ADR-014 D2) ----
            intended_method = "admin_review"
            message = form.cleaned_data.get("message", "").strip()
            intent, created = ClaimIntent.objects.get_or_create(
                user=request.user, profile=profile
            )
            # kb-j8u: persist the most recent message so admins see the latest
            # context if the user re-submits with updated info.
            if message and intent.message != message:
                intent.message = message
                intent.save(update_fields=["message"])

        token = MagicLinkToken.objects.create(
            email=email,
            profile=profile,
            user_target=request.user,
            expires_at=timezone.now() + timedelta(hours=24),
            intended_method=intended_method,
        )

        redeem_url = request.build_absolute_uri(
            reverse("organizer-claim-redeem", kwargs={"token": str(token.token)})
        )
        email_body = render_to_string(
            "email/claim_magic_link.html",
            {
                "user": request.user,
                "organizer": profile,
                "redeem_url": redeem_url,
            },
            request=request,
        )
        send_mail(
            subject=f"Verify your claim for {profile.name}",
            message=email_body,
            from_email=None,  # uses DEFAULT_FROM_EMAIL from settings
            recipient_list=[email],
            fail_silently=False,
        )

        return redirect(reverse("organizer-claim-check-email", kwargs={"slug": slug}))

    from django.conf import settings as django_settings

    # Suppress Turnstile in DEBUG (dev/localhost): the prod site key won't
    # validate against a localhost origin, so loading the widget renders
    # Cloudflare's "Unable to connect to website" error frame inline. In
    # prod (DEBUG=False) the configured key is used as normal.
    turnstile_site_key = (
        ""
        if django_settings.DEBUG
        else getattr(django_settings, "TURNSTILE_SITE_KEY", "")
    )

    return render(
        request,
        "organizers/claim_start.html",
        {
            "organizer": profile,
            "form": form,
            "already_claimant": False,
            "turnstile_site_key": turnstile_site_key,
        },
    )


@login_required
def claim_check_email(request, slug):
    """Post-submission page for the admin-review claim track.

    Serves two states for the same URL:
    - pre-redeem: 'check your inbox' (the verification email was just sent).
    - post-redeem: the magic-link redeem view stamps ClaimIntent.submitter_verified_at
      and redirects back here — so render 'email verified, claim pending review'
      instead of telling the user to check their inbox for a link they just used.
    """
    profile = get_object_or_404(Profile, slug=slug)
    verified = ClaimIntent.objects.filter(
        user=request.user, profile=profile, submitter_verified_at__isnull=False
    ).exists()
    return render(
        request,
        "organizers/claim_check_email.html",
        {"organizer": profile, "verified": verified},
    )


@login_required
def magic_link_redeem(request, token):
    """
    Magic-link redemption view.

    Validates the (email, profile_id, user_target=request.user) triple per ADR-014 D3.
    Fails loud (ADR-008 D3) on any mismatch:
      - wrong user (request.user ≠ user_target) → 403
      - expired token → 400
      - already-used token → 400
      - non-existent token → 404 (via get_object_or_404)

    On success, routes by token.intended_method (ADR-014 D1+D2):
      - 'email_domain': creates ProfileClaim(verified_method='email_domain'),
        marks token used, redirects to profile page (auto-claim complete).
      - 'admin_review': marks ClaimIntent.submitter_verified_at,
        marks token used, redirects to check-email page (admin must still approve).
    """
    magic_token = get_object_or_404(MagicLinkToken, token=token)

    # ADR-008 D3: fail loud — explicit check for user mismatch
    if magic_token.user_target != request.user:
        return HttpResponseForbidden(
            "This verification link was issued for a different account. "
            "Please sign in with the correct account and try again."
        )

    if magic_token.is_used:
        return HttpResponseBadRequest(
            "This verification link has already been used. "
            "Please start the claim process again."
        )

    if magic_token.is_expired:
        return HttpResponseBadRequest(
            "This verification link has expired (links are valid for 24 hours). "
            "Please start the claim process again."
        )

    # Mark token used BEFORE post-confirmation action — single-use invariant
    magic_token.mark_used()

    if magic_token.intended_method == "email_domain":
        # ---- Fast-path: auto-claim (ADR-014 D2) ----
        ProfileClaim.objects.get_or_create(
            profile=magic_token.profile,
            user=request.user,
            defaults={
                "verified_method": "email_domain",
                "role": "admin",
            },
        )
        return redirect(
            reverse("organizer-profile", kwargs={"slug": magic_token.profile.slug})
        )
    else:
        # ---- Admin-review path: stamp submitter_verified_at (ADR-014 D2) ----
        # ProfileClaim is NOT created here; admin must approve the ClaimIntent.
        ClaimIntent.objects.filter(
            user=request.user, profile=magic_token.profile
        ).update(submitter_verified_at=timezone.now())
        return redirect(
            reverse(
                "organizer-claim-check-email",
                kwargs={"slug": magic_token.profile.slug},
            )
        )
