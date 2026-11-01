# -*- coding: utf-8 -*-
"""Source Test Log: a record of every search while 'Source Test Log' is on (Settings > Results).

Written to source_test.jsonl in the add-on's data folder, one JSON object per line, for
analysing the external sources (Gears, Magneto, ...): how long each source takes, what it
finds, which links other sources found too, which are cached, and what played. Events of
one search share an 'sid':

  search      what was searched, the timeout, the modules searched, why (first try or a retry)
  source      one source of one module: time, links (name, hash, size, quality, seeders)
  scrape_end  when the search stopped waiting, and which sources were still running
  cache       each link's cache status on TorBox / Premiumize after the cache check
  kept        the links left after the add-on's own filters, in the order they were offered
  play        each link tried for playback: resolved or not, played or not

Off, every call returns at once. tools/source_test_report.py turns the file into a report."""
import os
import json
import time
import threading
from modules import kodi_utils

_FILE = 'source_test.jsonl'
_MAX_BYTES = 30 * 1024 * 1024
_NAME_CHARS = 160
# Keys some sources use for the site a link really came from (a source that wraps others).
_ORIGIN_KEYS = ('tracker', 'site', 'indexer', 'origin', 'source_site')
_SID_PROP = 'redlight.source_test.sid'
_lock = threading.Lock()
_state = {'enabled': None, 'sid': '', 'started': 0.0, 'ended': 0.0}

def enabled():
	if _state['enabled'] is None:
		try:
			from caches.settings_cache import get_setting
			_state['enabled'] = get_setting('redlight.source_test.enabled', 'false') == 'true'
		except Exception:
			_state['enabled'] = False
	return _state['enabled']

def _path():
	return os.path.join(kodi_utils.addon_profile(), _FILE)

def _write(event, **data):
	data.update({'event': event, 'sid': _state['sid'], 't': round(time.time(), 2)})
	try:
		line = json.dumps(data, separators=(',', ':'), default=str)
		with _lock:
			path = _path()
			try:
				if os.path.getsize(path) > _MAX_BYTES: os.replace(path, path.replace('.jsonl', '.old.jsonl'))
			except OSError: pass
			with open(path, 'a', encoding='utf-8') as handle: handle.write(line + '\n')
	except Exception as error:
		kodi_utils.logger('Source Test', 'write failed: %s' % error)

def _offset(at=None):
	return round((at or time.time()) - _state['started'], 2) if _state['started'] else None

def _num(value, digits=2):
	try: return round(float(value), digits)
	except Exception: return None

def _link(item):
	link = {'n': str(item.get('name') or '')[:_NAME_CHARS], 'h': str(item.get('hash') or '').lower(),
			'q': item.get('quality'), 's': _num(item.get('size')), 'sd': item.get('seeders')}
	if item.get('package'): link['pk'] = item.get('package')
	origin = [str(item.get(key)) for key in _ORIGIN_KEYS if item.get(key)]
	source = item.get('source')
	if source and str(source).lower() not in ('torrent', 'magnet'): origin.append(str(source))
	if origin: link['o'] = '|'.join(origin)[:80]
	return link

def search_start(meta, info, timeout, modules, background, reason):
	"""One external search begins (a retry is a new search with its own reason)."""
	if not enabled(): return
	now = time.time()
	_state['count'] = _state.get('count', 0) + 1
	_state['sid'], _state['started'], _state['ended'] = '%x%04x%02x' % (int(now * 1000), os.getpid() % 65536, _state['count'] % 256), now, 0.0
	# A next episode found in the background plays from another interpreter: it reads this.
	kodi_utils.set_property(_SID_PROP, _state['sid'])
	meta = meta or {}
	_write('search', media_type=info.get('media_type'), title=info.get('title'), year=info.get('year'),
		tmdb=info.get('tmdb_id'), imdb=info.get('imdb_id'), season=info.get('season'), episode=info.get('episode'),
		total_seasons=info.get('total_seasons'), first_aired=meta.get('premiered') or meta.get('first_air_date') or '',
		timeout=timeout, modules=modules, background=bool(background), reason=reason)

def source(module, provider, pack, started, from_cache, raw_count, links, used_count=None, error=None):
	"""One source of one module finished (or failed)."""
	if not enabled() or not _state['sid']: return
	ended = time.time()
	links = links or []
	data = {'module': module or '', 'provider': provider, 'pack': pack or '', 'start': _offset(started),
			'secs': round(ended - started, 2), 'cached': bool(from_cache), 'raw': raw_count,
			'count': len(links), 'links': [_link(i) for i in links if isinstance(i, dict)]}
	if used_count is not None and used_count != len(links): data['used'] = used_count
	# Finished after the search had already stopped waiting: its links were not offered.
	if _state['ended'] and ended > _state['ended']: data['late'] = True
	if error: data['error'] = str(error)[:200]
	_write('source', **data)

def scrape_end(threads, reason):
	if not enabled() or not _state['sid']: return
	_state['ended'] = time.time()
	running = [t.getName() for t in threads or [] if t.is_alive()]
	_write('scrape_end', secs=_offset(), reason=reason, running=running)

def cache(results):
	"""Cache status per link after the TorBox / Premiumize check."""
	if not enabled() or not _state['sid']: return
	status = {}
	for item in results or []:
		item_hash = str(item.get('hash') or '').lower()
		if item_hash: status.setdefault(item_hash, []).append(str(item.get('cache_provider') or ''))
	_write('cache', secs=_offset(), status=status)

def kept(results):
	"""The links the add-on kept after its own filters, in the order it offers them."""
	if not enabled() or not _state['sid']: return
	order = [[str(i.get('hash') or '').lower(), i.get('provider') or i.get('scrape_provider'), i.get('cache_provider') or '']
			for i in results or [] if i.get('scrape_provider') == 'external']
	_write('kept', count=len(results or []), external=order)

def play(item, step, detail=''):
	"""A link tried for playback. step: 'no_url' (resolve failed), 'opened', 'failed'."""
	if not enabled() or not isinstance(item, dict): return
	if not _state['sid']: _state['sid'] = kodi_utils.get_property(_SID_PROP) or ''
	if not _state['sid']: return
	_write('play', step=step, h=str(item.get('hash') or '').lower(), provider=item.get('provider') or item.get('scrape_provider'),
		module=item.get('external_module') or '', name=str(item.get('name') or '')[:_NAME_CHARS],
		cache=item.get('cache_provider') or '', detail=str(detail)[:200])
