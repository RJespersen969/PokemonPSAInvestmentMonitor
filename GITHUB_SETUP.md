# Gratis overvågning med GitHub Actions

Repository: https://github.com/RJespersen969/PokemonPSAInvestmentMonitor

Dette projekt kører selvstændigt. Det eksisterende `PokemonMonitor` ændres ikke.
Det nye repository er offentligt. Standard GitHub-hostede Linux-runners i offentlige
repositories er gratis ifølge GitHubs aktuelle prisregler.

## Upload

1. Udpak `PokemonPSAInvestmentMonitor-upload.zip` i en ny mappe.
2. Åbn det nye repository. Vælg **uploading an existing file**, eller **Add file → Upload files**.
3. Upload de udpakkede filer og mapper, inklusive `.github`, `.gitignore` og `.dockerignore`.
   `monitor.py`, `github_state.py`, `watchlist.json` og `Dockerfile` skal ligge i repositoryets rod.
   Begge workflows skal ligge i `.github/workflows/`.
4. Gem med **Commit changes** på `main`.
5. Åbn **Actions → Validate PSA investment monitor**, og kontrollér at testen bliver grøn.

Upload ikke selve zip-filen som erstatning for projektfilerne. Pakken indeholder ingen
`.env`, API-nøgler, webhook, købsdata eller lokale logfiler.

## Gem tre secrets

Opret en **ny** Discord-webhook til dette projekt. I det nye repository vælger du:
**Settings → Secrets and variables → Actions → New repository secret**.
Gem:

- `DISCORD_WEBHOOK_URL`
- `EBAY_CLIENT_ID`
- `EBAY_CLIENT_SECRET`

eBay skal give appen adgang til Browse API i produktion. Nøgler alene garanterer ikke adgang.
Del ikke værdierne i chatten, og læg dem ikke i kode eller `watchlist.json`.

Under fanen **Variables** kan du oprette `EUR_DKK_RATE` med en aktuel EUR/DKK-kurs.
Hvis den mangler, bruges standardværdien `7.46`. Kursen opdateres ikke automatisk.
`GITHUB_TOKEN` kommer automatisk fra GitHub; du skal ikke oprette et personligt token.

## Start

1. Kontrollér at **Actions → Validate PSA investment monitor** bliver grøn.
2. Åbn **Actions → PSA Pokemon monitoring → Run workflow → main → Run workflow**.
3. Kontrollér at kørslen bliver grøn, og at Discord modtager rapporten.
4. Derefter kører den planlagt kl. **00:17, 06:17, 12:17 og 18:17 UTC** hver dag.
   Danmark er UTC+1 om vinteren og UTC+2 om sommeren.

Ingen VPS, betalt hosting eller tændt pc er nødvendig. Workflowen laver ét pristjek
pr. kørsel og afslutter. Den er ikke en konstant kørende Discord-bot.

Workflowen får `contents: write` for at gemme markedsdata på en separat branch,
`monitor-state`. Hvis GitHub afviser skrivning, se fejlteksten og repositoryets
**Settings → Actions → General**. Organisationens regler eller branch-beskyttelse kan
begrænse tokenet. Koden ændrer ikke `main` eller dit gamle repository.

## Historik og privatliv

Prishistorik, alarm-id'er og tidspunktet for sidste daglige rapport gemmes komprimeret
som `market-state.sqlite3.gz` i roden af branchen `monitor-state`.
De hentes før hvert pristjek og gemmes bagefter, også efter almindelige delfejl.
Kørsler serialiseres, så to jobs ikke overskriver hinandens historik.

Denne branch er offentlig ligesom repositoryet. Den indeholder kun markedsobservationer,
kort-id'er, alarmgrænser og afsendelsestidspunkter. Nøgler, køb og private noter kopieres ikke.
Registrér køb privat på din pc med `monitor.py purchase` som beskrevet i README.
Discord viser i denne driftsform budgettet på 3.000 kr./måned, men ikke et beregnet
restbudget baseret på dine private køb.

En fejl ved hentning af eksisterende state stopper kørslen frem for at starte ny historik.
Ved et totalt timeout/nedbrud kan den seneste observation eller alarmkvittering gå tabt.
Hent løbende en backup af state-filen, hvis du vil sikre historikken uafhængigt af GitHub.
Slet ikke branchen `monitor-state`: det nulstiller historik og alarmhukommelse.
Komprimeret state har en grænse på 900 KB; ved mange overvågede kort kan separat
lagring blive nødvendig. Der er ingen garanti for fem års uændrede tjenestevilkår.

## Gratis drift og begrænsninger

Bevar repositoryet offentligt, og brug de medfølgende standard `ubuntu-latest` runners.
Workflowene bruger ingen betalte tjenester, større runners, Actions-artifacts eller caches.
Hvis repositoryet gøres privat, gælder kontoejerens delte gratis minutkvote i stedet;
eventuelt overforbrug kan blive faktureret afhængigt af kontoen.

GitHub kan forsinke eller springe planlagte kørsler over under belastning. I offentlige
repositories kan planlagte workflows blive deaktiveret efter 60 dage uden repositoryaktivitet.
Hold øje med daglige Discord-rapporter og GitHubs fejlmails, og kontrollér Actions,
hvis rapporterne udebliver. Det er gratis automatisk overvågning, ikke en garanti for 24/7 oppetid.

Kilder: [GitHub Actions-priser](https://docs.github.com/en/billing/concepts/product-billing/github-actions),
[planlagte workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).
