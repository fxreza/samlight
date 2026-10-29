# -*- coding: utf-8 -*-
"""Widget snapshots: replay a finished listing instead of rebuilding it.

Kodi asks for every plugin widget on Home again whenever Home opens, playback
starts or playback stops. Each of those requests is a fresh Python interpreter
(reuse of the language invoker crashes Kodi on the Fire TV), and each rebuild
loads the metadata and watched modules and assembles every item from scratch.
On a Fire TV that is 5 to 12 seconds per widget, several at once.

A snapshot records what a listing sent to Kodi (the list items, the content
type, the category and the end-of-directory call) the first time it is built
for a widget, and replays it on the next identical request. A replay needs
only xbmcgui / xbmcplugin and this module, so it costs the interpreter start
and little else.

Snapshots are keyed by the full plugin URL. Every snapshot carries the widget
generation; `invalidate()` bumps it, which makes every snapshot stale at once.
It is called wherever the addon already asks Kodi to refresh (watched marks,
progress saves, list membership changes, settings changes, playback stop), so
a replay never outlives the data it was built from by more than the TTL.
"""
import os
import sys
import time
import pickle
import binascii

import xbmc
import xbmcgui
import xbmcplugin

GENERATION_PROP = 'redlight.widget_generation'
# When the last playback ended (player callback). Widget requests in the seconds after a stop
# replay their last snapshot even if stale, so Home appears at once; one refresh follows.
PLAYBACK_END_AT_PROP = 'redlight.playback_end_at'
# Set when a stale snapshot was replayed: playback_widget_check then refreshes Home once.
REFRESH_NEEDED_PROP = 'redlight.widget_refresh_needed'
# The progress save after a stop lands before the player callback; either one opens the grace.
PLAYBACK_SAVED_AT_PROP = 'redlight.playback_widget_refresh_at'
# Set by an explicit refresh (kodi_refresh): grace timestamps older than this no longer count,
# otherwise the refresh's own widget requests would replay the stale snapshot again.
GRACE_CLOSED_AT_PROP = 'redlight.widget_grace_closed_at'
_STALE_GRACE_SEC = 15
_STALE_MAX_AGE_SEC = 6 * 3600
# Widget rebuilds run one at a time (a lock file in the cache folder): five at once starved
# the user's own navigation on a Fire TV. A rebuild that outlives the stale limit is presumed dead.
_REBUILD_LOCK = 'rebuild.lock'
_LOCK_STALE_SEC = 40
_LOCK_WAIT_MAX_SEC = 90
# A widget that already has a snapshot stops waiting for its turn after this and replays it.
_STALE_FALLBACK_WAIT_SEC = 30
_GENERATION_FILE = 'widget_generation'
_CACHE_DIR = 'widget_cache'
_FORMAT = 2
# Listings that are safe to replay: their contents only change through things
# the addon knows about (watched status, list membership, settings) or with time.
SNAPSHOT_MODES = frozenset((
	'build_movie_list', 'build_tvshow_list', 'build_season_list', 'build_episode_list',
	'build_in_progress_episode', 'build_recently_watched_episode', 'build_next_episode',
	'build_my_calendar', 'build_mdbl_calendar', 'build_punchplay_calendar', 'build_simkl_calendar',
	'build_simkl_public_calendar', 'build_mdbl_next_up',
	'trakt.list.build_trakt_list', 'tmdblist.build_tmdb_list', 'personal_lists.build_personal_list',
	'mdblist.build_mdbl_list', 'simkl.list.build_simkl_list', 'punchplay.list.build_punchplay_list',
))
_NO_SNAPSHOT_PARAMS = ('random', 'shuffle', 'random_support', 'random_continual')
_TAG_GETTERS = ('getVideoInfoTag', 'getMusicInfoTag')

_state = {'key': None, 'ops': [], 'items': 0, 'failed': False, 'locked': False}

def _window():
	return xbmcgui.Window(10000)

def _profile():
	try:
		import xbmcaddon
		import xbmcvfs
		return xbmcvfs.translatePath(xbmcaddon.Addon('plugin.video.redlight').getAddonInfo('profile'))
	except Exception:
		return _window().getProperty('redlight.addon_profile') or ''

def _cache_dir():
	path = os.path.join(_profile(), _CACHE_DIR)
	if not os.path.isdir(path):
		try: os.makedirs(path)
		except Exception: pass
	return path

def _generation_file():
	return os.path.join(_profile(), _GENERATION_FILE)

def _log(message):
	try: xbmc.log('###Red Light###: Widget snapshot: %s' % message, xbmc.LOGINFO)
	except Exception: pass

def ttl_seconds():
	"""How long a replayed widget may lag behind data the addon does not see change (new airings)."""
	try:
		from caches.settings_cache import get_setting
		minutes = int(get_setting('redlight.widget_snapshot_minutes', '20') or 20)
	except Exception:
		minutes = 20
	return max(60, minutes * 60)

def current_generation():
	"""The generation lives in a window property while Kodi runs and in a file across restarts."""
	window = _window()
	value = window.getProperty(GENERATION_PROP)
	if value: return value
	try:
		with open(_generation_file(), 'r') as handle: value = handle.read().strip()
	except Exception:
		value = ''
	if not value: value = '1'
	try: window.setProperty(GENERATION_PROP, value)
	except Exception: pass
	return value

def invalidate(reason=''):
	"""Make every snapshot stale. Cheap: one property write and one tiny file write."""
	try:
		new_value = str(int(current_generation()) + 1)
	except Exception:
		new_value = str(int(time.time()))
	try: _window().setProperty(GENERATION_PROP, new_value)
	except Exception: pass
	try:
		with open(_generation_file(), 'w') as handle: handle.write(new_value)
	except Exception: pass
	if reason: _log('invalidated (%s)' % reason)

def note_playback_end():
	try: _window().setProperty(PLAYBACK_END_AT_PROP, str(time.time()))
	except Exception: pass

def clear_playback_end_grace():
	try:
		_window().clearProperty(PLAYBACK_END_AT_PROP)
		_window().setProperty(GRACE_CLOSED_AT_PROP, str(time.time()))
	except Exception: pass

def refresh_needed():
	return _window().getProperty(REFRESH_NEEDED_PROP) == 'true'

def clear_refresh_needed():
	try: _window().clearProperty(REFRESH_NEEDED_PROP)
	except Exception: pass

def _stale_replay_allowed():
	"""A stale snapshot may stand in while a video plays (Home is not visible, and a rebuild
	would steal the CPU from the video) and in the first seconds after a playback end (Home
	is being drawn; the refresh scheduled by the progress save rebuilds it right after)."""
	try:
		if xbmc.Player().isPlayingVideo(): return True
	except Exception:
		pass
	window, now = _window(), time.time()
	try: closed = float(window.getProperty(GRACE_CLOSED_AT_PROP) or 0)
	except Exception: closed = 0
	for prop in (PLAYBACK_END_AT_PROP, PLAYBACK_SAVED_AT_PROP):
		try:
			at = float(window.getProperty(prop) or 0)
			if at > closed and 0 <= now - at < _STALE_GRACE_SEC: return True
		except Exception:
			pass
	return False

def user_inside_addon():
	"""The user is browsing a Red Light list: background widget rebuilds must not compete."""
	try: return 'plugin.video.redlight' in xbmc.getInfoLabel('Container.PluginName')
	except Exception: return False

def _lock_path():
	return os.path.join(_cache_dir(), _REBUILD_LOCK)

def _try_lock():
	path = _lock_path()
	for _ in range(2):
		try:
			fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
			os.write(fd, str(time.time()).encode('utf-8'))
			os.close(fd)
			_state['locked'] = True
			return True
		except FileExistsError:
			try:
				if time.time() - os.path.getmtime(path) > _LOCK_STALE_SEC:
					os.remove(path)
					continue
			except Exception:
				pass
			return False
		except Exception:
			# Cannot lock at all (read-only profile?): never block a build on it.
			return True
	return False

def _release_lock():
	if not _state.get('locked'): return
	_state['locked'] = False
	try: os.remove(_lock_path())
	except Exception: pass

def _wait_for_rebuild_turn(key, have_snapshot):
	"""Returns 'locked' (build now), 'fresh' (a sibling just built this widget: replay it),
	'stale' (replay the old snapshot, the rebuild waits for a later Home visit) or 'nolock'."""
	if have_snapshot and user_inside_addon(): return 'stale'
	started = time.time()
	while True:
		if _try_lock(): return 'locked'
		data, fresh = _load(key)
		if data and fresh: return 'fresh'
		waited = time.time() - started
		if have_snapshot and (user_inside_addon() or waited > _STALE_FALLBACK_WAIT_SEC): return 'stale'
		if waited > _LOCK_WAIT_MAX_SEC: return 'nolock'
		xbmc.sleep(250)

def is_widget_request(argv):
	"""A directory request from outside the addon: a Home widget, or the first step in from Home."""
	try:
		if int(argv[1]) < 0: return False
	except Exception:
		return False
	return 'plugin.video.redlight' not in xbmc.getInfoLabel('Container.PluginName')

def eligible(mode, params):
	if mode not in SNAPSHOT_MODES: return False
	for name in _NO_SNAPSHOT_PARAMS:
		if str(params.get(name, 'false')).lower() == 'true': return False
	return True

def make_key(argv):
	# crc32 plus length: cheap (no hashlib / OpenSSL import) and ample for a handful of widget URLs.
	raw = ('%s%s|%s' % (argv[0], argv[2], _profile())).encode('utf-8')
	return '%08x%x' % (binascii.crc32(raw) & 0xffffffff, len(raw))

def _path(key):
	return os.path.join(_cache_dir(), '%s.pkl' % key)

def _addon_version():
	try:
		import xbmcaddon
		return xbmcaddon.Addon('plugin.video.redlight').getAddonInfo('version')
	except Exception:
		return _window().getProperty('redlight.addon_version') or ''

# ---------------------------------------------------------------- recording

def recording():
	return _state['key'] is not None and not _state['failed']

def begin(key):
	_state['key'], _state['ops'], _state['items'], _state['failed'] = key, [], 0, False
	try: _window().clearProperty(REFRESH_NEEDED_PROP)
	except Exception: pass

def abandon():
	_state['key'], _state['ops'], _state['items'], _state['failed'] = None, [], 0, False
	_release_lock()

def _plain(value):
	"""Make call arguments picklable. xbmc.Actor objects become tagged tuples."""
	if isinstance(value, (str, int, float, bool)) or value is None: return value
	if isinstance(value, list): return [_plain(v) for v in value]
	if isinstance(value, tuple): return tuple(_plain(v) for v in value)
	if isinstance(value, dict): return {str(k): _plain(v) for k, v in value.items()}
	if type(value).__name__ == 'Actor':
		return ('__actor__', value.getName(), value.getRole(), value.getOrder(), value.getThumbnail())
	raise TypeError('not snapshot safe: %r' % type(value))

def _restore(value):
	if isinstance(value, tuple):
		if len(value) == 5 and value[0] == '__actor__':
			return xbmc.Actor(name=value[1], role=value[2], order=value[3], thumbnail=value[4])
		return tuple(_restore(v) for v in value)
	if isinstance(value, list): return [_restore(v) for v in value]
	if isinstance(value, dict): return {k: _restore(v) for k, v in value.items()}
	return value

class Recorder(object):
	"""Wraps a ListItem (or its info tag) and notes every setter call it forwards."""
	__slots__ = ('_real', '_ops')

	def __init__(self, real, ops):
		object.__setattr__(self, '_real', real)
		object.__setattr__(self, '_ops', ops)

	def __getattr__(self, name):
		attr = getattr(self._real, name)
		if not callable(attr): return attr
		if name in _TAG_GETTERS:
			def tag_getter(*args, **kwargs):
				tag = attr(*args, **kwargs)
				sub = []
				try: self._ops.append((name, _plain(args), _plain(kwargs), sub))
				except Exception: _state['failed'] = True
				return Recorder(tag, sub)
			return tag_getter
		if name.startswith('set') or name.startswith('add'):
			def setter(*args, **kwargs):
				result = attr(*args, **kwargs)
				try: self._ops.append((name, _plain(args), _plain(kwargs)))
				except Exception: _state['failed'] = True
				return result
			return setter
		return attr

def unwrap(listitem):
	return listitem._real if isinstance(listitem, Recorder) else listitem

def new_listitem(offscreen=True):
	real = xbmcgui.ListItem(offscreen=offscreen)
	if not recording(): return real
	ops = [('__new__', offscreen)]
	return Recorder(real, ops)

def record_items(item_list):
	if not recording(): return
	recorded = []
	for url, listitem, is_folder in item_list:
		if not isinstance(listitem, Recorder):
			_state['failed'] = True
			return
		recorded.append((url, listitem._ops, bool(is_folder)))
	_state['ops'].append(('items', recorded))
	_state['items'] += len(recorded)

def record_content(content):
	if recording(): _state['ops'].append(('content', content))

def record_category(label):
	if recording(): _state['ops'].append(('category', label))

def record_sort_method(method, label_mask):
	if recording(): _state['ops'].append(('sort', method, label_mask))

def record_end(update_listing, cache_to_disc):
	if not recording(): return
	_state['ops'].append(('end', bool(update_listing), bool(cache_to_disc)))
	key, ops, count = _state['key'], _state['ops'], _state['items']
	if count > 0:
		data = {'format': _FORMAT, 'key': key, 'generation': current_generation(), 'time': time.time(),
				'version': _addon_version(), 'ops': ops}
		try:
			payload = pickle.dumps(data, protocol=2)
			path = _path(key)
			tmp = '%s.%s.tmp' % (path, os.getpid())
			with open(tmp, 'wb') as handle: handle.write(payload)
			os.replace(tmp, path)
		except Exception as error:
			_log('store failed: %s' % error)
	# Stored first, released second: a sibling waiting for its turn then replays this snapshot.
	abandon()

# ------------------------------------------------------------------ replay

def _load(key):
	"""Returns (data, fresh). data is None when there is nothing usable at all."""
	path = _path(key)
	try:
		if not os.path.isfile(path): return None, False
		with open(path, 'rb') as handle: data = pickle.load(handle)
	except Exception:
		try: os.remove(path)
		except Exception: pass
		return None, False
	if not isinstance(data, dict) or data.get('format') != _FORMAT or data.get('key') != key: return None, False
	if data.get('version') != _addon_version(): return None, False
	age = time.time() - float(data.get('time', 0))
	if age > _STALE_MAX_AGE_SEC: return None, False
	fresh = data.get('generation') == current_generation() and age <= ttl_seconds()
	return data, fresh

def _build(ops):
	offscreen = True
	if ops and ops[0][0] == '__new__': offscreen = bool(ops[0][1])
	listitem = xbmcgui.ListItem(offscreen=offscreen)
	_apply(listitem, ops)
	return listitem

def _apply(target, ops):
	for op in ops:
		name = op[0]
		if name == '__new__': continue
		if name in _TAG_GETTERS:
			tag = getattr(target, name)(*_restore(op[1]), **_restore(op[2]))
			_apply(tag, op[3])
			continue
		try: getattr(target, name)(*_restore(op[1]), **_restore(op[2]))
		except Exception: pass

def replay(handle, key, allow_stale=False):
	"""Send a stored listing to Kodi. Returns 'fresh', 'stale' or False (nothing to replay)."""
	data, fresh = _load(key)
	if not data: return False
	if not fresh:
		if not allow_stale: return False
		try: _window().setProperty(REFRESH_NEEDED_PROP, 'true')
		except Exception: pass
	sort_methods = {'episodes': 24, 'files': 5, 'label': 2, 'none': 0}
	try:
		for op in data['ops']:
			kind = op[0]
			if kind == 'items':
				xbmcplugin.addDirectoryItems(handle, [(url, _build(ops), folder) for url, ops, folder in op[1]])
			elif kind == 'content': xbmcplugin.setContent(handle, op[1])
			elif kind == 'category': xbmcplugin.setPluginCategory(handle, op[1])
			elif kind == 'sort': xbmcplugin.addSortMethod(handle, sort_methods.get(op[1], 0), labelMask=op[2])
			elif kind == 'end': xbmcplugin.endOfDirectory(handle, updateListing=op[1], cacheToDisc=op[2])
	except Exception as error:
		_log('replay failed, rebuilding: %s' % error)
		try: os.remove(_path(key))
		except Exception: pass
		return False
	return 'fresh' if fresh else 'stale'

def try_replay(argv, mode, params):
	"""Entry point for the router: True when the request was answered from a snapshot."""
	try:
		if not is_widget_request(argv) or not eligible(mode, params): return False
		key = make_key(argv)
		handle = int(argv[1])
		outcome = replay(handle, key, allow_stale=_stale_replay_allowed() or user_inside_addon())
		if outcome:
			_log('replayed %s%s' % (mode, '' if outcome == 'fresh' else ' (stale, refresh follows)'))
			return True
		data, fresh = _load(key)
		turn = _wait_for_rebuild_turn(key, data is not None)
		if turn in ('fresh', 'stale'):
			outcome = replay(handle, key, allow_stale=True)
			if outcome:
				_log('replayed %s after waiting (%s)' % (mode, 'a sibling rebuilt it' if outcome == 'fresh' else 'stale, refresh follows'))
				return True
		begin(key)
		if turn == 'locked': _state['locked'] = True
	except Exception as error:
		_log('skipped: %s' % error)
		abandon()
	return False

def clear_all():
	"""Remove stored snapshots (cache clearing)."""
	try:
		folder = _cache_dir()
		for name in os.listdir(folder):
			if name.endswith('.pkl') or name == _REBUILD_LOCK:
				try: os.remove(os.path.join(folder, name))
				except Exception: pass
	except Exception: pass
	invalidate('cleared')
