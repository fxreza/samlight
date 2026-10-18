# -*- coding: utf-8 -*-
"""Checks a stream link before Kodi's player gets it.
Kodi can hang for good while it opens a link whose server stalls or trickles data:
its player blocks the whole interface and Back does nothing. Here the same link is
opened in Python with hard time limits, so a bad one is dropped without ever
reaching the player, and Back can stop the check at any moment."""
import time
from threading import Thread
from urllib.parse import parse_qsl
from modules import kodi_utils

CHECK_SECONDS = 12			# whole check, start and end of the file
HEAD_BYTES = 2 * 1024 * 1024	# must arrive from the start of the file
TAIL_BYTES = 256 * 1024			# must arrive from the end (MKV index / MP4 moov)
_CHUNK = 64 * 1024

OK, BAD, CANCELLED = 'ok', 'bad', 'cancelled'

def _split(url):
	url, _, header_str = str(url).partition('|')
	headers = dict(parse_qsl(header_str)) if header_str else {}
	return url, headers

def _read(requests, url, headers, range_header, want, deadline):
	'''Bytes read from the range before the deadline, or raises. Returns (count, total_size, status, content_type).'''
	h = dict(headers)
	h['Range'] = range_header
	left = deadline - time.time()
	if left <= 0: raise TimeoutError('no time left')
	r = requests.get(url, headers=h, stream=True, timeout=(min(left, 8), min(left, 6)), allow_redirects=True)
	try:
		if r.status_code >= 400: return 0, 0, r.status_code, ''
		ctype = (r.headers.get('Content-Type') or '').lower()
		total = 0
		content_range = r.headers.get('Content-Range') or ''
		if r.status_code == 206 and '/' in content_range:
			try: total = int(content_range.rsplit('/', 1)[1])
			except: total = 0
		elif r.headers.get('Content-Length'):
			try: total = int(r.headers['Content-Length'])
			except: total = 0
		count = 0
		for chunk in r.iter_content(_CHUNK):
			count += len(chunk)
			if count >= want or time.time() > deadline: break
		return count, total, r.status_code, ctype
	finally:
		try: r.close()
		except: pass

def _check(url, result):
	try:
		import requests
	except Exception:
		result[0] = OK
		return
	url, headers = _split(url)
	deadline = time.time() + CHECK_SECONDS
	try:
		count, total, status, ctype = _read(requests, url, headers, 'bytes=0-%d' % (HEAD_BYTES - 1), HEAD_BYTES, deadline)
	except requests.exceptions.SSLError:
		result[0] = OK	# certificate trouble on this device says nothing about the server
		return
	except Exception as e:
		result[0], result[1] = BAD, 'start of file: %s' % type(e).__name__
		return
	if status >= 400:
		result[0], result[1] = BAD, 'HTTP %s' % status
		return
	if 'text/html' in ctype:
		result[0], result[1] = BAD, 'web page instead of a video'
		return
	if count < HEAD_BYTES and not (total and count >= total):
		result[0], result[1] = BAD, 'start of file too slow (%d KB in %ds)' % (count // 1024, CHECK_SECONDS)
		return
	if status == 206 and total > HEAD_BYTES + TAIL_BYTES:
		try:
			count, _, status, _ = _read(requests, url, headers, 'bytes=%d-%d' % (total - TAIL_BYTES, total - 1), TAIL_BYTES, deadline)
		except Exception as e:
			result[0], result[1] = BAD, 'end of file: %s' % type(e).__name__
			return
		if status >= 400:
			result[0], result[1] = BAD, 'end of file: HTTP %s' % status
			return
		if count < TAIL_BYTES:
			result[0], result[1] = BAD, 'end of file too slow'
			return
	result[0] = OK

def check(url, cancelled, on_progress=None):
	'''OK, BAD or CANCELLED. cancelled() is polled every 50 ms; on_progress(percent) moves the bar.
	Links that are not http(s) (local files, plugin://) are not checked.'''
	if not str(url or '').startswith(('http://', 'https://')): return OK
	result = [None, '']
	started = time.time()
	worker = Thread(target=_check, args=(url, result), daemon=True)
	worker.start()
	while worker.is_alive():
		if cancelled(): return CANCELLED
		elapsed = time.time() - started
		if elapsed > CHECK_SECONDS + 2:
			result[0], result[1] = BAD, 'no answer in %ds' % CHECK_SECONDS
			break
		if on_progress:
			try: on_progress(int(min(elapsed / CHECK_SECONDS, 1.0) * 30))
			except: pass
		kodi_utils.sleep(50)
	if cancelled(): return CANCELLED
	status = result[0] or BAD
	if status == BAD:
		kodi_utils.logger('Red Light', 'Link check failed (%s), not handing it to the player: %s' % (result[1] or 'unknown', url.split('|')[0][:120]))
	else:
		kodi_utils.logger('Red Light', 'Link check passed in %.1fs' % (time.time() - started))
	return status
