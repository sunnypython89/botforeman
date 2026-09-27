# nativ_roman.bot — semnale contextuale, fără certificare

Evaluatorul existent a fost extins, nu înlocuit. Fluxul anterior de triere locală
și revizuire umană continuă să funcționeze. Noul flux produce numai
GOOD/BAD/UNCERTAIN și este folosit de CLI la cele cinci probe NATIV.
Celelalte 20 de probe și regulile lor sunt neschimbate.

## Probe și criterii

Poolul din `bots/native_pool.py` are 25 de probe, cinci per categorie:

| Categorie | Proprietăți urmărite |
|---|---|
| IDIOM | sens contextual, naturalețe idiomatică |
| PRAGMATICS | ironie, reproș, cerere indirectă, interpretare prudentă |
| REGISTER | registru familiar/formal/colocvial-vulgar, fidelitate față de cerință |
| COLLOCATION_NATURALNESS | expresii firești, absența calcurilor evidente |
| IMPLICIT_MEANING | sens subînțeles, lipsa angajamentului, ambiguitate contextuală |

Fiecare probă declară contextul, promptul, variantele, criteriul și proprietățile
testate. Rubrica internă asociază fiecărei variante un calificativ și o explicație.
Aceste calificative și explicații nu sunt trimise modelului. Raportul păstrează
`probe_id`, `category`, `context`, `prompt`, `answer_options`, `evaluator_criterion`,
`tested_properties`, `result`, `explanation`, `model_output`, `cycle_id`, `level`,
`evaluator_name`, `evaluator_version`, `usage` și `timestamp`.

Exemple de criterii:

- «Mă duce cu zăhărelul» în contextul unor promisiuni neonorate: sensul idiomatic
  este GOOD; sensul literal despre zahăr este BAD.
- «Ce punctual ești!» după o întârziere și cu iritare explicită: reproșul ironic
  este GOOD; lauda sinceră contrazice contextul și este BAD.
- Într-un mesaj familiar, formula birocratică încalcă registrul cerut.
- «Am 28 de ani» este GOOD; «Sunt 28 de ani vechi» este BAD, ca traducere literală.
- «Planul face sens», variantele cu «oleacă» și lecturile plauzibile ale unui mesaj
  fără ton primesc UNCERTAIN când contextul nu justifică respingerea lor sigură.

Sunt acceptate litera, litera cu punctuație, litera urmată de textul complet al
variantei și textul complet fără literă. Spațiile și punctuația finală sunt
normalizate numai pentru comparație. Răspunsul original nu este modificat.
Textul liber neacoperit, textul trunchiat și etichetele contradictorii rămân
UNCERTAIN, chiar dacă un om ar putea evalua răspunsul. Nu se pretinde evaluare
semantică generală printr-un parser de opțiuni.

## Selecție și repetare

Ordinea categoriilor este fixă. Pentru ciclul cu indicele `i`, fiecare categorie
alege proba `i % 5`. Ordinea variantelor este rotită determinist, separat de
calificative. Primele cinci cicluri au 25 de probe NATIV diferite. După epuizarea
poolului se reia rotația; un pool finit nu poate produce noutate nelimitată.

`native_selection.json`, lângă directoarele ciclurilor, păstrează indicele între
procese. Rezervarea este atomică, cu lock exclusiv; un lock rămas după un crash
sau un fișier corupt oprește rularea, fără resetare implicită. Și un ciclu oprit
consumă o poziție de selecție. Ciclul următor începe tot de la STRAIN.

Folosește același director părinte pentru aceeași serie. Mutarea într-un director
părinte nou începe o serie independentă; nu șterge cursorul pentru a pretinde
probe noi. Agregatorul verifică și ID-urile probelor pentru a detecta repetările.

## Stabilitate explicită și configurabilă

`native_signal_stability` este o agregare separată. Nu schimbă cele trei
calificative și nu introduce procente sau un scor de competență lingvistică.

Regulile implicite (`StabilityRules`) sunt:

```json
{
  "window_cycles": 5,
  "min_cycles_detected": 2,
  "min_cycles_consistent": 5,
  "min_good_per_cycle": 4,
  "max_bad_per_cycle": 1
}
```

Se folosesc ultimele cinci cicluri complete și comparabile, ordonate după
timestamp. Ciclurile parțiale și rapoartele vechi fără evaluatorul contextual
sunt excluse explicit. Modelele, providerii, versiunea evaluatorului și hash-ul
poolului trebuie să coincidă; amestecarea lor este refuzată. Un ID de ciclu
duplicat este refuzat. Repetarea unei probe în fereastră face semnalul neconcludent.

Un ciclu susține semnalul dacă are minimum 4 GOOD și maximum 1 BAD.

- `native_signal_consistent`: minimum 5 cicluri și toate susțin semnalul.
- `native_signal_detected`: minimum 2 cicluri susțin semnalul, dar regula de
  consistență nu este îndeplinită.
- `native_signal_inconclusive`: altfel, inclusiv un singur ciclu cu 5 GOOD.

Pragurile se pot modifica într-un JSON transmis cu `--rules`. Nici configurația
nu poate reduce pragul la un singur ciclu. Dacă mărești fereastra peste cinci,
extinde și poolul pentru a putea satisface condiția de probe distincte.
Se raportează separat distribuțiile GOOD/BAD/UNCERTAIN per ciclu și categorie.
Prin urmare, o slăbiciune persistentă într-o categorie rămâne vizibilă chiar dacă
regula configurată permite un BAD per ciclu. Eticheta tehnică nu este o certificare.

## Rulare

CLI-ul existent atașează acum automat ambele evaluatoare și rutează numai NATIV:

```powershell
python -m botforeman.levels
python -m botforeman.levels --provider copycat --adapter copycat_07_epoch1_adapter --max-tokens 10000 --max-api-calls 0 --max-cost 0
```

Prima comandă este un fixture sintetic, nu o măsurare Copycat. A doua folosește
modelul local și adaptorul existent exclusiv pentru inferență.

Integrare Python explicită:

```python
from botforeman import BotForeman
from botforeman.bots.romanian_levels_bot import RomanianLevelsBot
from botforeman.bots.nativ_roman_bot import NativRomanBot
from botforeman.levels.providers import FixtureProvider

foreman = BotForeman()
foreman.attach(RomanianLevelsBot())
foreman.attach(NativRomanBot())
report = foreman.run_level_cycle(
    "romanian_levels.bot", FixtureProvider(), "experiments/seria_mea/cycle_01",
    native_evaluator="nativ_roman.bot",
)
```

Parametrul explicit păstrează compatibilitatea apelurilor Python anterioare.
Fără el, un apel vechi rămâne pe evaluatorul său inițial.

Demo complet cu cinci cicluri **sintetice** și rezultate controlate:

```powershell
python -m botforeman.levels.native_demo
```

Demo-ul produce 5/5, 4/5, 5/5, 5/5, 4/5 la NATIV și
`native_signal_consistent`, pe 25 de probe native distincte. Providerul este
etichetat explicit SYNTHETIC; nu reprezintă rezultate reale ale modelului.

Agregarea unor rapoarte reale existente, fără alte apeluri de model:

```powershell
python -m botforeman.levels.native_signals experiments/seria_mea/cycle_01/report.json experiments/seria_mea/cycle_02/report.json experiments/seria_mea/cycle_03/report.json experiments/seria_mea/cycle_04/report.json experiments/seria_mea/cycle_05/report.json --output experiments/seria_mea/stability.json
```

Adaugă `--rules reguli.json` pentru alte praguri. Ieșirea nu suprascrie un fișier
existent. Pentru un singur raport rezultatul este obligatoriu neconcludent.

Toate testele:

```powershell
python -m unittest discover -s tests -v
```

## Cost, proveniență și limite

Limitele existente de tokenuri, apeluri și cost rămân active pe întregul ciclu
de 25 de probe, inclusiv NATIV. Nu există API plătit activ, retry sau antrenare.
Testele și demo-ul au cost API 0 USD. Răspunsurile modelului nu sunt rescrise.
Providerii locali salvează identitatea adaptorului prin SHA-256 și limita de
generare în contextul comparației. Un provider nou trebuie să furnizeze o
identitate stabilă care separă checkpointurile și setările de generare.

Rubricile sunt propuneri explicite și revizuibile, nu Gold validat de utilizator.
Exemplele testează recunoașterea contextuală, nu producția liberă, toate dialectele
sau toate registrele posibile. Numărul mic de probe și distractorii uneori evidenți
limitează concluziile. Poolul nu garantează independență semantică absolută între
exemple și nu poate elimina memorarea; rotația evită repetarea imediată a celor
cinci enunțuri. Nicio ieșire nu conferă automat o certificare.
