# Changelog

## [2.7.1.1] - 2026-10-03

- Reconnect after a stream drop checks whether the internet works, not the stream server. A dead debrid server now moves straight on instead of waiting and giving up.
- The wait for the internet is 20 seconds instead of 90.
- If the same source fails again, it goes on down the results in list order, whichever service they are on (TorBox, Premiumize, ...). If the video was started by a quick cloud match, the full search runs first, then it carries on with the results not tried yet. It always resumes from just before the drop, without asking.

## [2.7.0.1] - 2026-10-03

- New setting Playback > Reconnect When the Stream Drops (on by default). If a stream ends more than 5 minutes early or freezes for 30 seconds without being paused, usually after a short network drop, Sam Light waits up to 90 seconds for the network, then plays the same source again from just before the drop. If that fails it tries the other results. Cancelling the wait stops playback and keeps your progress.
- Stopping a video no longer reloads the home widgets two extra times. Kodi already reloads them when Home opens, so Sam Light refreshes only if they were built before your progress was saved, and never reloads a Sam Light menu you just opened.
- A stop is noticed within a tenth of a second instead of up to a second, so progress is saved before Kodi rebuilds the widgets.

## [2.6.1.1] - 2026-10-03

- The clear logo setting is now called Show/Hide Clear Logo. Turned off, it also hides the logo in the player and on Sam Light's own screens (source search and results, next episode, still watching, skip intro, extras).
- Switching the setting clears the saved Next Episodes, In Progress, Recently Watched and calendar lists and refreshes widgets, so no Clear Main Cache is needed.

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
