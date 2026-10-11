"""PSA-overvågning: eBay-udbud, lokal historik og Discord. Kun standardbibliotek."""
from __future__ import annotations

import argparse
import base64
import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import sqlite3
import statistics
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("DATA_DIR", str(ROOT / "data")))
LOG = logging.getLogger("psa")


def load_env():
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def money(value):
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("Beløb skal være et tal") from None
    if not result.is_finite() or result < 0:
        raise ValueError("Beløb skal være endelige og ikke negative")
    return result


def config():
    cfg = json.loads((ROOT / "watchlist.json").read_text(encoding="utf-8-sig"))
    if cfg["currency"] != "EUR":
        raise ValueError("Denne version kræver EUR; valutakursen er EUR/DKK")
    money(cfg["monthly_budget_dkk"])
    if cfg["interval_seconds"] < 300 or cfg["report_interval_hours"] < 1:
        raise ValueError("Minimum: 300 sekunder mellem søgninger og 1 time mellem rapporter")
    if not 1 <= cfg["max_pages"] <= 10 or cfg["holding_years"] < 5:
        raise ValueError("max_pages skal være 1..10, og holding_years mindst 5")
    ids = set()
    for card in cfg["cards"]:
        if card["id"] in ids or not card["query"].strip():
            raise ValueError("Kort skal have unikke id'er og en søgning")
        ids.add(card["id"])
        if card["grade"] not in range(1, 11):
            raise ValueError("PSA-grade skal være 1..10")
        if card.get("alert_below_dkk") is not None:
            money(card["alert_below_dkk"])
    return cfg


def database(path=None):
    DATA.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path or DATA / "psa.sqlite3")
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
      CREATE TABLE IF NOT EXISTS snapshots (
        time TEXT, card_id TEXT, count INTEGER, min_eur REAL, median_eur REAL,
        eur_dkk REAL, truncated INTEGER, PRIMARY KEY(time, card_id));
      CREATE TABLE IF NOT EXISTS alerts (
        card_id TEXT, item_id TEXT, threshold TEXT, sent_at TEXT,
        PRIMARY KEY(card_id, item_id, threshold));
      CREATE TABLE IF NOT EXISTS purchases (
        id INTEGER PRIMARY KEY, date TEXT, card_id TEXT, total_dkk REAL, note TEXT);
      CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT);
    """)
    return db


def http_json(url, method="GET", headers=None, body=None):
    headers = {"User-Agent": "PSASlabMonitor/1.0", **(headers or {})}
    for attempt in range(4):
        request = Request(url, data=body, method=method, headers=headers)
        try:
            with urlopen(request, timeout=30) as response:
                raw = response.read()
                return json.loads(raw) if raw else {}
        except HTTPError as exc:
            if exc.code == 429 or 500 <= exc.code <= 599:
                delay = exc.headers.get("Retry-After", "")
                if exc.code == 429:
                    try:
                        delay = json.loads(exc.read()).get("retry_after", delay)
                    except (ValueError, TypeError):
                        pass
                try:
                    seconds = max(1, float(delay))
                except (ValueError, TypeError):
                    seconds = 2 ** attempt
                if attempt < 3:
                    time.sleep(min(seconds, 300))
                    continue
            # Undgå at logge webhook, token eller response-body.
            raise RuntimeError(f"HTTP {exc.code}; kontrollér adgang og API-konfiguration") from None
        except (URLError, TimeoutError, OSError):
            if attempt == 3:
                raise RuntimeError("Netværksfejl efter 4 forsøg") from None
            time.sleep(2 ** attempt)
    raise RuntimeError("API-kald mislykkedes")


class Ebay:
    def __init__(self, cfg):
        self.cfg, self.token, self.expires = cfg, None, 0

    def auth(self):
        if self.token and time.time() < self.expires:
            return self.token
        key = os.environ.get("EBAY_CLIENT_ID", "")
        secret = os.environ.get("EBAY_CLIENT_SECRET", "")
        if not key or not secret:
            raise ValueError("Udfyld EBAY_CLIENT_ID og EBAY_CLIENT_SECRET i .env")
        encoded = base64.b64encode(f"{key}:{secret}".encode()).decode()
        response = http_json(
            "https://api.ebay.com/identity/v1/oauth2/token", "POST",
            {"Authorization": f"Basic {encoded}", "Content-Type": "application/x-www-form-urlencoded"},
            urlencode({"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"}).encode())
        self.token = response["access_token"]
        self.expires = time.time() + int(response["expires_in"]) - 60
        return self.token

    def search(self, card):
        result, seen, truncated = [], set(), False
        for page in range(self.cfg["max_pages"]):
            query = urlencode({"q": card["query"], "limit": 200, "offset": page * 200,
                               "sort": "price", "filter": "buyingOptions:{FIXED_PRICE}"})
            response = http_json("https://api.ebay.com/buy/browse/v1/item_summary/search?" + query,
                                 headers={"Authorization": f"Bearer {self.auth()}",
                                          "X-EBAY-C-MARKETPLACE-ID": self.cfg["marketplace"]})
            for item in response.get("itemSummaries", []):
                if item["itemId"] not in seen:
                    result.append(item)
                    seen.add(item["itemId"])
            truncated = bool(response.get("next"))
            if not truncated:
                break
        return result, truncated


def match(card, item):
    title = item.get("title", "").casefold()
    if not re.search(r"\bpsa\s*" + str(card["grade"]) + r"\b", title):
        return False
    return (all(term.casefold() in title for term in card["required_terms"])
            and not any(term.casefold() in title for term in card["excluded_terms"]))


def candidates(card, items, currency):
    result = []
    for item in items:
        if not match(card, item) or "FIXED_PRICE" not in item.get("buyingOptions", []):
            continue
        price = item.get("price", {})
        if price.get("currency") != currency:
            continue
        try:
            amount = money(price["value"])
        except (ValueError, KeyError):
            continue
        if amount == 0:
            continue
        result.append({"id": item["itemId"], "title": item["title"], "price": amount,
                       "url": item.get("itemWebUrl", "")})
    return sorted(result, key=lambda row: row["price"])


def webhook_url():
    url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.hostname != "discord.com" or
            not re.fullmatch(r"/api(?:/v\d+)?/webhooks/\d+/[\w.-]+", parts.path)):
        raise ValueError("Gem en gyldig https://discord.com/api/webhooks/... i .env")
    query = dict(parse_qsl(parts.query))
    query["wait"] = "true"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def send(content):
    http_json(webhook_url(), "POST", {"Content-Type": "application/json"},
              json.dumps({"username": "PSA-overvågning", "content": content[:1900],
                          "allowed_mentions": {"parse": []}}, ensure_ascii=False).encode())


def spent(db, month):
    return db.execute("SELECT COALESCE(SUM(total_dkk),0) FROM purchases WHERE substr(date,1,7)=?",
                      (month,)).fetchone()[0]


def cycle(db, cfg, source, dry_run=False):
    now = datetime.now(timezone.utc)
    stamp = now.isoformat()
    rate = money(os.environ.get("EUR_DKK_RATE", "7.46"))
    if rate == 0:
        raise ValueError("EUR_DKK_RATE skal være positiv")
    rows, failures = [], 0
    for card in cfg["cards"]:
        try:
            items, truncated = source.search(card)
            listings = candidates(card, items, cfg["currency"])
            prices = [float(x["price"]) for x in listings]
            minimum = min(prices) if prices else None
            median = statistics.median(prices) if prices else None
            previous = db.execute("SELECT median_eur FROM snapshots WHERE card_id=? AND median_eur IS NOT NULL ORDER BY time DESC LIMIT 1",
                                  (card["id"],)).fetchone()
            change = f" · {100 * (median / previous[0] - 1):+.1f}% siden sidst" if median and previous else ""
            db.execute("INSERT INTO snapshots VALUES(?,?,?,?,?,?,?)",
                       (stamp, card["id"], len(prices), minimum, median, float(rate), int(truncated)))
            db.commit()
            detail = (f"{len(prices)} annoncer · laveste ~{minimum * float(rate):.0f} kr. · median ~{median * float(rate):.0f} kr.{change}"
                      if prices else "Ingen matchende annoncer i denne søgning")
            rows.append(f"**{card['name']}**\n{detail}" + ("\nBegrænset udsnit: flere søgeresultater findes." if truncated else ""))
            threshold = card.get("alert_below_dkk")
            if threshold is None:
                continue
            for item in listings[:3]:
                if item["price"] * rate > money(threshold):
                    continue
                key = (card["id"], item["id"], str(threshold))
                if db.execute("SELECT 1 FROM alerts WHERE card_id=? AND item_id=? AND threshold=?", key).fetchone():
                    continue
                message = (f"Prisalarm: **{card['name']}**\nUdbudspris ~{item['price'] * rate:.0f} kr. "
                           f"({item['price']} EUR); din grænse: {threshold} kr.\n{item['url']}\n"
                           "Ekskl. fragt, import, moms og gebyrer. Kontrollér sprog, variant og PSA-certifikat manuelt.")
                if dry_run:
                    print(message)
                else:
                    send(message)
                    db.execute("INSERT INTO alerts VALUES(?,?,?,?)", (*key, stamp))
                    db.commit()
        except (RuntimeError, ValueError, KeyError, TypeError) as exc:
            failures += 1
            LOG.error("Kort %s fejlede (%s)", card["id"], type(exc).__name__)
            rows.append(f"**{card['name']}**\nDatakilden kunne ikke læses; ingen ny pris.")
    last = db.execute("SELECT value FROM state WHERE key='last_report'").fetchone()
    due = not last or time.time() - float(last[0]) >= cfg["report_interval_hours"] * 3600
    if due or dry_run:
        budget = cfg["monthly_budget_dkk"]
        used = spent(db, now.strftime("%Y-%m"))
        budget_line = (f"Månedsbudget {budget:.0f} kr. · køb registreres privat på din pc.\n"
                       if os.environ.get("PUBLIC_MARKET_MODE") == "1" else
                       f"Månedsbudget {budget:.0f} kr. · registreret {used:.0f} kr. · rest {budget-used:.0f} kr.\n")
        header = (f"PSA Pokémon · {now:%Y-%m-%d %H:%M} UTC · horisont {cfg['holding_years']}+ år\n"
                  + budget_line +
                  f"Manuel valutakurs: 1 EUR = {rate} DKK.\n"
                  "Aktive udbudspriser, ikke gennemførte salg. Ekskl. fragt, import og gebyrer. "
                  "Historik starter ved første kørsel; eksempler er ikke købsanbefalinger.")
        messages = [header] + rows
        for message in messages:
            if dry_run:
                print(message)
            else:
                send(message)
        if not dry_run:
            db.execute("INSERT OR REPLACE INTO state VALUES('last_report',?)", (str(time.time()),))
            db.commit()
    return failures


class Demo:
    def search(self, card):
        return [{"itemId": "DEMO-" + card["id"], "title": card["query"],
                 "price": {"value": "199.00", "currency": "EUR"},
                 "buyingOptions": ["FIXED_PRICE"], "itemWebUrl": "https://www.ebay.com/"}], False


def main():
    load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["run", "once", "demo", "test-discord", "export", "purchase", "check"])
    parser.add_argument("--dry-run", action="store_true", help="Ingen Discord-beskeder; live once/run gemmer stadig historik")
    parser.add_argument("--card")
    parser.add_argument("--amount", type=str, help="Samlet købspris i DKK inkl. omkostninger")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--note", default="")
    args = parser.parse_args()
    DATA.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, handlers=[logging.StreamHandler(), RotatingFileHandler(DATA / "monitor.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")])
    cfg = config()
    if args.command == "check":
        webhook_url()
        for key in ("EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET"):
            if not os.environ.get(key):
                raise ValueError(f"Udfyld {key} i .env")
        if money(os.environ.get("EUR_DKK_RATE", "7.46")) == 0:
            raise ValueError("Valutakurs skal være positiv")
        print("Lokal konfiguration OK. API-adgang er ikke testet.")
        return
    if args.command == "test-discord":
        send("PSA-overvågning: forbindelsestest OK. Budget: 3.000 kr./måned. Dette er en test.")
        print("Discord bekræftede testbeskeden.")
        return
    if args.command in ("run", "once") and not args.dry_run:
        webhook_url()
    with database(":memory:" if args.command == "demo" else None) as db:
        if args.command == "purchase":
            if args.card not in {c["id"] for c in cfg["cards"]} or args.amount is None:
                parser.error("purchase kræver et --card fra watchlist og --amount")
            date = datetime.strptime(args.date, "%Y-%m-%d").strftime("%Y-%m-%d")
            db.execute("INSERT INTO purchases(date,card_id,total_dkk,note) VALUES(?,?,?,?)",
                       (date, args.card, float(money(args.amount)), args.note))
            db.commit()
            print(f"Køb registreret. Forbrug {date[:7]}: {spent(db, date[:7]):.2f} kr.")
        elif args.command == "export":
            for table in ("snapshots", "purchases"):
                cursor = db.execute(f"SELECT * FROM {table}")
                with (DATA / f"{table}.csv").open("w", newline="", encoding="utf-8-sig") as output:
                    writer = csv.writer(output)
                    writer.writerow([col[0] for col in cursor.description])
                    writer.writerows(cursor)
            print("CSV-filer gemt i data-mappen.")
        elif args.command == "demo":
            print("DEMO — syntetiske priser; ingen netværkskald eller permanent prishistorik.")
            cycle(db, cfg, Demo(), True)
        else:
            source = Ebay(cfg)
            source.auth()
            while True:
                try:
                    failures = cycle(db, cfg, source, args.dry_run)
                    if args.command == "once":
                        if failures:
                            raise RuntimeError(f"{failures} søgninger fejlede; se log")
                        return
                    LOG.info("Cyklus færdig: %s fejl; næste om %s sekunder", failures, cfg["interval_seconds"])
                except (RuntimeError, ValueError) as exc:
                    if args.command == "once":
                        raise
                    LOG.error("Cyklus fejlede (%s); prøver igen efter intervallet", type(exc).__name__)
                time.sleep(cfg["interval_seconds"])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Stoppet.")
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
        # Ingen traceback med URL'er eller hemmeligheder.
        print(f"Fejl: {exc}" if isinstance(exc, (ValueError, RuntimeError)) else f"Fejl: {type(exc).__name__}; kontrollér konfiguration og filer", file=sys.stderr)
        sys.exit(1)
