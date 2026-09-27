# TEACHER_DELTA

Pentru export/import manual cu profesor uman/Chat, vezi [MANUAL.md](MANUAL.md).

Mod separat care consumă raportul real SCOUT/AUDIT existent. Nu regenerează Copycat
și nu schimbă evaluatorii, adaptorul sau dataseturile. Dependențe: Python standard.

Flux: output Copycat + verdict local → selecție → profesor compact → extractor
specializat → delta → PROPOSED. Verificarea explicită rămâne în KnowledgeStore.

AUTO selectează BAD, UNCERTAIN, UNSTABLE sau MODEL_FAILURE suspectat. MANUAL permite
și ID-uri GOOD selectate explicit. Restul sunt SKIP_TEACHER înainte de cache/apel.
Criteriul trebuie furnizat în înregistrare sau prin `--criteria`; lipsa lui produce
NEEDS_CRITERION, fără consum. Istoricul conversației nu intră în cererea profesorului.

## Contracte

Profesorul injectat are `name`, `model`, `version`, `paid=False`, `estimate(request)`
și `generate(request) -> TeacherReply(content, Usage)`. Cererea include promptul,
outputul Copycat, criteriul, verdictul/motivul local și `max_output_tokens`.
Providerul trebuie să aplice acest plafon la generare și să estimeze conservator
consumul. Depășirea detectată oprește rularea; un orchestrator nu poate recupera
tokenuri deja consumate de un provider care încalcă contractul.

Teacher output este un obiect cu listele ESSENTIAL_MEANING, NATIVE_SIGNAL,
CRITICAL_ERROR_IF_ANY: maximum trei puncte în total, fiecare maximum 300 caractere.

Extractorul este un specialist local pur, cu `name`, `version`, `paid=False` și
`extract(request, teacher_output)`. Primește exact prompt/output/criteriu/profesor,
fără încă un apel de profesor. BotForeman nu aplică euristici lexicale drept
comparație semantică. `UncertainExtractor` este fallback-ul conservator.

Schema delta: listele KNOWN_BY_BOTH, MISSING_IN_COPYCAT, WRONG_IN_COPYCAT,
EXTRA_IN_COPYCAT, UNCERTAIN_DELTA; plus `learning_value` LOW/MEDIUM/HIGH și `reason`.
Textele sunt scurte și nu pot fi duplicate între câmpuri. HIGH cere o lipsă/eroare
explicită, fără incertitudine, și un motiv reutilizabil declarat de specialist:
IDIOM, REGISTER, PRAGMATICS, TRANSLATION_ARTIFACT, FALSE_INFORMATION,
INSTRUCTION_VIOLATION. STYLE_ONLY trebuie LOW. Acestea sunt validări structurale,
nu confirmări ale adevărului afirmației profesorului.

Fără lipsă/eroare/extra și fără incertitudine: DELTA_EMPTY, fără knowledge item.
Cu numai incertitudine: UNCERTAIN_DELTA, păstrat în raport, fără lecție.
Delta relevantă creează doar PROPOSED, cu verified_content null. PROBE_QUALITY_ISSUE
produce PROBE_REVIEW, care nu poate deveni lecție de model în Gold/Dataset queue.
Proveniența include raportul sursă prin hash/manifest, înregistrarea originală,
profesorul, extractorul, criteriul, delta, valoarea, consumul și timestampul.

## Cache și cost

Cheia include requestul integral minimal, contextul model/adaptor/evaluator/pool,
profesorul și versiunile profesorului/extractorului/protocolului. Cache-ul reține
teacher output și delta; origin_usage rămâne vizibil, consumul nou al hitului e zero.
Importurile externe includ hash-ul întregului bundle în versiune. Același caz
produce același knowledge_id; nu se verifică și nu se implementează automat.

Implicit: max_teacher_tokens=128, max_teacher_calls_per_run=2,
max_teacher_cost=0. Se rezervă consumul estimat înainte de apel, apoi se verifică
consumul raportat. Erorile nu se reîncearcă. Raportul parțial rămâne salvat.
Limita apelurilor se aplică și providerilor locali; cache hit nu consumă apel.

**Transportul API plătit nu este implementat și este blocat**, inclusiv la un plafon
pozitiv. Nu există rate reale verificate sau aprobare de buget. Pentru un viitor
provider API sunt necesare tarife verificate și aprobarea explicită prin ledgerul
existent înaintea oricărui apel; modificarea plafonului singură nu este aprobare.

CLI suportă importul unei comparații externe prin `--bundle`, fără apel de model.
Bundle: teacher_identity, teacher_model, teacher_version, cases. Fiecare caz conține
probe_id, prompt, copycat_output, criterion, teacher_output și delta. Cele patru
câmpuri de identificare trebuie să coincidă exact cu cererea. Delta este furnizată
de autorul comparației, nu extrasă semantic de importer. Pentru comparații automate
reale se injectează un profesor local și un extractor specializat prin API Python.
Nu există un profesor extern real configurat în această etapă.

Tokenurile importului sunt zero tokenuri **noi**, nu costul istoric al autorului
extern. Raportul separă tokenurile Copycat din raportul existent de tokenurile noi
(zero), teacher usage, accounted usage, calls, cache hits, skipped calls,
useful_deltas (candidate fără incertitudine, nu validate) și DELTA_EMPTY.

## Comenzi

```powershell
python -m botforeman.teacher_delta.demo --output experiments/teacher_delta_synthetic
python -m botforeman.teacher_delta experiments/adaptive_copycat/scout_02/report.json --output experiments/teacher_delta_real_01
python -m unittest discover -s tests -v
```

Prima comandă este integral sintetică și demonstrează PROPOSED plus cache hit.
A doua reutilizează cele trei răspunsuri reale Copycat: trei GOOD → trei skip-uri,
fără profesor și fără inferență nouă. Nu reprezintă o comparație reală cu un profesor.
Folosește directoare de output noi la rerulare.

Comparație manuală cu material extern:

```powershell
python -m botforeman.teacher_delta report.json --output experiments/comparison_new --mode TEACHER_DELTA_MANUAL --select PROBE_ID --bundle comparison.json --criteria criteria.json --max-teacher-tokens 128 --max-teacher-calls-per-run 1 --max-teacher-cost 0
```

`criteria.json` este un obiect probe_id → criteriu. Rapoartele și cache-ul local sunt
considerate fișiere de încredere. Nu există autentificare a profesorului/importatorului.
