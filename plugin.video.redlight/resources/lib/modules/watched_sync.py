# -*- coding: utf-8 -*-
"""Shared watched status between devices, through the cloud backup GitHub repository.

One file, watched-sync.json.gz, holds the watched marks (movies and episodes), the
resume points and the dropped shows of every device. Each entry carries the time it was
last changed, and the newest change wins, so a mark on the Mac and an unmark on the
Fire Stick resolve the same way on both. A resume point is recorded when playback
stops (never while it plays), so the file only changes once per stop.

Only the local provider ("Red Light") takes part. Trakt, Simkl, MDBList and PunchPlay
already share their status through their own servers.

Changes are appended to a pending file as they happen (one JSON line each, append-only,
so the plugin process and the service never fight over a read-modify-write). The
service sends them a few seconds after the last change (and after playback has
stopped), and asks GitHub whether another device changed the file: once a minute while
nothing plays, every 10 seconds for two minutes after the remote is picked up again,
45 seconds after Kodi starts and a few seconds after every wake. Asking costs one small
request; the file is only downloaded when its hash changed.

Every entry: [state, time, title] where state is 1 (watched / dropped / has a resume
point) or 0 (unwatched / undropped / resume point cleared), time is unix seconds.
Resume entries carry two more fields: [state, time, title, resume_percent, seconds].
Keys: m:<tmdb>, e:<tmdb>:<season>:<episode>, d:<tmdb>, p:m:<tmdb>,
p:e:<tmdb>:<season>:<episode>. Older versions keep p: entries untouched and ignore them.
"""

import calendar
import gzip
import json
import os
import time

# Gzipped JSON: a 24,000-entry history is about 1 MB plain and a few hundred KB
# compressed, which keeps every pull one small request.
SYNC_FILE = 'watched-sync.json.gz'
# The plain file 2.11.0 wrote. Read and merged while it exists, so a device still on
# that version is not cut off; deleted once nothing has touched it for a week.
LEGACY_FILE = 'watched-sync.json'
LEGACY_STALE_DAYS = 7
PENDING_NAME = 'watched_sync.pending'
PROCESSING_NAME = 'watched_sync.processing'
STATE_NAME = 'watched_sync.json'
# Copy of the shared file from the last sync: stands in for a download when GitHub
# says the file has not changed since.
CACHE_NAME = 'watched_sync.cache'
HIDDEN_KEY = 'hidden_progress_items'
RUNNING_PROP = 'redlight.watched_sync_running'
# A tombstone (unwatched / undropped) this old no longer protects anything: every
# device has long since applied it. Dropping it keeps the file small.
TOMBSTONE_DAYS = 180
# Seconds the pending file must sit untouched before it is sent: the watched mark and
# the resume point of one stop, or a few marks in a row, make one push.
SETTLE_SECONDS = 5
# Pending older than this goes regardless of whether the user is idle.
FORCE_AFTER_SECONDS = 600
LAST_PLAYED_FORMAT = '%Y-%m-%d %H:%M:%S'


# ---------------------------------------------------------------- settings / paths

def _profile():
	from modules import kodi_utils
	return kodi_utils.translate_path(kodi_utils.addon_profile())

def _path(name):
	return os.path.join(_profile(), name)

def _config():
	from caches.settings_cache import get_setting
	repository = get_setting('redlight.cloud_backup.repository', 'empty_setting') or ''
	if repository == 'empty_setting': repository = ''
	owner, _sep, repo = repository.strip().strip('/').partition('/')
	token = get_setting('redlight.cloud_backup.token', 'empty_setting') or ''
	if token == 'empty_setting': token = ''
	return {'enabled': get_setting('redlight.watched_sync.enabled', 'true') == 'true',
			'token': token.strip(), 'owner': owner.strip(), 'repo': repo.strip()}

def _configured(cfg):
	return cfg['enabled'] and cfg['token'] and cfg['owner'] and cfg['repo']

def _local_provider():
	try:
		from modules.settings import watched_indicators
		return watched_indicators() == 0
	except Exception:
		return False

def enabled():
	return _configured(_config()) and _local_provider()

def _device_name():
	try:
		from modules import kodi_utils
		return kodi_utils.get_infolabel('System.FriendlyName') or 'kodi'
	except Exception:
		return 'kodi'


# ---------------------------------------------------------------- keys

def movie_key(tmdb_id):
	return 'm:%s' % tmdb_id

def episode_key(tmdb_id, season, episode):
	return 'e:%s:%s:%s' % (tmdb_id, int(season), int(episode))

def dropped_key(tmdb_id):
	return 'd:%s' % tmdb_id

def progress_key(media_type, tmdb_id, season='', episode=''):
	if media_type == 'movie': return 'p:m:%s' % tmdb_id
	return 'p:e:%s:%s:%s' % (tmdb_id, int(season), int(episode))

def _watched_key_for_progress(key):
	"""p:m:1 -> m:1, p:e:1:2:3 -> e:1:2:3"""
	return key[2:]

def _last_played_to_epoch(value):
	try: return int(time.mktime(time.strptime(str(value)[:19], LAST_PLAYED_FORMAT)))
	except Exception: return 0

def _epoch_to_last_played(stamp):
	try: return time.strftime(LAST_PLAYED_FORMAT, time.localtime(int(stamp)))
	except Exception: return time.strftime(LAST_PLAYED_FORMAT)


# ---------------------------------------------------------------- pending log (any process)

def _append_pending(entries):
	"""entries: iterable of (key, state, title[, extra list]). One JSON line each, appended."""
	if not entries: return
	now = int(time.time())
	lines = ''.join('%s\n' % json.dumps([entry[0], int(entry[1]), now, entry[2] or ''] + list(entry[3] if len(entry) > 3 else []),
				ensure_ascii=False) for entry in entries)
	try:
		with open(_path(PENDING_NAME), 'a', encoding='utf-8') as fh:
			fh.write(lines)
	except Exception as e:
		try:
			from modules.kodi_utils import logger
			logger('Watched Sync', 'could not queue change: %s' % e)
		except Exception: pass

def record_mark(media_type, media_id, action, season='', episode='', title=''):
	"""Called by watched_status_mark for the local provider. Never raises."""
	try:
		if not _configured(_config()): return
		state = 1 if action == 'mark_as_watched' else 0
		if media_type == 'movie': key = movie_key(media_id)
		elif media_type == 'episode': key = episode_key(media_id, season, episode)
		else: return
		_append_pending([(key, state, title)])
	except Exception: pass

def record_batch(insert_list, action):
	"""Called by batch_watched_status_mark. Rows are (media_type, media_id, season, episode[, last_played, title])."""
	try:
		if not _configured(_config()) or not insert_list: return
		state = 1 if action == 'mark_as_watched' else 0
		entries = []
		for row in insert_list:
			media_type, media_id, season, episode = row[0], row[1], row[2], row[3]
			title = row[5] if len(row) > 5 else ''
			if media_type == 'movie': entries.append((movie_key(media_id), state, title))
			elif media_type == 'episode': entries.append((episode_key(media_id, season, episode), state, title))
		_append_pending(entries)
	except Exception: pass

def record_drop(media_id, dropped):
	try:
		if not _configured(_config()): return
		_append_pending([(dropped_key(int(media_id)), 1 if dropped else 0, '')])
	except Exception: pass

def record_progress(media_type, media_id, season, episode, resume_point, curr_time, title=''):
	"""A resume point written when playback stopped. Never raises."""
	try:
		if not _configured(_config()): return
		if media_type not in ('movie', 'episode'): return
		key = progress_key(media_type, media_id, season, episode)
		_append_pending([(key, 1, title, [str(resume_point), str(curr_time)])])
	except Exception: pass

def record_progress_cleared(rows):
	"""rows: (media_type, media_id, season, episode) whose resume point was just removed. Never raises."""
	try:
		if not rows or not _configured(_config()): return
		entries = []
		for media_type, media_id, season, episode in rows:
			try: entries.append((progress_key(media_type, media_id, season, episode), 0, ''))
			except Exception: continue
		_append_pending(entries)
	except Exception: pass

def pending_age():
	"""Seconds since the pending file was last written, or None when there is nothing pending."""
	try:
		path = _path(PENDING_NAME)
		if os.path.isfile(path) and os.path.getsize(path) > 0:
			return max(0, time.time() - os.path.getmtime(path))
		if os.path.isfile(_path(PROCESSING_NAME)) and os.path.getsize(_path(PROCESSING_NAME)) > 0:
			return FORCE_AFTER_SECONDS
	except Exception: pass
	return None

def _take_pending():
	"""Move pending lines into the processing file (ours alone) and return them as {key: [state, t, title]}."""
	processing, pending = _path(PROCESSING_NAME), _path(PENDING_NAME)
	try:
		if os.path.isfile(pending) and os.path.getsize(pending) > 0:
			tmp = pending + '.tmp'
			if os.path.isfile(tmp): os.remove(tmp)
			os.rename(pending, tmp)
			with open(tmp, 'r', encoding='utf-8') as src, open(processing, 'a', encoding='utf-8') as dst:
				dst.write(src.read())
			os.remove(tmp)
	except Exception as e:
		from modules.kodi_utils import logger
		logger('Watched Sync', 'pending hand-off failed: %s' % e)
	changes = {}
	if not os.path.isfile(processing): return changes
	try:
		with open(processing, 'r', encoding='utf-8') as fh:
			for line in fh:
				line = line.strip()
				if not line: continue
				try:
					row = json.loads(line)
					key, state, stamp, title, extra = row[0], row[1], row[2], row[3], row[4:]
				except Exception: continue
				previous = changes.get(key)
				if previous is None or stamp >= previous[1]:
					changes[key] = [int(state), int(stamp), title or (previous[2] if previous else '')] + list(extra)
	except Exception: pass
	return changes

def _clear_processing():
	try: os.remove(_path(PROCESSING_NAME))
	except Exception: pass


# ---------------------------------------------------------------- local state

def _read_state():
	try:
		with open(_path(STATE_NAME), 'r', encoding='utf-8') as fh:
			data = json.load(fh)
		if isinstance(data, dict): return data
	except Exception: pass
	return {}

def _write_state(state):
	try:
		path = _path(STATE_NAME)
		with open(path + '.tmp', 'w', encoding='utf-8') as fh:
			json.dump(state, fh)
		os.replace(path + '.tmp', path)
	except Exception: pass

def last_run():
	try: return int(_read_state().get('last_run') or 0)
	except Exception: return 0

def retry_after():
	try: return int(_read_state().get('retry_after') or 0)
	except Exception: return 0


# ---------------------------------------------------------------- shared file format

def _empty_remote():
	return {'v': 1, 'items': {}}

def _parse_remote(raw):
	"""Plain or gzipped JSON; anything unreadable counts as empty."""
	if not raw: return _empty_remote()
	try:
		if isinstance(raw, bytes) and raw[:2] == b'\x1f\x8b': raw = gzip.decompress(raw)
		data = json.loads(raw.decode('utf-8') if isinstance(raw, bytes) else raw)
		if isinstance(data, dict) and isinstance(data.get('items'), dict): return data
	except Exception: pass
	return _empty_remote()

def _serialize(data):
	plain = json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
	# mtime=0 so the same content always gives the same bytes.
	# Level 6: a fraction of level 9's time on a Fire TV for a file a few percent larger.
	return gzip.compress(plain, compresslevel=6, mtime=0)

def _updated_epoch(data):
	try: return calendar.timegm(time.strptime(data.get('updated', '')[:19], '%Y-%m-%dT%H:%M:%S'))
	except Exception: return 0


# ---------------------------------------------------------------- merge (pure)

def _local_snapshot(dbcon):
	"""What this device's database says, as {key: [1, t, title]}, plus the dropped list."""
	items = {}
	for db_type, media_id, season, episode, last_played, title in dbcon.execute(
			'SELECT db_type, media_id, season, episode, last_played, title FROM watched').fetchall():
		stamp = _last_played_to_epoch(last_played)
		if db_type == 'movie': items[movie_key(media_id)] = [1, stamp, title or '']
		elif db_type == 'episode':
			try: items[episode_key(media_id, season, episode)] = [1, stamp, title or '']
			except Exception: continue
	dropped = _read_hidden(dbcon)
	for media_id in dropped: items[dropped_key(media_id)] = [1, 0, '']
	try:
		rows = dbcon.execute('SELECT db_type, media_id, season, episode, resume_point, curr_time, last_played, title FROM progress '
							'WHERE CAST(resume_point AS FLOAT) > 1').fetchall()
	except Exception: rows = []
	for db_type, media_id, season, episode, resume_point, curr_time, last_played, title in rows:
		try: key = progress_key(db_type, media_id, season, episode)
		except Exception: continue
		items[key] = [1, _last_played_to_epoch(last_played), title or '', str(resume_point), str(curr_time)]
	return items, dropped

def _read_hidden(dbcon):
	"""The dropped list is stored as repr() of a python list of ints, e.g. '[1396, 4607]'."""
	try:
		row = dbcon.execute('SELECT status FROM watched_status WHERE db_type = ?', (HIDDEN_KEY,)).fetchone()
	except Exception: return []
	if not row or not row[0]: return []
	try: return [int(i) for i in json.loads(row[0].replace("'", '"'))]
	except Exception:
		try: return [int(i) for i in eval(row[0])]
		except Exception: return []

def merge(remote_items, pending, local_items, now=None):
	"""Newest change per key wins. Local rows the shared file has never seen are added as
	watched / dropped with the time they were played. Returns the merged dict."""
	now = int(now or time.time())
	merged = dict((k, list(v)) for k, v in remote_items.items() if isinstance(v, list) and len(v) >= 2)
	for key, entry in pending.items():
		current = merged.get(key)
		if current is None or entry[1] >= current[1]:
			title = entry[2] or (current[2] if current and len(current) > 2 else '')
			merged[key] = [int(entry[0]), int(entry[1]), title] + list(entry[3:])
	for key, entry in local_items.items():
		current = merged.get(key)
		if current is None: merged[key] = list(entry)
		# A resume point this device saved after the shared one (a stop whose record was
		# lost) is the newer one.
		elif key.startswith('p:') and entry[1] > current[1]: merged[key] = list(entry)
	cutoff = now - TOMBSTONE_DAYS * 86400
	for key in [k for k, v in merged.items() if v[0] == 0 and v[1] < cutoff]:
		del merged[key]
	return merged

def _apply(dbcon, merged, local_items, local_dropped):
	"""Bring the database in line with the merged picture. Returns how many rows changed."""
	changed = 0
	for key, entry in merged.items():
		state = entry[0]
		stamp = entry[1]
		title = entry[2] if len(entry) > 2 else ''
		have = key in local_items
		if key.startswith('m:'):
			media_id = key[2:]
			if state == 1 and not have:
				dbcon.execute('INSERT OR IGNORE INTO watched VALUES (?, ?, ?, ?, ?, ?)',
							('movie', media_id, '', '', _epoch_to_last_played(stamp), title))
				dbcon.execute('DELETE FROM progress WHERE db_type = ? AND media_id = ?', ('movie', media_id))
				changed += 1
			elif state == 0 and have:
				dbcon.execute('DELETE FROM watched WHERE db_type = ? AND media_id = ?', ('movie', media_id))
				changed += 1
		elif key.startswith('e:'):
			try: media_id, season, episode = key[2:].split(':')
			except ValueError: continue
			season, episode = int(season), int(episode)
			if state == 1 and not have:
				dbcon.execute('INSERT OR IGNORE INTO watched VALUES (?, ?, ?, ?, ?, ?)',
							('episode', media_id, season, episode, _epoch_to_last_played(stamp), title))
				dbcon.execute('DELETE FROM progress WHERE db_type = ? AND media_id = ? AND season = ? AND episode = ?',
							('episode', media_id, season, episode))
				changed += 1
			elif state == 0 and have:
				dbcon.execute('DELETE FROM watched WHERE db_type = ? AND media_id = ? AND season = ? AND episode = ?',
							('episode', media_id, season, episode))
				changed += 1
		elif key.startswith('p:'):
			changed += _apply_progress(dbcon, key, entry, merged, local_items)
	dropped = sorted(int(k[2:]) for k, v in merged.items() if k.startswith('d:') and v[0] == 1)
	if dropped != sorted(local_dropped):
		dbcon.execute('INSERT OR REPLACE INTO watched_status VALUES (?, ?, ?)', (HIDDEN_KEY, 'hidden', repr(dropped)))
		changed += 1
	return changed


def _apply_progress(dbcon, key, entry, merged, local_items):
	parts = key.split(':')
	if parts[1] == 'm' and len(parts) == 3: media_type, media_id, season, episode = 'movie', parts[2], '', ''
	elif parts[1] == 'e' and len(parts) == 5:
		try: media_type, media_id, season, episode = 'episode', parts[2], int(parts[3]), int(parts[4])
		except ValueError: return 0
	else: return 0
	state, stamp = entry[0], entry[1]
	local = local_items.get(key)
	if state == 0:
		if not local: return 0
		dbcon.execute('DELETE FROM progress WHERE db_type = ? AND media_id = ? AND season = ? AND episode = ?', (media_type, media_id, season, episode))
		return 1
	if len(entry) < 5: return 0
	# Watched after this resume point was saved (a device on an older version does not
	# clear the resume point when it marks): the resume point no longer counts.
	watched = merged.get(_watched_key_for_progress(key))
	if watched and watched[0] == 1 and watched[1] >= stamp: return 0
	resume_point, curr_time = str(entry[3]), str(entry[4])
	if local and local[3] == resume_point and local[4] == curr_time: return 0
	if local and local[1] > stamp: return 0
	title = entry[2] if len(entry) > 2 else ''
	dbcon.execute('INSERT OR REPLACE INTO progress VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
				(media_type, media_id, season, episode, resume_point, curr_time, _epoch_to_last_played(stamp), 0, title))
	return 1


# ---------------------------------------------------------------- the sync itself

# After a failure (offline, bad token) wait this long before trying again, so a
# dead connection does not mean a request every tick.
RETRY_SECONDS = 120
# An unchanged check writes the state file, the status line and the log at most this often.
QUIET_WRITE_SECONDS = 600
# When the last check ran, in this Kodi session (the state file is not written for every check).
LAST_CHECK_PROP = 'redlight.watched_sync_last_check'

def last_check():
	"""Time of the most recent sync or check, from this session or, failing that, the state file."""
	try:
		from modules import kodi_utils
		value = float(kodi_utils.get_property(LAST_CHECK_PROP) or 0)
	except Exception: value = 0
	return max(value, last_run())

def _fail(code, message):
	from modules import kodi_utils
	from caches.settings_cache import set_setting
	set_setting('watched_sync.last_status', '[COLOR red]Failed %s - %s[/COLOR]' % (time.strftime('%d %b %H:%M'), message))
	kodi_utils.logger('Watched Sync', 'failed (%s): %s' % (code, message))
	state = _read_state()
	state['retry_after'] = int(time.time()) + RETRY_SECONDS
	_write_state(state)
	return code, message

def _read_cache():
	try:
		with open(_path(CACHE_NAME), 'rb') as fh: return fh.read()
	except Exception: return None

def _write_cache(data):
	try:
		path = _path(CACHE_NAME)
		with open(path + '.tmp', 'wb') as fh: fh.write(data)
		os.replace(path + '.tmp', path)
	except Exception: pass

def _changed_check(gh, cfg, state):
	"""One small request: the repository's file list with each file's hash. Returns
	(known, gz_sha, legacy_sha, gz_unchanged, legacy_unchanged). known is False when the
	listing could not be read, in which case the caller downloads as usual."""
	ok, listing = gh.list_contents(cfg)
	if not ok: return False, None, None, False, False
	gz_sha, legacy_sha = listing.get(SYNC_FILE), listing.get(LEGACY_FILE)
	gz_unchanged = bool(gz_sha) and gz_sha == state.get('sha') and _read_cache() is not None
	legacy_unchanged = legacy_sha == state.get('legacy_sha')
	return True, gz_sha, legacy_sha, gz_unchanged, legacy_unchanged

def run_sync(silent=True, reason='timer'):
	"""Pull, merge, apply, push. Dialog-free. Returns (status, message). Never raises.

	The pull starts with the repository's file list, which carries every file's hash.
	When the shared file's hash is the one from our last sync and nothing is pending,
	there is nothing to do and nothing is downloaded. When something is pending but the
	hash is unchanged, the copy kept from the last sync stands in for the download."""
	from modules import kodi_utils
	from caches.settings_cache import set_setting
	from caches.base_cache import connect_database
	from apis import github_backup_api as gh
	cfg = _config()
	if not _configured(cfg): return 'disabled', 'Watched sync is not configured.'
	if not _local_provider(): return 'disabled', 'Watched Status Provider is not Red Light.'
	running = kodi_utils.get_property(RUNNING_PROP)
	try:
		if running and time.time() - float(running) < 300: return 'busy', 'A sync is already running.'
	except Exception: pass
	kodi_utils.set_property(RUNNING_PROP, str(time.time()))
	dbcon = None
	try:
		pending = _take_pending()
		state = _read_state()
		pulled = pushed = 0
		unchanged = False
		for attempt in (1, 2):
			known, gz_sha, legacy_sha, gz_unchanged, legacy_unchanged = _changed_check(gh, cfg, state) if attempt == 1 else (False, None, None, False, False)
			if known and gz_unchanged and legacy_unchanged and not pending:
				message, unchanged = 'Nothing changed anywhere.', True
				break
			# Only opened once there is something to merge: the frequent checks stay one request.
			if dbcon is None: dbcon = connect_database('watched_db')
			if known and gz_unchanged:
				remote = {'sha': gz_sha, 'data': _read_cache()}
			else:
				ok, remote = gh.get_contents(cfg, SYNC_FILE)
				if not ok: return _fail(remote['code'], remote['message'])
			remote_data = _parse_remote(remote['data'])
			remote_items = remote_data.get('items') or {}
			base_items = remote_items
			# A device still on 2.11.0 writes the plain file. Its changes count like our own
			# pending ones: newest wins, and they are carried into the compressed file by
			# the push below. Once nobody has written it for a week it goes.
			legacy_present = legacy_sha if known else True
			if legacy_present and not (known and legacy_unchanged):
				ok, legacy = gh.get_contents(cfg, LEGACY_FILE)
				if ok and legacy.get('data'):
					legacy_data = _parse_remote(legacy['data'])
					base_items = merge(remote_items, legacy_data.get('items') or {}, {})
					state['legacy_sha'], state['legacy_updated'] = legacy.get('sha'), _updated_epoch(legacy_data)
				else:
					state['legacy_sha'], state['legacy_updated'] = None, 0
			if legacy_present and state.get('legacy_sha') and time.time() - (state.get('legacy_updated') or 0) > LEGACY_STALE_DAYS * 86400:
				ok, _result = gh.delete_contents(cfg, LEGACY_FILE, 'Watched sync: remove the uncompressed file', state['legacy_sha'])
				if ok: state['legacy_sha'], state['legacy_updated'] = None, 0
			local_items, local_dropped = _local_snapshot(dbcon)
			merged = merge(base_items, pending, local_items)
			pulled = _apply(dbcon, merged, local_items, local_dropped)
			pushed = sum(1 for k, v in merged.items() if remote_items.get(k) != v)
			if merged != remote_items:
				payload = {'v': 1, 'items': merged, 'updated': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'by': _device_name()}
				blob = _serialize(payload)
				ok, result = gh.put_contents(cfg, SYNC_FILE, blob, 'Watched sync from %s' % _device_name(), sha=remote.get('sha'))
				if not ok:
					if result['code'] in ('conflict', 'invalid_repo') and attempt == 1:
						# Another device pushed between our pull and our push: pull again and redo.
						continue
					return _fail(result['code'], result['message'])
				state['sha'] = result
				_write_cache(blob)
			else:
				state['sha'] = remote.get('sha')
				if remote.get('data'): _write_cache(remote['data'])
			message = 'Applied %s change%s from other devices, sent %s.' % (pulled, '' if pulled == 1 else 's', pushed)
			break
		_clear_processing()
		now = int(time.time())
		# A check that found nothing runs every minute or so: the state file, the status
		# setting and the log are only touched every few minutes for those.
		quiet = unchanged and not state.get('retry_after') and now - int(state.get('last_run') or 0) < QUIET_WRITE_SECONDS
		kodi_utils.set_property(LAST_CHECK_PROP, str(now))
		if quiet: return 'unchanged', message
		state.update({'last_run': now, 'retry_after': 0})
		_write_state(state)
		set_setting('watched_sync.last_status', 'OK %s' % time.strftime('%d %b %H:%M'))
		kodi_utils.logger('Watched Sync', '%s (%s)' % (message, reason))
		if pulled and reason != 'manual': kodi_utils.kodi_refresh()
		return 'success', message
	except Exception as e:
		return _fail('error', str(e))
	finally:
		try: dbcon.close()
		except Exception: pass
		kodi_utils.clear_property(RUNNING_PROP)


# ---------------------------------------------------------------- service and menu entry points

# Seconds between checks for other devices' changes while nothing plays.
CHECK_SECONDS = 60

def sync_due(now=None, check_every=CHECK_SECONDS):
	"""What the service asks every tick. Returns a reason string, or None."""
	now = now or time.time()
	if not enabled(): return None
	if now < retry_after(): return None
	age = pending_age()
	if age is not None and age >= SETTLE_SECONDS: return 'pending'
	if now - last_check() >= check_every: return 'check'
	return None

def status_line():
	from caches.settings_cache import get_setting
	cfg = _config()
	if not cfg['enabled']: return 'Off'
	if not _configured(cfg): return 'Needs the Cloud Backup token and repository'
	if not _local_provider(): return 'Only with the Red Light watched provider'
	status = get_setting('redlight.watched_sync.last_status', 'empty_setting')
	if status in (None, '', 'empty_setting'): return 'Never run'
	return status

def run_now(params=None):
	from modules import kodi_utils
	cfg = _config()
	if not cfg['enabled']:
		return kodi_utils.ok_dialog(heading='Watched Sync', text='Turn on Sync Watched Status Between Devices first, in Settings > General > Cloud Backup.')
	if not _configured(cfg):
		return kodi_utils.ok_dialog(heading='Watched Sync', text='Set your GitHub token and repository first, in Settings > General > Cloud Backup.')
	if not _local_provider():
		return kodi_utils.ok_dialog(heading='Watched Sync', text='Watched sync only works with Red Light as the Watched Status Provider. Trakt, Simkl, MDBList and PunchPlay sync through their own servers.')
	kodi_utils.notification('Watched sync started', 3000)
	status, message = run_sync(silent=False, reason='manual')
	if status == 'success':
		kodi_utils.kodi_refresh()
		return kodi_utils.ok_dialog(heading='Watched Sync', text=message)
	if status == 'busy':
		return kodi_utils.ok_dialog(heading='Watched Sync', text=message)
	return kodi_utils.ok_dialog(heading='Watched Sync failed', text=message, scroll=True)
