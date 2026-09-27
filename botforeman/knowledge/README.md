# Verified Knowledge Store

Extensie independentă: importă rapoarte SCOUT/AUDIT existente, fără să schimbe
Copycat, evaluatorii sau ciclurile. Folosește doar biblioteca standard Python.
Nu generează corecții, nu validează semantic, nu apelează modele/API și nu antrenează.

## Persistență și schema

`KnowledgeStore(path)` păstrează un JSON cu `schema_version`, `items`, `packets`,
`retests`, `history`. Cozile sunt colecțiile `packets` și `retests`, filtrate după
`destination`; nu sunt dataseturi aplicate. O tranzacție scrie întregul registru
atomic, cu flush/fsync și replace, sub un lock exclusiv. Un lock rămas după crash
necesită inspecție manuală. Nu există retry sau reluare automată.

Intrarea conține `knowledge_id`, `type`, `source`, `source_run_id`,
`related_probe_id`, `skill`, `category`, `original_input`, `model_output`,
`verified_content`, `verification_reason`, `verified_by`, `created_at`,
`updated_at`, `status`, `destination`, `version`, `approved_source`, `provenance`.

Statusuri: PROPOSED → VERIFIED → IMPLEMENTED → RETESTED. REJECTED și RETIRED sunt
terminale. `revise` crește versiunea unei intrări neterminale și revine la PROPOSED;
șterge validarea curentă, păstrând snapshoturile istorice și pachetele versiunilor
anterioare. Cererile vechi de retest încă în așteptare sunt retrase.

## Extracție și verificare explicită

`extract` citește raportul și păstrează calea absolută, hash-ul raportului,
manifestul și înregistrarea originală integrală (output, evaluator/trace, verdict).
Același raport și aceeași probă produc același ID, fără duplicate.

- BAD + MODEL_FAILURE într-o categorie CONFIRMED_FAILURE → PROPOSED/CORRECTION.
- UNCERTAIN → PROPOSED/ANALYSIS.
- PROBE_QUALITY_ISSUE → PROPOSED/PROBE_REVIEW.
- GOOD într-o categorie CONFIRMED_STRENGTH → PROPOSED/EVIDENCE.
- Alte cazuri nu sunt extrase ca lecții.

Niciun caz extras nu devine automat VERIFIED. `verify` cere textul exact aprobat,
verificatorul, motivul și o clasă de sursă aprobată. Clasele permise:
EXPLICIT_CORRECTION, APPROVED_GOLD, VALIDATED_BENCHMARK_RULE, CONFIRMED_AUDIT,
STABLE_ARCHITECTURE, APPROVED_DOCUMENTATION, MANUAL.
Clasa sursei nu înlocuiește operația explicită de verificare.

Sursele/fișierele locale și identitatea declarată a verificatorului sunt de
încredere: acest modul nu autentifică persoane și nu oferă semnături digitale.
Hash-ul documentează conținutul importat; nu dovedește adevărul informației.
Pentru corectarea unei probe se folosește BENCHMARK_FIX_QUEUE, nu Gold de model.
ANALYSIS/EVIDENCE/PROBE_REVIEW nu pot intra în GOLD_QUEUE sau DATASET_QUEUE,
nici după verificare. O corecție umană separată poate fi propusă explicit,
cu legătură în `provenance` spre cazul analizat.

## Learning packet și implementare

Destinații: GOLD_QUEUE, DATASET_QUEUE, RETEST_QUEUE, BENCHMARK_FIX_QUEUE,
DOCUMENTATION, KNOWLEDGE_ONLY. Toate sunt intermediare; DOCUMENTATION nu editează
documente existente. Nu există comandă de aplicare pe datasetul principal.

`implement` acceptă numai VERIFIED. Copiază `verified_content` în
`verified_correction`, fără un parametru care să permită înlocuirea sa. Pachetul
conține câmpurile cerute: packet_id, knowledge_id, source_run, skill, category,
probe_id, input, model_output, verdict, failure_reason, verified_correction,
destination, packet_status, created_at, implemented_at, retested_at; plus versiune,
hash de conținut și snapshot complet al provenienței/validării.

Implicit `dry_run=True`: returnează destinația, ID-ul, sursa și pachetul propus,
fără să scrie, să creeze lock sau să schimbe starea. `--apply` scrie numai coada.
Cheia pachetului include knowledge_id, version, destination și hash-ul conținutului.
Repetarea aceleiași implementări este NO_OP, inclusiv după RETESTED. Nu se schimbă
destinația unei versiuni deja implementate; se creează o versiune nouă și se verifică.
Retragerea unei intrări marchează și pachetele/cererile ei inactive.

## Retest

`retest` are tot dry run implicit. Selectează determinist prima probă nouă din
categoria respectivă (ordine după ID), excluzând ID-ul și textul original.
Dacă nu există, salvează o cerere cu `needs_new_probe=true`; un apel ulterior cu
pool complet poate furniza proba. Nu inventează întrebări și nu rulează modelul.
`record-retest` importă explicit rezultatul unei rulări externe, verifică versiunea
și ID-ul solicitat, apoi salvează RETEST_GOOD/BAD/UNCERTAIN și starea RETESTED.
RETESTED înseamnă retest efectuat, inclusiv BAD, nu succes sau generalizare.
Nu se poate înregistra de două ori rezultatul aceleiași cereri.

## Comenzi (din rădăcina proiectului)

```powershell
python -m botforeman.knowledge --store experiments/knowledge_real/store.json extract experiments/adaptive_copycat/audit_01/report.json
python -m botforeman.knowledge --store experiments/knowledge_real/store.json list proposed
python -m botforeman.knowledge --store experiments/knowledge_real/store.json show KNOWLEDGE_ID
python -m botforeman.knowledge --store experiments/knowledge_real/store.json history KNOWLEDGE_ID
```

Pentru un ID ales și conținut validat de tine, într-un fișier UTF-8:

```powershell
python -m botforeman.knowledge verify KNOWLEDGE_ID --content-file approved.txt --by human --reason "Revizuit explicit"
python -m botforeman.knowledge implement KNOWLEDGE_ID --destination GOLD_QUEUE --dry-run
python -m botforeman.knowledge implement KNOWLEDGE_ID --destination GOLD_QUEUE --apply
python -m botforeman.knowledge retest KNOWLEDGE_ID --pool new_probes.json --apply
python -m botforeman.knowledge record-retest REQUEST_ID result.json
```

Specifică același `--store` înaintea comenzii dacă nu folosești registrul implicit
`experiments/knowledge/store.json`. Poolul este o listă JSON cu `probe_id`, `prompt`,
`category`; rezultatul este un obiect cu `result`, `source_run`, `probe_id`,
`model_output`, `evaluator`. `propose proposal.json` acceptă argumentele metodei
`propose`, nu status/verified_content. `close ID REJECTED --reason ...`,
`close ID RETIRED --reason ...`, `revise ID --reason ...` completează ciclul.

```powershell
python -m botforeman.knowledge.demo --output experiments/knowledge_synthetic_demo
python -m unittest discover -s tests -v
```

Demo-ul refuză suprascrierea directorului. Este integral sintetic: verificatorul,
conținutul și rezultatul de retest sunt fixture-uri. Nu validează date reale.
Auditul Copycat existent conține CONFIRMED_STRENGTH, nu CONFIRMED_FAILURE:
extracția reală produce două PROPOSED/EVIDENCE, fără corecții sau implementare.
Costul acestei extensii și al validării locale: zero apeluri API și zero tokenuri
de inferență noi. Nu există presupunerea că un abonament ChatGPT acoperă API-ul.
