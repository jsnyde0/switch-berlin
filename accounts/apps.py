from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "accounts"

    def ready(self):
        from accounts.consent import _connect_pre_delete_signal

        _connect_pre_delete_signal()
