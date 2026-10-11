import base64
from contextlib import closing
from copy import deepcopy
import gzip
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from cryptography.fernet import Fernet, InvalidToken

import github_state
import monitor
import tracker


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data_patch = patch.object(monitor, 'DATA', self.root)
        self.data_patch.start()
        self.cfg = monitor.config()
        self.card = self.cfg['cards'][0]

    def tearDown(self):
        self.data_patch.stop()
        self.temp.cleanup()

    def response(self):
        return {'data': [{'tcgPlayerId': self.card['tcgplayer_id'], 'ebay': {'salesByGrade': {
            'psa10': {'medianPrice': 200, 'count': 8, 'lastSaleDate': '2026-10-11'},
            'psa9': {'medianPrice': 50, 'count': 12}}}}]}

    def test_exact_psa_grade_selected(self):
        result = tracker.parse_grade(self.card, self.response())
        self.assertEqual(result['median'], 200)
        self.assertEqual(result['count'], 8)

    def test_single_card_object_supported(self):
        response = {'data': self.response()['data'][0]}
        self.assertEqual(tracker.parse_grade(self.card, response)['median'], 200)

    def test_ungraded_and_other_grader_not_used(self):
        response = self.response()
        response['data'][0]['ebay']['salesByGrade'].pop('psa10')
        response['data'][0]['ebay']['salesByGrade']['cgc10'] = {'medianPrice': 999, 'count': 50}
        response['data'][0]['prices'] = {'market': 9999}
        self.assertIsNone(tracker.parse_grade(self.card, response))

    def test_wrong_card_and_nan_rejected(self):
        response = self.response()
        response['data'][0]['tcgPlayerId'] = 1
        with self.assertRaises(RuntimeError):
            tracker.parse_grade(self.card, response)
        response = self.response()
        response['data'][0]['ebay']['salesByGrade']['psa10']['medianPrice'] = 'NaN'
        with self.assertRaises(ValueError):
            tracker.parse_grade(self.card, response)

    def test_report_suppressed_until_due_and_alert_deduplicated(self):
        self.cfg['cards'] = [self.card]
        self.card['alert_below_dkk'] = 1500
        with patch.object(tracker, 'check', return_value=monitor.money('6.50')), \
                patch.object(monitor, 'config', return_value=self.cfg), \
                patch.object(tracker, 'fetch', return_value=tracker.parse_grade(self.card, self.response())), \
                patch.object(monitor, 'send') as send:
            tracker.once()
            first = send.call_count
            self.assertEqual(first, 3)
            tracker.once()
            self.assertEqual(send.call_count, first)
        with closing(sqlite3.connect(self.root/'psa.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM tracker_snapshots').fetchone()[0], 2)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM snapshots').fetchone()[0], 0)

    def test_plaintext_backup_of_tracker_history_blocked(self):
        with closing(monitor.database()) as db:
            db.execute("INSERT INTO tracker_snapshots VALUES('today','card',10,200,8,'today',6.5)")
            db.commit()
        with patch.dict(os.environ, {'STATE_ENCRYPTION_KEY': ''}):
            with self.assertRaises(RuntimeError):
                github_state.public_backup(self.root/'psa.sqlite3', self.root/'public.sqlite3')

    def test_encrypted_state_roundtrip_and_wrong_key_rejected(self):
        with closing(monitor.database()) as db:
            db.execute("INSERT INTO tracker_snapshots VALUES('today','card',10,200,8,'today',6.5)")
            db.commit()
        key = Fernet.generate_key()
        client = Mock()
        client.api.side_effect = [{'object': {}}, {'sha': 'file-sha'}, {}]
        with patch.dict(os.environ, {'STATE_ENCRYPTION_KEY': key.decode()}):
            github_state.save(client)
            payload = client.api.call_args.args[2]
            self.assertEqual(payload['branch'], 'tracker-state')
            encrypted = base64.b64decode(payload['content'])
            self.assertFalse(encrypted.startswith(b'SQLite'))
            raw = gzip.decompress(Fernet(key).decrypt(encrypted))
            self.assertTrue(raw.startswith(b'SQLite'))
            restore_client = Mock()
            restore_client.api.side_effect = [{'object': {}}, {'encoding': 'base64', 'content': payload['content'], 'size': len(encrypted)}]
            github_state.restore(restore_client)
        with patch.dict(os.environ, {'STATE_ENCRYPTION_KEY': Fernet.generate_key().decode()}):
            restore_client = Mock()
            restore_client.api.side_effect = [{'object': {}}, {'encoding': 'base64', 'content': payload['content'], 'size': len(encrypted)}]
            before = (self.root/'psa.sqlite3').read_bytes()
            with self.assertRaises(InvalidToken):
                github_state.restore(restore_client)
            self.assertEqual((self.root/'psa.sqlite3').read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
