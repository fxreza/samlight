# -*- coding: utf-8 -*-
"""Bring the watch widgets up to date right after a stop, before Home asks for them.

When playback stops, Home asks again for every widget at once. Next Episodes, In Progress
and Recently Watched then each start a fresh Python interpreter, load the settings,
metadata and watched modules and rebuild, one after another: 5 to 10 seconds each on a
Fire TV, during which Home shows the old list. A few seconds later the after-playback
check used to invalidate every widget and rebuild them all again.

The player's own process is already running with those modules loaded. So at the stop it
takes the widget rebuild lock (widget requests then wait for it instead of starting
their own build), waits for its watched mark and resume point to be written, and builds
each stored watch-widget listing again in place: recorded into its snapshot, never sent
to Kodi. Next Episodes only reprocesses the show that changed (nextep_cache) and reuses
every other row. The waiting widget requests then replay the fresh snapshot at once,
and the after-playback check no longer invalidates them a second time.

Anything unexpected (no snapshot that knows its request yet, the lock held by another
build, a next episode starting, an error) leaves things as they were: the lock is
released and the widgets rebuild themselves as before.
"""
import sys
import time
from urllib.parse import parse_qsl

LIST_TYPES = {'build_next_episode': 'episode.next', 'build_in_progress_episode': 'episode.progress',
			'build_recently_watched_episode': 'episode.recently_watched'}
# A dry build has no directory request; this handle is never handed to xbmcplugin.
DRY_HANDLE = -7
# Longest wait for the stop's own watched mark / resume point threads.
WRITE_WAIT_SEC = 8

_reserved = {'at': 0.0}


def _log(message):
	try:
		from modules.kodi_utils import logger
		logger('Red Light', 'Widget prebuild: %s' % message)
	except Exception:
		pass


def _local_provider():
	try:
		from modules.settings import watched_indicators
		return watched_indicators() == 0
	except Exception:
		return False


def reserve():
	"""At the stop: take the rebuild lock before Home's widget requests can. Cheap, never raises."""
	try:
		from modules import widget_snapshot as snap
		if _reserved['at'] and snap._state.get('locked'): return True
		# Only with Red Light as the watched provider: the others write their marks after
		# network calls, and their widgets keep the old path.
		if not _local_provider(): return False
		if not snap.watch_targets(): return False
		if snap.hold_lock(0):
			_reserved['at'] = time.time()
			return True
	except Exception as error:
		_log('reserve failed: %s' % error)
	return False


def release():
	"""Give the lock back. Safe to call any number of times, from any exit of the player."""
	if not _reserved['at']: return
	_reserved['at'] = 0.0
	try:
		from modules import widget_snapshot as snap
		snap.abandon()
		snap.release_hold()
	except Exception:
		pass


def run(write_threads=()):
	"""After the stop's writes: rebuild the stored watch widgets into their snapshots, then release."""
	if not _reserved['at']: return False
	from modules import widget_snapshot as snap
	from modules import kodi_utils
	started = time.time()
	done = []
	saved_argv, saved_external = sys.argv, kodi_utils.external
	try:
		for thread in write_threads or ():
			try: thread.join(max(0.0, WRITE_WAIT_SEC - (time.time() - started)))
			except Exception: pass
		if any(getattr(t, 'is_alive', lambda: False)() for t in (write_threads or ())):
			_log('skipped: the watched mark was still being written')
			return False
		if snap._playback_busy():
			_log('skipped: the next video is starting')
			return False
		# Only snapshots this stop made out of date: a stop that saved nothing (the first
		# seconds of a video) leaves them fresh, and Home replays them as they are.
		targets = [t for t in snap.watch_targets() if not snap._load(t[0])[1]]
		if not targets: return False
		# Widgets are external requests by definition; the user may already have opened a
		# Red Light menu, which must not change how the widget is drawn.
		kodi_utils.external = lambda: True
		kodi_utils._dry_listing = True
		from indexers.episodes import build_single_episode
		for key, argv0, query, mode in targets:
			if snap._playback_busy(): break
			one = time.time()
			try:
				params = dict(parse_qsl(query[1:] if query.startswith('?') else query, keep_blank_values=True))
				sys.argv = [argv0, str(DRY_HANDLE), query]
				snap.begin(key, [argv0, str(DRY_HANDLE), query], mode)
				build_single_episode(LIST_TYPES[mode], params)
				done.append('%s %.1fs' % (mode, time.time() - one))
			except Exception as error:
				_log('%s failed: %s' % (mode, error))
			finally:
				# A build that ended early leaves nothing half recorded; the lock stays held.
				snap.abandon()
				snap.touch_lock()
		if done:
			snap.mark_prebuilt()
			_log('%s (total %.1fs after the writes)' % (', '.join(done), time.time() - started))
		return bool(done)
	except Exception as error:
		_log('failed: %s' % error)
		return False
	finally:
		sys.argv = saved_argv
		kodi_utils.external = saved_external
		kodi_utils._dry_listing = False
		release()
