# -*- coding: utf-8 -*-
import os
import sys
import json
import time
from random import shuffle
from threading import Thread, Lock
from urllib.parse import unquote
from apis.tmdblist_api import tmdb_list_api
from caches.settings_cache import get_setting, set_setting
from caches.tmdb_lists import tmdb_lists_cache
from indexers.movies import Movies
from indexers.tvshows import TVShows
from modules.utils import paginate_list, sort_for_article, gen_md5, jsondate_to_datetime as js2date
from modules.settings import paginate, page_limit, widget_hide_next_page, ignore_articles, jump_to_enabled, tmdblist_user_active
from modules import kodi_utils
# logger = kodi_utils.logger

def get_tmdb_lists(params):
	def get_custom_image(list_name, image_type, images):
		try:
			md5_image_name = gen_md5(list_name)
			custom_image = [i for i in images if i.rsplit('_', 1)[0] == md5_image_name][0]
			return os.path.join(profile_path, 'images', 'tmdb_lists_%s' % image_type, custom_image)
		except: return ''
	def _process():
		for item in data:
			try:
				list_name, list_id, item_count = item['name'], item['id'], item['number_of_items']
				sort_order = sort_orders.get(list_id, 'None')
				updated_at = item['updated_at']
				custom_poster = get_custom_image(list_name, 'poster', all_posters)
				if custom_poster: poster = custom_poster
				else: poster = icon
				custom_fanart = get_custom_image(list_name, 'fanart', all_fanart)
				if custom_fanart: fanart = custom_fanart
				else: fanart = background
				random_contents = random or shuffle_lists
				mode = 'random.build_tmdb_lists_contents' if random_contents else 'tmdblist.build_tmdb_list'
				url_params = {'mode': mode, 'list_id': list_id, 'list_name': list_name,
				'sort_order': 'shuffle' if random_contents else sort_order, 'updated_at': updated_at, 'iconImage': poster, 'name': list_name}
				if random_contents: url_params['random'] = 'true'
				url = kodi_utils.build_folder_url(url_params)
				display = '%s [I](x%02d)[/I]' % (list_name, item_count)
				cm = [('[B]Make New List[/B]', 'RunPlugin(%s)' % build_url({'mode': 'tmdblist.make_new_tmdb_list'})),
				('[B]Set Custom Sort[/B]', 'RunPlugin(%s)' % build_url({'mode': 'list_sort_override_choice', 'list_key': 'tmdb:%s' % list_id,
					'adapter': 'tmdb', 'fallback': 'default:asc'})),
				('[B]Edit Properties[/B]', 'RunPlugin(%s)' % build_url({'mode': 'tmdblist.adjust_tmdb_list_properties', 'list_id': list_id, 'updated_at': updated_at,
					'original_list_name': list_name, 'original_sort_order': sort_order, 'custom_poster': custom_poster, 'custom_fanart': custom_fanart})),
				('[B]Delete List[/B]', 'RunPlugin(%s)' % build_url({'mode': 'tmdblist.delete_tmdb_list', 'list_id': list_id})),
				('[B]Clear Contents Cache[/B]', 'RunPlugin(%s)' % build_url({'mode': 'tmdblist.cache_delete_list_tmdb', 'list_id': list_id})),
				('[B]Clear All Lists Cache[/B]', 'RunPlugin(%s)' % build_url({'mode': 'tmdblist.cache_delete_all_tmdb'})),
				('[B]Add to Shortcut Folder[/B]', 'RunPlugin(%s)' % build_url({'mode': 'menu_editor.shortcut_folder_add_known', 'url': url}))]
				listitem = kodi_utils.make_listitem()
				listitem.setLabel(display)
				listitem.setArt({'icon': poster, 'poster': poster, 'thumb': poster, 'fanart': fanart, 'banner': fanart})
				info_tag = listitem.getVideoInfoTag(True)
				info_tag.setPlot(' ')
				listitem.addContextMenuItems(cm)
				yield (url, listitem, True)
			except: pass
	def _new_process():
		url = build_url({'mode': 'tmdblist.make_new_tmdb_list'})
		new_icon = kodi_utils.get_icon('new')
		listitem = kodi_utils.make_listitem()
		listitem.setLabel('[I]Make New TMDb List...[/I]')
		listitem.setArt({'icon': new_icon, 'poster': new_icon, 'thumb': new_icon, 'fanart': background, 'banner': background})
		info_tag = listitem.getVideoInfoTag(True)
		info_tag.setPlot(' ')
		yield (url, listitem, False)
	handle, icon, background = int(sys.argv[1]), kodi_utils.get_icon('tmdb'), kodi_utils.get_addon_fanart()
	tmdb_image_url = 'https://image.tmdb.org/t/p/%s%s'
	profile_path = kodi_utils.addon_profile()
	all_posters = kodi_utils.list_dirs(os.path.join(profile_path, 'images', 'tmdb_lists_poster'))[1]
	all_fanart = kodi_utils.list_dirs(os.path.join(profile_path, 'images', 'tmdb_lists_fanart'))[1]
	sort_orders = get_sort_orders()
	build_url = kodi_utils.build_url
	random, shuffle_lists = params.get('random', 'false') == 'true', params.get('shuffle', 'false') == 'true'
	returning_to_list = False
	try:
		data = get_all_tmdb_lists(get_setting('redlight.tmdblist.list_sort', '0'))
		if data:
			if shuffle_lists:
				returning_to_list = 'build_tmdb_lists_contents' in kodi_utils.folder_path()
				if returning_to_list:
					try: data = json.loads(kodi_utils.get_property('redlight.tmdb.lists.order'))
					except: pass
				else:
					shuffle(data)
					kodi_utils.set_property('redlight.tmdb.lists.order', json.dumps(data))
			else:
				kodi_utils.clear_property('redlight.tmdb.lists.order')
			result = list(_process())
		else: result = list(_new_process())
		kodi_utils.add_items(handle, result)
	except: pass
	kodi_utils.set_content(handle, kodi_utils.MENU_FOLDER_CONTENT)
	kodi_utils.set_category(handle, params.get('category_name', ''))
	if shuffle_lists and not returning_to_list: kodi_utils.focus_index(0)
	kodi_utils.end_directory(handle, cacheToDisc=not (random or shuffle_lists))
	kodi_utils.set_view_mode('view.main', kodi_utils.MENU_FOLDER_CONTENT)

def build_tmdb_list(params):
	def _process(function, _list, _type):
		if not _list['list']: return
		item_list_extend(function(_list).worker())
	def _paginate_list(data, page_no, paginate_start):
		if use_result: total_pages = 1
		elif paginate_enabled:
			limit = page_limit(is_external)
			data, total_pages = paginate_list(data, page_no, limit, paginate_start)
			if is_external: paginate_start = limit
		else: total_pages = 1
		return data, total_pages, paginate_start
	handle, is_external, content = int(sys.argv[1]), kodi_utils.external(), 'movies'
	hide_next_page = is_external and widget_hide_next_page()
	try:
		threads, item_list = [], []
		item_list_extend = item_list.extend
		user, slug, list_type = '', '', ''
		paginate_enabled = paginate(is_external)
		use_result = 'result' in params
		list_name, list_id, media_type, sort_order = params.get('list_name'), params.get('list_id'), params.get('media_type'), params.get('sort_order')
		page_no, paginate_start = int(params.get('new_page', '1')), int(params.get('paginate_start', '0'))
		new_params = {'mode': 'tmdblist.build_tmdb_list', 'list_id': list_id, 'list_name': list_name, 'media_type': media_type,
						'paginate_start': paginate_start, 'sort_order': sort_order}
		if page_no == 1 and not is_external: kodi_utils.set_property('redlight.exit_params', kodi_utils.list_collection_exit_params(params))
		if use_result: result = params.get('result', [])
		else: result = get_tmdb_list(params)
		result, total_pages, paginate_start = _paginate_list(result, page_no, paginate_start)
		all_movies = [dict(i, **{'order': c}) for c, i in enumerate(result) if i['media_type'] == 'movie']
		all_tvshows = [dict(i, **{'order': c}) for c, i in enumerate(result) if i['media_type'] == 'tv']
		movie_list = {'list': [(i['order'], i['id']) for i in all_movies], 'custom_order': 'true'}
		tvshow_list = {'list': [(i['order'], i['id']) for i in all_tvshows], 'custom_order': 'true'}
		content = max([('movies', len(all_movies)), ('tvshows', len(all_tvshows))], key=lambda k: k[1])[0]
		for item in ((Movies, movie_list, 'movies'), (TVShows, tvshow_list, 'tvshows')):
			threaded_object = Thread(target=_process, args=item)
			threaded_object.start()
			threads.append(threaded_object)
		[i.join() for i in threads]
		item_list.sort(key=lambda k: k[1])
		if use_result: return content, [i[0] for i in item_list]
		kodi_utils.add_items(handle, [i[0] for i in item_list])
		if total_pages > 2 and jump_to_enabled() and not is_external:
				kodi_utils.add_dir(handle, {'mode': 'navigate_to_page_choice', 'current_page': page_no, 'total_pages': total_pages, 'url_params': json.dumps(new_params)},
											'Jump To...', 'item_jump', kodi_utils.get_icon('item_jump_landscape'), isFolder=False)
		if total_pages > page_no and not hide_next_page:
			new_page = str(page_no + 1)
			new_params['new_page'] = new_page
			kodi_utils.add_dir(handle, new_params, 'Next Page (%s) >>' % new_page, 'nextpage', kodi_utils.get_icon('nextpage_landscape'))
	except: pass
	kodi_utils.set_content(handle, content)
	kodi_utils.set_category(handle, list_name)
	kodi_utils.end_directory(handle, cacheToDisc=False if is_external else True)
	if not is_external:
		if params.get('refreshed') == 'true': kodi_utils.sleep(1000)
		kodi_utils.set_view_mode('view.%s' % content, content, is_external)

def adjust_tmdb_list_properties(params):
	from modules import list_sort
	list_id = params.get('list_id')
	original_list_name = params.get('original_list_name', '')
	custom_poster, custom_fanart = params.get('custom_poster', ''), params.get('custom_fanart', '')
	current_name = params.get('list_name', '') or original_list_name
	# The sort_order carried in the URL is the legacy column, which nothing reads any more. The label
	# and the picker both go through the override store so the row states what the list actually does.
	# 'default:asc' is get_tmdb_list's fallback: no override means the list is served in TMDb order.
	current_sort = list_sort.resolve('tmdb:%s' % list_id, None, 'default:asc')
	choices = [('Change Name', 'Currently [B]%s[/B]' % (current_name), 'list_name'),
				('Change Sort Order', 'Currently [B]%s[/B]' % list_sort.spec_label(current_sort), 'sort_order'),
				('Make Custom Poster', '', 'make_poster'),
				('Make Custom Fanart', '', 'make_fanart')]
	if custom_poster: choices.append(('Delete Custom Poster', '', 'delete_poster'))
	if custom_fanart: choices.append(('Delete Custom Fanart', '', 'delete_fanart'))
	choices.extend([('Empty List Contents', 'Delete All Contents of %s' % current_name, 'empty_contents'),
					('Import Trakt List', 'Import a Trakt List into %s' % current_name, 'import_trakt')])
	list_items = [{'line1': item[0], 'line2': item[1] or item[0]} for item in choices]
	kwargs = {'items': json.dumps(list_items), 'heading': 'TMDb List Properties', 'multi_line': 'true', 'narrow_window': 'true'}
	action = kodi_utils.select_dialog([i[2] for i in choices], **kwargs)
	if action == None:
		if params.get('refresh_cache', 'false') == 'true': cache_delete_all_tmdb()
		elif params.get('refresh', 'false') == 'true': return kodi_utils.kodi_refresh()
		return None
	if action in ('make_poster', 'make_fanart'):
		art_type = 'Posters' if action == 'make_poster' else 'Fanart'
		shuffle_sort_order = kodi_utils.confirm_dialog(heading='TMDb Lists', text='Use [B]4 Random[/B] %s from List?[CR]OR[CR]Use [B]First 4[/B] %s from List?' % (art_type, art_type),
												ok_label='4 Random', cancel_label='First 4')
		if shuffle_sort_order == None: return adjust_tmdb_list_properties(params)
	if action == 'list_name':
		list_name = rename_tmdb_list(current_name, list_id)
		if not list_name: return adjust_tmdb_list_properties(params)
		current_name = list_name
		params.update({'list_name': current_name, 'refresh_cache': 'true'})
	elif action == 'sort_order':
		from caches.list_sort_cache import set_override
		from indexers.dialogs import _pick_sort_spec
		# No "Use Default" entry: a TMDb list is mixed media, so it has no mediatype default to fall
		# back to. The equivalent choice is the adapter's own 'default' field (Provider Default),
		# which stores 'default:asc' and hands back TMDb's ordering untouched.
		spec = _pick_sort_spec('List Sort Order', 'tmdb', current=current_sort)
		if spec == None: return adjust_tmdb_list_properties(params)
		if set_override('tmdb:%s' % list_id, list_sort.format_spec(spec)): params.update({'refresh': 'true'})
		else: kodi_utils.notification('Error Setting Sort Order', 3000)
	elif action == 'make_poster':
		new_poster = tmdb_image_maker(current_name, list_id, 'poster', custom_poster, shuffle_sort_order)
		if new_poster is None: return adjust_tmdb_list_properties(params)
		params.update({'custom_poster': new_poster, 'refresh': 'true'})
	elif action == 'make_fanart':
		new_fanart = tmdb_image_maker(current_name, list_id, 'fanart', custom_fanart, shuffle_sort_order)
		if new_fanart is None: return adjust_tmdb_list_properties(params)
		params.update({'custom_fanart': new_fanart, 'refresh': 'true'})
	elif action == 'delete_poster':
		success = delete_current_image(custom_poster)
		if not success: return adjust_tmdb_list_properties(params)
		params.update({'custom_poster': None, 'refresh': 'true'})
	elif action == 'delete_fanart':
		success = delete_current_image(custom_fanart)
		if not success: return adjust_tmdb_list_properties(params)
		params.update({'custom_fanart': None, 'refresh': 'true'})
	elif action == 'empty_contents':
		if not clear_tmdb_list(current_name, list_id): return adjust_tmdb_list_properties(params)
		params.update({'refresh_cache': 'true'})
	elif action == 'import_trakt':
		import_trakt_list_tmdb({'list_name': current_name, 'list_id': list_id})
		params.update({'refresh_cache': 'true'})
	return adjust_tmdb_list_properties(params)

def delete_current_image(custom_image):
	os.remove(custom_image)
	kodi_utils.sleep(1000)
	if kodi_utils.path_exists(custom_image): return False
	return True

def tmdb_image_maker(list_name, list_id, image_type, custom_image, shuffle_sort_order):
	from modules.utils import make_image
	kodi_utils.show_busy_dialog()
	content = get_tmdb_list({'list_id': list_id})
	if shuffle_sort_order: shuffle(content)
	images = []
	if image_type == 'poster': image_dimension, image_key = 'w780', 'poster_path'
	else: image_dimension, image_key = 'w1280', 'backdrop_path'
	for item in content:
		if item[image_key]: images.append('https://image.tmdb.org/t/p/%s%s' % (image_dimension, item[image_key]))
		if len(images) == 4: break
	final_image = make_image('tmdb_lists', image_type, list_name, images, custom_image)
	kodi_utils.hide_busy_dialog()
	return final_image

def _tmdb_media_type(media_type):
	if media_type in ('movie', 'movies'): return 'movie'
	return 'tv'

def _tmdb_list_remove_succeeded(data):
	if not data: return False
	results = data.get('results')
	if isinstance(results, list):
		if not results: return False
		return any(isinstance(i, dict) and i.get('success') for i in results)
	return bool(data.get('success'))

# TMDb Watchlist and Favorites are kept on the box like Mona: rows in the favourites table
# under their own db_type, so backups carry them and the table count never changes. Reads
# are local; a change is made here first and pushed to TMDb in the background.
_TMDB_ACCOUNT_SHELVES = ('watchlist', 'favorites')
_TMDB_SHELF_LABELS = {'watchlist': 'TMDb Watchlist', 'favorites': 'TMDb Favorites'}

def tmdb_shelf_db_type(list_type, media_type):
	return 'tmdb_%s_%s' % (list_type, 'movie' if _tmdb_media_type(media_type) == 'movie' else 'tvshow')

def tmdb_shelf_items(list_type, media_type):
	"""Local copy, oldest added first - the order TMDb serves the shelf in."""
	from caches.favorites_cache import favorites_cache
	return list(reversed(favorites_cache.get_favorites(tmdb_shelf_db_type(list_type, media_type))))

def _tmdb_title_for(media_type, media_id):
	try:
		from modules import metadata, settings
		from modules.utils import get_datetime
		function = metadata.movie_meta if _tmdb_media_type(media_type) == 'movie' else metadata.tvshow_meta
		meta = function('tmdb_id', media_id, settings.tmdb_api_key(), settings.mpaa_region(), get_datetime())
		return meta.get('title') or str(media_id)
	except: return str(media_id)

def add_remove_watchfavs(media_type, media_id, list_type, status, title=None):
	from caches.favorites_cache import favorites_cache
	db_type, media_id = tmdb_shelf_db_type(list_type, media_type), str(media_id)
	present = any(i['tmdb_id'] == media_id for i in favorites_cache.get_favorites(db_type))
	if status:
		if present: return True
		success = favorites_cache.set_favourite(db_type, media_id, title or _tmdb_title_for(media_type, media_id))
	else:
		if not present:
			kodi_utils.notify_not_in_list()
			return False
		success = favorites_cache.delete_favourite(db_type, media_id, '')
	if not success:
		kodi_utils.notify_error()
		return False
	tmdb_sync_after_change('account', media_type=media_type, list_type=list_type)
	return True

def add_to_tmdb_list(list_id, items, list_name=None, notify=True):
	data = tmdb_list_api.add_remove_from_list(list_id, items, 'post')
	if not data or not data.get('success'):
		if notify: kodi_utils.notify_error()
		return False
	if notify: kodi_utils.notify_added_to(list_name)
	return True

def remove_from_tmdb_list(list_id, items, list_name=None, notify=True):
	try:
		payload = {'items': []}
		for item in items.get('items', []):
			if not isinstance(item, dict): continue
			payload['items'].append({'media_type': _tmdb_media_type(item.get('media_type', '')), 'media_id': int(item.get('media_id'))})
		if not payload['items']: raise ValueError('no_items')
		data = tmdb_list_api.add_remove_from_list(list_id, payload, 'delete')
		if not _tmdb_list_remove_succeeded(data):
			if notify: kodi_utils.notify_not_in_list(settle_ms=300)
			return False
		if notify: kodi_utils.notify_removed_from(list_name)
		return True
	except:
		if notify: kodi_utils.notify_not_in_list(settle_ms=300)
		return False

def rename_tmdb_list(current_name, list_id):
	list_name = kodi_utils.kodi_dialog().input('Please Choose a Name for the New List', defaultt=current_name)
	if list_name == None: return None
	tmdb_list_api.rename_list(list_id, list_name)
	return list_name

def check_item_status(list_id, media_type, media_id):
	media_type = _tmdb_media_type(media_type)
	try: media_id = int(media_id)
	except: return False
	cached = tmdb_lists_cache.get('get_list_details_%s' % list_id)
	if cached is not None:
		try:
			return any(i.get('media_type') == media_type and int(i.get('id')) == media_id for i in cached)
		except: return False
	try:
		item_status = tmdb_list_api.item_status(list_id, media_type, media_id)
		return item_status.get('success', False) if item_status else False
	except: return False

def check_item_status_watchfav(list_id, media_type, media_id):
	try: return str(media_id) in [i['tmdb_id'] for i in tmdb_shelf_items(list_id, media_type)]
	except: return False

def tmdb_lists_split_by_membership(media_type, media_id):
	from modules.utils import TaskPool
	from modules.settings import max_threads
	results = []
	results_append = results.append
	def _check(item):
		list_id = item.get('id')
		if not list_id: return
		entry = {
			'name': item.get('name') or '',
			'id': list_id,
			'number_of_items': int(item.get('number_of_items') or 0)
		}
		results_append((entry, check_item_status(list_id, media_type, media_id)))
	all_lists = get_all_tmdb_lists('0') or []
	if not all_lists: return [], []
	threads = TaskPool().tasks(_check, all_lists, min(len(all_lists), max_threads()) or 1)
	[i.join() for i in threads]
	in_lists, out_lists = [], []
	for entry, is_in in results:
		(in_lists if is_in else out_lists).append(entry)
	in_lists.sort(key=lambda k: k['name'])
	out_lists.sort(key=lambda k: k['name'])
	return in_lists, out_lists

def select_tmdb_lists(lists):
	if not lists: return None
	choices = [('%s [I](x%02d)[/I]' % (i['name'], i.get('number_of_items', 0)), i['id']) for i in lists]
	list_items = [{'line1': i[0]} for i in choices]
	kwargs = {'items': json.dumps(list_items), 'narrow_window': 'true'}
	return kodi_utils.select_dialog([i[1] for i in choices], **kwargs)

def make_new_tmdb_list(params):
	suggested_list_name, chosen_list = '', None
	external_creation = params.get('external_creation', 'false') == 'true'
	if not external_creation and kodi_utils.confirm_dialog(heading='TMDb Lists', text='Import a Trakt List to populate this new list?',
																				ok_label='Yes', cancel_label='No'):
		from apis.trakt_api import get_trakt_list_selection
		chosen_list = get_trakt_list_selection(['default', 'personal'])
		if chosen_list == None:
			kodi_utils.notification(kodi_utils.LIST_CREATE_CANCELLED, 3000)
			return None
		suggested_list_name = chosen_list.get('name')
	list_name = kodi_utils.kodi_dialog().input('Please Choose a Name for the New TMDb List', defaultt=suggested_list_name)
	if not list_name:
		kodi_utils.notification(kodi_utils.LIST_CREATE_CANCELLED, 3000)
		return None
	list_name = unquote(list_name)
	data = tmdb_list_api.make_list(list_name)
	if not data or not data.get('success') or not data.get('id'):
		kodi_utils.notification(kodi_utils.LIST_CREATE_ERROR, 3000)
		return None
	if chosen_list:
		new_contents = process_trakt_list(chosen_list)
		success = process_add_to_list(data.get('id'), new_contents)
	tmdb_lists_cache.clear_all_lists()
	if not external_creation: kodi_utils.kodi_refresh()
	return data.get('id'), list_name

def delete_tmdb_list(params):
	if not kodi_utils.confirm_dialog(heading='TMDb Lists', text='Are You Sure?', ok_label='Yes', cancel_label='No'): return
	list_id = params['list_id']
	data = tmdb_list_api.delete_list(list_id)
	if not data.get('success'): return kodi_utils.notification('Error Deleting List')
	tmdb_lists_cache.clear_list(list_id)
	tmdb_lists_cache.clear_all_lists()
	kodi_utils.kodi_refresh()

def clear_tmdb_list(list_name, list_id):
	if not list_change_warning(list_name): return None
	data = tmdb_list_api.clear_list(list_id)
	if not data.get('success'):
		kodi_utils.notification('Error Clearing List Contents')
		return None
	tmdb_lists_cache.clear_list(list_id)
	tmdb_lists_cache.clear_all_lists()
	return True

def get_all_tmdb_lists(sort_order=None):
	contents = tmdb_list_api.get_user_lists() or []
	try:
		if sort_order:
			if sort_order in ('', '0', 'None'):
				contents = sort_for_article(contents, 'name', ignore_articles())
			elif sort_order in ('1', '2'):
				reverse = sort_order != '1'
				contents.sort(key=lambda k: (k['created_at'] is None, k['created_at']), reverse=reverse)
			elif sort_order in ('3', '4'):
				reverse = sort_order != '3'
				contents.sort(key=lambda k: (k['updated_at'] is None, k['updated_at']), reverse=reverse)
			elif sort_order in ('5', '6'):
				reverse = sort_order != '5'
				contents.sort(key=lambda k: (k['number_of_items'] is None, k['number_of_items']), reverse=reverse)
			elif sort_order in ('7', '8'):
				reverse = sort_order != '7'
				contents.sort(key=lambda k: (k['average_rating'] is None, k['average_rating']), reverse=reverse)
			elif sort_order in ('9', '10'):
				reverse = sort_order != '9'
				contents.sort(key=lambda k: (k['runtime'] is None, k['runtime']), reverse=reverse)
			elif sort_order in ('11', '12'):
				reverse = sort_order != '11'
				contents.sort(key=lambda k: (k['revenue'] is None, k['revenue']), reverse=reverse)
	except: pass
	return contents

def get_tmdb_list(params):
	list_id, media_type = params['list_id'], params.get('media_type')
	if list_id in _TMDB_ACCOUNT_SHELVES:
		contents = _tmdb_shelf_contents(list_id, media_type)
	elif list_id == 'recommendations':
		contents = [dict(i, **{'media_type': media_type}) for i in tmdb_list_api.get_watchfavrecs_list_details(list_id, media_type)]
	else:
		contents = tmdb_list_api.get_list_details(list_id)
	contents = [dict(i, **{'title': i.get('title') or i.get('name'), 'release_date': i.get('release_date') or i.get('first_air_date')}) for i in contents]
	from modules import list_sort
	# No override means the list was never sorted client-side: the old getters fell back to code 4
	# (original_order) for watchlist/favorites and to the stored 'None' for a user list. DEFAULT_SPEC
	# would reorder every one of them to title on upgrade, with no legacy row left to migrate.
	# Fixed shelves are media-split (tmdb.watchlist:movies / :shows) with media_type=None so
	# "Use Default" / no override keeps TMDb provider order via fallback — not Content → Movies/TV.
	# Custom My Lists stay mixed under tmdb:<id>.
	if list_id in ('watchlist', 'favorites', 'recommendations'):
		sort_media = 'movies' if media_type in ('movie', 'movies') else 'shows'
		return list_sort.sort_source(contents, 'tmdb.%s:%s' % (list_id, sort_media), None, 'tmdb', fallback='default:asc')
	return list_sort.sort_source(contents, 'tmdb:%s' % list_id, None, 'tmdb', fallback='default:asc')

def _tmdb_shelf_contents(list_type, media_type):
	"""The local shelf in the row shape the TMDb list builder and sorter expect."""
	from caches import list_sync_cache
	source = _tmdb_source_for('account', media_type=media_type, list_type=list_type)
	# First open after the update, before the service has run: fill the shelf from TMDb once
	# rather than show it empty.
	if not list_sync_cache.last_synced(_TMDB_SYNC_SERVICE, source['key']) and tmdblist_user_active():
		try: _tmdb_sync_source(source, None, allow_pick=False)
		except Exception as e: kodi_utils.logger('TMDb Sync', 'first fill failed: %s' % e)
	v4_type = _tmdb_media_type(media_type)
	contents = [{'id': int(i['tmdb_id']), 'title': i['title'], 'media_type': v4_type, 'original_order': c, 'release_date': ''}
				for c, i in enumerate(tmdb_shelf_items(list_type, media_type)) if str(i['tmdb_id']).isdigit()]
	# Release dates are not stored. Only a release date sort needs them, so only then are they
	# read from the metadata cache, fetching the few titles it does not hold yet - no extra
	# work for every other sort.
	try:
		from modules import list_sort
		sort_media = 'movies' if v4_type == 'movie' else 'shows'
		if list_sort.resolve('tmdb.%s:%s' % (list_type, sort_media), None, 'default:asc').get('field') == 'release_date':
			from caches.meta_cache import meta_cache
			meta_type = 'movie' if v4_type == 'movie' else 'tvshow'
			missing = []
			for item in contents:
				meta = meta_cache.get(meta_type, 'tmdb_id', item['id'])
				if meta: item['release_date'] = meta.get('premiered') or ''
				else: missing.append(item)
			if missing:
				from modules import metadata, settings
				from modules.utils import TaskPool, get_datetime
				function = metadata.movie_meta if v4_type == 'movie' else metadata.tvshow_meta
				api_key, mpaa_region, current_date = settings.tmdb_api_key(), settings.mpaa_region(), get_datetime()
				def _fetch(item):
					try: item['release_date'] = (function('tmdb_id', item['id'], api_key, mpaa_region, current_date) or {}).get('premiered') or ''
					except: pass
				[i.join() for i in TaskPool().tasks(_fetch, missing, settings.max_threads())]
	except: pass
	return contents

def cache_delete_all_tmdb(params=None):
	tmdb_lists_cache.clear_all()
	kodi_utils.notification('Success')
	kodi_utils.kodi_refresh()

def cache_delete_list_tmdb(params):
	tmdb_lists_cache.clear_list(params['list_id'])
	tmdb_lists_cache.clear_all_lists()
	kodi_utils.notification('Success')
	kodi_utils.kodi_refresh()

def import_trakt_list_tmdb(params):
	if not list_change_warning(params['list_name']): return None
	from apis.trakt_api import get_trakt_list_selection
	list_id = params.get('list_id', '')
	chosen_list = get_trakt_list_selection(['default', 'personal'])
	if chosen_list == None: return None
	if kodi_utils.confirm_dialog(heading='TMDb Lists', text='Rename List to Match Trakt List Name?', ok_label='Yes', cancel_label='No'): rename_list = True
	else: rename_list = False
	trakt_list_name = chosen_list.get('name')
	new_contents = process_trakt_list(chosen_list)
	success = process_add_to_list(list_id, new_contents)
	if success and rename_list:
			tmdb_list_api.rename_list(list_id, trakt_list_name)
	kodi_utils.notify_success() if success else kodi_utils.notify_error()

def process_trakt_list(chosen_list):
	from apis.trakt_api import trakt_fetch_collection_watchlist, get_trakt_list_contents
	tmdb_media_converter = {'movie': 'movie', 'tvshow': 'tv', 'show': 'tv'}
	media_type_check = {'movie': 'movie', 'show': 'tvshow', 'tvshow': 'tvshow'}
	new_contents = []
	new_contents_append = new_contents.append
	trakt_list_type, trakt_list_name = chosen_list.get('list_type'), chosen_list.get('name')
	if trakt_list_type in ('collection', 'watchlist'):
		trakt_media_type = chosen_list.get('media_type')
		result = trakt_fetch_collection_watchlist(trakt_list_type, trakt_media_type)
		try:
			from modules import list_sort
			result = list_sort.sort_source(result, 'trakt.%s' % trakt_list_type, trakt_media_type, 'trakt_sync')
		except: pass
	else:
		result = get_trakt_list_contents(trakt_list_type, chosen_list.get('user'), chosen_list.get('slug'), trakt_list_type == 'my_lists')
		try: result.sort(key=lambda k: (k['order']))
		except: pass
	for item in result:
		try:
			media_type = item.get('type') or media_type_check[trakt_media_type]
			if trakt_list_type in ('my_lists', 'liked_lists') and item['type'] not in ('movie', 'show'): continue
			media_id = item['media_ids']['tmdb']
			if media_id in (None, 'None', ''): continue
			new_contents_append({'media_type': tmdb_media_converter[media_type], 'media_id': media_id})
		except: continue
	return new_contents

_TMDB_FAV_LINK_SETTING = {'movie': 'tmdb.link_favorites_movie', 'tvshow': 'tmdb.link_favorites_tvshow'}
_TMDB_SYNC_SERVICE = 'tmdb'

def _tmdb_send_sources():
	"""Everything syncable: local personal lists, each half of Favourites, and TMDb's own
	Watchlist and Favorites."""
	from caches import personal_lists_cache, favorites_cache
	sources = []
	for row in personal_lists_cache.personal_lists_cache.get_lists():
		sources.append({'kind': 'personal', 'label': row['name'], 'list_name': row['name'],
						'author': row['author'], 'total': row['total'] or 0,
						'key': 'personal:%s|%s' % (row['name'], row['author'])})
	for media_type, label in (('movie', "Mona's Movies"), ('tvshow', "Mona's TV Shows")):
		favs = favorites_cache.favorites_cache.get_favorites(media_type)
		sources.append({'kind': 'favorites', 'label': label, 'media_type': media_type,
						'total': len(favs), 'key': 'favorites:%s' % media_type})
	for list_type in _TMDB_ACCOUNT_SHELVES:
		for media_type in ('movie', 'tvshow'):
			source = _tmdb_source_for('account', media_type=media_type, list_type=list_type)
			source['total'] = len(tmdb_shelf_items(list_type, media_type))
			sources.append(source)
	return sources

def _tmdb_local_members(source):
	"""Local membership as {(media_type, media_id)}, in TMDb's v4 vocabulary."""
	if source['kind'] == 'account':
		raw = [{'media_id': i['tmdb_id'], 'type': source['media_type']} for i in tmdb_shelf_items(source['list_type'], source['media_type'])]
	elif source['kind'] == 'favorites':
		from caches import favorites_cache
		media_type = source['media_type']
		raw = [{'media_id': i['tmdb_id'], 'type': media_type} for i in favorites_cache.favorites_cache.get_favorites(media_type)]
	else:
		from caches import personal_lists_cache
		raw = personal_lists_cache.personal_lists_cache.get_list(source['list_name'], source['author'], update_seen=False)
	members = set()
	for item in raw or []:
		try: media_id = int(str(item.get('media_id') or '').strip())
		except: continue
		if media_id > 0: members.add((_tmdb_media_type(item.get('type') or 'movie'), media_id))
	return members

def _tmdb_remote_members(list_id):
	"""Live membership of the TMDb list, plus the titles it already gave us.

	Returns (members, titles). members is None when the fetch failed - a failure must
	never be read as "the list is empty", or a mirror would wipe both sides.
	"""
	tmdb_lists_cache.clear_list(list_id)
	results = tmdb_list_api.get_list_details(list_id)
	if not isinstance(results, list): return None, {}
	members, titles = set(), {}
	for item in results:
		try: media_id = int(item.get('id'))
		except: continue
		media_type = 'tv' if (item.get('media_type') or '').lower() in ('tv', 'tvshow', 'show') else 'movie'
		key = (media_type, media_id)
		members.add(key)
		titles[key] = item.get('title') or item.get('name') or str(media_id)
	return members, titles

def _tmdb_account_url(list_type, media_type):
	return '%s/account/%s/%s/%s' % (tmdb_list_api.base_url, get_setting('redlight.tmdb.account_id'), _tmdb_media_type(media_type), list_type)

def _tmdb_account_remote_members(list_type, media_type):
	"""Live membership of a Watchlist or Favorites shelf, oldest added first.

	Pages are read one after another and any failed page fails the whole read: a partial
	read would look like removals on TMDb and delete them here.
	"""
	url, v4_type = _tmdb_account_url(list_type, media_type), _tmdb_media_type(media_type)
	members, titles, page, total_pages = set(), {}, 1, 1
	while page <= total_pages:
		result = tmdb_list_api.request_data(url, params={'page': page, 'sort_by': 'created_at.asc'})
		if not isinstance(result, dict) or not isinstance(result.get('results'), list): return None, {}
		total_pages = result.get('total_pages') or 1
		for item in result['results']:
			try: key = (v4_type, int(item.get('id')))
			except: continue
			members.add(key)
			titles[key] = item.get('title') or item.get('name') or str(key[1])
		page += 1
	return members, titles

def _tmdb_account_stamp(list_type, media_type):
	"""One small request: the shelf's size plus its newest page. An add or a removal on the
	TMDb website changes one or the other. None when the request failed."""
	result = tmdb_list_api.request_data(_tmdb_account_url(list_type, media_type), params={'page': 1, 'sort_by': 'created_at.desc'})
	if not isinstance(result, dict) or not isinstance(result.get('results'), list): return None
	return '%s|%s' % (result.get('total_results') or 0, ','.join(str(i.get('id')) for i in result['results']))

def _tmdb_account_push(source, to_add, to_remove):
	"""Watchlist and Favorites take one title per request. True only if every one landed."""
	for status, members in ((True, to_add), (False, to_remove)):
		for media_type, media_id in sorted(members):
			data = tmdb_list_api.add_remove_from_watchfavs(media_type, media_id, source['list_type'], status)
			if not data or not data.get('success'): return False
	return True

def _tmdb_write_local(source, members, titles=None):
	"""Make the local list match `members` exactly."""
	titles = titles or {}
	if source['kind'] == 'account':
		from caches.favorites_cache import favorites_cache
		db_type = tmdb_shelf_db_type(source['list_type'], source['media_type'])
		wanted = set(i[1] for i in members)
		current = set(int(i['tmdb_id']) for i in favorites_cache.get_favorites(db_type) if str(i['tmdb_id']).isdigit())
		for media_id in current - wanted: favorites_cache.delete_favourite(db_type, media_id, '')
		# titles is in TMDb's order, so new rows land in the order they were added there.
		new_keys = [key for key in titles if key[1] in wanted - current]
		new_keys += [key for key in members if key[1] in wanted - current and key not in titles]
		for key in new_keys: favorites_cache.set_favourite(db_type, key[1], titles.get(key) or str(key[1]))
		return True
	if source['kind'] == 'favorites':
		from caches import favorites_cache
		cache, media_type = favorites_cache.favorites_cache, source['media_type']
		wanted = set(i[1] for i in members)
		current = {int(i['tmdb_id']): i['title'] for i in cache.get_favorites(media_type) if str(i['tmdb_id']).isdigit()}
		for media_id in set(current) - wanted: cache.delete_favourite(media_type, media_id, current.get(media_id, ''))
		for media_id in wanted - set(current):
			key = ('tv' if media_type == 'tvshow' else 'movie', media_id)
			cache.set_favourite(media_type, media_id, titles.get(key) or str(media_id))
		return True
	from caches import personal_lists_cache
	cache = personal_lists_cache.personal_lists_cache
	existing = {}
	for item in cache.get_list(source['list_name'], source['author'], update_seen=False) or []:
		try: existing[(_tmdb_media_type(item.get('type') or 'movie'), int(item.get('media_id')))] = item
		except: continue
	contents = []
	for key in members:
		item = existing.get(key)
		if item: contents.append(item)
		else:
			media_type, media_id = key
			local_type = 'tvshow' if media_type == 'tv' else 'movie'
			contents.append({'media_id': str(media_id), 'title': titles.get(key) or str(media_id),
							'type': local_type, 'release_date': '', 'date_added': str(int(time.time()))})
	return cache.set_list_contents(source['list_name'], source['author'], contents)

def _tmdb_source_link(source):
	# Watchlist and Favorites belong to the account itself, so they are always linked.
	if source['kind'] == 'account': return 'account:%s' % source['list_type'] if tmdblist_user_active() else None
	if source['kind'] == 'favorites':
		value = get_setting('redlight.%s' % _TMDB_FAV_LINK_SETTING[source['media_type']], 'empty_setting')
		return None if value in (None, '', '0', 'empty_setting') else str(value)
	from caches import personal_lists_cache
	return personal_lists_cache.personal_lists_cache.get_service_link('tmdb', source['list_name'], source['author'])

def _tmdb_set_source_link(source, list_id):
	if source['kind'] == 'account': return
	if source['kind'] == 'favorites':
		set_setting(_TMDB_FAV_LINK_SETTING[source['media_type']], str(list_id) if list_id else 'empty_setting')
		return
	from caches import personal_lists_cache
	personal_lists_cache.personal_lists_cache.set_service_link('tmdb', source['list_name'], source['author'], list_id)

def _tmdb_pick_target(source, user_lists):
	"""Pick or create the TMDb list this source mirrors. Returns (list_id, cancelled)."""
	choices = [{'name': '[I]Create a new TMDb list (private)...[/I]', 'id': None}]
	choices += [{'name': i.get('name') or 'TMDb List', 'id': i.get('id')} for i in user_lists]
	display = [{'line1': i['name']} for i in choices]
	chosen = kodi_utils.select_dialog(choices, items=json.dumps(display), heading='Link "%s" to' % source['label'], narrow_window='true')
	if chosen is None: return None, True
	if chosen['id'] is not None: return str(chosen['id']), False
	new_name = kodi_utils.kodi_dialog().input('Name for the new TMDb list', defaultt=source['label'])
	if not new_name: return None, True
	data = tmdb_list_api.make_list(unquote(new_name))
	if not data or not data.get('success') or not data.get('id'):
		kodi_utils.notification(kodi_utils.LIST_CREATE_ERROR, 3000)
		return None, False
	tmdb_lists_cache.clear_all_lists()
	return str(data.get('id')), False

def _tmdb_payload(members):
	return [{'media_type': i[0], 'media_id': i[1]} for i in sorted(members)]

def _tmdb_mirror(local, remote, snapshot):
	"""Agreed membership after mirroring. Pure set logic, no side effects.

	snapshot is what both sides agreed on last time. Anything that has gone missing
	from a side since then was deleted there, and that deletion is honoured. With no
	snapshot (first sync) nothing is treated as a deletion, so the two sides merge and
	nothing can be lost.
	"""
	if not snapshot: return local | remote
	removed_local = snapshot - local
	removed_remote = snapshot - remote
	return (local | remote) - removed_local - removed_remote

def _tmdb_sync_source(source, user_lists, allow_pick=True):
	"""Mirror one local list against its TMDb list.

	Returns (message, changed). `changed` is what decides whether widgets get
	refreshed - most runs find nothing to do, and a pointless refresh is the one
	cost the user actually feels. Pass user_lists=None to skip validating that the
	linked list still exists, which saves a request on the open-a-list path.
	"""
	from caches import list_sync_cache
	is_account = source['kind'] == 'account'
	list_id = _tmdb_source_link(source)
	if is_account:
		if not list_id: return '%s: TMDb account not authorised' % source['label'], False
	elif list_id and user_lists is not None and not any(str(i.get('id')) == str(list_id) for i in user_lists):
		_tmdb_set_source_link(source, None)
		list_sync_cache.clear_snapshot(_TMDB_SYNC_SERVICE, source['key'])
		list_id = None
	if not list_id:
		if not allow_pick: return '%s: not linked yet' % source['label'], False
		list_id, cancelled = _tmdb_pick_target(source, user_lists)
		if cancelled: return '%s: cancelled' % source['label'], False
		if not list_id: return '%s: could not create the list' % source['label'], False
		_tmdb_set_source_link(source, list_id)
		list_sync_cache.clear_snapshot(_TMDB_SYNC_SERVICE, source['key'])
	local = _tmdb_local_members(source)
	if is_account: remote, titles = _tmdb_account_remote_members(source['list_type'], source['media_type'])
	else: remote, titles = _tmdb_remote_members(list_id)
	if remote is None: return '%s: could not read the TMDb list, skipped' % source['label'], False
	snapshot = list_sync_cache.get_snapshot(_TMDB_SYNC_SERVICE, source['key'])
	final = _tmdb_mirror(local, remote, snapshot)
	to_add_remote = final - remote
	to_remove_remote = remote - final
	pushed = True
	if is_account:
		if to_add_remote or to_remove_remote: pushed = _tmdb_account_push(source, to_add_remote, to_remove_remote)
	else:
		if to_add_remote:
			pushed = add_to_tmdb_list(list_id, {'items': _tmdb_payload(to_add_remote)}, notify=False)
		if pushed and to_remove_remote:
			pushed = remove_from_tmdb_list(list_id, {'items': _tmdb_payload(to_remove_remote)}, list_name=source['label'], notify=False)
	if not pushed: return '%s: TMDb rejected the change, nothing saved' % source['label'], False
	if final != local: _tmdb_write_local(source, final, titles)
	if is_account: tmdb_lists_cache.clear_watchfavrecs(source['list_type'], _tmdb_media_type(source['media_type']))
	else:
		tmdb_lists_cache.clear_list(list_id)
		tmdb_lists_cache.clear_all_lists()
	list_sync_cache.set_snapshot(_TMDB_SYNC_SERVICE, source['key'], list_id, final)
	if is_account:
		# Stamp the shelf as it now stands, so the poll does not re-read what this run just did.
		stamp = _tmdb_account_stamp(source['list_type'], source['media_type'])
		if stamp: list_sync_cache.set_remote_stamp(_TMDB_SYNC_SERVICE, source['key'], list_id, stamp)
	up, down = len(to_add_remote), len(final - local)
	gone_up, gone_down = len(to_remove_remote), len(local - final)
	if not any((up, down, gone_up, gone_down)): return '%s: already in step (%s)' % (source['label'], len(final)), False
	bits = []
	if up: bits.append('%s up' % up)
	if down: bits.append('%s down' % down)
	if gone_up: bits.append('%s removed on TMDb' % gone_up)
	if gone_down: bits.append('%s removed here' % gone_down)
	return '%s: %s' % (source['label'], ', '.join(bits)), True

_change_sync_lock = Lock()
_change_sync_busy = set()
_change_sync_dirty = set()

def _tmdb_source_for(kind, list_name=None, author=None, media_type=None, list_type=None):
	if kind == 'account':
		media_type = 'movie' if _tmdb_media_type(media_type) == 'movie' else 'tvshow'
		label = '%s: %s' % (_TMDB_SHELF_LABELS[list_type], 'Movies' if media_type == 'movie' else 'TV Shows')
		return {'kind': 'account', 'label': label, 'list_type': list_type, 'media_type': media_type,
				'total': 0, 'key': 'account:%s:%s' % (list_type, media_type)}
	if kind == 'favorites':
		return {'kind': 'favorites', 'label': 'Favourites', 'media_type': media_type,
				'total': 0, 'key': 'favorites:%s' % media_type}
	author = author or 'Unknown'
	return {'kind': 'personal', 'label': list_name, 'list_name': list_name, 'author': author,
			'total': 0, 'key': 'personal:%s|%s' % (list_name, author)}

def tmdb_sync_after_change(kind, list_name=None, author=None, media_type=None, list_type=None):
	"""Push a local add or remove straight up to TMDb, in the background.

	Runs off the UI thread so adding to a list stays instant, and only ever touches
	the one list that changed. If that list is already syncing the call is not run
	twice - it marks the list dirty and the run in flight goes round once more, since
	it may have read the list before this change landed.
	"""
	try:
		if get_setting('redlight.tmdb.list_sync_on_change', 'true') != 'true': return False
		if not tmdblist_user_active(): return False
		source = _tmdb_source_for(kind, list_name, author, media_type, list_type)
		if not _tmdb_source_link(source): return False
		with _change_sync_lock:
			if source['key'] in _change_sync_busy:
				_change_sync_dirty.add(source['key'])
				return False
			_change_sync_busy.add(source['key'])
		def _run():
			try:
				while True:
					with _change_sync_lock: _change_sync_dirty.discard(source['key'])
					_tmdb_sync_source(source, None, allow_pick=False)
					with _change_sync_lock:
						if source['key'] not in _change_sync_dirty: break
			except Exception as e: kodi_utils.logger('TMDb Sync', 'on change failed: %s' % e)
			finally:
				with _change_sync_lock:
					_change_sync_busy.discard(source['key'])
					_change_sync_dirty.discard(source['key'])
		Thread(target=_run, daemon=True).start()
		return True
	except Exception as e:
		kodi_utils.logger('TMDb Sync', 'on change skipped: %s' % e)
		return False

def tmdb_poll_lists(params=None):
	"""One request: has any linked list changed on TMDb? Sync only the ones that did.

	This is the cheap check that makes a short interval affordable. TMDb returns a
	last-changed marker per list, so an idle poll is a single small request, no list
	downloads, no database writes and no widget redraw.

	Watchlist and Favorites have no such marker, so each of the four costs one more small
	request (its size and newest page). Only a shelf whose answer moved is read in full.
	"""
	from caches import list_sync_cache
	if not tmdblist_user_active(): return 'no account'
	sources = [i for i in _tmdb_send_sources() if _tmdb_source_link(i)]
	if not sources: return 'nothing linked'
	stamps = {}
	if any(i['kind'] != 'account' for i in sources):
		tmdb_lists_cache.clear_all_lists()
		user_lists = tmdb_list_api.get_user_lists() or []
		if isinstance(user_lists, dict): user_lists = user_lists.get('results') or []
		for item in user_lists:
			list_id = str(item.get('id'))
			# number_of_items covers the case of a list edited twice within one timestamp tick.
			stamps[list_id] = '%s|%s' % (item.get('updated_at') or '', item.get('number_of_items') or item.get('item_count') or '')
	changed = False
	for source in sources:
		list_id = str(_tmdb_source_link(source))
		if source['kind'] == 'account': stamp = _tmdb_account_stamp(source['list_type'], source['media_type'])
		else: stamp = stamps.get(list_id)
		if stamp is None: continue
		if stamp == list_sync_cache.get_remote_stamp(_TMDB_SYNC_SERVICE, source['key']): continue
		_, source_changed = _tmdb_sync_source(source, None, allow_pick=False)
		changed = changed or source_changed
		# An account shelf stamps itself at the end of a successful sync.
		if source['kind'] != 'account': list_sync_cache.set_remote_stamp(_TMDB_SYNC_SERVICE, source['key'], list_id, stamp)
	if changed: kodi_utils.kodi_refresh()
	return 'success'

def tmdb_sync_lists(params=None, silent=False):
	"""Two way sync between the local lists and their TMDb twins.

	Anything added on TMDb from a browser comes down; anything added on this box goes
	up; a removal on either side is applied to the other.
	"""
	if not tmdblist_user_active():
		if not silent: kodi_utils.notification('TMDb account not authorised', 3000)
		return 'no account'
	sources = _tmdb_send_sources()
	if not sources:
		if not silent: kodi_utils.notification('Nothing to sync', 3000)
		return 'nothing'
	user_lists = tmdb_list_api.get_user_lists() or []
	if isinstance(user_lists, dict): user_lists = user_lists.get('results') or []
	if silent:
		linked = [i for i in sources if _tmdb_source_link(i)]
		if not linked: return 'nothing linked'
		changed = False
		for source in linked:
			_, source_changed = _tmdb_sync_source(source, user_lists, allow_pick=False)
			changed = changed or source_changed
		# Only redraw when something actually moved: an unconditional refresh every run
		# is the one cost that shows up on screen.
		if changed: kodi_utils.kodi_refresh()
		return 'success'
	linked_count = len([i for i in sources if _tmdb_source_link(i)])
	rows = []
	if linked_count:
		rows.append({'label': '[B]Sync all %s linked lists now[/B]' % linked_count, 'source': None})
	for source in sources:
		target = _tmdb_source_link(source)
		if source['kind'] == 'account': name = 'TMDb' if target else None
		else: name = next((i.get('name') for i in user_lists if str(i.get('id')) == str(target)), None) if target else None
		status = '[COLOR lime]<-> %s[/COLOR]' % name if name else '[COLOR grey]not linked[/COLOR]'
		rows.append({'label': '%s [I](x%s)[/I]  %s' % (source['label'], source['total'], status), 'source': source})
	display = [{'line1': i['label']} for i in rows]
	chosen = kodi_utils.select_dialog(rows, items=json.dumps(display), heading='Sync with TMDb', narrow_window='true')
	if chosen is None: return
	kodi_utils.show_busy_dialog()
	try:
		if chosen['source'] is not None: outcomes = [_tmdb_sync_source(chosen['source'], user_lists)]
		else: outcomes = [_tmdb_sync_source(i, user_lists, allow_pick=False) for i in sources if _tmdb_source_link(i)]
	finally:
		kodi_utils.hide_busy_dialog()
	kodi_utils.ok_dialog(heading='TMDb Sync', text='[CR]'.join(i[0] for i in outcomes), scroll=True)
	if any(i[1] for i in outcomes): kodi_utils.kodi_refresh()
	return 'success'

def tmdb_send_lists(params=None):
	"""Kept so an older context menu entry still works."""
	return tmdb_sync_lists(params)

def process_add_to_list(list_id, new_contents):
	success = False
	kodi_utils.show_busy_dialog()
	try:
		if add_to_tmdb_list(list_id, {'items': new_contents}, notify=False):
			success = True
			tmdb_lists_cache.clear_list(list_id)
			tmdb_lists_cache.clear_all_lists()
		else: pass
	except: pass
	kodi_utils.hide_busy_dialog()
	return success

def get_sort_orders():
	return tmdb_lists_cache.get_sort_orders()

def list_change_warning(list_name, text='[B]CAUTION!!![/B][CR][CR]This will change the contents of [B]%s[/B]. Continue?'):
	return kodi_utils.confirm_dialog(heading='TMDb Lists', text=text % list_name, ok_label='Yes', cancel_label='No')

