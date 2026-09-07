import json
import pathlib
from decimal import Decimal

import pytest

from bapp_connectors.core.dto import CustomerPricing, CustomerProductPercent
from bapp_connectors.core.errors import PermanentProviderError
from bapp_connectors.providers.shop.bapp_store.adapter import BappStoreShopAdapter
from bapp_connectors.providers.shop.bapp_store.mappers import customers_to_body
from bapp_connectors.providers.shop.bapp_store.models import SyncTaskResponse
from tests.fake_http import FakeHttpClient
from tests.shop.bapp_store.fake_response import FakeResponse

RECORD = CustomerPricing(
    customer_key="12345678",
    order_value_percent=Decimal("3.0"),
    product_percents=[CustomerProductPercent(sku="P-100", discount_percent=Decimal("4"))],
)


def test_customers_applied_defaults_to_false():
    assert SyncTaskResponse.model_validate({}).customers_applied is False


def test_customers_applied_reads_back_from_a_store_response():
    assert SyncTaskResponse.model_validate({"customers_applied": True}).customers_applied is True


def test_percentages_go_out_as_two_decimal_strings():
    body = customers_to_body([RECORD], full=True)
    assert body == {
        "customers": [{
            "customer_key": "12345678",
            "order_value_percent": "3.00",
            "product_percents": [{"sku": "P-100", "discount_percent": "4.00"}],
        }],
        "customers_full": True,
    }


def test_an_empty_full_push_is_a_valid_instruction_to_clear_the_store():
    assert customers_to_body([], full=True) == {"customers": [], "customers_full": True}


def test_the_shipped_fixture_matches_what_the_mapper_produces():
    path = pathlib.Path(__file__).parents[3] / "src/bapp_connectors/providers/shop/bapp_store/fixtures/customers.json"
    doc = json.loads(path.read_text())
    assert customers_to_body([RECORD], full=True) == doc["request"]


@pytest.fixture
def fake():
    return FakeHttpClient()


@pytest.fixture
def adapter(fake):
    return BappStoreShopAdapter(
        credentials={"store_url": "https://demo-st.sites.bapp.ro/", "token": "tok"},
        http_client=fake,
        config={"vat_rate": "0.21"},
    )


def test_adapter_raises_when_the_store_does_not_confirm(adapter, fake):
    fake.add("POST", "tasks/store.CatalogSyncTask", FakeResponse(200, {"customers_applied": False}))
    with pytest.raises(PermanentProviderError, match="customer pricing"):
        adapter.push_customer_pricing([RECORD])
