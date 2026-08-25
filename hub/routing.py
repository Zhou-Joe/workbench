"""Channels WebSocket routes."""

from django.urls import re_path

from hub import consumers

websocket_urlpatterns = [
    re_path(r"^meetings/ws/$", consumers.MeetingStreamConsumer.as_asgi()),
]
