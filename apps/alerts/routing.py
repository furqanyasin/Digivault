from django.urls import path

from apps.alerts.consumers import AlertConsumer

websocket_urlpatterns = [
    path("ws/alerts/", AlertConsumer.as_asgi()),
]
