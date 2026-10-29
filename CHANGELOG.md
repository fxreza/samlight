# Changelog

## [2.11.0.1] - 2026-10-29

- Watched status now follows you between devices. Watched marks for movies and episodes, and dropped TV shows, are shared through the Cloud Backup GitHub repository in one file for all devices, so what you watch on the Mac shows as watched on the Fire Stick and the other way round. Your own marks are sent about a minute after the last one; other devices' marks are pulled at start-up and every hour, never while a video plays or in the 90 seconds after it stops. When both devices change the same title, the newest change wins. The first sync takes the union of every device's history.
- Resume points stay on each device on purpose: they change on every stop and would keep the shared file churning.
- New Settings > General > Cloud Backup rows: Sync Watched Status Between Devices (on by default, needs the Cloud Backup token and repository), Pull Every (minutes), Last Sync. Tools > Import & Export > Sync Watched Status Now runs it at once.
- Only with Red Light as the Watched Status Provider. Trakt, Simkl, MDBList and PunchPlay already share through their own servers.

## [2.10.4.1] - 2026-10-22

- Restore from Cloud, Import Settings and Kodi favourites import and export failed on Android devices such as the Fire TV with "Permission denied" (Errno 13). They now copy only the file contents, which Android allows.

## [2.10.3.1] - 2026-10-22

- Confirm and message windows (such as Restore from Cloud and Import Settings) could open with nothing highlighted, so their buttons could not be reached with a remote. When the text fits without scrolling, the default button is now highlighted.

## [2.10.2.1] - 2026-10-22

- TV Shows Progress Manager: selecting the Show row now opens the All / Dropped / Not Dropped choice. Since 2.10.0 it did nothing.

## [2.10.1.1] - 2026-10-22

- TV Shows Progress Manager: the Drop / Undrop text and the red [DROPPED] tag show again. 2.10.0 let skins show the plain show title or its clear logo instead.
- Long press a show in the TV Shows Progress Manager for Drop TV Show or Undrop TV Show, above Browse Seasons. Selecting a show still drops or undrops it.

## [2.10.0.1] - 2026-10-22

- TV Shows Progress Manager shows each show's poster and fanart, like the other TV show lists.
- New Show row at the top of the TV Shows Progress Manager: list All shows, only Dropped shows, or only Not Dropped shows. The row also shows how many shows are listed.
- Long press a show in the TV Shows Progress Manager for Browse Seasons. Selecting a show still drops or undrops it.

## [2.9.1.1] - 2026-10-22

- Cloud Backup to GitHub is back, with its settings and Tools menu entries. It still runs once a day, but now only after Kodi has been idle for 10 minutes with nothing playing, so it never runs right after a video or while you browse. Back Up to Cloud Now still runs at once.
- The Trakt, Simkl, MDBList and PunchPlay background syncs stay off.

## [2.9.0.1] - 2026-10-21

- Faster menus after playback. Only the TMDb list sync still runs in the background. Trakt, Simkl, MDBList and PunchPlay no longer sync on a timer, because they all started at once after every video and slowed Kodi down.
- Removed Cloud Backup (the daily upload to GitHub), its settings and its Tools menu entries. TMDb sync now keeps the lists. Import & Export still works. The stored GitHub token is deleted at the next settings sync.
- Menus no longer re-check the databases each time they open. This now happens once per Kodi session, as in POV.

## [2.8.1.2] - 2026-10-18

- Removed the link check and back-to-list change from 2.8.1.1; it did not stop the freezes. Same as 2.8.0.1, with a higher number so Kodi installs it.

## [2.8.0.1] - 2026-10-03

- New setting Playback > Resume from Last Source (on by default). Playing a movie or episode again plays the source it last played from, with no search, so it starts much faster, also after a crash. The source is saved when playback starts and dropped once the title is marked watched, or after 14 days. If it no longer plays, the normal search runs.
- Season and show packs: once an episode plays from a pack (a torrent pack on any debrid, or a TorBox cloud folder), the next episodes play from the same pack, with no search for manual plays and first in line for Autoplay Next Episode. Kept for 30 days per show.
- Playback Options (Select Source, Rescrape, Scrape with...) always search, so you can still pick another source.
- Show/Hide Clear Logo is now off by default (text titles). This only changes new installs; an existing choice stays as it is.

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
