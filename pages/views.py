import time

from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods

from a_core.models import get_flag


def home_view(request):
    return redirect(reverse("event-list"))


@staff_member_required
def debug_smoketest_view(request):
    return render(request, "pages/home.html", {})


@staff_member_required
def test_partial_view(request):
    if request.htmx:
        return render(request, "pages/home.html#test-partial")
    return HttpResponse("HTMX not working; it should have replaced the button with a partial.")


@staff_member_required
def test_skeleton_hx(request):
    time.sleep(1)
    return render(request, "pages/home.html#skeleton-partial")


@require_http_methods(["GET", "POST"])
def age_check_view(request):
    if request.method == "POST" and request.POST.get("confirm") == "yes":
        next_url = request.POST.get("next", "/")
        if not url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            next_url = "/"
        response = redirect(next_url)
        max_age = 365 * 24 * 3600 if request.POST.get("remember") else None
        response.set_cookie("age_gate", "ok", max_age=max_age, httponly=True, samesite="Lax")
        return response
    next_url = request.GET.get("next", "/")
    return render(request, "age_check.html", {"next_url": next_url})


def robots_txt_view(request):
    public = get_flag("PUBLIC_READ_ENABLED", default=True)
    if public:
        content = "User-agent: *\nAllow: /\nDisallow: /admin/\n"
    else:
        content = "User-agent: *\nDisallow: /\n"
    return HttpResponse(content, content_type="text/plain")


def impressum_view(request):
    return render(request, "pages/impressum.html", {})


def privacy_view(request):
    return render(
        request,
        "pages/privacy.html",
        {"privacy_last_updated": "2026-04-22"},
    )


def terms_view(request):
    return render(
        request,
        "pages/terms.html",
        {"terms_last_updated": "2026-04-22"},
    )
