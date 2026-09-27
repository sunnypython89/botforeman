# SCOUT și AUDIT — extensie opțională pentru consum redus

Aceste moduri sunt separate de ciclul fix 5×5. Ciclul existent și stabilitatea
NATIV nu sunt modificate. Nu există antrenare, LoRA nou, embeddings sau metode
statistice. Rezultatele probelor rămân GOOD / BAD / UNCERTAIN.

## SCOUT

Implicit, selectează cel mult 3 probe, una per categorie. Folosește poolul contextual
al `nativ_roman.bot`, nu benchmarkurile înghețate. Ordinea priorităților:
UNSTABLE/NEEDS_RETEST, ACTIVE, STABLE_GOOD. Între categorii cu aceeași prioritate
preferă cele cu mai puține observații; seed-ul oferă departajarea deterministă.
Într-o categorie preferă probe mai puțin folosite și probe CORE marcate manual.

Salvează toate răspunsurile și identifică probele și categoriile BAD/UNCERTAIN.
Nu pretinde acoperirea tuturor competențelor după o rulare scurtă.

## AUDIT

Primește raportul SCOUT și extrage suspecții din rezultate, nu din etichete
introduse arbitrar. Modelul, adaptorul, poolul și versiunile evaluatorilor trebuie
să coincidă cu manifestul SCOUT. Implicit selectează 2 întrebări noi per categorie
suspectă, cu maximum 6 în total. Nu reutilizează nici ID-urile, nici textul exact
al întrebărilor din SCOUT; în interiorul auditului nu permite duplicate.

Verdictul intern se referă la probele noi ale auditului:

- minimum două probe distincte și toate BAD: CONFIRMED_FAILURE;
- minimum două probe distincte și toate GOOD: CONFIRMED_STRENGTH;
- minimum două probe și apar atât GOOD, cât și BAD: UNSTABLE;
- altfel: NEEDS_MORE_EVIDENCE.

Probele WEAK/RETIRED nu contribuie la confirmarea unui eșec sau a unei capacități.
Un verdict CONFIRMED_STRENGTH nu certifică o competență generală și nu șterge
observația SCOUT. Starea persistentă a abilității ține separat întregul istoric.
Dacă nu există suspecți, AUDIT face zero apeluri de model. Modelul local este
încărcat la nevoie, astfel încât un audit gol nici nu încarcă greutățile GPU.
Dacă poolul nu oferă suficiente întrebări noi, categoriile rămân NEEDS_MORE_EVIDENCE.

## Starea abilităților și calitatea probelor

Reguli implicite, configurabile prin JSON `--rules`:

```json
{
  "scout_probes": 3,
  "audit_per_category": 2,
  "max_audit_probes": 6,
  "stable_good_distinct": 3,
  "alternations": 3,
  "history_window": 6,
  "weak_uncertain": 3,
  "weak_unresolved_evaluators": 2,
  "audit_confirmation": 2
}
```

Fără observații: ACTIVE. Ultimul BAD sau UNCERTAIN: NEEDS_RETEST. Trei GOOD
consecutive pe ID-uri și texte distincte: STABLE_GOOD. Trei alternanțe GOOD/BAD
în fereastra ultimelor șase observații: UNSTABLE, cu prioritate față de celelalte
stări. UNCERTAIN nu este convertit în BAD. O singură probă repetată nu poate
stabiliza singură o abilitate.

Registrul păstrează separat NORMAL, CORE, WEAK și RETIRED. CORE și RETIRED se
setează explicit prin `Registry.set_probe_state`; niciun GOOD nu promovează
automat proba în CORE. WEAK apare după trei observații neclare noi sau după ce
doi evaluatori locali diferiți nu pot clarifica răspunsul. Este un semnal de
revizuire a probei/parserelor, nu dovada că întrebarea este greșită.

WEAK_PROBE se raportează ca PROBE_QUALITY_ISSUE. Chiar dacă ulterior apare BAD
pe acea probă, nu se declară MODEL_FAILURE pe baza ei. Observațiile sale din starea
abilității devin neconcludente; răspunsurile și verdictele originale din jurnale
rămân nemodificate. Probele WEAK și RETIRED sunt excluse din selecția automată,
iar alte probe ale aceleiași categorii pot fi investigate.

Starea este separată după model, adaptor, provider, versiunile evaluatorilor și
hash-ul poolului. Nu se transferă STABLE_GOOD între checkpointuri. Reutilizarea
identică din cache nu adaugă dovezi artificiale. Un răspuns schimbat al modelului
este însă o observație nouă, chiar dacă evaluarea acelui răspuns exista în cache.
Selecția evită probele rezolvate în rularea imediat precedentă; ulterior pot fi
folosite din nou, în funcție de prioritate și istoricul de utilizare.

## Evaluatori și cache

Lanțul este LOCAL_PRIMARY → numai la UNCERTAIN, LOCAL_SECONDARY → numai dacă
rămâne UNCERTAIN, API_EVALUATOR explicit permis. Un GOOD/BAD încheie evaluarea.
Evaluatorul secundar actual recunoaște suplimentar doar răspunsuri explicite
precum «Varianta A». Nu este un al doilea model lingvistic și nu inventează
interpretări. Textul Copycat salvat rămâne exact cel primit.

Cache-ul este per etapă. Cheia conține modelul, adaptorul, providerul/configurația,
probe_id, promptul, răspunsul exact, evaluatorul, versiunea sa, modelul evaluatorului
dacă există, criteriul, versiunea și hash-ul întregului pool. Schimbarea oricăruia
invalidează reutilizarea. Erorile și rezultatele după depășirea limitelor nu sunt
introduse în cache. `--no-cache` dezactivează citirea și scrierea cache-ului.

Cache-ul economisește evaluarea, nu generarea răspunsului Copycat: răspunsul
trebuie cunoscut înainte de a calcula cheia. Un cache hit are consum nou zero
pentru etapa de evaluare și este vizibil în `evaluation_trace`.

## Costuri și API

Implicit: maximum 10.000 tokenuri locale, 0 apeluri API și 0 USD. CLI-ul nu
instalează și nu expune niciun transport API plătit. Toate testele și demo-ul
funcționează la cost API zero. Rularea SCOUT și rularea AUDIT au plafoane separate;
consumul perechii se obține prin însumarea celor două rapoarte.

`Meter` verifică limita superioară estimată înainte de fiecare apel de model
sau evaluator, apoi înregistrează consumul efectiv. La plafon, eroare ori consum
peste estimare oprește rularea și salvează rezultatele parțiale. Nu face retry.
Consumul necunoscut rămâne null în `usage`; `accounted_usage` păstrează rezervarea
conservatoare. Costul necunoscut poate folosi limita de tokenuri/apeluri existentă.

Pentru o extensie API, `EvaluationChain` cere simultan `allow_api=True`, limite
pozitive și finite de cost/apeluri, un evaluator injectat explicit și un
`BudgetLedger` cu modelul, tarife recente și aprobarea exactă a bugetului. La
`max_api_calls=0` sau `max_cost=0`, evaluatorul API nu este apelat. Modelul API
trebuie să coincidă cu cel aprobat. Contabilizarea recalculează costul din tarife
și tokenurile raportate; nu acceptă un cost zero declarat arbitrar de provider.

Nu s-a verificat și nu s-a propus niciun tarif real în această etapă, fiindcă nu
există apel plătit. Tarifele din teste sunt explicit fictive și nu pot fi folosite
în producție. Înaintea primei rulări reale plătite trebuie prezentate modelul,
tarifele oficiale verificate, limitele, estimarea maximă și cerută aprobarea unui
buget concret. Abonamentul ChatGPT nu este considerat credit API.

## Comenzi

Demo sintetic reproductibil, 3 probe SCOUT + 4 AUDIT:

```powershell
python -m botforeman.adaptive.demo
```

Rulare reală locală (folosește nume noi de directoare):

```powershell
python -m botforeman.adaptive SCOUT --provider copycat --adapter copycat_07_epoch1_adapter --workspace experiments/seria_adaptiva/state --output experiments/seria_adaptiva/scout_01 --max-tokens 4096 --max-api-calls 0 --max-cost 0
python -m botforeman.adaptive AUDIT --provider copycat --adapter copycat_07_epoch1_adapter --workspace experiments/seria_adaptiva/state --output experiments/seria_adaptiva/audit_01 --scout experiments/seria_adaptiva/scout_01/report.json --max-tokens 4096 --max-api-calls 0 --max-cost 0
```

Fără `--provider copycat` rulează fixture-ul sintetic. `--seed`, `--rules` și
`--no-cache` sunt disponibile în ambele moduri. Nu se suprascriu directoare existente.

```powershell
python -m unittest discover -s tests -v
```

## Fișiere și reproductibilitate

Fiecare rulare salvează `manifest.json`, `registry_before.json`,
`selected_probes.json`, `events.jsonl`, `results.jsonl` (dacă există rezultate) și
`report.json`. Manifestul include modul, identitățile, versiunile, seed-ul,
timestamp-ul, limitele, starea cache-ului, regulile și proveniența SCOUT pentru AUDIT.
Snapshotul registrului explică selecția; snapshotul întrebărilor reproduce lotul.

Workspace-ul comun păstrează `registry.json` și `cache/`. Lock-ul exclusiv evită
actualizări concurente și consum duplicat accidental. Un lock rămas după crash
trebuie inspectat manual; nu se reia implicit o cerere cu rezultat necunoscut.
Fișierele de configurare și rapoartele locale sunt considerate de încredere.

Rezumatul conține NEW_FAILURES, CONFIRMED_FAILURES, CONFIRMED_STRENGTHS,
UNSTABLE, NEEDS_MORE_EVIDENCE, STABLE_GOOD și PROBE_QUALITY_ISSUES.

Ipoteze: implementarea inițială tratează categoriile native drept abilități;
un pool viitor poate folosi categorii mai fine. Identitatea textului este SHA-256
al textului exact, fără embeddings sau deduplicare semantică. Confirmările
sunt strict limitate la probele folosite și la pragurile declarate. Nicio probă
sau ieșire nu este exportată automat în Gold ori în antrenare.
