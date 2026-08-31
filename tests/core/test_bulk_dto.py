from bapp_connectors.core.dto import BulkItemResult, BulkUpsertResult


def test_bulk_upsert_result_counts_failures_across_both_lists():
    result = BulkUpsertResult(
        created=[BulkItemResult(index=0, remote_id="1"), BulkItemResult(index=1, error="dup", error_code="product_invalid_sku")],
        updated=[BulkItemResult(index=0, error="boom")],
    )
    assert result.failed == 2
    assert result.succeeded == 1
