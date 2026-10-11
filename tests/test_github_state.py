import base64
from contextlib import closing
import gzip
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

import github_state
import monitor


class GitHubStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patch = patch.object(monitor, 'DATA', self.root)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def make_source(self):
        db = monitor.database()
        db.execute('INSERT INTO purchases(date,card_id,total_dkk,note) VALUES(?,?,?,?)',
                   ('2026-10-11', 'private-card', 1234, 'PRIVATE PURCHASE NOTE'))
        db.execute("INSERT INTO state VALUES('private-token','SECRET_TOKEN')")
        db.execute("INSERT INTO state VALUES('last_report','100')")
        db.execute("INSERT INTO snapshots VALUES('today','card',1,100,100,7.46,0)")
        db.execute("INSERT INTO alerts VALUES('card','item','1500','today')")
        db.commit()
        db.close()
        return self.root / 'psa.sqlite3'

    def test_public_backup_excludes_private_data(self):
        source = self.make_source()
        destination = self.root / 'public.sqlite3'
        github_state.public_backup(source, destination)
        with closing(sqlite3.connect(destination)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM purchases').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT * FROM state').fetchall(), [('last_report', '100')])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM snapshots').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM alerts').fetchone()[0], 1)
        self.assertNotIn(b'PRIVATE PURCHASE NOTE', destination.read_bytes())
        self.assertNotIn(b'SECRET_TOKEN', destination.read_bytes())

    def test_restore_recovers_history(self):
        self.make_source()
        clean = self.root / 'clean.sqlite3'
        github_state.public_backup(self.root / 'psa.sqlite3', clean)
        compressed = gzip.compress(clean.read_bytes())
        client = Mock()
        client.api.side_effect = [{'object': {'sha': 'branchsha'}},
                                  {'content': base64.b64encode(compressed).decode(),
                                   'encoding': 'base64', 'size': len(compressed)}]
        github_state.restore(client)
        with closing(sqlite3.connect(self.root / 'psa.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM snapshots').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM purchases').fetchone()[0], 0)

    def test_missing_first_run_keeps_local_database(self):
        source = self.make_source()
        before = source.read_bytes()
        client = Mock()
        client.api.return_value = None
        github_state.restore(client)
        self.assertEqual(source.read_bytes(), before)

    def test_network_failure_does_not_reset_history(self):
        source = self.make_source()
        before = source.read_bytes()
        client = Mock()
        client.api.side_effect = RuntimeError('HTTP 500')
        with self.assertRaises(RuntimeError):
            github_state.restore(client)
        self.assertEqual(source.read_bytes(), before)

    def test_state_with_purchases_rejected_before_restore(self):
        source = self.make_source()
        before = source.read_bytes()
        compressed = gzip.compress(before)
        client = Mock()
        client.api.side_effect = [{'object': {}}, {'content': base64.b64encode(compressed).decode(),
                                  'encoding': 'base64', 'size': len(compressed)}]
        with self.assertRaises(RuntimeError):
            github_state.restore(client)
        self.assertEqual(source.read_bytes(), before)

    def test_guard_excludes_old_repository(self):
        with patch.dict('os.environ', {'GITHUB_REPOSITORY': 'RJespersen969/PokemonMonitor', 'GH_TOKEN': 'test'}):
            with self.assertRaises(RuntimeError):
                github_state.GitHub()

    def test_save_uses_current_sha_and_only_state_branch(self):
        self.make_source()
        client = Mock()
        client.api.side_effect = [{'object': {}}, {'sha': 'current-file-sha'}, {}]
        github_state.save(client)
        call = client.api.call_args
        self.assertEqual(call.args[0], '/contents/market-state.sqlite3.gz')
        self.assertEqual(call.args[1], 'PUT')
        self.assertEqual(call.args[2]['branch'], 'monitor-state')
        self.assertEqual(call.args[2]['sha'], 'current-file-sha')


if __name__ == '__main__':
    unittest.main()
