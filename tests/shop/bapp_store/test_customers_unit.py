from bapp_connectors.providers.shop.bapp_store.models import SyncTaskResponse


def test_customers_applied_defaults_to_false():
    assert SyncTaskResponse.model_validate({}).customers_applied is False


def test_customers_applied_reads_back_from_a_store_response():
    assert SyncTaskResponse.model_validate({"customers_applied": True}).customers_applied is True
