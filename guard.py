"""
Prompter — GUARD
Keeps the robot safe to leave on a public URL, and keeps the bill small.

  1. Per-visitor caps    -- how many robot calls one visitor can make an hour
  2. Daily ceiling       -- how many profiles Prompter makes in a day, total
  3. Material caps       -- how much text one request can send the robot
  4. Safe fetch          -- the URL reader only visits normal public websites

All counting lives in this process's memory: no database. It resets when
Railway redeploys, which is fine for this job. It also assumes ONE gunicorn
worker (pinned in the Procfile) -- with two, every cap quietly doubles.

Every number is a Railway variable with a sensible default.
"""

import ipaddress
import os
import socket
import threading
import time
from collections import deque
from datetime import datetime
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

from flask import jsonify, request
import requests as req


def _int_env(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


# --- The numbers ------------------------------------------------------------
ROBOT_CALLS_PER_HOUR = _int_env('PROMPTER_CALLS_PER_HOUR', 80)    # per visitor
READS_PER_HOUR       = _int_env('PROMPTER_READS_PER_HOUR', 30)    # uploads + URL reads, per visitor
PROFILES_PER_DAY     = _int_env('PROMPTER_PROFILES_PER_DAY', 100) # everyone, NZ day
ROBOT_CALLS_PER_DAY  = _int_env('PROMPTER_CALLS_PER_DAY', 3000)   # everyone, NZ day -- backstop
MAX_MATERIAL_CHARS   = _int_env('PROMPTER_MAX_MATERIAL_CHARS', 200_000)  # per request, all files
MAX_UPLOAD_MB        = _int_env('PROMPTER_MAX_UPLOAD_MB', 10)
FETCH_MAX_BYTES      = 2 * 1024 * 1024
FETCH_MAX_REDIRECTS  = 3

NZ = ZoneInfo('Pacific/Auckland')

# Which routes count as what. Anything under /api/ not listed costs nothing.
ROBOT_ROUTES = {
    '/api/consult', '/api/confirm', '/api/confirm/regenerate', '/api/extract',
    '/api/summarise', '/api/revise', '/api/rules',
    '/api/pipeline/sort', '/api/pipeline/calibrate',
    '/api/pipeline/shape', '/api/pipeline/run',
}
PROFILE_ROUTES = {'/api/extract', '/api/pipeline/shape', '/api/pipeline/run'}
READ_ROUTES = {'/api/upload', '/api/fetch'}

# Messages the browser may show. Michael's words -- change them here.
MSG_SLOW_DOWN = "Sorry we've hit the cap. Try again in an hour."
MSG_CLOSED    = "Closed for today, we've maxed out the robot."
MSG_TOO_MUCH  = "Woah, there's lots there. Can you pick tighter examples?"


# --- Counting ---------------------------------------------------------------
_lock = threading.Lock()
_visitors = {}          # (kind, ip) -> deque of timestamps
_day = {'date': None, 'profiles': 0, 'calls': 0}


def client_ip():
    """Railway's edge adds the real visitor address to the END of
    X-Forwarded-For. Anything earlier in the list the visitor could have typed
    themselves, so take the last one."""
    fwd = request.headers.get('X-Forwarded-For', '')
    if fwd:
        return fwd.split(',')[-1].strip()
    return request.remote_addr or 'unknown'


def _hit(kind, ip, limit, window=3600):
    """Record one hit. True if it's within the limit."""
    now = time.time()
    with _lock:
        q = _visitors.setdefault((kind, ip), deque())
        while q and q[0] <= now - window:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        # Stop the table growing forever: drop visitors gone quiet.
        if len(_visitors) > 5000:
            for k in [k for k, v in _visitors.items() if not v or v[-1] <= now - window]:
                del _visitors[k]
        return True


def _spend(profile):
    """Count one robot call against today's ceiling. True if allowed."""
    today = datetime.now(NZ).date()
    with _lock:
        if _day['date'] != today:
            _day.update(date=today, profiles=0, calls=0)
        if _day['calls'] >= ROBOT_CALLS_PER_DAY:
            return False
        if profile and _day['profiles'] >= PROFILES_PER_DAY:
            return False
        _day['calls'] += 1
        if profile:
            _day['profiles'] += 1
        return True


def _material_size(data):
    """Rough size of the text a request is sending the robot."""
    if not isinstance(data, dict):
        return 0
    total = 0
    for f in data.get('files') or []:
        if isinstance(f, dict):
            total += len(str(f.get('text', '')))
    for h in data.get('history') or []:
        if isinstance(h, dict):
            total += len(str(h.get('content', '')))
    for key in ('material', 'consultNotes', 'text'):
        total += len(str(data.get(key) or ''))
    for key in ('profile', 'brief'):
        if data.get(key):
            total += len(str(data.get(key)))
    return total


def check_request():
    """Runs before every request. Returns a response to stop it, or None."""
    path = request.path
    if not path.startswith('/api/'):
        return None
    ip = client_ip()

    if path in READ_ROUTES:
        if not _hit('read', ip, READS_PER_HOUR):
            return jsonify({'error': MSG_SLOW_DOWN, 'code': 'slow_down'}), 429
        return None

    if path in ROBOT_ROUTES:
        if request.is_json:
            if _material_size(request.get_json(silent=True)) > MAX_MATERIAL_CHARS:
                return jsonify({'error': MSG_TOO_MUCH, 'code': 'too_much'}), 413
        if not _hit('robot', ip, ROBOT_CALLS_PER_HOUR):
            return jsonify({'error': MSG_SLOW_DOWN, 'code': 'slow_down'}), 429
        if not _spend(path in PROFILE_ROUTES):
            return jsonify({'error': MSG_CLOSED, 'code': 'closed'}), 503
    return None


def install(app):
    app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD_MB * 1024 * 1024
    app.before_request(check_request)

    @app.errorhandler(413)
    def _too_big(_e):
        return jsonify({'error': MSG_TOO_MUCH, 'code': 'too_much'}), 413


# --- Safe fetch -------------------------------------------------------------
class UnsafeURL(Exception):
    pass


def _check_public(url):
    """Refuse anything that isn't a normal public website: other schemes,
    odd ports, and any address that points inside a network (localhost,
    office/home ranges, Railway's internal network, cloud metadata)."""
    p = urlparse(url)
    if p.scheme not in ('http', 'https'):
        raise UnsafeURL('Only web addresses (http or https).')
    if not p.hostname:
        raise UnsafeURL('That address has no site in it.')
    if p.port not in (None, 80, 443):
        raise UnsafeURL('That address uses an unusual port.')
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == 'https' else 80))
    except socket.gaierror:
        raise UnsafeURL("Couldn't find that site.")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split('%')[0])
        if not ip.is_global:
            raise UnsafeURL("That address isn't a public website.")


def safe_get(url, headers=None, timeout=12):
    """GET a public page. Checks every redirect hop, and stops reading at
    FETCH_MAX_BYTES. Returns (final_url, raw bytes) -- the HTML parser works
    out the page's own character set from the bytes."""
    for _ in range(FETCH_MAX_REDIRECTS + 1):
        _check_public(url)
        resp = req.get(url, headers=headers, timeout=timeout,
                       allow_redirects=False, stream=True)
        if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
            loc = resp.headers.get('Location')
            resp.close()
            if not loc:
                break
            url = urljoin(url, loc)
            continue
        resp.raise_for_status()
        body = b''
        for chunk in resp.iter_content(64 * 1024):
            body += chunk
            if len(body) >= FETCH_MAX_BYTES:
                break
        resp.close()
        return url, body
    raise UnsafeURL('That address redirects too many times.')
