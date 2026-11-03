from decimal import Decimal

from bapp_connectors.core.dto import Article, ImportProblem, ImportResult, ImportStatus, StockLine, TrialBalanceLine
from bapp_connectors.core.manifest import AuthConfig
from bapp_connectors.core.ports import AccountingPort, BasePort
from bapp_connectors.core.types import ProviderFamily


def test_accounting_family_value():
    assert ProviderFamily.ACCOUNTING == "accounting"


def test_accounting_port_is_abstract_base_port():
    assert issubclass(AccountingPort, BasePort)
    assert {
        "import_file",
        "get_article_stock",
        "get_stock_report",
        "get_account_balance",
        "get_trial_balance",
        "get_article",
    } <= set(AccountingPort.__abstractmethods__)


def test_auth_config_rotating_credentials_defaults_false():
    assert AuthConfig().rotating_credentials is False
    assert AuthConfig(rotating_credentials=True).rotating_credentials is True


def test_import_result_defaults():
    r = ImportResult(status=ImportStatus.PARTIAL, http_status=207)
    assert r.problems == [] and r.report == "" and r.message == ""
    assert ImportProblem(message="x").document_number == ""


def test_decimal_defaults_on_lines():
    assert StockLine(warehouse="0001", warehouse_name="G", article_code="A", name="N").qty_final == Decimal(0)
    assert TrialBalanceLine(account="371", name="MARFURI").debit_final == Decimal(0)
    assert Article(name="A").vat is None
