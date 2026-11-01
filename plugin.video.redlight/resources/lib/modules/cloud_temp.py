# -*- coding: utf-8 -*-
"""Temporary cloud copies: Store Resolved to Cloud set to 'All, Remove After 24 Hours'.

What playback adds to TorBox or Premiumize stays in the cloud for 24 hours after it was last
played, then the service removes it. Only what this add-on added is ever removed:

- TorBox has no folders, so a ledger (cloud_temp.json in the profile) lists every torrent and
  usenet download playback added. The entry is written before the add, so a crash between the
  add and the write still leaves its hash to find. Before deleting, the item's own creation
  time on TorBox is checked: anything created before the play (added by hand, or already
  there) is never deleted, even if the ledger names it.
- Premiumize transfers go into their own 'Samlight Temp' folder, and the sweep only ever looks
  inside that folder, so nothing outside it can be touched even if the ledger is lost.

The sweep runs from the service (after start-up, every hour, after a wake), never while a video
plays. An entry leaves the ledger only once the item is confirmed gone, so a failed delete is
simply tried again on the next sweep.
"""
import os
import re
import json
import time
import calendar
from modules import kodi_utils

KEEP_SECONDS = 24 * 3600
PM_FOLDER_NAME = 'Samlight Temp'
# TorBox creation times may lag or lead our clock a little: only an item clearly older than
# the play counts as one that was already there.
_CREATED_SLACK = 300
_LEDGER = 'cloud_temp.json'
_LOCK = 'cloud_temp.lock'
_LOCK_STALE_SEC = 30

def _log(message):
	kodi_utils.logger('Red Light', 'Cloud 24h: %s' % message)

def _path(name):
	return os.path.join(kodi_utils.addon_profile(), name)

def _read():
	try:
		with open(_path(_LEDGER), 'r', encoding='utf-8') as handle: data = json.load(handle)
		return data if isinstance(data, dict) else {}
	except Exception:
		return {}

def _lock():
	path = _path(_LOCK)
	for _ in range(40):
		try:
			os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
			return True
		except FileExistsError:
			try:
				if time.time() - os.path.getmtime(path) > _LOCK_STALE_SEC: os.remove(path)
			except Exception: pass
			time.sleep(0.1)
		except Exception:
			return False
	return False

def _update(change):
	"""Read, change and write the ledger under a lock shared by the plugin and the service."""
	locked = _lock()
	try:
		data = _read()
		result = change(data)
		path = _path(_LEDGER)
		tmp = '%s.%s.tmp' % (path, os.getpid())
		with open(tmp, 'w', encoding='utf-8') as handle: json.dump(data, handle)
		os.replace(tmp, path)
		return result
	finally:
		if locked:
			try: os.remove(_path(_LOCK))
			except Exception: pass

def _key(kind, info_hash, item_id=''):
	info_hash = str(info_hash or '').strip().lower()
	return '%s:%s' % (kind, info_hash) if info_hash else '%s:id:%s' % (kind, item_id)

# ------------------------------------------------------------------ TorBox (playback side)

def torbox_pending(kind, info_hash):
	"""Called before playback adds a torrent or usenet download in 24-hour mode."""
	if not info_hash: return
	now = time.time()
	def change(data):
		entries = data.setdefault('torbox', {})
		entry = entries.get(_key(kind, info_hash))
		if entry: entry['used'] = now
		else: entries[_key(kind, info_hash)] = {'kind': kind, 'hash': str(info_hash).lower(), 'id': '', 'added': now, 'used': now}
	try: _update(change)
	except Exception as error: _log('could not note %s %s: %s' % (kind, info_hash, error))

def torbox_added(kind, info_hash, item_id, preexisting=False):
	"""After the add: note the TorBox id. One that was in the cloud before this play is not ours."""
	if not item_id: return
	item_id, now = str(item_id), time.time()
	def change(data):
		entries = data.setdefault('torbox', {})
		key = _key(kind, info_hash, item_id)
		entry = entries.get(key)
		if preexisting and (not entry or entry.get('id') != item_id):
			entries.pop(key, None)
			return
		if not entry: entry = entries[key] = {'kind': kind, 'hash': str(info_hash or '').lower(), 'added': now}
		entry['id'], entry['used'] = item_id, now
	try: _update(change)
	except Exception as error: _log('could not note %s %s: %s' % (kind, item_id, error))

# ------------------------------------------------------------------ Premiumize (playback side)

def _pm_find_folder(api):
	response = api._get('folder/list')
	if not isinstance(response, dict) or response.get('status') != 'success': return None
	for item in response.get('content') or []:
		if item.get('type') == 'folder' and item.get('name') == PM_FOLDER_NAME: return str(item.get('id'))
	return ''

def _pm_folder(api, create=False):
	folder = _read().get('pm_folder')
	if folder: return folder
	folder = _pm_find_folder(api)
	if folder is None: return None
	if not folder and create:
		response = api._post('folder/create', {'name': PM_FOLDER_NAME})
		if isinstance(response, dict) and response.get('status') == 'success': folder = str(response.get('id') or '')
	if folder:
		def change(data): data['pm_folder'] = folder
		_update(change)
	return folder or None

def pm_store_temporarily(api, magnet_url, info_hash):
	"""Premiumize in 24-hour mode: the transfer goes into the Samlight Temp folder. Nothing is
	stored if that folder cannot be found or made, so nothing can land outside it."""
	try:
		info_hash, now = str(info_hash or '').lower(), time.time()
		recent = _read().get('pm_hashes', {}).get(info_hash)
		if info_hash and recent and now - float(recent) < KEEP_SECONDS: return
		folder = _pm_folder(api, create=True)
		if not folder:
			_log('Premiumize: no %s folder, not storing' % PM_FOLDER_NAME)
			return
		response = api._post('transfer/create', {'src': magnet_url, 'folder_id': folder})
		if not isinstance(response, dict) or response.get('status') != 'success':
			_log('Premiumize transfer failed: %s' % (response.get('message') if isinstance(response, dict) else response))
			return
		transfer_id = str(response.get('id') or '')
		def change(data):
			if transfer_id: data.setdefault('pm_transfers', {})[transfer_id] = now
			if info_hash: data.setdefault('pm_hashes', {})[info_hash] = now
		_update(change)
	except Exception as error:
		_log('Premiumize store failed: %s' % error)

# ------------------------------------------------------------------ sweep (service side)

def _parse_time(value):
	"""TorBox times are ISO 8601 in UTC ('2026-10-31T23:03:24Z', maybe with fractions or an offset)."""
	if value in (None, ''): return None
	if isinstance(value, (int, float)): return float(value)
	match = re.match(r'(\d{4})-(\d\d)-(\d\d)[T ](\d\d):(\d\d):(\d\d)(?:\.\d+)?\s*(Z|[+-]\d\d:?\d\d)?', str(value).strip())
	if not match: return None
	stamp = calendar.timegm(tuple(int(match.group(i)) for i in range(1, 7)) + (0, 0, 0))
	zone = match.group(7)
	if zone and zone != 'Z':
		sign = 1 if zone[0] == '+' else -1
		digits = zone[1:].replace(':', '')
		stamp -= sign * (int(digits[:2]) * 3600 + int(digits[2:4]) * 60)
	return float(stamp)

def _ok(response):
	return isinstance(response, dict) and bool(response.get('success'))

def _sweep_torbox(now):
	entries = _read().get('torbox') or {}
	due = {key: entry for key, entry in entries.items() if now - float(entry.get('used') or 0) >= KEEP_SECONDS}
	if not due: return 0
	from modules.settings import authorized_debrid_check
	if not authorized_debrid_check('tb'): return 0
	from apis.torbox_api import TorBoxAPI
	api, done, removed = TorBoxAPI(), [], 0
	for kind in set(entry.get('kind') for entry in due.values()):
		error, items = api.mylist_items(kind, fresh=True)
		# The list could not be read: nothing is decided, the next sweep tries again.
		if error: continue
		by_id = {str(item.get('id')): item for item in items}
		by_hash = {str(item.get('hash') or '').lower(): item for item in items if item.get('hash')}
		for key, entry in due.items():
			if entry.get('kind') != kind: continue
			item = by_id.get(str(entry.get('id') or '')) if entry.get('id') else None
			if item is None and entry.get('hash'): item = by_hash.get(entry['hash'])
			if item is None:
				done.append(key)
				continue
			created = _parse_time(item.get('created_at'))
			# Created before the play: it was already in the cloud. Never ours to remove.
			if created is not None and created < float(entry.get('added') or 0) - _CREATED_SLACK:
				done.append(key)
				continue
			# No creation time and no id from our own add: cannot prove it is ours.
			if created is None and not entry.get('id'):
				done.append(key)
				continue
			item_id = item.get('id')
			response = api.delete_usenet(item_id) if kind == 'usenet' else api.delete_torrent(item_id)
			if _ok(response):
				done.append(key)
				removed += 1
				_log('removed TorBox %s %s (%s)' % (kind, item_id, item.get('name') or ''))
	if done:
		def change(data):
			for key in done: (data.get('torbox') or {}).pop(key, None)
		_update(change)
		try: api.clear_cache(clear_hashes=False)
		except Exception: pass
	return removed

def _sweep_premiumize(now):
	data = _read()
	from modules.settings import authorized_debrid_check
	if not authorized_debrid_check('pm'): return 0
	from apis.premiumize_api import PremiumizeAPI
	api, removed = PremiumizeAPI(), 0
	folder = data.get('pm_folder') or _pm_find_folder(api)
	seen_now, cleared = {}, []
	if folder:
		response = api._get('folder/list?id=%s' % folder)
		if isinstance(response, dict) and response.get('status') == 'success':
			seen = data.get('pm_seen') or {}
			for item in response.get('content') or []:
				item_id = str(item.get('id') or '')
				if not item_id: continue
				# Premiumize gives created_at; the first time the sweep saw it stands in otherwise.
				since = float(item.get('created_at') or seen.get(item_id) or now)
				seen_now[item_id] = seen.get(item_id) or now
				if now - since < KEEP_SECONDS: continue
				try: status = api.delete_object('folder' if item.get('type') == 'folder' else 'item', item_id)
				except Exception: status = None
				if status == 'success':
					seen_now.pop(item_id, None)
					removed += 1
					_log('removed Premiumize %s (%s)' % (item_id, item.get('name') or ''))
		elif isinstance(response, dict):
			# The folder itself is gone: it is made again at the next temporary store.
			folder = ''
	for transfer_id, at in (data.get('pm_transfers') or {}).items():
		if now - float(at) < KEEP_SECONDS: continue
		# Only the transfer record: its files are in the Samlight Temp folder, handled above.
		try: response = api.delete_transfer(transfer_id)
		except Exception: response = None
		if isinstance(response, dict): cleared.append(transfer_id)
	def change(data):
		if folder: data['pm_folder'] = folder
		else: data.pop('pm_folder', None)
		if folder: data['pm_seen'] = seen_now
		for transfer_id in cleared: (data.get('pm_transfers') or {}).pop(transfer_id, None)
		hashes = data.get('pm_hashes') or {}
		for info_hash in [h for h, at in hashes.items() if now - float(at) >= KEEP_SECONDS]: hashes.pop(info_hash, None)
	_update(change)
	if removed:
		try: api.clear_cache(clear_hashes=False)
		except Exception: pass
	return removed

def apply_default_once():
	"""2.11.8 made 'All, Remove After 24 Hours' the default for TorBox and Premiumize. Once per
	device, a choice still at None moves to it; any other choice the user made is kept."""
	from caches.settings_cache import get_setting, set_setting, settings_cache, default_setting_values
	if get_setting('redlight.cloud_temp.default_applied', 'false') == 'true': return
	for service in ('torbox', 'premiumize.me'):
		setting_id = 'store_resolved_to_cloud.%s' % service
		if get_setting('redlight.%s' % setting_id, '0') != '0': continue
		set_setting(setting_id, '3')
		try:
			label = default_setting_values(setting_id)['settings_options']['3']
			settings_cache.set_memory_cache('%s_name' % setting_id, label)
		except Exception: pass
		_log('%s set to All, Remove After 24 Hours' % setting_id)
	set_setting('cloud_temp.default_applied', 'true')

def has_work():
	data = _read()
	if data.get('torbox') or data.get('pm_folder') or data.get('pm_transfers'): return True
	from modules.settings import cloud_temporary
	return cloud_temporary('Premiumize.me')

def sweep():
	"""Remove temporary cloud items older than 24 hours. Safe to run any time; never raises."""
	now, removed = time.time(), 0
	for name, function in (('TorBox', _sweep_torbox), ('Premiumize', _sweep_premiumize)):
		try: removed += function(now)
		except Exception as error: _log('%s sweep failed: %s' % (name, error))
	return removed
