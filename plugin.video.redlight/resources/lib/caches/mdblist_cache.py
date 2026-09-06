# -*- coding: utf-8 -*-
import time
from threading import Thread
from caches.base_cache import connect_database
from modules import kodi_utils

# Rows written before this column existed, and every row that must never go stale
# (activities, watched, progress), store expires = 0 and are returned forever.
_expires_column_ready = [False]

def _ensure_expires_column():
	if _expires_column_ready[0]: return
	# Set first: a failure here must not retry on every single cache read.
	_expires_column_ready[0] = True
	try:
		dbcon = connect_database('mdblist_db')
		columns = [i[1] for i in dbcon.execute('PRAGMA table_info(mdblist_data)').fetchall()]
		if 'expires' not in columns:
			dbcon.execute('ALTER TABLE mdblist_data ADD COLUMN expires integer')
	except: pass

class MdblistCache:
	def get(self, string, allow_stale=False):
		try:
			_ensure_expires_column()
			dbcon = connect_database('mdblist_db')
			cache_data = dbcon.execute('SELECT data, expires FROM mdblist_data WHERE id = ?', (string,)).fetchone()
			if cache_data:
				expires = cache_data[1] or 0
				if allow_stale or not expires or int(expires) > int(time.time()):
					return eval(cache_data[0])
		except: pass
		return None

	def set(self, string, data, expiration=0):
		"""expiration is in MINUTES. 0 means never expire."""
		try:
			_ensure_expires_column()
			dbcon = connect_database('mdblist_db')
			expires = int(time.time()) + int(expiration) * 60 if expiration else 0
			dbcon.execute('INSERT OR REPLACE INTO mdblist_data (id, data, expires) VALUES (?, ?, ?)', (string, repr(data), expires))
		except: return None

	def delete(self, string):
		try:
			dbcon = connect_database('mdblist_db')
			dbcon.execute('DELETE FROM mdblist_data WHERE id = ?', (string,))
		except: pass

mdblist_cache = MdblistCache()

class MdblistWatched:
	def set_bulk_movie_watched(self, insert_list):
		self._delete('DELETE FROM watched WHERE db_type = ?', ('movie',))
		self._executemany('INSERT OR IGNORE INTO watched VALUES (?, ?, ?, ?, ?, ?)', insert_list)

	def set_bulk_tvshow_watched(self, insert_list):
		self._delete('DELETE FROM watched WHERE db_type = ?', ('episode',))
		self._executemany('INSERT OR IGNORE INTO watched VALUES (?, ?, ?, ?, ?, ?)', insert_list)

	def set_bulk_movie_progress(self, insert_list):
		self._delete('DELETE FROM progress WHERE db_type = ?', ('movie',))
		self._executemany('INSERT OR IGNORE INTO progress VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', insert_list)

	def set_bulk_tvshow_progress(self, insert_list):
		self._delete('DELETE FROM progress WHERE db_type = ?', ('episode',))
		self._executemany('INSERT OR IGNORE INTO progress VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', insert_list)

	def _executemany(self, command, insert_list):
		if not insert_list: return
		dbcon = connect_database('mdblist_db')
		dbcon.executemany(command, insert_list)

	def _delete(self, command, args):
		dbcon = connect_database('mdblist_db')
		dbcon.execute(command, args)
		# No VACUUM here — watched bulk sync must not rewrite the whole DB on the playback path.

mdblist_watched_cache = MdblistWatched()

def cache_mdblist_object(function, string, url, expiration=0):
	"""expiration is in MINUTES. 0 keeps the old behaviour: cache until something clears it."""
	try:
		cached = mdblist_cache.get(string)
		if cached is not None: return cached
		result = function(url)
		if result is not None:
			mdblist_cache.set(string, result, expiration)
			return result
		# Refresh failed (MDBList down, no network, timeout). Keep serving the copy we
		# already have rather than emptying a widget - never worse than before the refresh.
		return mdblist_cache.get(string, allow_stale=True)
	except: return None

def reset_activity(latest_activities):
	string = 'mdblist_get_activity'
	try:
		cached_data = mdblist_cache.get(string) or default_activities()
		mdblist_cache.set(string, latest_activities)
	except: cached_data = default_activities()
	return cached_data

def default_activities():
	return {'watchlisted_at': '', 'watched_at': '', 'season_watched_at': '', 'episode_watched_at': '', 'rated_at': '',
		'collected_at': '', 'dropped_at': '', 'paused_at': '', 'episode_paused_at': '', 'list_updated_at': ''}

def clear_mdblist_collection_watchlist_data(list_type):
	mdblist_cache.delete('mdblist_%s' % list_type)
	if list_type == 'watchlist':
		mdblist_cache.delete('mdblist_watchlist_v2')
		mdblist_cache.delete('mdblist_watchlist_v3')
		mdblist_cache.delete('mdblist_watchlist_v4')
		mdblist_cache.delete('mdblist_watchlist_live')

def clear_mdblist_list_contents_data(list_type):
	try:
		dbcon = connect_database('mdblist_db')
		dbcon.execute('DELETE FROM mdblist_data WHERE id LIKE ?', ('mdblist_list_contents_%s_%%' % list_type,))
	except: pass

def clear_mdblist_list_data(list_type):
	mdblist_cache.delete('mdblist_%s' % list_type)

def clear_mdblist_calendar_data():
	try:
		dbcon = connect_database('mdblist_db')
		dbcon.execute('DELETE FROM mdblist_data WHERE id LIKE ?', ('mdblist_calendar_airings%',))
		dbcon.execute('DELETE FROM mdblist_data WHERE id = ?', ('mdblist_calendar_events',))
	except: pass

def clear_all_mdblist_cache_data(silent=False, refresh=True):
	try:
		if not silent and not kodi_utils.confirm_dialog(): return False
		dbcon = connect_database('mdblist_db')
		dbcon.execute('DELETE FROM mdblist_data')
		dbcon.execute('DELETE FROM watched')
		dbcon.execute('DELETE FROM progress')
		dbcon.execute('VACUUM')
		if not silent: kodi_utils.notification('MDBList Cache Cleared', 3000)
		if refresh:
			from apis.mdblist_api import mdblist_sync_activities
			Thread(target=mdblist_sync_activities, kwargs={'force_update': True}).start()
		return True
	except: return False
