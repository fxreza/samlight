# Changelog

## [2.6.0.1] - 2026-10-03

- New setting Settings > Content > Send Clear Logos to Skin (on by default). Turn it off and skins like Arctic Fuse 3 show the text title instead of the clear logo in widgets and lists.

## [2.5.1.1] - 2026-10-03

- Fixed Kodi freezing on the loading screen when a stream stalls right after it opens. It now tries the next source instead.
- Back always closes the loading screen; it closes itself if nothing else does within 3 seconds.
- The loading screen switches from searching to resolving in place, so there is no black screen in between.
- A stream server that failed or stalled at the start is tried last for 6 hours.

## [2.5.0.1] - 2026-10-02

- Cloud check runs alongside the external search, and a cloud match stops it and plays at once.
- TorBox is checked first, Premiumize is the fallback.
- TorBox checks the torrents list first; Premiumize lists the whole cloud in one request.
- Loading screen no longer shows the plot; the setting now only covers the pause screen.

## [2.4.3.1] - 2026-09-30

- First version tracked in this file. The add-on's own detailed changelog is in `plugin.video.redlight/resources/text/changelog.txt`, also shown in Kodi under Tools > Changelog & Log Utils.
