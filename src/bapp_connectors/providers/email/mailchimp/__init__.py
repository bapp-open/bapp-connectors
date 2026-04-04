"""Mailchimp Transactional (Mandrill) email provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.email.mailchimp.adapter import MailchimpEmailAdapter
from bapp_connectors.providers.email.mailchimp.manifest import manifest

__all__ = ["MailchimpEmailAdapter", "manifest"]

# Auto-register with the global registry
registry.register(MailchimpEmailAdapter)
