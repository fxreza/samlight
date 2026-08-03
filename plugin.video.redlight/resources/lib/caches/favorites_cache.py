# -*- coding: utf-8 -*-
from caches.base_cache import connect_database
# from modules.kodi_utils import logger

class FavoritesCache:
	def set_favourite(self, media_type, tmdb_id, title):
		try:
			dbcon = connect_database('favorites_db')
			dbcon.execute('INSERT INTO favourites VALUES (?, ?, ?)', (media_type, str(tmdb_id), title))
			return True
		except: return False

	def delete_favourite(self, media_type, tmdb_id, title):
		try:
			dbcon = connect_database('favorites_db')
			dbcon.execute('DELETE FROM favourites where db_type=? and tmdb_id=?', (media_type, str(tmdb_id)))
			return True
		except: return False

	def get_favorites(self, media_type):
		dbcon = connect_database('favorites_db')
		# No date column exists, but rowid increments on insert, so DESC is newest added first.
		favorites = dbcon.execute('SELECT tmdb_id, title FROM favourites WHERE db_type=? ORDER BY rowid DESC', (media_type,)).fetchall()
		return [{'tmdb_id': str(i[0]), 'title': str(i[1])} for i in favorites]

	def clear_favorites(self, media_type):
		dbcon = connect_database('favorites_db')
		dbcon.execute('DELETE FROM favourites WHERE db_type=?', (media_type,))
		dbcon.execute('VACUUM')

favorites_cache = FavoritesCache()
