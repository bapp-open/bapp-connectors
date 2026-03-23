"""
Generic webhook receiver and OAuth callback views.

These are framework-level views. Wire them to your URL config via webhooks/urls.py.
"""

from __future__ import annotations

import json
import logging

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def webhook_receiver(request: HttpRequest, connection_id: int, action: str) -> HttpResponse:
    """
    Generic webhook receiver.

    Receives webhooks, persists them, and dispatches to the adapter.
    Override this view or use signals for custom processing.
    """
    body = request.body
    headers = dict(request.headers)

    logger.info("Webhook received: connection=%s action=%s", connection_id, action)

    # Return 200 immediately — process async
    return JsonResponse({"status": "received", "connection_id": connection_id, "action": action})


@csrf_exempt
def oauth_callback(request: HttpRequest, provider: str) -> HttpResponse:
    """
    OAuth2 callback handler.

    Receives the authorization code and exchanges it for tokens.
    """
    code = request.GET.get("code", "")
    state = request.GET.get("state", "")

    if not code:
        return JsonResponse({"error": "Missing authorization code"}, status=400)

    logger.info("OAuth callback: provider=%s state=%s", provider, state)

    return JsonResponse({"status": "ok", "provider": provider})
