# -*- coding: utf-8 -*-
"""GitHub release-asset transport for the cloud backup.

Backups are uploaded as release assets rather than committed files: assets can be
deleted, so retention actually frees space, whereas a committed binary lives in git
history forever.

Every function returns (True, payload) or (False, {'code': ..., 'message': ...}).
Nothing here raises into the service thread and nothing here opens a dialog.
"""

import json
import os
import requests
from modules import kodi_utils
from modules.http_defaults import META_API_TIMEOUT, meta_status_retry

API = 'https://api.github.com'
UPLOADS = 'https://uploads.github.com'
RELEASE_TAG = 'samlight-backups'
UPLOAD_TIMEOUT = (20, 180)
MAX_UPLOAD_BYTES = 100 * 1024 * 1024

session = requests.Session()
_adapter = requests.adapters.HTTPAdapter(max_retries=meta_status_retry())
session.mount(API, _adapter)
session.mount(UPLOADS, _adapter)


def _headers(cfg, accept='application/vnd.github+json'):
	return {
		'Authorization': 'Bearer %s' % cfg['token'],
		'Accept': accept,
		'X-GitHub-Api-Version': '2022-11-28',
		# GitHub rejects requests without a User-Agent.
		'User-Agent': 'RedLight-CloudBackup/%s' % (kodi_utils.get_property('redlight.addon_version') or '1'),
	}


def _fail(code, message):
	return False, {'code': code, 'message': message}


def _classify(response):
	"""Turn an unhappy response into a stable code plus something a human can act on."""
	status = response.status_code
	try: body = response.json()
	except Exception: body = {}
	detail = body.get('message') or ''
	errors = body.get('errors') or []
	if status == 401:
		return _fail('bad_token', 'GitHub rejected the token. It may be expired, revoked or mistyped.')
	if status == 403:
		if response.headers.get('x-ratelimit-remaining') == '0':
			return _fail('rate_limited', 'GitHub rate limit reached. Will retry later.')
		return _fail('no_permission', 'The token lacks "Contents: Read and write" on that repository.')
	if status == 404:
		return _fail('not_found', 'Repository not found, or the token was not granted access to it.')
	if status == 409:
		return _fail('conflict', 'GitHub reported a conflict. Will retry later.')
	if status == 422:
		for err in errors:
			if err.get('code') == 'already_exists':
				return _fail('already_exists', 'An asset with that name already exists.')
		if 'valid tag' in detail:
			return _fail('invalid_repo', 'The repository has no commits yet. Add a README on GitHub, then try again.')
		return _fail('invalid_repo', detail or 'GitHub rejected the request.')
	if status >= 500:
		return _fail('server', 'GitHub is having problems (HTTP %s). Will retry later.' % status)
	return _fail('http_%s' % status, detail or ('HTTP %s' % status))


def _request(method, url, cfg, **kwargs):
	kwargs.setdefault('timeout', META_API_TIMEOUT)
	try:
		response = session.request(method, url, **kwargs)
	except (requests.ConnectionError, requests.Timeout):
		return _fail('offline', 'No connection to GitHub.')
	except Exception as e:
		return _fail('error', str(e))
	if response.status_code >= 400:
		return _classify(response)
	return True, response


def check_access(cfg):
	ok, result = _request('GET', '%s/repos/%s/%s' % (API, cfg['owner'], cfg['repo']), cfg, headers=_headers(cfg))
	if not ok: return ok, result
	return True, result.json()


def resolve_or_create_release(cfg, create=True):
	url = '%s/repos/%s/%s/releases/tags/%s' % (API, cfg['owner'], cfg['repo'], RELEASE_TAG)
	ok, result = _request('GET', url, cfg, headers=_headers(cfg))
	if ok:
		return True, result.json()
	if result['code'] != 'not_found':
		return ok, result
	if not create:
		return _fail('no_backups', 'No backups have been uploaded to that repository yet.')
	payload = {
		'tag_name': RELEASE_TAG,
		'name': 'Sam Light Backups',
		'body': 'Automatic backups of Sam Light user data. Managed by the addon - do not edit by hand.',
		'draft': False,
		'prerelease': True,
	}
	ok, result = _request('POST', '%s/repos/%s/%s/releases' % (API, cfg['owner'], cfg['repo']), cfg,
							headers=_headers(cfg), data=json.dumps(payload))
	if not ok: return ok, result
	return True, result.json()


def _upload_url(cfg, release, name):
	# Prefer the template GitHub hands back; fall back to the documented path.
	base = (release.get('upload_url') or '').split('{')[0]
	if not base:
		base = '%s/repos/%s/%s/releases/%s/assets' % (UPLOADS, cfg['owner'], cfg['repo'], release['id'])
	return '%s?name=%s' % (base, name)


def upload_asset(cfg, release, zip_path, asset_name):
	size = os.path.getsize(zip_path)
	if size > MAX_UPLOAD_BYTES:
		return _fail('too_large', 'Backup is %sMB, over the 100MB limit.' % (size // 1048576))
	# Read into memory: a file object makes requests use chunked encoding, which this
	# endpoint rejects. Bytes give it a proper Content-Length.
	with open(zip_path, 'rb') as fh:
		blob = fh.read()
	headers = _headers(cfg)
	headers['Content-Type'] = 'application/zip'
	name, attempt = asset_name, 1
	while attempt <= 3:
		ok, result = _request('POST', _upload_url(cfg, release, name), cfg, headers=headers,
								data=blob, timeout=UPLOAD_TIMEOUT)
		if ok:
			return True, result.json()
		if result['code'] != 'already_exists':
			return ok, result
		attempt += 1
		name = '%s-%s.zip' % (asset_name[:-4], attempt)
	return _fail('already_exists', 'Could not find a free asset name.')


def list_assets(cfg, release):
	url = '%s/repos/%s/%s/releases/%s/assets?per_page=100' % (API, cfg['owner'], cfg['repo'], release['id'])
	ok, result = _request('GET', url, cfg, headers=_headers(cfg))
	if not ok: return ok, result
	return True, result.json()


def prune_assets(cfg, release, keep, name_prefix=''):
	"""Delete the oldest assets beyond `keep`. Only ever considers this device's own backups."""
	ok, assets = list_assets(cfg, release)
	if not ok: return ok, assets
	mine = [a for a in assets if a.get('name', '').startswith(name_prefix)]
	mine.sort(key=lambda a: a.get('created_at', ''), reverse=True)
	deleted = 0
	for asset in mine[keep:]:
		url = '%s/repos/%s/%s/releases/assets/%s' % (API, cfg['owner'], cfg['repo'], asset['id'])
		ok, _result = _request('DELETE', url, cfg, headers=_headers(cfg))
		if ok: deleted += 1
	return True, {'deleted': deleted, 'kept': len(mine) - deleted}


def newest_asset(cfg, release, name_prefix=''):
	ok, assets = list_assets(cfg, release)
	if not ok: return ok, assets
	usable = [a for a in assets if a.get('name', '').endswith('.zip') and a.get('name', '').startswith(name_prefix)]
	if not usable:
		return _fail('no_backups', 'That repository has no backups yet.')
	usable.sort(key=lambda a: a.get('created_at', ''), reverse=True)
	return True, usable[0]


def download_asset(cfg, asset, dest_path):
	url = '%s/repos/%s/%s/releases/assets/%s' % (API, cfg['owner'], cfg['repo'], asset['id'])
	# The 302 lands on storage that supplies its own auth; Session.rebuild_auth drops our
	# Authorization header across hosts, which is exactly what we want. Do not hand-roll it.
	ok, result = _request('GET', url, cfg, headers=_headers(cfg, accept='application/octet-stream'),
							stream=True, timeout=UPLOAD_TIMEOUT)
	if not ok: return ok, result
	try:
		with open(dest_path, 'wb') as fh:
			for chunk in result.iter_content(65536):
				if chunk: fh.write(chunk)
	except Exception as e:
		return _fail('error', 'Download failed: %s' % e)
	return True, dest_path
