#!/usr/bin/env python3
"""
Auto-update the README.md providers table and project structure from the registry.

Run manually or as a pre-commit hook:
    python scripts/update_readme.py

Markers in README.md:
    <!-- PROVIDERS:BEGIN --> ... <!-- PROVIDERS:END -->
    <!-- STRUCTURE:BEGIN --> ... <!-- STRUCTURE:END -->
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
PROVIDERS_DIR = ROOT / "src" / "bapp_connectors" / "providers"


def discover_providers() -> dict[str, list[dict]]:
    """
    Discover all providers by importing their manifests from the registry.

    Returns: {family: [{name, display_name, settings_count, capabilities}, ...]}
    """
    # Import all provider packages to trigger auto-registration
    for family_dir in sorted(PROVIDERS_DIR.iterdir()):
        if not family_dir.is_dir() or family_dir.name.startswith("_"):
            continue
        for provider_dir in sorted(family_dir.iterdir()):
            if not provider_dir.is_dir() or provider_dir.name.startswith("_"):
                continue
            # Only import if it has an adapter.py (fully implemented)
            if not (provider_dir / "adapter.py").exists():
                continue
            module = f"bapp_connectors.providers.{family_dir.name}.{provider_dir.name}"
            try:
                __import__(module)
            except Exception as e:
                print(f"  Warning: could not import {module}: {e}", file=sys.stderr)

    from bapp_connectors.core.registry import registry

    result: dict[str, list[dict]] = defaultdict(list)
    for manifest in registry.list_providers():
        caps = [c.__name__ for c in manifest.capabilities]
        result[manifest.family.value].append({
            "name": manifest.name,
            "display_name": manifest.display_name,
            "description": manifest.description,
            "settings_count": len(manifest.settings.fields),
            "capabilities": caps,
        })

    # Sort providers within each family
    for family in result:
        result[family].sort(key=lambda p: p["name"])

    return dict(result)


def build_providers_table(providers: dict[str, list[dict]]) -> str:
    """Build the markdown providers table."""
    family_order = ["shop", "courier", "payment", "messaging", "storage", "llm"]
    # Include any families not in the predefined order
    for fam in sorted(providers.keys()):
        if fam not in family_order:
            family_order.append(fam)
    family_labels = {
        "shop": "Shop",
        "courier": "Courier",
        "payment": "Payment",
        "messaging": "Messaging",
        "storage": "Storage",
        "llm": "LLM",
    }

    lines = [
        "| Family | Providers | Count |",
        "|---|---|---|",
    ]

    for family in family_order:
        if family not in providers:
            continue
        label = family_labels.get(family, family.title())
        names = ", ".join(p["display_name"] for p in providers[family])
        count = len(providers[family])
        lines.append(f"| **{label}** | {names} | {count} |")

    total = sum(len(v) for v in providers.values())
    lines.append(f"| | **Total** | **{total}** |")

    return "\n".join(lines)


def build_structure_tree(providers: dict[str, list[dict]]) -> str:
    """Build the providers section of the project structure tree."""
    family_order = ["shop", "courier", "payment", "messaging", "storage", "llm"]
    for fam in sorted(providers.keys()):
        if fam not in family_order:
            family_order.append(fam)
    lines = []
    for family in family_order:
        if family not in providers:
            continue
        names = ", ".join(p["display_name"] for p in providers[family])
        lines.append(f"│       ├── {family + '/':14s} # {names}")
    # Fix last line to use └ instead of ├
    if lines:
        lines[-1] = lines[-1].replace("├──", "└──")
    return "\n".join(lines)


def update_readme(providers: dict[str, list[dict]]) -> bool:
    """Update README.md between markers. Returns True if changed."""
    content = README.read_text()
    original = content

    # Update providers table
    table = build_providers_table(providers)
    content = re.sub(
        r"<!-- PROVIDERS:BEGIN -->.*?<!-- PROVIDERS:END -->",
        f"<!-- PROVIDERS:BEGIN -->\n{table}\n<!-- PROVIDERS:END -->",
        content,
        flags=re.DOTALL,
    )

    # Update structure tree
    tree = build_structure_tree(providers)
    content = re.sub(
        r"<!-- STRUCTURE:BEGIN -->.*?<!-- STRUCTURE:END -->",
        f"<!-- STRUCTURE:BEGIN -->\n{tree}\n<!-- STRUCTURE:END -->",
        content,
        flags=re.DOTALL,
    )

    if content != original:
        README.write_text(content)
        return True
    return False


def main():
    print("Discovering providers...")
    providers = discover_providers()

    for family, provs in sorted(providers.items()):
        print(f"  {family}: {', '.join(p['display_name'] for p in provs)}")

    print("\nUpdating README.md...")
    changed = update_readme(providers)

    if changed:
        print("README.md updated.")
    else:
        print("README.md already up to date.")

    return 0 if not changed else 0  # always succeed (pre-commit stages the change)


if __name__ == "__main__":
    sys.exit(main())
