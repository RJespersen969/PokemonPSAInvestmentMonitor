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
    if isinstance(rows, dict) and 'tcgPlayerId' in rows:
        rows = [rows]
    if not isinstance(rows, list):
        fields = ','.join(sorted(rows)[:30]) if isinstance(rows, dict) else type(rows).__name__
        raise RuntimeError('Ukendt API-format; data-felter: ' + fields + '; topniveau: ' + ','.join(sorted(response)[:30]))
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


def kr(amount):
    return f"{amount:,.0f}".replace(',', '.') + ' kr.'


def in_price_range(cfg, result, rate):
    amount = result['median'] * rate
    return monitor.money(cfg.get('min_price_dkk', 0)) <= amount <= monitor.money(cfg.get('max_price_dkk', 1000000000))


def card_embed(card, result=None, rate=None, change=None, error=False):
    name = card.get('tracker_name', card['name']).split(' · ')[0]
    embed = {'title': name, 'description': f"💎 **PSA {card['grade']}** · 🇬🇧 Engelsk", 'color': 0x5865F2}
    if result is None:
        embed.update(color=0xF0B232, fields=[{'name': '⏳ Status', 'value': 'Priskilden kunne ikke læses.' if error else 'Ingen PSA-salgsmedian tilgængelig.'}])
        return embed
    trend = 'Første måling' if change is None else f"{'📈' if change > 0 else '📉' if change < 0 else '➖'} {change:+.1f}% siden sidst"
    embed['color'] = 0x57F287 if change and change > 0 else 0xED4245 if change and change < 0 else 0x5865F2
    date = str(result['last_sale'])[:10]
    try:
        date = datetime.strptime(date, '%Y-%m-%d').strftime('%d.%m.%Y')
    except ValueError:
        date = 'Ukendt'
    embed['fields'] = [
        {'name': '💰 Salgsmedian', 'value': f"**≈ {kr(result['median']*rate)}**\n${result['median']:,.2f}", 'inline': True},
        {'name': '📊 Udvikling', 'value': trend, 'inline': True},
        {'name': '🧾 Registrerede salg', 'value': f"{result['count']:,}".replace(',', '.'), 'inline': True},
        {'name': '🕓 Seneste salg', 'value': date, 'inline': True}]
    if card.get('tracker_variant_note'):
        embed['fields'].append({'name': '⚠️ Variant', 'value': 'Unlimited er ikke særskilt verificeret.'})
    embed['footer'] = {'text': 'Salgstal fra udbyderen · ikke kun dagens salg'}
    return embed


def report_embeds(cfg, rows, rate, now):
    overview = {'title': '⚡ PSA WATCH', 'description': f"Dit Pokémon-overblik · **{len(rows)} kort**",
                'color': 0xFEE75C, 'fields': [
                    {'name': '💳 Månedsbudget', 'value': kr(cfg['monthly_budget_dkk']), 'inline': True},
                    {'name': '🗓️ Horisont', 'value': f"{cfg['holding_years']}+ år", 'inline': True},
                    {'name': '🔄 Pristjek', 'value': 'Hver 6. time', 'inline': True}],
                'footer': {'text': f'PokemonPriceTracker · manuel USD/DKK {rate} · ekskl. omkostninger · eksempler, ikke købsråd'},
                'timestamp': now.isoformat()}
    if 'min_price_dkk' in cfg:
        overview['fields'].append({'name': '🎯 Prisinterval', 'value': kr(cfg['min_price_dkk']) + '–' + kr(cfg['max_price_dkk']), 'inline': True})
        overview['description'] = f"**{len(rows)} PSA-kort i dit prisinterval** · {len(cfg['cards'])} kandidater tjekket"
        if not rows:
            overview['description'] += '\nIngen kandidater har en verificeret salgsmedian i intervallet lige nu.'
    return [overview] + rows


def once(force_report=False):
    rate = check()
    cfg = monitor.config()
    # Two credits per card per run, four scheduled runs/day. Reserve half the free allowance.
    if len(cfg['cards']) > 6 or cfg['interval_seconds'] < 21600:
        raise RuntimeError('Gratis opsætning er begrænset til 6 kort for at bevare plads til genforsøg')
    now = datetime.now(timezone.utc)
    rows, failures = [], 0
    with closing(monitor.database()) as db:
        had_observations = bool(db.execute('SELECT 1 FROM tracker_snapshots LIMIT 1').fetchone())
        for card in cfg['cards']:
            name = card.get('tracker_name', card['name'])
            try:
                result = fetch(card)
                if result is None:
                    if 'min_price_dkk' not in cfg:
                        rows.append(card_embed(card))
                    continue
                previous = db.execute('SELECT median_usd FROM tracker_snapshots WHERE card_id=? ORDER BY time DESC LIMIT 1',
                                      (card['id'],)).fetchone()
                change = 100*(float(result['median'])/previous[0]-1) if previous else None
                db.execute('INSERT INTO tracker_snapshots VALUES(?,?,?,?,?,?,?)',
                           (now.isoformat(), card['id'], card['grade'], float(result['median']),
                            result['count'], result['last_sale'], float(rate)))
                db.commit()
                print(f"PSA {card['grade']}-observation gemt for {card['id']}; ingen API-nøgler eller priser i loggen.")
                if not in_price_range(cfg, result, rate):
                    continue
                rows.append(card_embed(card, result, rate, change))
                threshold = card.get('alert_below_dkk')
                if threshold is not None and result['median']*rate <= monitor.money(threshold):
                    key = (card['id'], 'tracker-median:' + str(result['median']), str(threshold))
                    if not db.execute('SELECT 1 FROM alerts WHERE card_id=? AND item_id=? AND threshold=?', key).fetchone():
                        alarm = card_embed(card, result, rate, change)
                        alarm.update(title='🔔 MEDIAN-ALARM · ' + alarm['title'], color=0xF0B232)
                        alarm['description'] += f"\nUnder din grænse på **{kr(threshold)}**"
                        alarm['footer'] = {'text': 'Salgsstatistik · ikke et aktivt købstilbud · ekskl. omkostninger'}
                        monitor.send_embeds([alarm])
                        db.execute('INSERT INTO alerts VALUES(?,?,?,?)', (*key, now.isoformat()))
                        db.commit()
            except (RuntimeError, ValueError, TypeError, KeyError) as error:
                failures += 1
                detail = str(error) if isinstance(error, RuntimeError) else type(error).__name__
                print(f"Datakilde fejlede for {card['id']}: {detail}", file=sys.stderr)
                if 'min_price_dkk' not in cfg:
                    rows.append(card_embed(card, error=True))
        last = db.execute("SELECT value FROM state WHERE key='last_report'").fetchone()
        first_prices = not had_observations and bool(db.execute('SELECT 1 FROM tracker_snapshots LIMIT 1').fetchone())
        if force_report or not last or first_prices or time.time()-float(last[0]) >= cfg['report_interval_hours']*3600:
            monitor.send_embeds(report_embeds(cfg, rows, rate, now))
            if not failures:
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
            once(force_report='--force-report' in sys.argv[2:])
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
