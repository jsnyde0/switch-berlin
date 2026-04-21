import time

from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from a_core.models import get_flag


def home_view(request):
    return render(request, "pages/home.html", {})


def test_partial_view(request):
    if request.htmx:
        return render(request, "pages/home.html#test-partial")
    return HttpResponse(
        "HTMX not working; it should have replaced the button with a partial."
    )


def test_skeleton_hx(request):
    time.sleep(1)
    return render(request, "pages/home.html#skeleton-partial")


@require_http_methods(["GET", "POST"])
def age_check_view(request):
    if request.method == "POST" and request.POST.get("confirm") == "yes":
        next_url = request.POST.get("next", "/")
        if not next_url.startswith("/"):
            next_url = "/"
        response = redirect(next_url)
        max_age = 365 * 24 * 3600 if request.POST.get("remember") else None
        response.set_cookie(
            "age_gate", "ok", max_age=max_age, httponly=True, samesite="Lax"
        )
        return response
    next_url = request.GET.get("next", "/")
    return render(request, "age_check.html", {"next_url": next_url})


def robots_txt_view(request):
    public = get_flag("PUBLIC_READ_ENABLED", default=True)
    if public:
        content = "User-agent: *\nAllow: /\n\nUser-agent: *\nDisallow: /admin/\n"
    else:
        content = "User-agent: *\nDisallow: /\n"
    return HttpResponse(content, content_type="text/plain")
