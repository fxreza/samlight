# -*- coding: utf-8 -*-
"""Snapshot of what a local list and its remote twin looked like at the end of the last sync.

Two way mirroring needs to tell "added on this side" apart from "removed on the other
side", and the only way to know that is to remember the agreed state. Lives in its own
database file so it never affects the table counts check_databases_integrity enforces.
"""
import time
from caches.base_cache import connect_database

_table_ready = [False]

def _ensure_table():
	if _table_ready[0]: return
	# Set first: a failure here must not retry on every read.
	_table_ready[0] = True
	try:
		dbcon = connect_database('list_sync_db')
		dbcon.execute('CREATE TABLE IF NOT EXISTS list_sync (service text not null, source_key text not null, '
					'list_id text, snapshot text, updated text, remote_stamp text, unique (service, source_key))')
		columns = [i[1] for i in dbcon.execute('PRAGMA table_info(list_sync)').fetchall()]
		if 'remote_stamp' not in columns:
			dbcon.execute('ALTER TABLE list_sync ADD COLUMN remote_stamp text')
	except: pass

def get_snapshot(service, source_key):
	"""Returns a set of (media_type, media_id) tuples, empty if this pair never synced."""
	try:
		_ensure_table()
		dbcon = connect_database('list_sync_db')
		row = dbcon.execute('SELECT snapshot FROM list_sync WHERE service=? AND source_key=?', (service, source_key)).fetchone()
		if row and row[0]: return set(tuple(i) for i in eval(row[0]))
	except: pass
	return set()

def set_snapshot(service, source_key, list_id, snapshot):
	try:
		_ensure_table()
		dbcon = connect_database('list_sync_db')
		dbcon.execute('INSERT OR REPLACE INTO list_sync (service, source_key, list_id, snapshot, updated) VALUES (?, ?, ?, ?, ?)',
					(service, source_key, str(list_id), repr(sorted(snapshot)), str(int(time.time()))))
		return True
	except: return False

def clear_snapshot(service, source_key):
	try:
		_ensure_table()
		dbcon = connect_database('list_sync_db')
		dbcon.execute('DELETE FROM list_sync WHERE service=? AND source_key=?', (service, source_key))
		return True
	except: return False

def last_synced(service, source_key):
	try:
		_ensure_table()
		dbcon = connect_database('list_sync_db')
		row = dbcon.execute('SELECT updated FROM list_sync WHERE service=? AND source_key=?', (service, source_key)).fetchone()
		if row and row[0]: return int(row[0])
	except: pass
	return 0

def get_remote_stamp(service, source_key):
	"""The remote list's last-changed marker as of the last poll."""
	try:
		_ensure_table()
		dbcon = connect_database('list_sync_db')
		row = dbcon.execute('SELECT remote_stamp FROM list_sync WHERE service=? AND source_key=?', (service, source_key)).fetchone()
		if row and row[0]: return str(row[0])
	except: pass
	return ''

def set_remote_stamp(service, source_key, list_id, stamp):
	try:
		_ensure_table()
		dbcon = connect_database('list_sync_db')
		row = dbcon.execute('SELECT source_key FROM list_sync WHERE service=? AND source_key=?', (service, source_key)).fetchone()
		if row: dbcon.execute('UPDATE list_sync SET remote_stamp=? WHERE service=? AND source_key=?', (str(stamp), service, source_key))
		else: dbcon.execute('INSERT INTO list_sync (service, source_key, list_id, snapshot, updated, remote_stamp) VALUES (?, ?, ?, ?, ?, ?)',
						(service, source_key, str(list_id), repr([]), str(int(time.time())), str(stamp)))
		return True
	except: return False
