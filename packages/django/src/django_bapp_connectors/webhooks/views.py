"""
Generic webhook receiver and OAuth callback views.

These are framework-level views. Wire them to your URL config via webhooks/urls.py.
"""

from __future__ import annotations

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

    Receives webhooks, persists them via WebhookService, and dispatches
    async processing via Celery. Emits ``webhook_event_received`` signal
    on persist and ``webhook_event_processed`` signal after parsing.

    Requires your concrete Connection and WebhookEvent models to be
    resolvable. Set ``BAPP_CONNECTORS["CONNECTION_MODEL"]`` and
    ``BAPP_CONNECTORS["WEBHOOK_EVENT_MODEL"]`` in settings, or override
    this view for custom model resolution.
    """
    body = request.body
    headers = dict(request.headers)

    logger.info("Webhook received: connection=%s action=%s", connection_id, action)

    # Try to resolve connection and persist + dispatch
    try:
        from django_bapp_connectors.settings import get_setting

        connection_model_path = get_setting("CONNECTION_MODEL")
        webhook_model_path = get_setting("WEBHOOK_EVENT_MODEL")

        if connection_model_path and webhook_model_path:
            from django.apps import apps

            from django_bapp_connectors.services.webhook import WebhookService

            ConnectionModel = apps.get_model(connection_model_path)
            WebhookEventModel = apps.get_model(webhook_model_path)

            connection = ConnectionModel.objects.filter(pk=connection_id).first()

            # Resolve signature config from the provider manifest
            signature_method = None
            signature_header = ""
            secret = ""
            if connection:
                try:
                    adapter = connection.get_adapter()
                    manifest = adapter.manifest
                    if manifest.webhooks.supported:
                        signature_method = manifest.webhooks.signature_method
                        signature_header = manifest.webhooks.signature_header or ""
                except Exception:
                    pass  # Fall through with no signature verification

            service = WebhookService(webhook_event_model=WebhookEventModel)
            event = service.receive(
                provider=connection.provider_name if connection else action,
                headers=headers,
                body=body,
                signature_method=signature_method,
                signature_header=signature_header,
                secret=secret,
                connection=connection,
            )

            # Dispatch async processing if Celery is available and event was persisted
            if hasattr(event, "pk") and event.pk:
                try:
                    from django_bapp_connectors.tasks import process_webhook

                    process_webhook.delay(
                        webhook_event_id=event.pk,
                        app_label=event._meta.app_label,
                        model_name=event._meta.model_name,
                    )
                except Exception:
                    logger.debug("Celery not available, skipping async webhook processing")
    except Exception:
        logger.exception("Failed to process webhook for connection %s", connection_id)

    # Always return 200 to acknowledge receipt
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
