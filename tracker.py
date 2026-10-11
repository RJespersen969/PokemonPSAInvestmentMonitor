"""PSA sold-price summaries from PokemonPriceTracker's free API."""
from contextlib import closing
from datetime import datetime, timezone
import os
import sys
import time
from urllib.parse import urlencode

import monitor


def check():
    monitor.webhook_url()
    if not os.environ.get('POKEMON_PRICE_TRACKER_API_KEY'):
        raise RuntimeError('Gem POKEMON_PRICE_TRACKER_API_KEY som GitHub-secret')
    if os.environ.get('GITHUB_ACTIONS') and not os.environ.get('STATE_ENCRYPTION_KEY'):
        raise RuntimeError('GitHub-drift kræver STATE_ENCRYPTION_KEY til privat historik')
    rate = monitor.money(os.environ.get('USD_DKK_RATE', '6.50'))
    if rate == 0:
        raise RuntimeError('USD_DKK_RATE skal være positiv')
    return rate


def parse_grade(card, response):
    rows = response.get('data')
    if not isinstance(rows, list):
        raise RuntimeError('Ukendt API-format; ingen pris blev antaget')
    found = [row for row in rows if str(row.get('tcgPlayerId')) == str(card['tcgplayer_id'])]
    if len(found) != 1:
        raise RuntimeError('Kortet blev ikke entydigt identificeret')
    row = found[0]
    grade = (row.get('ebay') or {}).get('salesByGrade', {}).get('psa' + str(card['grade']))
    if not isinstance(grade, dict) or grade.get('medianPrice') is None:
        return None
    median = monitor.money(grade['medianPrice'])
    count = int(grade.get('count', 0))
    if median <= 0 or count <= 0:
        return None
    if count > 10_000_000:
        raise RuntimeError('Ugyldigt antal salg')
    return {'median': median, 'count': count, 'last_sale': grade.get('lastSaleDate') or 'ukendt'}


def fetch(card):
    query = urlencode({'tcgPlayerId': card['tcgplayer_id'], 'includeEbay': 'true',
                       'days': 3, 'language': 'english', 'limit': 1})
    data = monitor.http_json('https://www.pokemonpricetracker.com/api/v2/cards?' + query,
                             headers={'Authorization': 'Bearer ' + os.environ['POKEMON_PRICE_TRACKER_API_KEY']})
    return parse_grade(card, data)


def once():
    rate = check()
    cfg = monitor.config()
    # Two credits per card per run, four scheduled runs/day. Reserve half the free allowance.
    if len(cfg['cards']) > 6 or cfg['interval_seconds'] < 21600:
        raise RuntimeError('Gratis opsætning er begrænset til 6 kort for at bevare plads til genforsøg')
    now = datetime.now(timezone.utc)
    rows, failures = [], 0
    with closing(monitor.database()) as db:
        for card in cfg['cards']:
            name = card.get('tracker_name', card['name'])
            try:
                result = fetch(card)
                if result is None:
                    rows.append(f"**{name}**\nIngen brugbar PSA {card['grade']}-salgsmedian tilgængelig.")
                    continue
                previous = db.execute('SELECT median_usd FROM tracker_snapshots WHERE card_id=? ORDER BY time DESC LIMIT 1',
                                      (card['id'],)).fetchone()
                change = f" · {100*(float(result['median'])/previous[0]-1):+.1f}% siden sidst" if previous else ''
                db.execute('INSERT INTO tracker_snapshots VALUES(?,?,?,?,?,?,?)',
                           (now.isoformat(), card['id'], card['grade'], float(result['median']),
                            result['count'], result['last_sale'], float(rate)))
                db.commit()
                print(f"PSA {card['grade']}-observation gemt for {card['id']}; ingen API-nøgler eller priser i loggen.")
                rows.append(f"**{name}**\nPSA {card['grade']}-salgsmedian: ${result['median']:.2f} "
                            f"(~{result['median']*rate:.0f} kr.){change}\n"
                            f"Udbyderen angiver {result['count']} registrerede salg; det er ikke nødvendigvis dagens eller tre dages salg.\n"
                            f"Seneste salg angivet: {result['last_sale']}" +
                            (f"\n{card['tracker_variant_note']}" if card.get('tracker_variant_note') else ''))
                threshold = card.get('alert_below_dkk')
                if threshold is not None and result['median']*rate <= monitor.money(threshold):
                    key = (card['id'], 'tracker-median:' + str(result['median']), str(threshold))
                    if not db.execute('SELECT 1 FROM alerts WHERE card_id=? AND item_id=? AND threshold=?', key).fetchone():
                        monitor.send(f"Median-alarm: **{name}**\nUdbyderens PSA {card['grade']}-salgsmedian er "
                                     f"~{result['median']*rate:.0f} kr., under din grænse på {threshold} kr.\n"
                                     "Dette er salgsstatistik, ikke en annonce, du kan købe. Kontrollér variant og samlede omkostninger.")
                        db.execute('INSERT INTO alerts VALUES(?,?,?,?)', (*key, now.isoformat()))
                        db.commit()
            except (RuntimeError, ValueError, TypeError, KeyError) as error:
                failures += 1
                print(f"Datakilde fejlede for {card['id']} ({type(error).__name__})", file=sys.stderr)
                rows.append(f"**{name}**\nDatakilden kunne ikke læses; ingen ny pris.")
        last = db.execute("SELECT value FROM state WHERE key='last_report'").fetchone()
        if not last or time.time()-float(last[0]) >= cfg['report_interval_hours']*3600:
            monitor.send(f"PSA Pokémon · {now:%Y-%m-%d %H:%M} UTC · {cfg['holding_years']}+ år\n"
                         f"Månedsbudget: {cfg['monthly_budget_dkk']:.0f} kr. Køb registreres privat.\n"
                         f"Kilde: PokemonPriceTracker, sammenfattede graderede salg. Manuel kurs: 1 USD = {rate} DKK.\n"
                         "Priser er ikke aktive købstilbud eller afkastprognoser. Eksempler er ikke købsanbefalinger. "
                         "Fragt, import, moms og gebyrer er ikke indregnet. Historik starter ved første kørsel.")
            for row in rows:
                monitor.send(row)
            db.execute("INSERT OR REPLACE INTO state VALUES('last_report',?)", (str(time.time()),))
            db.commit()
    if failures:
        raise RuntimeError(f'{failures} kort kunne ikke læses; se log')


if __name__ == '__main__':
    monitor.load_env()
    try:
        command = sys.argv[1] if len(sys.argv) > 1 else 'once'
        if command == 'check':
            check()
            print('Tracker-konfiguration OK; API-adgang endnu ikke testet.')
        elif command == 'once':
            once()
        elif command == 'run':
            check()
            while True:
                try:
                    once()
                except (RuntimeError, ValueError) as error:
                    print('Pristjek fejlede (' + type(error).__name__ + '); næste forsøg efter intervallet', file=sys.stderr)
                time.sleep(max(21600, monitor.config()['interval_seconds']))
        else:
            raise RuntimeError('Brug tracker.py check|once|run')
    except Exception as error:
        print(str(error) if isinstance(error, RuntimeError) else 'Tracker-fejl: '+type(error).__name__, file=sys.stderr)
        sys.exit(1)
