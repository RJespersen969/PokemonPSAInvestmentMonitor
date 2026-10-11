# GitHub-ops?tning

Repository: https://github.com/RJespersen969/PokemonPSAInvestmentMonitor

Standard GitHub-hostede Linux-runners i dette offentlige repository er gratis.
PokemonPriceTrackers Free-plan angiver 100 credits/d?gn og kr?ver ingen eBay-godkendelse.
Projektet v?lger ikke en betalt API-plan og bruger ikke betalte GitHub-runners eller artifacts.

## Secrets

Under **Settings ? Secrets and variables ? Actions** gemmes:

- `DISCORD_WEBHOOK_PSA`: den nye PSA-kanals webhook. `DISCORD_WEBHOOK_URL` underst?ttes ogs?.
- `PSA_API_KEY`: PokemonPriceTracker-n?glen. `POKEMON_PRICE_TRACKER_API_KEY` underst?ttes ogs?.
- `STATE_ENCRYPTION_KEY`: en Fernet-n?gle til historikken. Den er oprettet ved ops?tningen.

N?glen fra PokemonPriceTracker findes p? https://www.pokemonpricetracker.com/api-keys.
V?lg Free-planen. Del ikke n?gler eller webhook-URL i kode eller chatten.
Hvis begge alternative navne findes, har de lange navne forrang.
Gem en aktuel `USD_DKK_RATE` som **Variable**; ellers bruges den manuelle standardv?rdi 6.50.

## Start og kontrol

1. **Actions ? Validate PSA investment monitor** skal v?re gr?n.
2. **Actions ? PSA Pokemon monitoring ? Run workflow ? main** starter et pristjek.
3. Kontroll?r at **Check prices and send Discord messages** og **Preserve encrypted history** bliver gr?nne.
4. F?rste k?rsel sender rapporten til Discord. Senere rapporter sendes cirka hver 24. time.
5. Tidsplanen laver fire pristjek/d?gn: 00:17, 06:17, 12:17 og 18:17 UTC.

**Test PSA Discord connection** tester webhooken uden API-n?glen.
GitHub opretter automatisk `GITHUB_TOKEN`; du skal ikke gemme et personligt token til workflowen.
`contents: write` bruges til at gemme state p? den separate branch, ikke til at ?ndre `main`.

## Historik

Branchen `tracker-state` indeholder `private-market-state.fernet`, en krypteret,
komprimeret SQLite-database. Selvom repositoryet er offentligt, kan prishistorikken
ikke l?ses uden `STATE_ENCRYPTION_KEY`. Private k?b og noter udelades ogs? f?r kryptering.
Tag backup af den krypterede fil sammen med en separat sikker backup af krypteringsn?glen.
Slet eller udskift ikke n?glen uden en migrationsplan: eksisterende historik kan ellers ikke ?bnes.

En fejl ved restore stopper pristjekket for at undg? at nulstille historik.
Almindelige delfejl gemmer stadig succesfulde observationer. Et totalt timeout/nedbrud
kan miste seneste observation eller alarmkvittering. Samme alarm kan da blive gentaget.
Krypteret state er begr?nset til 900 KB i denne version; flere kort eller mange ?rs historik
kan kr?ve separat lagring. Samlede registrerede salg er udbyderens statistik, ikke n?dvendigvis
salg i dag eller i de seneste tre dage. Der k?bes ingen kort automatisk.

## Drift

Bevar repositoryet offentligt for den valgte gratis GitHub-drift. Private repositories
bruger kontoejerens delte gratis minutkvote og kan have betalt overforbrug.
GitHub kan forsinke eller springe planlagte k?rsler over og kan deaktivere tidsplaner
p? offentlige repositories efter 60 dage uden aktivitet. Hold ?je med Discord og Actions.

Priskilden er til personlig/hobbybrug. Et projekt med indt?gter, butik, reklamer eller
kommerciel brug kr?ver en s?rskilt vurdering af udbyderens plan og licens.

Kilder: [API og gratisplan](https://www.pokemonpricetracker.com/api-reference),
[licens](https://www.pokemonpricetracker.com/licensing),
[GitHub-priser](https://docs.github.com/en/billing/concepts/product-billing/github-actions).
