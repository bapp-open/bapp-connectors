"""GitLab DevOps provider (REST API v4)."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.devops.gitlab.adapter import GitLabAdapter
from bapp_connectors.providers.devops.gitlab.manifest import manifest

__all__ = ["GitLabAdapter", "manifest"]

# Auto-register with the global registry
registry.register(GitLabAdapter)
