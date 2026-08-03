# -*- coding: utf-8 -*-
from caches.favorites_cache import favorites_cache
# from modules.kodi_utils import logger

def get_favorites(media_type, dummy_arg):
	# Newest added first. The cache already returns them in that order.
	data = favorites_cache.get_favorites(media_type)
	return [{'media_id': i['tmdb_id'], 'title': i['title']} for i in data]
