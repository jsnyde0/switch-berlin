from allauth.account.adapter import DefaultAccountAdapter


class NoSignupAdapter(DefaultAccountAdapter):
    """Closes public signup — accounts are staff-minted only in phase 0.3."""

    def is_open_for_signup(self, request):
        return False
