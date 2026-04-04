"""
Email port contract test suite.

Provides a reusable base class that any EmailPort adapter must pass.
"""

from __future__ import annotations

import pytest

from bapp_connectors.core.dto import DeliveryReport, DeliveryStatus, MessageChannel, OutboundMessage


class EmailContractTests:
    """
    Contract tests for EmailPort implementations.

    Subclasses MUST provide an `adapter` fixture and a `test_recipient` fixture.
    """

    @pytest.fixture
    def adapter(self):
        """Override in subclass to provide a connected adapter."""
        raise NotImplementedError

    @pytest.fixture
    def test_recipient(self) -> str:
        """Override in subclass to provide a valid test recipient email."""
        return "test@example.com"

    def test_validate_credentials(self, adapter):
        assert adapter.validate_credentials() is True

    def test_test_connection(self, adapter):
        result = adapter.test_connection()
        assert result.success is True

    def test_send_returns_delivery_report(self, adapter, test_recipient):
        message = OutboundMessage(
            channel=MessageChannel.EMAIL,
            to=test_recipient,
            subject="Contract Test",
            body="This is a contract test message.",
        )
        report = adapter.send(message)
        assert isinstance(report, DeliveryReport)
        assert report.status in (DeliveryStatus.SENT, DeliveryStatus.QUEUED)

    def test_send_bulk_returns_reports(self, adapter, test_recipient):
        messages = [
            OutboundMessage(
                channel=MessageChannel.EMAIL,
                to=test_recipient,
                subject=f"Bulk Test {i}",
                body=f"Bulk message {i}.",
            )
            for i in range(2)
        ]
        reports = adapter.send_bulk(messages)
        assert isinstance(reports, list)
        assert len(reports) == 2
        assert all(isinstance(r, DeliveryReport) for r in reports)
        assert all(r.status in (DeliveryStatus.SENT, DeliveryStatus.QUEUED) for r in reports)
