# -*- coding: utf-8 -*-
from caches.favorites_cache import favorites_cache
# from modules.kodi_utils import logger

def get_favorites(media_type, dummy_arg):
	# Freshen this half of Favourites from its linked TMDb list before showing it.
	# No-op unless it is linked and the cooldown has passed.
	try:
		from indexers.tmdb_lists import tmdb_sync_on_open
		tmdb_sync_on_open('favorites', media_type=media_type)
	except: pass
	# Newest added first. The cache already returns them in that order.
	data = favorites_cache.get_favorites(media_type)
	return [{'media_id': i['tmdb_id'], 'title': i['title']} for i in data]
