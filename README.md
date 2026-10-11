# PSA Pokémon-overvågning til Discord

Dette er et **separat projekt**, beregnet til det nye repository:
`RJespersen969/PokemonPSAInvestmentMonitor`. Upload filerne fra denne mappe til
roden af det nye repository. Projektet skal ikke lægges ind i det eksisterende
`RJespersen969/PokemonMonitor`, og det ændrer ingen af dets workflows eller bots.

Opret en ny Discord-webhook til dette projekt. Bevar den eksisterende bots webhook,
secrets, hosting og opsætning. På samme VPS skal projektet ligge i sin egen mappe,
så det får sit eget Docker Compose-projekt og datavolume.

**Valgt gratis drift: GitHub Actions.** Følg `GITHUB_SETUP.md` for at aktivere fire
automatiske pristjek om dagen og bevare offentlig markedsprishistorik mellem kørslerne.
`.github/workflows/monitor.yml` kører overvågningen; `validate.yml` tester koden.
Begge workflows kører kun i det nye repository med navnet angivet ovenfor.
Docker og systemd nedenfor er alternative driftsformer, hvis du senere får en VPS.

Python-script til en horisont på mindst 5 år og et månedsbudget på **3.000 kr.**
Det søger hver 6. time, gemmer prishistorik i SQLite og sender en daglig rapport til Discord.
Ingen eksterne Python-pakker er nødvendige. Kræver Python 3.11 eller nyere.

## Status

Projektet er klargjort til gratis, planlagte kørsler med GitHub Actions.
Det er **ikke aktiveret på GitHub eller tilsluttet Discord endnu**. Projektfilerne skal
uploades, og dine API-nøgler og den nye Discord-webhook skal gemmes som repository-secrets.
Til GitHub-drift bruges ingen `.env`-fil; guiden nedenfor til `.env` gælder lokal/VPS-drift.

## 1. Discord og eBay

1. Lav en tekstkanal, fx `psa-overvaagning`, i din Discord-server.
2. Kanalindstillinger → Integrationer → Webhooks → Ny webhook → Kopiér webhook-URL.
3. Kopiér `.env.example` til `.env`. Indsæt webhooken i `DISCORD_WEBHOOK_URL`.
4. Opret et udvikler-login på https://developer.ebay.com/ og hent dine **Production**-nøgler.
   Gem App ID/Client ID i `EBAY_CLIENT_ID` og Cert ID/Client Secret i `EBAY_CLIENT_SECRET`.
   eBay skal give appen adgang til Browse API i produktion; nøgler alene garanterer ikke adgang.
5. Indtast en aktuel EUR/DKK-kurs i `EUR_DKK_RATE`. Den opdateres ikke automatisk.

Gem aldrig webhook eller nøgler i GitHub eller chatten. `.env` er udeladt fra Git og Docker-image.
På en hostingtjeneste kan værdierne i stedet gemmes som miljøvariabler/secrets.

## 2. Vælg kort

Redigér `watchlist.json`. De to Pokémon-kort er **tekniske eksempler**, ikke anbefalede investeringer.
Der er ingen aktive prisalarmer, før du erstatter `alert_below_dkk: null` med din egen prisgrænse.

- `query`: eBay-søgning, helst med sæt, kortnummer, sprog og grade.
- `required_terms`: tekst, der skal optræde i annoncens titel.
- `excluded_terms`: tekst, der udelukker annoncen.
- `grade`: præcis PSA-grade; matcher fx PSA 10, men ikke PSA 9.
- `alert_below_dkk`: alarmgrænse i DKK for **kortets udbudspris**, ekskl. omkostninger.
- `id`: stabilt, unikt id. Skift id, hvis kortets sprog, variant eller grade ændres,
  så forskellige produkter ikke blandes i historikken.

Titelmatch er et filter, ikke verificering af ægthed, sprog eller variant.
Kontrollér billeder, PSA-certifikat, sælger og omkostninger inden et køb.

## 3. Lokal test

PowerShell på denne pc:

```powershell
cd C:\Users\ralle\projekter_til_Discord\PokemonPSAInvestmentMonitor
Copy-Item .env.example .env
$psaPython = 'C:\Users\ralle\AppData\Local\Python\pythoncore-3.14-64\python.exe'
& $psaPython -m unittest discover -s tests -v
& $psaPython monitor.py demo
& $psaPython monitor.py check
& $psaPython monitor.py test-discord
& $psaPython monitor.py once --dry-run
& $psaPython monitor.py once
```

`demo` bruger syntetiske priser og sender intet. `check` validerer kun lokale indstillinger.
`test-discord` sender en testbesked. `once --dry-run` henter virkelige priser og gemmer historik,
men sender ingen Discord-beskeder. `once` sender også rapport/alarmer, hvis de er relevante.
`run` fortsætter løbende. Kør kun én overvågningsproces pr. database.

## 4. Permanent drift med Docker på VPS

Serveren skal have Docker Engine og Docker Compose installeret.
Upload eller klon projektet, og opret `.env` på serveren. Kør fra projektmappen:

```sh
docker compose build
docker compose run --rm psa-monitor python monitor.py check
docker compose run --rm psa-monitor python monitor.py test-discord
docker compose run --rm psa-monitor python monitor.py once --dry-run
docker compose up -d
docker compose logs --tail=50 psa-monitor
```

Containeren genstarter efter fejl og servergenstart, når Docker starter automatisk.
Den sender en daglig rapport, også når ingen annoncer matcher, så du kan se, at den kører.
Hvis rapporten udebliver, kontrollér hostens status og loggen.

SQLite-historikken ligger på det persistente volume `psa-data`, ikke i containerens midlertidige filsystem.
Tag regelmæssige backups, og bevar volumet ved opdateringer. Undgå `docker compose down -v`,
som sletter volumet. En server, der slukkes eller går i sleep, kan ikke overvåge.

Eksportér CSV-filer og kopier dem ud som backup:

```sh
docker compose exec psa-monitor python monitor.py export
docker compose cp psa-monitor:/app/data/snapshots.csv ./snapshots.csv
docker compose cp psa-monitor:/app/data/purchases.csv ./purchases.csv
```

Til fuld databasebackup: stop først containeren, kopiér hele data-mappen ud,
og start igen. Det undgår en inkonsistent SQLite-kopi med aktive WAL-filer.

### Hosting direkte fra GitHub

Upload projektfilerne til et privat repository; udelad `.env`, `data/` og zip-filer.
En tjeneste med understøttelse af vedvarende workers kan bygge `Dockerfile`.
Kør `python monitor.py run`, tilføj miljøvariablerne og montér persistent disk på `/app/data`.
Disken skal være skrivbar for UID 10001, som containeren bruger.
Denne proces har ingen HTTP-port: vælg en baggrundsworker, ikke en webservice med portkrav.
Et GitHub-repository i sig selv kører ikke processen. GitHub Actions er ikke den permanente worker i denne opsætning.

### Alternativ: systemd uden Docker

Placér projektet i `/opt/psa-investment-monitor` og opret en servicebruger:

```sh
sudo useradd --system --home /opt/psa-investment-monitor --shell /usr/sbin/nologin psa-investment-monitor
sudo mkdir -p /opt/psa-investment-monitor/data
sudo chown psa-investment-monitor:psa-investment-monitor /opt/psa-investment-monitor/data
sudo chown root:psa-investment-monitor /opt/psa-investment-monitor/.env
sudo chmod 640 /opt/psa-investment-monitor/.env
sudo cp deploy/psa-investment-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now psa-investment-monitor
sudo journalctl -u psa-investment-monitor -n 50
```

Vælg Docker **eller** systemd, så der ikke sendes dobbelte beskeder.

## 5. Registrér køb og følg budgettet

Angiv hele købets pris i DKK inkl. fragt, moms, import og gebyrer:

```sh
python monitor.py purchase --card umbreon-vmax-215-en-psa10 --amount 1200 --date 2026-10-11 --note "Købspris inkl. omkostninger"
```

Brug kortets eksisterende `id` fra `watchlist.json` og din faktiske købspris og købsdato.
Ved Docker-drift bruges `docker compose exec psa-monitor python monitor.py purchase ...`.
Rapporten viser månedens registrerede forbrug og restbudget; et overskredet budget vises negativt.
Uregistrerede køb tælles ikke med. Scriptet køber ingen kort og placerer ingen ordrer.

## Hvad tallene betyder for en 5+ års horisont

eBay Browse API viser aktive annoncer, **ikke gennemførte salg**.
Medianen er medianen af de matchende udbudspriser i det hentede udsnit og er ikke en porteføljeværdi.
Rapporten viser ændring siden sidste vellykkede observation, ikke et afkast.
Flere annoncer fra samme sælger/certifikat kan forekomme. En forsvundet annonce beviser ikke et salg.
Fragt, dansk importmoms, told, platformgebyrer og valutabevægelser er ikke indregnet.
Hver observation gemmer den manuelt angivne valutakurs. Historik begynder ved første kørsel.

Før en eventuel investering bør din vurdering også bygge på dokumenterede salg,
handelsvolumen, PSA-population og dens vækst samt stand, variant og samlede handelsomkostninger.
Scriptet henter ikke PSA-population, historiske salg eller beregner forventet afkast.
En horisont på 5 år giver ingen garanti for værdistigning eller mulighed for hurtigt salg.

API-kald har timeout og begrænsede genforsøg; Discord-rate limits håndteres.
Prisalarmer huskes efter bekræftet afsendelse pr. annonce og prisgrænse.
Et nedbrud efter afsendelse men før lagring kan dog give en gentaget besked.
Ved ændring af en alarmgrænse kan samme annonce udløse en ny alarm.
Der sendes højst tre prisalarmer pr. kort pr. cyklus.

Officielle referencer: [eBay Browse API](https://www.developer.ebay.com/develop/api/buy/browse_api),
[eBay Buy API-adgang](https://developer.ebay.com/api-docs/buy/static/buy-requirements.html),
[Discord-webhooks](https://docs.discord.com/developers/resources/webhook).
