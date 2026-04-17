"""Accounts middleware for kinky-bubbles."""


class ApprovalGateMiddleware:
    """Pass-through middleware placeholder for approval-gating.

    Phase 0.1: field ``accounts.User.is_approved`` exists; this middleware is
    registered so MIDDLEWARE ordering is established. Exemption logic for
    ``/admin/`` and allauth routes will be wired in a later phase (0.3+) once
    the public auth surface ships.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)
