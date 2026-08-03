# Samlight

A personal fork of **Red Light** (`plugin.video.redlight`) from
[The Red Wizard](https://github.com/The-Red-Wiz/TheRedWizard), republished as
**`plugin.video.samlight`** through a self-hosted Kodi repository so Kodi
updates it automatically.

Upstream is GPL-3.0. All credit for the addon belongs to The Red Wizard.

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
| `plugin.video.redlight/` | The addon source. Upstream's code **plus my changes**. Folder name and addon id stay upstream's on purpose. |
| `repo/repository.samlight/` | The Kodi repository addon that points at GitHub Pages. |
| `tools/` | Sync and build scripts. |
| `docs/` | What GitHub Pages serves: `addons.xml`, `addons.xml.md5`, and the zips. Generated - never edit by hand. |

Two branches:

- **`upstream`** - pristine snapshots of upstream's `plugin.video.redlight`,
  nothing else, never hand-edited.
- **`main`** - `upstream` plus my tweaks and the tooling.

`git diff upstream main -- plugin.video.redlight` shows exactly what I changed.

## Why the id is rewritten at build time, not in the repo

`tools/build.py` copies the source, replaces every `plugin.video.redlight`
string with `plugin.video.samlight`, and zips that. The repo itself keeps
upstream's names, which means:

- `git merge upstream` is a clean text merge instead of a rename war,
- any new file upstream adds gets renamed automatically,
- my actual changes stay a small, readable diff.

## Updating from upstream

Upstream's git endpoints are disabled (`403`), so syncing pulls the source zip
that codeload still serves rather than using a git remote.

```powershell
pwsh tools\update.ps1
```

That syncs the `upstream` branch, merges it into `main`, rebuilds `docs/`, and
pushes. A GitHub Action does the same thing daily, and fails loudly if upstream
touched a line I also touched - in that case resolve it locally:

```powershell
git checkout main; git merge upstream
```

## Versioning

Built version = upstream's version plus a revision counter, e.g. upstream
`2.1.7` becomes `2.1.7.1`, `2.1.7.2`, ... A new number is only minted when the
built content actually changed, so Kodi never re-downloads an identical build.
