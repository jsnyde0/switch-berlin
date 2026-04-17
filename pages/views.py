import time

from django.http import HttpResponse
from django.shortcuts import render


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
