import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import monitor


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.cfg = monitor.config()
        self.card = self.cfg['cards'][0]
        self.temp = tempfile.TemporaryDirectory()
        self.data_patch = patch.object(monitor, 'DATA', Path(self.temp.name))
        self.data_patch.start()
        self.db = monitor.database(':memory:')

    def tearDown(self):
        self.db.close()
        self.data_patch.stop()
        self.temp.cleanup()

    def test_grade_and_variant_filter(self):
        good = {'title': self.card['query']}
        self.assertTrue(monitor.match(self.card, good))
        for title in (self.card['query'].replace('PSA 10', 'PSA 9'),
                      self.card['query'].replace('PSA 10', 'PSA 100'),
                      self.card['query'] + ' Japanese',
                      self.card['query'].replace(self.card['required_terms'][-1], '999/999')):
            self.assertFalse(monitor.match(self.card, {'title': title}))

    def test_currency_and_price_filter(self):
        items, _ = monitor.Demo().search(self.card)
        self.assertEqual(len(monitor.candidates(self.card, items, 'EUR')), 1)
        self.assertEqual(monitor.candidates(self.card, items, 'USD'), [])
        items[0]['price']['value'] = 'NaN'
        self.assertEqual(monitor.candidates(self.card, items, 'EUR'), [])

    def test_successful_alert_deduplicated(self):
        self.card['alert_below_dkk'] = 2000
        with patch.object(monitor, 'send') as send:
            monitor.cycle(self.db, self.cfg, monitor.Demo())
            first = send.call_count
            monitor.cycle(self.db, self.cfg, monitor.Demo())
            self.assertEqual(send.call_count, first)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM alerts').fetchone()[0], 1)

    def test_failed_send_is_not_marked_delivered(self):
        self.card['alert_below_dkk'] = 2000
        with patch.object(monitor, 'send', side_effect=RuntimeError('test failure')):
            with self.assertRaises(RuntimeError):
                monitor.cycle(self.db, self.cfg, monitor.Demo())
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM alerts').fetchone()[0], 0)
        self.assertIsNone(self.db.execute("SELECT value FROM state WHERE key='last_report'").fetchone())

    def test_dry_run_never_sends_or_records_delivery(self):
        self.card['alert_below_dkk'] = 2000
        with patch.object(monitor, 'send') as send, patch('builtins.print'):
            monitor.cycle(self.db, self.cfg, monitor.Demo(), True)
        send.assert_not_called()
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM alerts').fetchone()[0], 0)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM snapshots').fetchone()[0], len(self.cfg['cards']))

    def test_budget_is_month_specific(self):
        self.db.executemany('INSERT INTO purchases(date,card_id,total_dkk,note) VALUES(?,?,?,?)',
                            [('2026-10-11', 'a', 1250, ''), ('2026-10-12', 'a', 500, ''),
                             ('2026-09-30', 'a', 2800, '')])
        self.assertEqual(monitor.spent(self.db, '2026-10'), 1750)

    def test_missing_data_is_not_zero_price(self):
        source = monitor.Demo()
        with patch.object(source, 'search', return_value=([], False)), patch('builtins.print'):
            monitor.cycle(self.db, self.cfg, source, True)
        self.assertEqual(self.db.execute('SELECT count,min_eur,median_eur FROM snapshots LIMIT 1').fetchone(),
                         (0, None, None))

    def test_discord_mentions_disabled_and_confirmation_requested(self):
        with patch.dict('os.environ', {'DISCORD_WEBHOOK_URL': 'https://discord.com/api/webhooks/123/testtoken'}), \
                patch.object(monitor, 'http_json', return_value={}) as http:
            monitor.send('@everyone test')
        self.assertIn('wait=true', http.call_args.args[0])
        payload = json.loads(http.call_args.args[3])
        self.assertEqual(payload['allowed_mentions'], {'parse': []})


if __name__ == '__main__':
    unittest.main()
