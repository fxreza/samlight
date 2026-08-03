# -*- coding: utf-8 -*-
"""Daily one-way backup of this device's user data to a private GitHub repo.

The zip is byte-format identical to the one Tools > Export Red Light Settings makes,
so a downloaded cloud backup can also be restored through the normal Import dialog.

Databases are copied with sqlite's own backup API rather than as files: they run in
WAL mode, and a file copy taken mid-write is torn. A torn database is not noticed at
backup time - it is noticed at restore time by check_databases_integrity, which
silently deletes it and rebuilds it empty. So the snapshot is where the care goes.
"""

import calendar
import json
import os
import re
import shutil
import sqlite3
import time
from zipfile import ZipFile
from caches.base_cache import connect_database
from caches.settings_cache import get_setting, set_setting
from modules import kodi_utils
from modules.settings_backup import (
	_apply_settings_import, _local_inventory, _read_manifest, _write_settings_zip, _zip_inventory)

# Table counts must match check_databases_integrity (caches/base_cache.py:163).
EXPECTED_TABLES = {'settings.db': 1, 'navigator.db': 1, 'personal_lists.db': 1, 'discover.db': 1,
					'episode_groups.db': 1, 'watched.db': 3, 'favourites.db': 1, 'list_sort.db': 1}

STAGE_DIR = 'special://temp/redlight_cloud_stage'
VERIFY_DIR = 'special://temp/redlight_cloud_verify'
ZIP_PATH = 'special://temp/redlight_cloud_backup.zip'
RESTORE_PATH = 'special://temp/redlight_cloud_restore.zip'

# Failures the user has to act on. Everything else is weather - log it and retry.
ACTIONABLE = ('bad_token', 'no_permission', 'not_found', 'invalid_repo', 'too_large')


def _now():
	return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def _config():
	repository = get_setting('redlight.cloud_backup.repository', 'empty_setting') or ''
	owner, _sep, repo = repository.strip().strip('/').partition('/')
	token = get_setting('redlight.cloud_backup.token', 'empty_setting') or ''
	if token == 'empty_setting': token = ''
	try: retention = max(1, int(get_setting('redlight.cloud_backup.retention', '14')))
	except: retention = 14
	return {'enabled': get_setting('redlight.cloud_backup.enabled', 'false') == 'true',
			'token': token.strip(), 'owner': owner.strip(), 'repo': repo.strip(), 'retention': retention}


def _configured(cfg):
	return cfg['enabled'] and cfg['token'] and cfg['owner'] and cfg['repo']


def _interval_hours():
	try: return max(1, int(get_setting('redlight.cloud_backup.interval_hours', '24')))
	except: return 24


def _device_prefix():
	name = kodi_utils.get_infolabel('System.FriendlyName') or 'kodi'
	slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')[:16] or 'kodi'
	return 'samlight-%s-' % slug


def backup_due():
	if not _configured(_config()): return False
	last = get_setting('redlight.cloud_backup.last_run', 'empty_setting')
	if last in (None, '', 'empty_setting'): return True
	try:
		stamp = calendar.timegm(time.strptime(last.rstrip('Z').split('.')[0], '%Y-%m-%dT%H:%M:%S'))
	except:
		return True
	return (time.time() - stamp) >= (_interval_hours() * 3600)


def _snapshot_databases(inventory):
	"""Consistent copy of every backed-up database into a staging folder."""
	stage = kodi_utils.translate_path(STAGE_DIR)
	shutil.rmtree(stage, ignore_errors=True)
	os.makedirs(stage)
	for item in inventory['databases']:
		src = dst = None
		try:
			src = connect_database(item['key'])
			dst = sqlite3.connect(os.path.join(stage, item['filename']))
			src.backup(dst, pages=256, sleep=0.05)
			# Plain rollback journal in the copy: no -wal sidecar to leave behind.
			dst.execute('PRAGMA journal_mode = DELETE')
			result = dst.execute('PRAGMA quick_check').fetchone()
			if not result or result[0] != 'ok':
				raise ValueError('%s failed its integrity check' % item['filename'])
		finally:
			for con in (src, dst):
				try: con.close()
				except: pass
	return stage


def run_backup(silent=True):
	"""Dialog-free. Returns (status, message). Never raises."""
	from apis import github_backup_api as gh
	cfg = _config()
	if not _configured(cfg):
		return 'disabled', 'Cloud backup is not configured.'
	inventory = _local_inventory()
	if not inventory['databases']:
		return 'empty', 'Nothing to back up on this device.'
	stage, zip_path = None, kodi_utils.translate_path(ZIP_PATH)
	try:
		stage = _snapshot_databases(inventory)
		_write_settings_zip(zip_path, inventory, source_dir=stage)
		ok, release = gh.resolve_or_create_release(cfg)
		if not ok: return _record_failure(release, silent)
		name = '%s%s.zip' % (_device_prefix(), time.strftime('%Y%m%d-%H%M%S', time.gmtime()))
		ok, asset = gh.upload_asset(cfg, release, zip_path, name)
		if not ok: return _record_failure(asset, silent)
		gh.prune_assets(cfg, release, cfg['retention'], _device_prefix())
		set_setting('cloud_backup.last_run', _now())
		set_setting('cloud_backup.last_status', 'OK %s' % time.strftime('%d %b %H:%M'))
		set_setting('cloud_backup.last_error_notified', 'empty_setting')
		return 'success', 'Uploaded %s' % asset.get('name', name)
	except Exception as e:
		return _record_failure({'code': 'error', 'message': str(e)}, silent)
	finally:
		if stage: shutil.rmtree(stage, ignore_errors=True)
		try:
			if os.path.isfile(zip_path): os.remove(zip_path)
		except: pass


def _record_failure(error, silent):
	code, message = error.get('code', 'error'), error.get('message', 'Unknown error')
	set_setting('cloud_backup.last_status', '[COLOR red]Failed %s - %s[/COLOR]' % (time.strftime('%d %b'), message))
	kodi_utils.logger('Red Light', 'Cloud Backup failed (%s): %s' % (code, message))
	if silent and code in ACTIONABLE and _should_notify(code):
		kodi_utils.notification('Cloud backup failed - %s' % message, 7000)
	return code, message


def _should_notify(code):
	"""Nag at most once a week, and once per distinct problem."""
	previous = get_setting('redlight.cloud_backup.last_error_notified', 'empty_setting') or ''
	today = time.strftime('%Y-%m-%d')
	stamp = '%s|%s' % (code, today)
	if previous in (None, '', 'empty_setting'):
		set_setting('cloud_backup.last_error_notified', stamp)
		return True
	last_code, _sep, last_date = previous.partition('|')
	if last_code != code:
		set_setting('cloud_backup.last_error_notified', stamp)
		return True
	try:
		age = (time.time() - calendar.timegm(time.strptime(last_date, '%Y-%m-%d'))) / 86400
	except:
		age = 999
	if age >= 7:
		set_setting('cloud_backup.last_error_notified', stamp)
		return True
	return False


def backup_status_line():
	cfg = _config()
	if not _configured(cfg): return 'Not configured'
	status = get_setting('redlight.cloud_backup.last_status', 'empty_setting')
	if status in (None, '', 'empty_setting'): status = 'Never run'
	last = get_setting('redlight.cloud_backup.last_run', 'empty_setting')
	if last not in (None, '', 'empty_setting') and 'Failed' not in status:
		try:
			age = (time.time() - calendar.timegm(time.strptime(last.rstrip('Z').split('.')[0], '%Y-%m-%dT%H:%M:%S'))) / 3600
			# Silent staleness matters more than loud errors: expired tokens fail quietly.
			if age > (_interval_hours() * 3):
				return '[COLOR yellow]Last backup %s days ago[/COLOR]' % int(age // 24)
		except: pass
	return status


def run_now(params):
	cfg = _config()
	if not _configured(cfg):
		return kodi_utils.ok_dialog(heading='Cloud Backup',
			text='Set your GitHub token and repository first, in Settings > General > Cloud Backup.')
	kodi_utils.notification('Cloud backup started', 4000)
	status, message = run_backup(silent=False)
	if status == 'success':
		return kodi_utils.ok_dialog(heading='Cloud Backup', text='%s[CR][CR]Keeping the newest %s backups.' % (message, cfg['retention']))
	return kodi_utils.ok_dialog(heading='Cloud Backup failed', text=message, scroll=True)


def _verify_zip_databases(zip_path, inventory):
	"""Check every database in the zip before letting it near the live profile."""
	scratch = kodi_utils.translate_path(VERIFY_DIR)
	shutil.rmtree(scratch, ignore_errors=True)
	os.makedirs(scratch)
	try:
		with ZipFile(zip_path, 'r') as archive:
			for item in inventory['databases']:
				archive.extract(item['arcname'], scratch)
				path = os.path.join(scratch, item['arcname'].replace('/', os.sep))
				con = sqlite3.connect(path)
				try:
					result = con.execute('PRAGMA integrity_check').fetchone()
					if not result or result[0] != 'ok':
						raise ValueError('%s is corrupt in this backup.' % item['filename'])
					expected = EXPECTED_TABLES.get(item['filename'])
					if expected:
						tables = len(con.execute('SELECT name FROM sqlite_master WHERE type="table"').fetchall())
						if tables != expected:
							raise ValueError('%s has %s tables, expected %s.' % (item['filename'], tables, expected))
				finally:
					try: con.close()
					except: pass
	finally:
		shutil.rmtree(scratch, ignore_errors=True)


def restore_latest(params):
	from apis import github_backup_api as gh
	cfg = _config()
	if not _configured(cfg):
		return kodi_utils.ok_dialog(heading='Restore from Cloud',
			text='Set your GitHub token and repository first, in Settings > General > Cloud Backup.')
	if kodi_utils.kodi_player().isPlayingVideo():
		return kodi_utils.ok_dialog(heading='Restore from Cloud', text='Stop playback first.')
	ok, release = gh.resolve_or_create_release(cfg, create=False)
	if not ok: return kodi_utils.ok_dialog(heading='Restore from Cloud', text=release['message'], scroll=True)
	ok, asset = gh.newest_asset(cfg, release, _device_prefix())
	if not ok:
		# Fall back to any device's backup - moving to a new stick is exactly when this is needed.
		ok, asset = gh.newest_asset(cfg, release)
		if not ok: return kodi_utils.ok_dialog(heading='Restore from Cloud', text=asset['message'], scroll=True)
	size = '%.1f MB' % (asset.get('size', 0) / 1048576.0)
	text = '[B]%s[/B][CR]%s, uploaded %s[CR][CR]Download this backup?' % (
		asset.get('name', ''), size, (asset.get('created_at') or '')[:10])
	if not kodi_utils.confirm_dialog(heading='Restore from Cloud', text=text, ok_label='Download', cancel_label='Cancel'):
		return
	path = kodi_utils.translate_path(RESTORE_PATH)
	kodi_utils.notification('Downloading backup', 4000)
	ok, result = gh.download_asset(cfg, asset, path)
	if not ok: return kodi_utils.ok_dialog(heading='Restore failed', text=result['message'], scroll=True)
	try:
		with ZipFile(path, 'r') as archive:
			manifest = _read_manifest(archive)
			inventory = _zip_inventory(archive, manifest)
		if not inventory['databases']:
			raise ValueError('That backup contains no databases.')
		_verify_zip_databases(path, inventory)
	except Exception as e:
		return kodi_utils.ok_dialog(heading='Restore failed', text='The backup did not pass its checks.[CR][CR]%s' % e, scroll=True)
	confirm = ('[B]%s[/B][CR]From Red Light %s (%s)[CR][CR]This replaces your current settings, menus, lists, '
				'favorites, watched status and resume points on this device.') % (
				asset.get('name', ''), manifest.get('addon_version') or 'unknown', (manifest.get('exported') or 'unknown')[:10])
	if not kodi_utils.confirm_dialog(heading='Restore from Cloud', text=confirm, ok_label='Restore', cancel_label='Cancel', scroll=True):
		return
	try:
		summary = _apply_settings_import(path, inventory)
	except Exception as e:
		return kodi_utils.ok_dialog(heading='Restore failed', text=str(e), scroll=True)
	finally:
		try: os.remove(path)
		except: pass
	kodi_utils.ok_dialog(heading='Restore complete', text=summary, scroll=True)
	kodi_utils.notification('Restored from cloud', 6500)
	kodi_utils.kodi_refresh()
