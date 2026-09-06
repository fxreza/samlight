# Samlight

A personal fork of **Red Light** (`plugin.video.redlight`) from
[The Red Wizard](https://github.com/The-Red-Wiz/TheRedWizard), republished as
**`plugin.video.samlight`** through a self-hosted Kodi repository so Kodi
updates it automatically.

Upstream is GPL-3.0. All credit for the original addon belongs to The Red
Wizard. Upstream took its public source down in September 2026; this repo is now
standalone and no longer syncs from it.

## Install in Kodi

1. Settings > System > Add-ons > enable **Unknown sources**.
2. Download `repository.samlight-1.0.0.zip` from
   <https://fxreza.github.io/samlight/repository.samlight/>
3. Add-ons > Install from zip file > pick that zip.
4. Add-ons > Install from repository > **Samlight Repository** > Video add-ons >
   **Sam Light**.

From then on Kodi checks the repository on its own and pulls new builds.

## How this repo is laid out

| Path | What it is |
| --- | --- |
| `plugin.video.redlight/` | The addon source. The folder name and addon id stay as upstream's, and are rewritten at build time. |
| `repo/repository.samlight/` | The Kodi repository addon that points at GitHub Pages. |
| `tools/` | The build script. |
| `docs/` | What GitHub Pages serves: `addons.xml`, `addons.xml.md5`, and the zips. Generated - never edit by hand. |

One branch: **`main`**.

## Why the id is rewritten at build time, not in the repo

`tools/build.py` copies the source, replaces every `plugin.video.redlight`
string with `plugin.video.samlight`, and zips that. Keeping the original names
in the tree means the source stays directly comparable with the version it was
forked from.

## Publishing an update

Edit the addon under `plugin.video.redlight/`, commit, and push to `main`. The
GitHub Action rebuilds `docs/` and publishes it; Kodi picks it up on its next
repository check.

To build and publish by hand instead:

```powershell
pwsh tools\update.ps1
```

## Versioning

Built version = the source's version plus a revision counter, e.g. `2.4.2`
becomes `2.4.2.1`, `2.4.2.2`, ... A new number is only minted when the built
content actually changed, so Kodi never re-downloads an identical build.
