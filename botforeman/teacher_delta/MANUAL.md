# TEACHER_PACKET_MANUAL

Modulul `manual.py` exportă maximum cinci răspunsuri Copycat deja salvate, preferând
o probă din fiecare categorie. A doua trecere completează dacă lipsesc categorii.
Nu apelează API, nu rulează inferență și nu modifică dataseturi/adaptoare.

Batch real pregătit: `experiments/teacher_delta_manual_01/teacher_packets.txt`.
Copiază acest fișier în Chat. JSON-ul alăturat păstrează proveniența completă.

Selecția exclude ID/text duplicat, WEAK/RETIRED (exceptând `--explicit ID`),
prompt/output gol și `context_sufficient=false`. Prompturile sursă sunt considerate
autonome; nu există detecție semantică automată a contextului insuficient.
Rapoartele mai recente sunt preferate conform ordinii fișierelor furnizate.

Deduplicarea include probe_id, model, adapter, output, profesor și versiune.
Atât exporturile în așteptare, cât și răspunsurile valide blochează retrimiterea.
Export înseamnă pregătit, nu trimis automat. `--override` creează pachete noi.

## Răspuns JSON UTF-8

Se acceptă un obiect sau o listă. Exemplu de formă, nu răspuns real:

```json
{
  "PACKET_ID": "ID_DIN_PACHET",
  "ESSENTIAL_MEANING": ["Numai informația relevantă lipsă"],
  "NATIVE_SIGNAL": [],
  "CRITICAL_ERROR_IF_ANY": [],
  "DELTA_EMPTY": false,
  "LEARNING_VALUE": "MEDIUM",
  "teacher_tokens": 42
}
```

Fără diferențe: `{"PACKET_ID":"ID_DIN_PACHET","DELTA_EMPTY":true}` este suficient.
Celelalte liste pot lipsi. Maximum trei puncte în total. Textul liber nu este
importat; JSON evită interpretarea ambiguă. RUN_ID/PROBE_ID opționale sunt verificate
dacă apar. Profesorul și versiunea declarate trebuie să coincidă cu exportul.
Chat-manual/manual-v1 este eticheta workflow-ului, nu un model Chat autentificat.

TASK cere numai diferențe: ESSENTIAL_MEANING și NATIVE_SIGNAL sunt structurate în
MISSING_IN_COPYCAT; CRITICAL_ERROR_IF_ANY în WRONG_IN_COPYCAT. Nu se inventează
KNOWN_BY_BOTH, EXTRA_IN_COPYCAT sau UNCERTAIN_DELTA; rămân liste goale.
Aceasta este structurarea afirmațiilor profesorului, nu validare semantică.
LEARNING_VALUE este declarat de profesor; dacă lipsește, LOW conservator.
Diferențele exclusiv stilistice trebuie etichetate LOW de profesor.

DELTA_EMPTY produce NO_MEANINGFUL_DELTA, fără propunere. Altfel se creează numai
PROPOSED, verified_content null, cu pachet/răspuns/identitate/timestamp/proveniență.
GOOD + MEDIUM/HIGH declarat marchează LOCAL_EVALUATOR_MISSED_SIGNAL pentru revizuire,
nu drept eroare demonstrată a evaluatorului. Evaluatorii nu sunt modificați.

Importul validează întregul fișier înainte de propuneri. Reimportul identic este
no-op; răspunsul conflictual cere pachet nou prin override. Knowledge IDs sunt
deterministe. Registrul este salvat atomic sub lock. Fișierele locale și identitatea
declarată sunt considerate de încredere, fără autentificare externă.

## Comenzi

```powershell
python -m botforeman.teacher_delta.manual --help
python -m botforeman.teacher_delta.manual --registry experiments/teacher_manual/registry.json export experiments/adaptive_copycat/scout_01/report.json experiments/adaptive_copycat/audit_01/report.json experiments/adaptive_copycat/scout_02/report.json experiments/adaptive_copycat/scout_03/report.json --teacher Chat-manual --version manual-v1 --output experiments/teacher_delta_manual_next
python -m botforeman.teacher_delta.manual --registry experiments/teacher_manual/registry.json import teacher_responses.json --teacher Chat-manual --version manual-v1 --store experiments/teacher_manual/knowledge.json --output experiments/teacher_delta_manual_01/import_report.json
python -m unittest discover -s tests -v
```

Salvează răspunsurile externe în teacher_responses.json înainte de import.
Folosește directoare/rapoarte de output inexistente. Tokenurile declarate lipsă
rămân null. Cost API BotForeman: zero; nu estimăm costul abonamentului extern Chat.
La import parțial, statisticile răspunsurilor se referă la fișierul curent;
registrul păstrează cumulativ toate răspunsurile. Niciun mesaj nu este trimis automat.
