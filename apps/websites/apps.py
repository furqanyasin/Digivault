from django.apps import AppConfig


class WebsitesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.websites"
    label = "websites"

    def ready(self):
        import apps.websites.signals  # noqa: F401
