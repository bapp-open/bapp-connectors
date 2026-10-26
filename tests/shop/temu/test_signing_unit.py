from bapp_connectors.providers.shop.temu.signing import sign_params, signed_document_headers

SECRET = "c7e0a1a63542be4de3cb5488f9fba8149e8fc290"
# The documented vector, verbatim (Temu "Signature Method for API Request").
PARAMS = {
    "access_token": "2nifvmpyymvypwmcms5ct4uqqudrwgpmzbcnmkt1jzjkuaf3x56iixym",
    "app_key": "f9d5cc9313893a20d5aa85c654e8f503",
    "data_type": "JSON",
    "sendRequestList": [
        {
            "orderSendInfoList": [
                {
                    "quantity": 1,
                    "orderSn": "211-21905473070712792",
                    "parentOrderSn": "PO-211-21905452099192792",
                    "goodsId": 601099548666279,
                    "skuId": 17592352673534,
                }
            ],
            "carrierId": "699272611",
            "trackingNumber": "270324232756",
        }
    ],
    "sendType": 0,
    "timestamp": 1711009072,
    "type": "bg.logistics.shipment.confirm",
}


def test_sign_matches_documented_vector():
    assert sign_params(SECRET, PARAMS) == "4CCF219942D4180C6DDA3CE36C1B838F"


def test_sign_ignores_existing_sign_key():
    assert sign_params(SECRET, {**PARAMS, "sign": "x"}) == "4CCF219942D4180C6DDA3CE36C1B838F"


def test_document_headers_shape():
    h = signed_document_headers("k", SECRET, "t", timestamp=1711009072, random_digits="1" * 32)
    assert set(h) == {"toa-app-key", "toa-access-token", "toa-random", "toa-timestamp", "toa-sign"}
    assert h["toa-timestamp"] == "1711009072" and h["toa-random"] == "1" * 32
    assert h["toa-sign"] == sign_params(
        SECRET, {"toa-app-key": "k", "toa-access-token": "t", "toa-random": "1" * 32, "toa-timestamp": "1711009072"}
    )


def test_document_headers_random_is_32_digits():
    h = signed_document_headers("k", SECRET, "t")
    assert len(h["toa-random"]) == 32 and h["toa-random"].isdigit() and len(h["toa-timestamp"]) == 10
