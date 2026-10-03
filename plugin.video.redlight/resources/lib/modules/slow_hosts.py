# -*- coding: utf-8 -*-
"""Stream servers that recently failed or stalled right at the start of playback.
The resolve queue tries other sources before a link on one of these servers."""
import json
import os
import time
from urllib.parse import urlparse
from modules import kodi_utils

SLOW_HOST_HOURS = 6
_FILE_NAME = 'slow_hosts.json'

def _path():
	profile = kodi_utils.addon_profile()
	return os.path.join(profile, _FILE_NAME) if profile else ''

def stream_host(url):
	try:
		url = str(url or '').split('|')[0]
		if not url.startswith(('http://', 'https://')): return ''
		return (urlparse(url).hostname or '').lower()
	except Exception:
		return ''

def _load():
	path = _path()
	if not path or not os.path.isfile(path): return {}
	try:
		with open(path, 'r') as f: data = json.load(f)
	except Exception:
		return {}
	now = time.time()
	return {host: until for host, until in data.items() if isinstance(until, (int, float)) and until > now}

def mark_slow(url):
	host, path = stream_host(url), _path()
	if not host or not path: return
	data = _load()
	data[host] = time.time() + SLOW_HOST_HOURS * 3600
	try:
		with open(path, 'w') as f: json.dump(data, f)
		kodi_utils.logger('Red Light', 'Slow stream server noted: %s (other sources go first for %sh)' % (host, SLOW_HOST_HOURS))
	except Exception:
		pass

def is_slow(url):
	host = stream_host(url)
	return bool(host) and host in _load()
