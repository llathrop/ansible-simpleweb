"""
Flat File (SQLite) Storage Backend

Implements the StorageBackend interface using a single SQLite database.
Designed for Raspberry Pi:
- Transactional integrity (power loss safe)
- Thread-local connections for efficiency
- Process-safe concurrency (BEGIN IMMEDIATE)
- Indexed search performance (COLLATE NOCASE)
"""

import json
import os
import sqlite3
import fnmatch
import threading
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Callable
from .base import StorageBackend, compute_diff, is_empty_diff

logger = logging.getLogger(__name__)

class FlatFileStorage(StorageBackend):
    def __init__(self, config_dir: str = '/app/config'):
        self.config_dir = config_dir
        self.db_path = os.path.join(config_dir, 'storage.db')
        self._local = threading.local()
        os.makedirs(config_dir, exist_ok=True)
        self._init_db()
        self._migrate_json_data(config_dir)

    def _get_connection(self):
        """Get or create a thread-local SQLite connection."""
        if not hasattr(self._local, 'conn'):
            conn = sqlite3.connect(self.db_path, timeout=30)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return self._local.conn

    def _init_db(self):
        conn = self._get_connection()
        with conn:
            # Table Schema with proper COLLATE NOCASE for indexing
            conn.execute("CREATE TABLE IF NOT EXISTS inventory (id TEXT PRIMARY KEY, hostname TEXT UNIQUE COLLATE NOCASE, data TEXT)")
            conn.execute("CREATE TABLE IF NOT EXISTS host_facts (host TEXT PRIMARY KEY COLLATE NOCASE, last_updated TEXT, groups TEXT, data TEXT)")
            conn.execute("CREATE TABLE IF NOT EXISTS schedules (id TEXT PRIMARY KEY, data TEXT)")
            conn.execute("CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, schedule_id TEXT, timestamp TEXT, data TEXT)")
            conn.execute("CREATE TABLE IF NOT EXISTS batch_jobs (id TEXT PRIMARY KEY, status TEXT, created TEXT, data TEXT)")
            conn.execute("CREATE TABLE IF NOT EXISTS workers (id TEXT PRIMARY KEY, status TEXT, data TEXT)")
            conn.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, status TEXT, submitted_at TEXT, assigned_worker TEXT, data TEXT)")
            conn.execute("CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY COLLATE NOCASE, id TEXT UNIQUE, data TEXT)")
            conn.execute("CREATE TABLE IF NOT EXISTS groups (name TEXT PRIMARY KEY COLLATE NOCASE, data TEXT)")
            conn.execute("CREATE TABLE IF NOT EXISTS roles (name TEXT PRIMARY KEY COLLATE NOCASE, data TEXT)")
            conn.execute("CREATE TABLE IF NOT EXISTS api_tokens (id TEXT PRIMARY KEY, token_hash TEXT UNIQUE, user_id TEXT, data TEXT)")
            conn.execute("CREATE TABLE IF NOT EXISTS audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, user TEXT, action TEXT, resource TEXT, success INTEGER, data TEXT)")
            
            # Indexes for performance
            conn.execute("CREATE INDEX IF NOT EXISTS idx_inv_hostname ON inventory(hostname)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_facts_updated ON host_facts(last_updated)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_hist_sid ON history(schedule_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_filter ON audit_log(user, action, resource, timestamp)")

    def _migrate_json_data(self, config_dir):
        flag = os.path.join(config_dir, '.sqlite_migrated')
        if os.path.exists(flag): return
        def load(f, k):
            p = os.path.join(config_dir, f)
            if not os.path.exists(p): return None
            try:
                with open(p, 'r') as jf: return json.load(jf).get(k)
            except Exception as e:
                logger.error(f"Migration: Failed to load {f}: {e}"); return None
        conn = self._get_connection()
        try:
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                inv = load('inventory.json', 'inventory')
                if inv:
                    for i in inv: conn.execute("INSERT OR IGNORE INTO inventory (id, hostname, data) VALUES (?, ?, ?)", (i['id'], i['hostname'], json.dumps(i)))
                facts = load('host_facts.json', 'hosts')
                if facts:
                    for h, d in facts.items():
                        conn.execute("INSERT OR IGNORE INTO host_facts (host, last_updated, groups, data) VALUES (?, ?, ?, ?)", (h, d.get('last_updated'), json.dumps(d.get('groups', [])), json.dumps(d)))
                sc = load('schedules.json', 'schedules')
                if sc:
                    for sid, sd in sc.items(): conn.execute("INSERT OR IGNORE INTO schedules (id, data) VALUES (?, ?)", (sid, json.dumps(sd)))
                us = load('users.json', 'users')
                if us:
                    for u, ud in us.items(): conn.execute("INSERT OR IGNORE INTO users (username, id, data) VALUES (?, ?, ?)", (u, ud.get('id'), json.dumps(ud)))
            with open(flag, 'w') as f: f.write(datetime.now(timezone.utc).isoformat())
        except Exception as e:
            logger.error(f"Migration CRITICAL FAILURE: {e}")

    # =========================================================================
    # Methods implementing StorageBackend ABC
    # =========================================================================

    def get_all_schedules(self) -> Dict:
        cursor = self._get_connection().execute("SELECT id, data FROM schedules")
        return {r['id']: json.loads(r['data']) for r in cursor}
    def get_schedule(self, sid: str) -> Optional[Dict]:
        r = self._get_connection().execute("SELECT data FROM schedules WHERE id = ?", (sid,)).fetchone()
        return json.loads(r['data']) if r else None
    def save_schedule(self, sid: str, s: Dict) -> bool:
        s['id'] = sid
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT OR REPLACE INTO schedules (id, data) VALUES (?, ?)", (sid, json.dumps(s))); return True
    def delete_schedule(self, sid: str) -> bool:
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            res = conn.execute("DELETE FROM schedules WHERE id = ?", (sid,)); return res.rowcount > 0
    def save_all_schedules(self, s: Dict) -> bool:
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM schedules")
            for sid, sd in s.items():
                sd['id'] = sid
                conn.execute("INSERT INTO schedules (id, data) VALUES (?, ?)", (sid, json.dumps(sd)))
            return True

    def get_history(self, sid: Optional[str] = None, limit: int = 50) -> List:
        sql = "SELECT data FROM history"
        p = []
        if sid: sql += " WHERE schedule_id = ?"; p.append(sid)
        sql += " ORDER BY timestamp DESC LIMIT ?"; p.append(limit)
        return [json.loads(r['data']) for r in self._get_connection().execute(sql, p)]
    def add_history_entry(self, e: Dict) -> bool:
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT INTO history (schedule_id, timestamp, data) VALUES (?, ?, ?)", (e.get('schedule_id'), e.get('timestamp'), json.dumps(e))); return True
    def cleanup_history(self, m: int = 1000) -> int:
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            total = conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]
            if total <= m: return 0
            res = conn.execute("DELETE FROM history WHERE id IN (SELECT id FROM history ORDER BY timestamp ASC LIMIT ?)", (total - m,))
            return res.rowcount

    def get_all_inventory(self) -> List:
        return [json.loads(r['data']) for r in self._get_connection().execute("SELECT data FROM inventory")]
    def get_inventory_item(self, iid: str) -> Optional[Dict]:
        r = self._get_connection().execute("SELECT data FROM inventory WHERE id = ?", (iid,)).fetchone()
        return json.loads(r['data']) if r else None
    def save_inventory_item(self, iid: str, item: Dict) -> bool:
        item['id'] = iid
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT OR REPLACE INTO inventory (id, hostname, data) VALUES (?, ?, ?)", (iid, item.get('hostname'), json.dumps(item))); return True
    def delete_inventory_item(self, iid: str) -> bool:
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            res = conn.execute("DELETE FROM inventory WHERE id = ?", (iid,)); return res.rowcount > 0
    def search_inventory(self, query: Dict) -> List:
        if len(query) == 1 and 'hostname' in query:
            h = str(query['hostname'])
            if '*' not in h:
                r = self._get_connection().execute("SELECT data FROM inventory WHERE hostname = ?", (h,)).fetchone()
                return [json.loads(r['data'])] if r else []
            else:
                sql_h = h.replace('*', '%')
                cursor = self._get_connection().execute("SELECT data FROM inventory WHERE hostname LIKE ?", (sql_h,))
                return [json.loads(r['data']) for r in cursor]
        all_inv = self.get_all_inventory()
        return [i for i in all_inv if all(fnmatch.fnmatch(str(i.get(k, '')).lower(), str(v).lower()) for k, v in query.items())]

    def get_host_facts(self, host: str) -> Optional[Dict]:
        r = self._get_connection().execute("SELECT data FROM host_facts WHERE host = ?", (host,)).fetchone()
        return json.loads(r['data']) if r else None
    def get_host_collection(self, host: str, coll: str, inc_hist: bool = False) -> Optional[Dict]:
        hd = self.get_host_facts(host)
        if not hd: return None
        c = hd.get('collections', {}).get(coll)
        if not c: return None
        return c if inc_hist else {'current': c.get('current'), 'last_updated': c.get('last_updated')}
    def save_host_facts(self, host: str, collection: str, data: Dict, groups: List[str] = None, source: str = None) -> Dict:
        now = datetime.now(timezone.utc).isoformat()
        conn = self._get_connection()
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT data FROM host_facts WHERE host = ?", (host,)).fetchone()
            if not row:
                hd = {'host': host, 'groups': groups or [], 'collections': {}, 'first_seen': now, 'last_updated': now}
                status, changes, actual_host = 'created', None, host
            else:
                hd = json.loads(row['data']); actual_host = hd['host']
                if groups: hd['groups'] = list(set(hd.get('groups', [])) | set(groups))
                status = 'updated'
            
            coll = hd['collections'].get(collection)
            if not coll:
                hd['collections'][collection] = {'current': data, 'last_updated': now, 'source': source, 'history': []}
                changes = None
            else:
                diff = compute_diff(coll.get('current', {}), data)
                if is_empty_diff(diff): return {'status': 'unchanged', 'host': actual_host, 'collection': collection}
                coll.setdefault('history', []).insert(0, {'timestamp': coll.get('last_updated', now), 'source': coll.get('source'), 'diff_from_next': diff})
                coll['history'] = coll['history'][:100]
                coll.update({'current': data, 'last_updated': now, 'source': source})
                changes = diff
            hd['last_updated'] = now
            conn.execute("INSERT OR REPLACE INTO host_facts (host, last_updated, groups, data) VALUES (?, ?, ?, ?)", (actual_host, now, json.dumps(hd['groups']), json.dumps(hd)))
            return {'status': status, 'host': actual_host, 'collection': collection, 'changes': changes}

    def get_all_hosts(self) -> List[Dict]:
        cursor = self._get_connection().execute("SELECT host, groups, last_updated, data FROM host_facts ORDER BY last_updated DESC")
        return [{'host': r['host'], 'groups': json.loads(r['groups']), 'last_updated': r['last_updated'], 'collections': list(json.loads(r['data'])['collections'].keys())} for r in cursor]
    def get_hosts_by_group(self, group: str) -> List[Dict]:
        return [h for h in self.get_all_hosts() if group in h['groups']]
    def get_host_history(self, host: str, coll: str, limit: int = 50) -> List:
        hd = self.get_host_facts(host)
        return hd.get('collections', {}).get(coll, {}).get('history', [])[:limit] if hd else []
    def delete_host_facts(self, host: str, coll: str = None) -> bool:
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if not coll: conn.execute("DELETE FROM host_facts WHERE host = ?", (host,)); return True
            hd = self.get_host_facts(host)
            if hd and coll in hd.get('collections', {}):
                del hd['collections'][coll]
                conn.execute("UPDATE host_facts SET data = ? WHERE host = ?", (json.dumps(hd), hd['host'])); return True
            return False
    def import_host_facts(self, hd: Dict) -> bool:
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT OR REPLACE INTO host_facts (host, last_updated, groups, data) VALUES (?, ?, ?, ?)", (hd['host'], hd.get('last_updated'), json.dumps(hd.get('groups', [])), json.dumps(hd))); return True

    def get_all_batch_jobs(self) -> List:
        return [json.loads(r['data']) for r in self._get_connection().execute("SELECT data FROM batch_jobs ORDER BY created DESC")]
    def get_batch_job(self, bid: str) -> Optional[Dict]:
        r = self._get_connection().execute("SELECT data FROM batch_jobs WHERE id = ?", (bid,)).fetchone(); return json.loads(r['data']) if r else None
    def save_batch_job(self, bid: str, bj: Dict) -> bool:
        bj['id'] = bid
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT OR REPLACE INTO batch_jobs (id, status, created, data) VALUES (?, ?, ?, ?)", (bid, bj.get('status'), bj.get('created'), json.dumps(bj))); return True
    def delete_batch_job(self, bid: str) -> bool:
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            res = conn.execute("DELETE FROM batch_jobs WHERE id = ?", (bid,))
            return res.rowcount > 0
    def get_batch_jobs_by_status(self, s: str) -> List:
        return [json.loads(r['data']) for r in self._get_connection().execute("SELECT data FROM batch_jobs WHERE status = ?", (s,))]
    def cleanup_batch_jobs(self, m: int = 30, k: int = 100) -> int:
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cutoff = (datetime.now(timezone.utc) - timedelta(days=m)).isoformat()
            res = conn.execute("DELETE FROM batch_jobs WHERE status != 'running' AND created < ? AND id NOT IN (SELECT id FROM batch_jobs ORDER BY created DESC LIMIT ?)", (cutoff, k))
            return res.rowcount

    def get_all_workers(self) -> List:
        return [json.loads(r['data']) for r in self._get_connection().execute("SELECT data FROM workers ORDER BY id")]
    def get_worker(self, wid: str) -> Optional[Dict]:
        r = self._get_connection().execute("SELECT data FROM workers WHERE id = ?", (wid,)).fetchone(); return json.loads(r['data']) if r else None
    def save_worker(self, w: Dict) -> bool:
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT OR REPLACE INTO workers (id, status, data) VALUES (?, ?, ?)", (w['id'], w.get('status'), json.dumps(w))); return True
    def delete_worker(self, wid: str) -> bool:
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            res = conn.execute("DELETE FROM workers WHERE id = ?", (wid,)); return res.rowcount > 0
    def get_workers_by_status(self, sl: List[str]) -> List:
        q = f"SELECT data FROM workers WHERE status IN ({','.join(['?']*len(sl))})"
        return [json.loads(r['data']) for r in self._get_connection().execute(q, sl)]
    def update_worker_checkin(self, wid: str, cd: Dict) -> bool:
        conn = self._get_connection()
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            r = conn.execute("SELECT data FROM workers WHERE id = ?", (wid,)).fetchone()
            if not r: return False
            w = json.loads(r['data'])
            w['last_checkin'] = datetime.now(timezone.utc).isoformat()
            if 'stats' in cd: w.setdefault('stats', {}).update(cd['stats'])
            if 'status' in cd: w['status'] = cd['status']
            conn.execute("UPDATE workers SET status = ?, data = ? WHERE id = ?", (w['status'], json.dumps(w), wid)); return True

    def get_all_jobs(self, f: Dict = None) -> List:
        sql = "SELECT data FROM jobs"; p = []
        if f: cl = [f"{k} = ?" for k in f]; sql += " WHERE " + " AND ".join(cl); p.extend(f.values())
        sql += " ORDER BY submitted_at DESC"
        return [json.loads(r['data']) for r in self._get_connection().execute(sql, p)]
    def get_job(self, jid: str) -> Optional[Dict]:
        r = self._get_connection().execute("SELECT data FROM jobs WHERE id = ?", (jid,)).fetchone(); return json.loads(r['data']) if r else None
    def save_job(self, j: Dict) -> bool:
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT OR REPLACE INTO jobs (id, status, submitted_at, assigned_worker, data) VALUES (?, ?, ?, ?, ?)", (j['id'], j.get('status'), j.get('submitted_at'), j.get('assigned_worker'), json.dumps(j))); return True
    def update_job(self, jid: str, up: Dict) -> bool:
        conn = self._get_connection()
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            r = conn.execute("SELECT data FROM jobs WHERE id = ?", (jid,)).fetchone()
            if not r: return False
            j = json.loads(r['data'])
            j.update(up)
            conn.execute("UPDATE jobs SET status = ?, assigned_worker = ?, data = ? WHERE id = ?", (j.get('status'), j.get('assigned_worker'), json.dumps(j), jid)); return True
    def delete_job(self, jid: str) -> bool:
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            res = conn.execute("DELETE FROM jobs WHERE id = ?", (jid,)); return res.rowcount > 0
    def get_pending_jobs(self) -> List:
        return [json.loads(r['data']) for r in self._get_connection().execute("SELECT data FROM jobs WHERE status = 'queued' ORDER BY submitted_at ASC")]
    def get_worker_jobs(self, wid: str, sl: List[str] = None) -> List:
        sql = "SELECT data FROM jobs WHERE assigned_worker = ?"; p = [wid]
        if sl: sql += f" AND status IN ({','.join(['?']*len(sl))})"; p.extend(sl)
        return [json.loads(r['data']) for r in self._get_connection().execute(sql, p)]
    def cleanup_jobs(self, m: int = 30, k: int = 500) -> int:
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cutoff = (datetime.now(timezone.utc) - timedelta(days=m)).isoformat()
            total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            if total <= k: return 0
            res = conn.execute("DELETE FROM jobs WHERE status IN ('completed', 'failed', 'cancelled') AND submitted_at < ? AND id NOT IN (SELECT id FROM jobs ORDER BY submitted_at DESC LIMIT ?)", (cutoff, k))
            return res.rowcount

    def get_user(self, u: str) -> Optional[Dict]:
        r = self._get_connection().execute("SELECT data FROM users WHERE username = ?", (u,)).fetchone(); return json.loads(r['data']) if r else None
    def get_user_by_id(self, uid: str) -> Optional[Dict]:
        r = self._get_connection().execute("SELECT data FROM users WHERE id = ?", (uid,)).fetchone(); return json.loads(r['data']) if r else None
    def get_all_users(self) -> List:
        return [{k:v for k,v in json.loads(r['data']).items() if k != 'password_hash'} for r in self._get_connection().execute("SELECT data FROM users")]
    def save_user(self, u: str, ud: Dict) -> bool:
        ud['username'] = u
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT OR REPLACE INTO users (username, id, data) VALUES (?, ?, ?)", (u, ud.get('id'), json.dumps(ud))); return True
    def delete_user(self, u: str) -> bool:
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            res = conn.execute("DELETE FROM users WHERE username = ?", (u,)); return res.rowcount > 0
    def check_user_credentials(self, u: str, ph: str) -> bool:
        ud = self.get_user(u); return ud and ud.get('password_hash') == ph

    def get_group(self, n: str) -> Optional[Dict]:
        r = self._get_connection().execute("SELECT data FROM groups WHERE name = ?", (n,)).fetchone(); return json.loads(r['data']) if r else None
    def get_all_groups(self) -> List:
        return [json.loads(r['data']) for r in self._get_connection().execute("SELECT data FROM groups")]
    def save_group(self, n: str, g: Dict) -> bool:
        g['name'] = n
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT OR REPLACE INTO groups (name, data) VALUES (?, ?)", (n, json.dumps(g))); return True
    def delete_group(self, n: str) -> bool:
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            res = conn.execute("DELETE FROM groups WHERE name = ?", (n,)); return res.rowcount > 0

    def get_role(self, n: str) -> Optional[Dict]:
        r = self._get_connection().execute("SELECT data FROM roles WHERE name = ?", (n,)).fetchone(); return json.loads(r['data']) if r else None
    def get_all_roles(self) -> List:
        return [json.loads(r['data']) for r in self._get_connection().execute("SELECT data FROM roles")]
    def save_role(self, n: str, r: Dict) -> bool:
        r['name'] = n
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT OR REPLACE INTO roles (name, data) VALUES (?, ?)", (n, json.dumps(r))); return True
    def delete_role(self, n: str) -> bool:
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            res = conn.execute("DELETE FROM roles WHERE name = ?", (n,)); return res.rowcount > 0

    def get_api_token(self, tid: str) -> Optional[Dict]:
        r = self._get_connection().execute("SELECT data FROM api_tokens WHERE id = ?", (tid,)).fetchone(); return json.loads(r['data']) if r else None
    def get_api_token_by_hash(self, th: str) -> Optional[Dict]:
        r = self._get_connection().execute("SELECT data FROM api_tokens WHERE token_hash = ?", (th,)).fetchone(); return json.loads(r['data']) if r else None
    def get_user_api_tokens(self, uid: str) -> List:
        cursor = self._get_connection().execute("SELECT data FROM api_tokens WHERE user_id = ?", (uid,))
        return [{k:v for k,v in json.loads(r['data']).items() if k != 'token_hash'} for r in cursor]
    def save_api_token(self, tid: str, t: Dict) -> bool:
        t['id'] = tid
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT OR REPLACE INTO api_tokens (id, token_hash, user_id, data) VALUES (?, ?, ?, ?)", (tid, t.get('token_hash'), t.get('user_id'), json.dumps(t))); return True
    def update_api_token(self, tid: str, t: Dict) -> bool: return self.save_api_token(tid, t)
    def delete_api_token(self, tid: str) -> bool:
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            res = conn.execute("DELETE FROM api_tokens WHERE id = ?", (tid,))
            return res.rowcount > 0

    def add_audit_entry(self, e: Dict) -> bool:
        if 'timestamp' not in e: e['timestamp'] = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT INTO audit_log (timestamp, user, action, resource, success, data) VALUES (?, ?, ?, ?, ?, ?)", (e.get('timestamp'), e.get('user'), e.get('action'), e.get('resource'), 1 if e.get('success') else 0, json.dumps(e))); return True
    def get_audit_log(self, f: Dict = None, limit: int = 100, offset: int = 0) -> List:
        sql = "SELECT data FROM audit_log"; p = []
        if f:
            cl = []
            for k,v in f.items():
                if k == 'start_time': cl.append("timestamp >= ?"); p.append(v)
                elif k == 'end_time': cl.append("timestamp <= ?"); p.append(v)
                elif k == 'success': cl.append("success = ?"); p.append(1 if v else 0)
                else: cl.append(f"{k} = ?"); p.append(v)
            sql += " WHERE " + " AND ".join(cl)
        sql += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"; p.extend([limit, offset])
        return [json.loads(r['data']) for r in self._get_connection().execute(sql, p)]
    def cleanup_audit_log(self, m: int = 90, k: int = 10000) -> int:
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cutoff = (datetime.now(timezone.utc) - timedelta(days=m)).isoformat()
            res = conn.execute("DELETE FROM audit_log WHERE timestamp < ? AND id NOT IN (SELECT id FROM audit_log ORDER BY timestamp DESC LIMIT ?)", (cutoff, k))
            return res.rowcount

    def health_check(self) -> bool:
        try: self._get_connection().execute("SELECT 1"); return True
        except: return False
    def get_backend_type(self) -> str: return 'flatfile'
