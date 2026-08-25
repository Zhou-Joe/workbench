"""ASGI entry point: Django HTTP + channels WebSocket on one server."""

import os

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ridehub.settings")

import hub.routing  # noqa: E402  (imports need DJANGO_SETTINGS_MODULE set)

application = ProtocolTypeRouter(
    {
        "http": get_asgi_application(),
        "websocket": AllowedHostsOriginValidator(URLRouter(hub.routing.websocket_urlpatterns)),
    }
)
