# -*- coding: utf-8 -*-
import sys
import json
import random
from datetime import date
from modules.sources import Sources
from modules.settings import date_offset, watched_indicators, ignore_articles, playback_key, max_threads, tmdb_api_key, mpaa_region
from modules.metadata import tvshow_meta, episodes_meta, all_episodes_meta
from modules.watched_status import get_watched_status_episode, get_next_episodes, get_hidden_progress_items, watched_info_episode, get_next
from modules.utils import adjust_premiered_date, get_datetime, title_key, TaskPool
from modules import kodi_utils
# logger = kodi_utils.logger

def _log_nextep_skip(title, season, episode, reason):
	try:
		kodi_utils.logger('Red Light', 'Next episode prep skipped: %s S%02dE%02d (%s)' % (title, int(season), int(episode), reason))
	except:
		pass

class EpisodeTools:
	def __init__(self, meta, nextep_settings=None):
		self.meta = meta
		self.meta_get = self.meta.get
		self.nextep_settings = nextep_settings

	def next_episode_info(self):
		title = self.meta_get('title') or ''
		current_season, current_episode = 0, 0
		try:
			play_type = self.nextep_settings['play_type']
			season_data = self.meta_get('season_data')
			watch_count = self.meta_get('watch_count')
			current_season, current_episode = int(self.meta_get('season')), int(self.meta_get('episode'))
			watched_info = watched_info_episode(self.meta_get('tmdb_id'))
			season, episode = get_next(current_season, current_episode, watched_info, season_data, 0, self.meta)
			if season is None or episode is None:
				_log_nextep_skip(title, current_season, current_episode, 'no next episode')
				return 'no_next_episode'
			kodi_utils.logger('Red Light', 'Next episode prep target: %s S%02dE%02d (literal next)' % (title, season, episode))
			playcount = get_watched_status_episode(watched_info, (season, episode))
			ep_data = episodes_meta(season, self.meta)
			if not ep_data:
				_log_nextep_skip(title, season, episode, 'episode list unavailable')
				return 'no_next_episode'
			ep_data = next((i for i in ep_data if i['episode'] == episode), None)
			if not ep_data:
				_log_nextep_skip(title, season, episode, 'episode not in metadata')
				return 'no_next_episode'
			adjust_hours, current_date = date_offset(), get_datetime()
			episode_date, premiered = adjust_premiered_date(ep_data['premiered'], adjust_hours)
			if not episode_date or current_date < episode_date:
				_log_nextep_skip(title, season, episode, 'episode not aired yet')
				return 'no_next_episode'
			custom_title = self.meta_get('custom_title', None)
			title = custom_title or self.meta_get('title')
			display_name = '%s - %dx%.2d' % (title, int(season), int(episode))
			self.meta.update({'media_type': 'episode', 'rootname': display_name, 'season': season, 'ep_name': ep_data['title'], 'ep_thumb': ep_data.get('thumb', None),
							'episode': episode, 'premiered': premiered, 'plot': ep_data['plot']})
			url_params = {'media_type': 'episode', 'tmdb_id': self.meta_get('tmdb_id'), 'tvshowtitle': self.meta_get('rootname'), 'season': season, 'playcount': playcount,
						'episode': episode, 'background': 'true', 'nextep_settings': self.nextep_settings, 'play_type': play_type, 'watch_count': watch_count}
			if custom_title: url_params['custom_title'] = custom_title
			if 'custom_year' in self.meta: url_params['custom_year'] = self.meta_get('custom_year')
		except Exception as exc:
			kodi_utils.logger('Red Light', 'Next episode prep error: %s S%02dE%02d (%s)' % (title, current_season, current_episode, exc))
			url_params = 'error'
		return self.add_playback_key(url_params)

	def get_random_episode(self, continual=False, first_run=True):
		try:
			adjust_hours, current_date = date_offset(), get_datetime()
			tmdb_id = self.meta_get('tmdb_id')
			tmdb_key = str(tmdb_id)
			ep_meta = all_episodes_meta(self.meta)
			episodes_data = [i for i in ep_meta if i['premiered'] and adjust_premiered_date(i['premiered'], adjust_hours)[0] <= current_date]
			if continual:
				episode_list = []
				try:
					episode_history = json.loads(kodi_utils.get_property('redlight.random_episode_history'))
					if tmdb_key in episode_history: episode_list = episode_history[tmdb_key]
					else: kodi_utils.set_property('redlight.random_episode_history', '')
				except: kodi_utils.set_property('redlight.random_episode_history', '')
				episodes_data = [i for i in episodes_data if not i in episode_list]
				if not episodes_data:
					kodi_utils.set_property('redlight.random_episode_history', '')
					return self.get_random_episode(continual=True)
			chosen_episode = random.choice(episodes_data)
			if continual:
				episode_list.append(chosen_episode)
				episode_history = {tmdb_key: episode_list}
				kodi_utils.set_property('redlight.random_episode_history', json.dumps(episode_history))
			title, season, episode = self.meta['title'], int(chosen_episode['season']), int(chosen_episode['episode'])
			watched_info = watched_info_episode(tmdb_id)
			playcount = get_watched_status_episode(watched_info, (season, episode))
			query = title + ' S%.2dE%.2d' % (season, episode)
			display_name = '%s - %dx%.2d' % (title, season, episode)
			ep_name, plot = chosen_episode['title'], chosen_episode['plot']
			ep_thumb = chosen_episode.get('thumb', None)
			try: premiered = adjust_premiered_date(chosen_episode['premiered'], adjust_hours)[1]
			except: premiered = chosen_episode['premiered']
			self.meta.update({'media_type': 'episode', 'rootname': display_name, 'season': season, 'ep_name': ep_name, 'ep_thumb': ep_thumb,
							'episode': episode, 'premiered': premiered, 'plot': plot})
			url_params = {'media_type': 'episode', 'tmdb_id': tmdb_id, 'tvshowtitle': self.meta_get('rootname'), 'season': season, 'episode': episode,
						'playcount': playcount, 'autoplay': 'true'}
			if continual:
				url_params['random_continual'] = 'true'
				url_params['watch_count'] = self.meta_get('watch_count', 1)
			else: url_params['random'] = 'true'
			if not first_run:
				url_params['background'] = 'true'
				url_params['play_type'] = 'random_continual'
				url_params['autoplay'] = 'true'
				url_params['random_continual'] = 'true'
		except: url_params = 'error'
		return self.add_playback_key(url_params)

	def play_random(self):
		url_params = self.get_random_episode()
		if url_params == 'error': return kodi_utils.notification('Single Random Play Error', 3000)
		return Sources().playback_prep(url_params)

	def play_random_continual(self, first_run=True, from_skip=False):
		url_params = self.get_random_episode(continual=True, first_run=first_run)
		if url_params == 'error': return kodi_utils.notification('Continual Random Play Error', 3000)
		if from_skip and isinstance(url_params, dict):
			url_params['continual_skip'] = 'true'
		return Sources().playback_prep(url_params)

	def auto_nextep(self):
		url_params = self.next_episode_info()
		if url_params == 'error': return kodi_utils.notification('Next Episode Error', 3000)
		elif url_params == 'no_next_episode':
			kodi_utils.set_property('redlight.nextep_prep_declined', 'true')
			return
		return Sources().playback_prep(url_params)

	def add_playback_key(self, url_params):
		_key = playback_key()
		url_params[_key] = _key
		return url_params

NEXTEP_MANAGER_FILTERS = (('all', 'All'), ('dropped', 'Dropped'), ('active', 'Not Dropped'))

def build_next_episode_manager(params={}):
	def _process(item):
		try:
			tmdb_id, title = item['media_ids']['tmdb'], item['title']
			dropped = int(tmdb_id) in hidden_list
			if show_filter == 'dropped' and not dropped: return
			if show_filter == 'active' and dropped: return
			listitem = make_listitem()
			if dropped: display, action = 'Undrop [B]%s[/B] [COLOR=red][DROPPED][/COLOR]' % title, 'undrop'
			else: display, action = 'Drop [B]%s[/B]' % title, 'drop'
			url_params = {'mode': mode, 'action': action, 'media_type': 'shows', 'media_id': tmdb_id, 'section': 'dropped'}
			url = build_url(url_params)
			listitem.setLabel(display)
			# Show art from the saved show details, so the skin shows the poster like other TV lists.
			try: meta = tvshow_meta('tmdb_id', str(tmdb_id), api_key, mpaa_region_value, current_date) or {}
			except: meta = {}
			poster, fanart = meta.get('poster') or icon, meta.get('fanart') or addon_fanart
			# No clear logo: skins would draw it instead of the Drop / Undrop text and the [DROPPED] tag.
			listitem.setArt({'poster': poster, 'thumb': poster, 'icon': poster, 'fanart': fanart, 'landscape': meta.get('landscape') or fanart})
			info_tag = listitem.getVideoInfoTag(True)
			info_tag.setMediaType('tvshow')
			# TV show views show the title, not the label, so the title carries the same text.
			info_tag.setTitle(display)
			info_tag.setPlot(meta.get('plot') or ' ')
			# Selecting a show drops or undrops it; the long press offers the same, plus seasons as in other lists.
			listitem.addContextMenuItems([('[B]%s TV Show[/B]' % ('Undrop' if dropped else 'Drop'), 'RunPlugin(%s)' % url),
				('[B]Browse Seasons[/B]', 'Container.Update(%s)' % build_url({'mode': 'build_season_list', 'tmdb_id': tmdb_id}))])
			append({'listitem': (url, listitem, False), 'sort_title': title})
		except: pass
	handle = int(sys.argv[1])
	make_listitem, build_url, addon_fanart = kodi_utils.make_listitem, kodi_utils.build_url, kodi_utils.get_addon_fanart()
	api_key, mpaa_region_value, current_date = tmdb_api_key(), mpaa_region(), get_datetime()
	show_filter = params.get('show_filter', 'all')
	list_items = []
	append = list_items.append
	indicators = watched_indicators()
	show_list = get_next_episodes(0)
	hidden_list = get_hidden_progress_items(indicators)
	if indicators == 0: icon, mode = kodi_utils.get_icon('folder'), 'hide_unhide_progress_items'
	elif indicators == 2: icon, mode = kodi_utils.get_icon('simkl'), 'simkl.simkl_hide_unhide_progress_items'
	elif indicators == 3: icon, mode = kodi_utils.get_icon('mdblist'), 'mdblist.mdblist_hide_unhide_progress_items'
	else: icon, mode = kodi_utils.get_icon('trakt'), 'trakt.hide_unhide_progress_items'
	if show_list:
		threads = TaskPool().tasks(_process, show_list, min(len(show_list), max_threads()))
		[i.join() for i in threads]
	item_list = sorted(list_items, key=lambda k: (title_key(k['sort_title'], ignore_articles())), reverse=False)
	item_list = [i['listitem'] for i in item_list]
	filter_item = make_listitem()
	filter_label = '[B]Show: %s[/B]  [I](%s)[/I]' % (dict(NEXTEP_MANAGER_FILTERS).get(show_filter, 'All'), len(item_list))
	filter_item.setLabel(filter_label)
	filter_icon = kodi_utils.get_icon('settings2')
	filter_item.setArt({'poster': filter_icon, 'thumb': filter_icon, 'icon': filter_icon, 'fanart': addon_fanart})
	filter_tag = filter_item.getVideoInfoTag(True)
	filter_tag.setTitle(filter_label)
	filter_tag.setPlot('Choose which shows to list: all of them, only dropped shows, or only shows that are not dropped.')
	item_list.insert(0, (build_url({'mode': 'next_episode_manager_filter', 'show_filter': show_filter}), filter_item, False))
	kodi_utils.add_items(handle, item_list)
	kodi_utils.set_content(handle, 'tvshows')
	kodi_utils.end_directory(handle, cacheToDisc=False)
	kodi_utils.set_view_mode('view.tvshows', 'tvshows', False)

def next_episode_manager_filter(params):
	current = params.get('show_filter', 'all')
	list_items = [{'line1': ('%s  [I](current)[/I]' % name) if key == current else name} for key, name in NEXTEP_MANAGER_FILTERS]
	kwargs = {'items': json.dumps(list_items), 'heading': 'Show', 'narrow_window': 'true'}
	choice = kodi_utils.select_dialog([key for key, name in NEXTEP_MANAGER_FILTERS], **kwargs)
	if choice in (None, current): return
	# Replace rather than stack, so Back leaves the manager instead of stepping through filters.
	kodi_utils.execute_builtin('Container.Update(%s,replace)' % kodi_utils.build_url({'mode': 'build_next_episode_manager', 'show_filter': choice}))

def single_last_watched_episodes(data):
	seen = set()
	seen_add = seen.add
	return sorted([i for i in sorted(data, key=lambda x: (x['last_played'], x['media_ids']['tmdb'], x['season'], x['episode']), reverse=True)
				if not (i['media_ids']['tmdb'] in seen or seen_add(i['media_ids']['tmdb']))],
				key=lambda x: (x['last_played'], x['media_ids']['tmdb'], x['season'], x['episode']), reverse=True)
