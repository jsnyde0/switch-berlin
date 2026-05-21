"""Custom view decorators for accounts authorization."""

from django.http import HttpResponse


def approved_required(view_func):
    """Decorator: require request.user.is_staff or request.user.status == 'vouched'.

    Must be applied AFTER @login_required (which ensures the user is
    authenticated before this check runs).

    Returns 403 for authenticated users who are neither staff nor vouched,
    ensuring write endpoints remain safe even when LoginWallMiddleware is
    relaxed or removed.
    """

    def wrapper(request, *args, **kwargs):
        if not (request.user.is_staff or request.user.status == "vouched"):
            return HttpResponse(status=403)
        return view_func(request, *args, **kwargs)

    wrapper.__name__ = view_func.__name__
    wrapper.__module__ = view_func.__module__
    return wrapper
