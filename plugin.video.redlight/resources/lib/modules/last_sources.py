# -*- coding: utf-8 -*-
"""The source each title last played from, so playing it again skips the search.

A movie or an episode is kept until it is marked watched, or for TITLE_DAYS. A season
or show pack is kept per show for PACK_DAYS, so later episodes play from the same pack.
Resolving always gets a fresh link: only the result is kept, never the play URL."""
import json
import os
import time
from modules import kodi_utils

TITLE_DAYS = 14
PACK_DAYS = 30
_FILE_NAME = 'last_sources.json'

def _path():
	profile = kodi_utils.addon_profile()
	return os.path.join(profile, _FILE_NAME) if profile else ''

def _load():
	path = _path()
	if not path or not os.path.isfile(path): return {}
	try:
		with open(path, 'r') as f: data = json.load(f)
	except Exception:
		return {}
	now = time.time()
	return {key: value for key, value in data.items() if isinstance(value, dict) and value.get('until', 0) > now}

def _save(data):
	path = _path()
	if not path: return
	try:
		with open(path, 'w') as f: json.dump(data, f)
	except Exception as e:
		kodi_utils.logger('Red Light', 'Last source not saved: %s' % e)

def _num(value):
	try: return str(int(value))
	except Exception: return str(value or '')

def title_key(media_type, tmdb_id, season='', episode=''):
	if media_type == 'movie': return 'movie|%s' % tmdb_id
	return 'episode|%s|%s|%s' % (tmdb_id, _num(season), _num(episode))

def pack_key(tmdb_id):
	return 'pack|%s' % tmdb_id

def _clean_item(item):
	# Keep what resolving needs; drop per-play runtime keys.
	clean = {}
	for key, value in item.items():
		if key.startswith('_') or key == 'resolve_display': continue
		try: json.dumps(value)
		except Exception: continue
		clean[key] = value
	return clean

def _pack_record(item, season):
	# A TorBox cloud file sits in a torrent folder that may hold the whole season.
	if item.get('scrape_provider') == 'tb_cloud' and item.get('folder_id') not in (None, ''):
		return {'kind': 'tb_cloud', 'folder_id': item['folder_id'], 'cloud_media_type': item.get('cloud_media_type') or 'torrent', 'season': _num(season)}
	if 'package' in item and item.get('hash'):
		return {'kind': 'torrent', 'item': item, 'package': item.get('package'), 'season': _num(season)}
	return None

def remember(media_type, tmdb_id, season, episode, item):
	if not tmdb_id or not item: return
	data, now = _load(), time.time()
	clean = _clean_item(item)
	data[title_key(media_type, tmdb_id, season, episode)] = {'item': clean, 'until': now + TITLE_DAYS * 86400}
	if media_type == 'episode':
		# The latest episode's source wins: playing a single file drops an older pack.
		pack = _pack_record(clean, season)
		if pack:
			pack['until'] = now + PACK_DAYS * 86400
			data[pack_key(tmdb_id)] = pack
		else: data.pop(pack_key(tmdb_id), None)
	_save(data)

def get_title(media_type, tmdb_id, season='', episode=''):
	record = _load().get(title_key(media_type, tmdb_id, season, episode))
	return dict(record['item']) if record and record.get('item') else None

def get_pack(tmdb_id):
	return _load().get(pack_key(tmdb_id))

def pack_covers(pack, season):
	# A season pack only holds its own season; a show pack holds them all.
	return pack.get('package') == 'show' or pack.get('season') == _num(season) or pack.get('kind') == 'tb_cloud'

def forget_title(media_type, tmdb_id, season='', episode=''):
	data = _load()
	if data.pop(title_key(media_type, tmdb_id, season, episode), None) is not None: _save(data)

def forget_pack(tmdb_id):
	data = _load()
	if data.pop(pack_key(tmdb_id), None) is not None: _save(data)
