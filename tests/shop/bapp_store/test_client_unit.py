from bapp_connectors.providers.shop.bapp_store.models import SyncItemResult, SyncTaskResponse


def test_sync_task_response_parses_positional_results():
    parsed = SyncTaskResponse.model_validate(
        {
            "categories": [{"index": 0, "id": "12", "status": "created", "error": "", "code": ""}],
            "products": [
                {"index": 0, "id": "501", "status": "updated"},
                {"index": 1, "id": "502", "status": "error", "error": "unknown category 99", "code": "unknown_category"},
            ],
            "rules_applied": True,
        }
    )
    assert parsed.categories == [SyncItemResult(index=0, id="12", status="created")]
    assert parsed.products[1].code == "unknown_category"
    assert parsed.rules_applied is True and parsed.webhook_applied is False


def test_sync_task_response_defaults_to_empty():
    assert SyncTaskResponse.model_validate({}) == SyncTaskResponse()
