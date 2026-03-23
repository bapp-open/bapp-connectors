"""
URL patterns for webhook and OAuth callback endpoints.

Include in your project's urls.py:

    urlpatterns = [
        path("webhooks/", include("django_bapp_connectors.webhooks.urls")),
    ]
"""

from django.urls import path

from . import views

app_name = "bapp_connectors_webhooks"

urlpatterns = [
    path("<int:connection_id>/<str:action>/", views.webhook_receiver, name="webhook_receiver"),
    path("oauth/callback/<str:provider>/", views.oauth_callback, name="oauth_callback"),
]
