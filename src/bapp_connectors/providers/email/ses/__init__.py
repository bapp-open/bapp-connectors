"""Amazon SES email provider."""

# Conditional registration — only if boto3 is installed
try:
    import boto3  # noqa: F401

    from bapp_connectors.core.registry import registry
    from bapp_connectors.providers.email.ses.adapter import SESEmailAdapter
    from bapp_connectors.providers.email.ses.manifest import manifest

    __all__ = ["SESEmailAdapter", "manifest"]

    registry.register(SESEmailAdapter)
except ImportError:
    pass
