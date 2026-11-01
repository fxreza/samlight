#!/usr/bin/env python3
"""Report on a Source Test Log (source_test.jsonl from the add-on's data folder).

    python3 tools/source_test_report.py source_test.jsonl [more.jsonl ...]

Per source (module / provider): speed, how often it finds anything (movies, newer and older
shows), how many of its links nobody else found, how many look wrong for the title or episode,
how many were cached, and how its links did when played. Then the same per module."""
import re
import sys
import json
import statistics
from collections import defaultdict

STOP_WORDS = {'the', 'a', 'an', 'and', 'of', 'in', 'on', 'at', 'to'}
OLD_SHOW_BEFORE = 2010

def load(paths):
	events = []
	for path in paths:
		with open(path, encoding='utf-8') as handle:
			for line in handle:
				line = line.strip()
				if not line: continue
				try: events.append(json.loads(line))
				except ValueError: pass
	return events

def words(text):
	return [w for w in re.sub(r'[^a-z0-9]+', ' ', str(text or '').lower()).split() if w]

def first_year(search):
	for value in (search.get('first_aired'), search.get('year')):
		match = re.match(r'(\d{4})', str(value or ''))
		if match: return int(match.group(1))
	return None

def link_problem(name, search, pack):
	"""Why a link's name does not fit what was searched, or '' when it looks right."""
	name_words = words(name)
	joined = ' '.join(name_words)
	title = [w for w in words(search.get('title')) if w not in STOP_WORDS] or words(search.get('title'))
	if title and not all(w in name_words or w in joined.replace(' ', '') for w in title): return 'title'
	if search.get('media_type') == 'movie':
		years = [int(y) for y in re.findall(r'\b(19\d\d|20\d\d)\b', ' '.join(words(name)))]
		want = first_year(search)
		if years and want and not any(abs(y - want) <= 1 for y in years): return 'year'
		return ''
	season, episode = int(search.get('season') or 0), int(search.get('episode') or 0)
	text = ' ' + joined + ' '
	pairs = re.findall(r'(?<![a-z0-9])s(\d{1,2}) ?e(\d{1,3})(?!\d)', joined) or re.findall(r'\b(\d{1,2})x(\d{1,3})\b', joined)
	if pairs:
		if not any(int(s) == season and int(e) == episode for s, e in pairs):
			# A multi-episode file (S02E01-E03) is still right.
			ranges = re.findall(r'(?<![a-z0-9])s(\d{1,2}) ?e(\d{1,3}) ?e(\d{1,3})(?!\d)', joined)
			if not any(int(s) == season and int(a) <= episode <= int(b) for s, a, b in ranges): return 'episode'
		return ''
	seasons = [int(s) for s in re.findall(r'\b(?:s|season )(\d{1,2})\b', text)]
	spans = re.findall(r'\bs(\d{1,2}) ?s?(\d{1,2})\b', joined)
	if any(int(a) <= season <= int(b) for a, b in spans if int(a) < int(b)): return ''
	if seasons and season not in seasons: return 'season'
	if not seasons and not pack and not re.search(r'complete|collection|series', joined): return 'no_episode'
	return ''

def pct(part, whole):
	return '%3.0f%%' % (100.0 * part / whole) if whole else '   -'

def secs(values):
	if not values: return '    -     -     -'
	return '%5.1f %5.1f %5.1f' % (statistics.mean(values), statistics.median(values), max(values))

def main(paths):
	events = load(paths)
	searches, sources, ends, caches, plays = {}, defaultdict(list), {}, {}, defaultdict(list)
	for event in events:
		kind, sid = event.get('event'), event.get('sid')
		if kind == 'search': searches[sid] = event
		elif kind == 'source': sources[sid].append(event)
		elif kind == 'scrape_end': ends[sid] = event
		elif kind == 'cache': caches[sid] = event.get('status') or {}
		elif kind == 'play': plays[sid].append(event)
	stat = defaultdict(lambda: defaultdict(list))
	module_stat = defaultdict(lambda: defaultdict(list))
	problem_names = defaultdict(list)
	for sid, search in searches.items():
		search_sources = sources.get(sid, [])
		end = ends.get(sid, {})
		running = set(end.get('running') or [])
		status = caches.get(sid, {})
		year = first_year(search)
		if search.get('media_type') == 'movie': group = 'movie'
		elif year and year < OLD_SHOW_BEFORE: group = 'old_show'
		else: group = 'new_show'
		# Who found each torrent in this search, to tell unique links from duplicates.
		finders = defaultdict(set)
		for event in search_sources:
			for link in event.get('links') or []:
				if link.get('h'): finders[link['h']].add((event.get('module'), event.get('provider')))
		played = {p.get('h'): p for p in plays.get(sid, [])}
		for event in search_sources:
			key = (event.get('module') or '?', event.get('provider') or '?', event.get('pack') or '')
			s = stat[key]
			s['searches'].append(1)
			s['group_' + group].append(1 if event.get('count') else 0)
			if not event.get('cached'): s['secs'].append(event.get('secs') or 0)
			if event.get('late') or event.get('provider') in running: s['cut_off'].append(1)
			if event.get('error'): s['errors'].append(event['error'])
			s['links'].append(event.get('count') or 0)
			for link in event.get('links') or []:
				h = link.get('h')
				s['link_total'].append(1)
				if h and len(finders[h]) == 1: s['unique'].append(1)
				problem = link_problem(link.get('n'), search, link.get('pk') or event.get('pack'))
				if problem:
					s['wrong'].append(1)
					if len(problem_names[key]) < 5: problem_names[key].append('%s [%s] for %s' % (link.get('n'), problem, search.get('title')))
				cache_values = status.get(h) or []
				if any(v and not v.startswith('Uncached') for v in cache_values): s['cached'].append(1)
				if h in played:
					s['play_' + played[h].get('step', '?')].append(1)
				if link.get('o'): s['origin'].append(link['o'])
		for module in {e.get('module') or '?' for e in search_sources}:
			module_events = [e for e in search_sources if (e.get('module') or '?') == module]
			m = module_stat[module]
			m['searches'].append(1)
			m['found'].append(1 if any(e.get('count') for e in module_events) else 0)
			hashes = {l.get('h') for e in module_events for l in e.get('links') or [] if l.get('h')}
			m['hashes'].append(len(hashes))
			m['only_here'].append(sum(1 for h in hashes if all(f[0] == module for f in finders[h])))
			live = [e.get('secs') or 0 for e in module_events if not e.get('cached')]
			if live: m['slowest'].append(max(live))

	print('Source Test report: %d searches, %d source runs' % (len(searches), sum(len(v) for v in sources.values())))
	print('Show groups: movie, new_show (first aired %d or later), old_show (before %d)\n' % (OLD_SHOW_BEFORE, OLD_SHOW_BEFORE))
	header = '%-34s %4s  %-17s %4s %4s  %-14s %5s %5s %5s %5s  %s' % (
		'module / source', 'runs', 'secs avg/med/max', 'cut', 'err', 'found m/new/old', 'links', 'uniq', 'wrong', 'cache', 'played ok/bad')
	print(header)
	print('-' * len(header))
	rows = sorted(stat.items(), key=lambda kv: -(statistics.mean(kv[1]['secs']) if kv[1]['secs'] else 0))
	for (module, provider, pack), s in rows:
		label = '%s / %s%s' % (module, provider, ' (%s)' % pack if pack else '')
		runs = len(s['searches'])
		found = '/'.join(pct(sum(s['group_' + g]), len(s['group_' + g])).strip() for g in ('movie', 'new_show', 'old_show'))
		total = len(s['link_total'])
		played = '%d/%d' % (len(s['play_opened']), len(s['play_failed']) + len(s['play_no_url']))
		print('%-34s %4d  %-17s %4d %4d  %-14s %5.1f %5s %5s %5s  %s' % (
			label[:34], runs, secs(s['secs']), len(s['cut_off']), len(s['errors']), found,
			statistics.mean(s['links']) if s['links'] else 0, pct(len(s['unique']), total), pct(len(s['wrong']), total),
			pct(len(s['cached']), total), played))
	print('\ncut = times it was still running when the search stopped; found = share of runs with any link')
	print('uniq = its links no other source found; wrong = names that do not fit the title/year/episode')
	print('cache = links cached on TorBox or Premiumize; played = links of it that played / failed\n')
	print('%-20s %6s %7s %10s %12s %16s' % ('module', 'runs', 'found', 'links/run', 'only here', 'slowest med/max'))
	for module, m in sorted(module_stat.items()):
		print('%-20s %6d %7s %10.1f %12.1f %16s' % (module, len(m['searches']), pct(sum(m['found']), len(m['found'])),
			statistics.mean(m['hashes']) if m['hashes'] else 0, statistics.mean(m['only_here']) if m['only_here'] else 0,
			'%.1f / %.1f s' % (statistics.median(m['slowest']), max(m['slowest'])) if m['slowest'] else '-'))
	errors = {k: s['errors'] for k, s in stat.items() if s['errors']}
	if errors:
		print('\nErrors:')
		for key, values in errors.items(): print('  %s: %s' % (' / '.join(k for k in key if k), values[0]))
	if problem_names:
		print('\nExamples of wrong links:')
		for key, names in problem_names.items():
			print('  %s' % ' / '.join(k for k in key if k))
			for name in names: print('    %s' % name)
	origins = {k: s['origin'] for k, s in stat.items() if s['origin']}
	if origins:
		print('\nInner sites seen inside sources:')
		for key, values in origins.items():
			counts = defaultdict(int)
			for value in values: counts[value] += 1
			print('  %s: %s' % (' / '.join(k for k in key if k), ', '.join('%s %d' % kv for kv in sorted(counts.items(), key=lambda kv: -kv[1])[:8])))

if __name__ == '__main__':
	if len(sys.argv) < 2: sys.exit(__doc__)
	main(sys.argv[1:])
