import os
import sys

from django.apps import AppConfig


class HubConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "hub"

    def ready(self):
        # Never run background threads during tests or one-off commands.
        if os.environ.get("RIDEHUB_DISABLE_WORKER") == "1":
            return
        if "test" in sys.argv or "makemigrations" in sys.argv or "migrate" in sys.argv:
            return
        from . import runtime

        runtime.start_background()
