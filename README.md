# PSA Pok?mon-overv?gning til Discord

Gratis automatisk overv?gning med **PokemonPriceTracker + GitHub Actions**.
Budget: **3.000 kr./m?ned**. Horisont: **5+ ?r**.
Dette projekt ligger separat i `RJespersen969/PokemonPSAInvestmentMonitor`.
Det ?ndrer ikke det eksisterende `PokemonMonitor`.

## S?dan k?rer det

- GitHub laver ?t pristjek hver 6. time, planlagt kl. 00:17, 06:17, 12:17 og 18:17 UTC.
- Discord f?r en rapport cirka ?n gang i d?gnet og valgfrie median-alarmer.
- Priserne er **PSA-salgsmedianer fra PokemonPriceTracker**, ikke aktuelle k?bstilbud.
- Historik og sendte alarmer gemmes krypteret p? branchen `tracker-state`.
- N?gler, private k?b og noter uploades ikke som data.

Scriptet bruger en manuel USD/DKK-kurs, som vises i rapporten.
`USD_DKK_RATE` kan ?ndres under GitHub Settings ? Secrets and variables ? Actions ? Variables.
Standardv?rdien 6.50 er en beregningsv?rdi og ikke en automatisk opdateret valutakurs.
Fragt, import, moms og handelsgebyrer er ikke inkluderet i de omregnede markedspriser.

## GitHub-ops?tning

Se [GITHUB_SETUP.md](GITHUB_SETUP.md). De aktuelt anvendte secret-navne er:

- `DISCORD_WEBHOOK_PSA` (eller `DISCORD_WEBHOOK_URL`).
- `PSA_API_KEY` (eller `POKEMON_PRICE_TRACKER_API_KEY`).
- `STATE_ENCRYPTION_KEY`, oprettet til den krypterede historik.

eBay Client ID og Client Secret er **ikke n?dvendige** til denne driftsform.
`monitor.py` indeholder stadig den tidligere eBay-version som et alternativ.

?bn **Actions ? PSA Pokemon monitoring ? Run workflow** for et ekstra pristjek.
Det sender kun en ny rapport, hvis den er forfalden, eller en relevant alarm udl?ses.
**Test PSA Discord connection** sender en s?rskilt forbindelsestest uden at kr?ve prisn?glen.
GitHub kan forsinke eller springe planlagte k?rsler over. Hold ?je med daglige rapporter
og Actions-status; gratis drift er ikke en garanti for 24/7-oppetid eller fem ?rs u?ndrede vilk?r.

## Overv?gningsliste

Redig?r `watchlist.json`. Kortene er tekniske eksempler, ikke k?bsanbefalinger.
`tcgplayer_id` identificerer kortet hos udbyderen, og `grade` v?lger pr?cis PSA-grade.
Andre graders priser og ugraderede kort bruges ikke som erstatning, hvis PSA-data mangler.
Listen tester Pikachu 160/159, Suicune V GG38, Raikou V GG41 og Entei V GG36 i engelsk PSA 10. Discord viser kun kort med salgsmedian mellem 500 og 2.500 DKK (inklusive), ekskl. fragt og afgifter. Kandidater uden PSA-data eller uden for intervallet udelades; historikken bevares.

`alert_below_dkk: null` betyder ingen alarm. S?t en egen prisgr?nse for at f? en alarm,
n?r udbyderens salgsmedian omregnet til DKK er under den. Alarmen er en statistikalarm,
ikke en annonce, man kan k?be. Samme median og prisgr?nse gentages normalt ikke.

Den gratis ops?tning tillader h?jst seks kort og mindst seks timer mellem pristjek.
De fire kandidater bruger normalt 32 credits/d?gn med fire k?rsler; gratisplanen
angiver 100 credits/d?gn. Ekstra k?rsler og genfors?g t?ller ogs?. Ingen betalt plan v?lges automatisk.

## Privat registrering af k?b

K?b registreres lokalt, s? de ikke ligger i det offentlige repository:

```sh
python monitor.py purchase --card pikachu-160-159-en-psa10 --amount 1200 --date 2026-10-11 --note "Pris inkl. omkostninger"
python monitor.py export
```

Brug dine faktiske k?bsoplysninger. GitHub-rapporten viser m?nedsbudgettet, men beregner
ikke dit restbudget ud fra k?b, der kun findes privat p? din pc.
Scriptet handler ikke automatisk og giver ingen garanti for fremtidigt afkast.

## Lokal drift og tests

Python 3.11+:

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python monitor.py demo
```

Til lokal drift kopieres `.env.example` til `.env`, og prisn?gle og webhook udfyldes.
K?r `python tracker.py check`, derefter `python tracker.py once` eller `python tracker.py run`.
`demo` bruger kun syntetiske data. `.env` og `data/` skal ikke uploades.

Docker er en valgfri alternativ driftsform p? en server, du selv har:

```sh
docker compose up -d --build
```

Brug kun ?n driftsform, s? der ikke kommer dobbelte beskeder.
Systemd-filen i `deploy/` forventer et virtuelt Python-milj? i projektets `.venv`.
VPS/Docker er ikke n?dvendigt til den valgte gratis GitHub-l?sning.

Kilder: [PokemonPriceTracker API](https://www.pokemonpricetracker.com/api-reference),
[PSA-felter](https://www.pokemonpricetracker.com/psa-pokemon-card-api),
[GitHub Actions-priser](https://docs.github.com/en/billing/concepts/product-billing/github-actions).
