"""URL configuration for test_views.py."""

from django.urls import include, path

urlpatterns = [
    path("webhooks/", include("django_bapp_connectors.webhooks.urls")),
]
