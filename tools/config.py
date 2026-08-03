"""Single place for every name/URL used by the sync and build scripts."""

# --- upstream -------------------------------------------------------------
# Upstream's git endpoints are disabled (HTTP 403), so we sync from the
# source zip that codeload still serves.
UPSTREAM_REPO = "The-Red-Wiz/TheRedWizard"
UPSTREAM_BRANCH = "main"
UPSTREAM_ZIP = f"https://codeload.github.com/{UPSTREAM_REPO}/zip/refs/heads/{UPSTREAM_BRANCH}"

# Folder we track, both inside the upstream zip and at the root of this repo.
SOURCE_ID = "plugin.video.redlight"

# Branch holding the pristine upstream snapshots. Never hand-edit it.
VENDOR_BRANCH = "upstream"

# --- our build ------------------------------------------------------------
TARGET_ID = "plugin.video.samlight"
TARGET_NAME = "[COLOR red]Sam Light[/COLOR]"
TARGET_PROVIDER = "Sam"

REPO_ADDON_ID = "repository.samlight"

# GitHub Pages root that Kodi will poll for updates.
PAGES_URL = "https://fxreza.github.io/samlight/"

# Directory published by GitHub Pages.
DOCS_DIR = "docs"

# How many old zips of each addon to keep.
KEEP_ZIPS = 5
