"""Persist public market history in this project's dedicated GitHub state branch."""
import base64
from contextlib import closing
import gzip
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import monitor

REPOSITORY = 'RJespersen969/PokemonPSAInvestmentMonitor'
BRANCH = 'monitor-state'
FILENAME = 'market-state.sqlite3.gz'
MAX_COMPRESSED = 900_000
MAX_DATABASE = 50_000_000


def state_location():
    return ('tracker-state', 'private-market-state.fernet') if os.environ.get('STATE_ENCRYPTION_KEY') else (BRANCH, FILENAME)


def cipher():
    from cryptography.fernet import Fernet
    return Fernet(os.environ['STATE_ENCRYPTION_KEY'].encode())


class GitHub:
    def __init__(self):
        if os.environ.get('GITHUB_REPOSITORY') != REPOSITORY:
            raise RuntimeError('State storage is restricted to the new investment-monitor repository')
        self.token = os.environ.get('GH_TOKEN', '')
        if not self.token:
            raise RuntimeError('Missing automatic GitHub Actions token')

    def api(self, path, method='GET', payload=None, allow_missing=False):
        request = Request('https://api.github.com/repos/' + REPOSITORY + path,
                          method=method,
                          data=json.dumps(payload).encode() if payload is not None else None,
                          headers={'Authorization': 'Bearer ' + self.token,
                                   'User-Agent': 'PokemonPSAInvestmentMonitor',
                                   'Accept': 'application/vnd.github+json',
                                   'Content-Type': 'application/json'})
        try:
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as error:
            if error.code == 404 and allow_missing:
                return None
            raise RuntimeError(f'GitHub state API failed (HTTP {error.code}); existing state was not replaced') from None
        except (URLError, TimeoutError, OSError):
            raise RuntimeError('GitHub state connection failed; existing state was not replaced') from None


def read_remote(client):
    branch_name, filename = state_location()
    branch = client.api('/git/ref/heads/' + branch_name, allow_missing=True)
    if branch is None:
        return None
    # Missing data on an existing branch is an error, not permission to discard history.
    return client.api('/contents/' + filename + '?ref=' + branch_name)


def validate_market_state(path):
    with closing(sqlite3.connect(path)) as db:
        if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise RuntimeError('Invalid SQLite market history')
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if tables not in ({'snapshots', 'alerts', 'purchases', 'state'},
                          {'snapshots', 'alerts', 'purchases', 'state', 'tracker_snapshots'}):
            raise RuntimeError('Unexpected tables in market history')
        if db.execute('SELECT COUNT(*) FROM purchases').fetchone()[0]:
            raise RuntimeError('Public market state must not contain purchases')
        if db.execute("SELECT COUNT(*) FROM state WHERE key != 'last_report'").fetchone()[0]:
            raise RuntimeError('Unexpected private state')


def restore(client):
    remote = read_remote(client)
    if remote is None:
        print('First run: no market-history branch yet.')
        return
    if remote.get('encoding') != 'base64' or remote.get('size', 0) > MAX_COMPRESSED:
        raise RuntimeError('Market history is too large or has an unsupported encoding')
    compressed = base64.b64decode(remote['content'])
    if os.environ.get('STATE_ENCRYPTION_KEY'):
        compressed = cipher().decrypt(compressed)
    import io
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
        raw = stream.read(MAX_DATABASE + 1)
    if len(raw) > MAX_DATABASE:
        raise RuntimeError('Market database exceeded the safety size limit')
    monitor.DATA.mkdir(parents=True, exist_ok=True)
    temporary = monitor.DATA / 'restored.sqlite3'
    temporary.write_bytes(raw)
    validate_market_state(temporary)
    temporary.replace(monitor.DATA / 'psa.sqlite3')
    print('Market history and delivered alerts restored.')


def public_backup(source, destination):
    # Construct a fresh database from an explicit list. Never copy purchase records,
    # notes, logs, secrets, arbitrary state keys or extra tables to the public branch.
    with closing(sqlite3.connect(source)) as original, closing(monitor.database(destination)) as public:
        public.executemany('INSERT INTO snapshots VALUES(?,?,?,?,?,?,?)',
                           original.execute('SELECT time,card_id,count,min_eur,median_eur,eur_dkk,truncated FROM snapshots'))
        public.executemany('INSERT INTO alerts VALUES(?,?,?,?)',
                           original.execute('SELECT card_id,item_id,threshold,sent_at FROM alerts'))
        public.executemany('INSERT INTO state VALUES(?,?)',
                           original.execute("SELECT key,value FROM state WHERE key='last_report'"))
        tables = {row[0] for row in original.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'tracker_snapshots' in tables:
            if original.execute('SELECT COUNT(*) FROM tracker_snapshots').fetchone()[0] and not os.environ.get('STATE_ENCRYPTION_KEY'):
                raise RuntimeError('Tracker history requires encrypted storage; no plaintext upload allowed')
            public.executemany('INSERT INTO tracker_snapshots VALUES(?,?,?,?,?,?,?)',
                               original.execute('SELECT time,card_id,grade,median_usd,sales_count,last_sale,usd_dkk FROM tracker_snapshots'))
        public.commit()
        public.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    validate_market_state(destination)


def save(client):
    source = monitor.DATA / 'psa.sqlite3'
    if not source.exists():
        print('No database created; no remote changes.')
        return
    with tempfile.TemporaryDirectory() as folder:
        clean = Path(folder) / 'market.sqlite3'
        public_backup(source, clean)
        compressed = gzip.compress(clean.read_bytes(), mtime=0)
    if os.environ.get('STATE_ENCRYPTION_KEY'):
        compressed = cipher().encrypt(compressed)
    if len(compressed) > MAX_COMPRESSED:
        raise RuntimeError('Compressed history exceeded 900 KB; export and plan separate storage before continuing')
    remote = read_remote(client)
    branch_name, filename = state_location()
    if remote is None:
        main = client.api('/git/ref/heads/main')
        client.api('/git/refs', 'POST', {'ref': 'refs/heads/' + branch_name, 'sha': main['object']['sha']})
    payload = {'message': 'Save PSA monitoring history', 'branch': branch_name,
               'content': base64.b64encode(compressed).decode()}
    if remote:
        payload['sha'] = remote['sha']
    client.api('/contents/' + filename, 'PUT', payload)
    print('Market history saved. Purchase data and notes were excluded.')


if __name__ == '__main__':
    try:
        if len(sys.argv) != 2 or sys.argv[1] not in ('restore', 'save'):
            raise RuntimeError('Use github_state.py restore|save')
        client = GitHub()
        (restore if sys.argv[1] == 'restore' else save)(client)
    except Exception as error:
        print(str(error) if isinstance(error, RuntimeError) else 'Market state failed: ' + type(error).__name__, file=sys.stderr)
        sys.exit(1)
