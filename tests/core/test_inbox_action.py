"""Unit tests for the InboxAction DTO."""

from __future__ import annotations

from bapp_connectors.core.dto import InboxAction, InboxActionType


def test_default_is_none():
    action = InboxAction()
    assert action.type == InboxActionType.NONE
    assert action.folder == ""
    assert action.read is True


def test_delete_factory():
    action = InboxAction.delete()
    assert action.type == InboxActionType.DELETE


def test_move_factory():
    action = InboxAction.move("Archive")
    assert action.type == InboxActionType.MOVE
    assert action.folder == "Archive"


def test_mark_read_factory():
    assert InboxAction.mark_read().type == InboxActionType.MARK_READ
    assert InboxAction.mark_read().read is True
    assert InboxAction.mark_read(read=False).read is False


def test_none_factory():
    assert InboxAction.none().type == InboxActionType.NONE
