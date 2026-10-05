"""Release links and version comparison for the project's GitHub repository."""

import re

REPOSITORY_URL = "https://github.com/ryanw341/BlenderQueue"
LATEST_RELEASE_URL = REPOSITORY_URL + "/releases/latest"
LATEST_RELEASE_API = "https://api.github.com/repos/ryanw341/BlenderQueue/releases/latest"


def release_status(release, installed):
    """Describe stable release tags without guessing about unfamiliar versions."""
    tag = release.get("tag_name")
    if not isinstance(tag, str) or not tag.strip():
        raise ValueError("GitHub did not return a release version.")
    tag = tag.strip()

    def version(value):
        match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:\+[\w.-]+)?", value, re.I)
        return tuple(map(int, match.groups())) if match else None

    latest, current = version(tag), version(installed)
    if latest is None or current is None or release.get("prerelease"):
        return f"Latest published release: {tag}. Installed version: {installed}."
    if latest > current:
        return f"Update available: {tag}. Installed version: {installed}."
    if latest == current:
        return f"You're up to date ({installed})."
    return f"Installed version {installed} is newer than the latest release ({tag})."
