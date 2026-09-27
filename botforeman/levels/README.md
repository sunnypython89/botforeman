# Ciclul rapid 5 × 5

Extensia contextuală `nativ_roman.bot` este acum activă în CLI numai la NATIV.
Celelalte patru niveluri sunt neschimbate. Vezi [NATIVE_SIGNALS.md](NATIVE_SIGNALS.md)
pentru cele cinci categorii, poolul rotativ și agregarea stabilității între cicluri.

`BotForeman.run_level_cycle()` orchestrează exact:
STRAIN → INCEPATOR → INTERMEDIAR → AVANSAT → NATIV, câte cinci probe distincte.
Un ciclu complet are 25 de probe; după NATIV se termină. Nu există salturi,
amestecare, retry sau reluare automată. O invocare nouă are alt `cycle_id` și
începe din nou de la STRAIN. Un director existent nu este suprascris.

## Arhitectură

- `protocol.py`: nivelurile, numărul de exemple, calificativele, probele,
  răspunsurile și consumul. Constantele sunt centralizate pentru extensii viitoare;
  versiunea curentă impune exact 5 × 5, fără opțiuni CLI care să schimbe ordinea.
- `runner.py`: verifică lotul înainte de consum, execută secvențial, verifică
  limitele, salvează răspunsurile nemodificate și produce rezumatele.
- `providers.py`: sursă sintetică rapidă și inferență Copycat offline.
- `bots/romanian_levels_bot.py`: toate probele, cheile și regulile lingvistice.
  Este un evaluator atașat normal, derivat din `ForemanBot`; adaugă metodele
  `level_tests()` și `evaluate_rating(prompt, output)` pentru noul ciclu.

Cu extensia activă, probele NATIV din acest evaluator de bază sunt înlocuite de
`bots/nativ_roman_bot.py` și poolul său, `bots/native_pool.py`. Evaluatorul de bază
rămâne disponibil pentru compatibilitatea apelurilor vechi.

Interfața v0.1 și testele existente sunt păstrate. Ciclul rapid nu folosește
scoruri, procente sau calificative suplimentare. Pentru compatibilitate, numai
apelurile vechi `evaluate()` păstrează formatul PASS/FAIL/UNCERTAIN, cu scor null.
Rândurile ciclului rapid folosesc exclusiv GOOD/BAD/UNCERTAIN.

## Ipoteze lingvistice

Acesta este un curriculum propus, necalibrat, de recunoaștere cu două variante.
Nivelurile denumesc dificultatea intenționată a probelor, nu certifică nivelul
general al unui vorbitor/model. NATIV nu este o certificare a exprimării libere.

- STRAIN: formule uzuale elementare.
- INCEPATOR: acorduri gramaticale simple.
- INTERMEDIAR: alegerea registrului pentru un context explicit.
- AVANSAT: păstrarea sensului condițiilor, negațiilor și cuantificatorilor.
- NATIV: interpretarea prudentă a unor expresii și nuanțe pragmatice.

Cele cinci exemple ale unui nivel au aceeași formă și o dificultate intenționat
apropiată; această comparabilitate nu este validată psihometric. Cheile se află
numai în evaluator și pot fi revizuite. Nu sunt citite benchmarkuri sau Gold.

GOOD: alegerea corespunde cheii probei. BAD: este aleasă explicit cealaltă
variantă. UNCERTAIN: alegerea nu poate fi stabilită sigur. Sunt acceptate `A`,
`B`, `A.`, `B!` și litera urmată de textul integral al variantei, de exemplu
`A: Bună dimineața!`. Spațiile și punctuația finală a variantei sunt tolerate.
O etichetă contradictorie, un text trunchiat sau explicații neprevăzute rămân
UNCERTAIN. Parserul nu completează și nu corectează textul modelului.

## Comenzi

Din rădăcina proiectului, demo sintetic foarte rapid, fără model sau API:

```powershell
python -m botforeman.levels
```

Providerul sintetic returnează deliberat `A` la fiecare probă; măsoară funcționarea
ciclului, nu Copycat. Tokenurile sale sunt unități sintetice pentru testarea limitelor.

Inferență reală, locală, cu adaptorul existent (fără antrenare):

```powershell
python -m botforeman.levels --provider copycat --adapter copycat_07_epoch1_adapter --max-tokens 10000 --max-api-calls 0 --max-cost 0
```

Fără `--output` se creează un director nou în `experiments/`. Poți specifica unul
cu `--output experiments/numele_unui_ciclu_nou`. Providerul Copycat folosește
modelul din cache, `trainable=False`, generare deterministă și maximum 64 de
tokenuri noi per răspuns. Nu există descărcare/fallback API sau apel de training.

Toate testele, inclusiv cele anterioare:

```powershell
python -m unittest discover -s tests -v
```

## Consum și oprire

Limite CLI configurabile per ciclu:

```powershell
python -m botforeman.levels --max-cost 0 --max-tokens 7 --max-api-calls 0
```

Acest demo se oprește după șapte probe și salvează rezultatele parțiale.
În Python se pot dezactiva individual limitele cu `None`, dar trebuie păstrată
cel puțin una:

```python
from botforeman import BotForeman
from botforeman.bots.romanian_levels_bot import RomanianLevelsBot
from botforeman.levels import Limits
from botforeman.levels.providers import FixtureProvider

foreman = BotForeman()
bot = RomanianLevelsBot()
foreman.attach(bot)
result = foreman.run_level_cycle(
    bot.name, FixtureProvider(), "experiments/un_ciclu_nou",
    limits=Limits(max_cost_per_cycle=None,
                  max_tokens_per_cycle=20,
                  max_api_calls_per_cycle=0),
)
```

`provider.estimate(input)` trebuie să returneze limita superioară de consum a
următoarei probe, nu o medie. Ciclul nu pornește proba dacă rezervarea ar depăși
plafonul. După apel înregistrează consumul observat. Dacă providerul raportează
o depășire, păstrează proba și oprește înainte de orice apel următor. Nu poate
anula retrospectiv costul unui provider care nu respectă limita declarată.

`Usage` conține input_tokens, output_tokens, total_tokens, api_calls, cost_usd și
credits. Valoarea necunoscută este `null`, niciodată zero inventat. Costul este USD,
calculat cu Decimal. Creditele sunt unitățile providerului și nu sunt convertite
implicit în USD. Evaluatorul atașat este local, fără consum API propriu.

Dacă prețul lipsește, limita de tokenuri/apeluri rămâne activă. O limită configurată
de tokenuri/apeluri cere o estimare cunoscută pentru acea măsură; dacă providerul
nu o poate furniza, dezactivează explicit limita respectivă numai dacă există
o altă limită verificabilă. Dacă nu există nicio măsură verificabilă, ciclul se
oprește fără apel. Dacă lipsește consumul final, `usage` îl păstrează necunoscut,
iar `accounted_usage` reține rezervarea conservatoare pentru controlul plafonului.

La eroare de provider nu se reîncearcă; rezervarea rămâne contabilizată. La eroare
de evaluator se salvează UNCERTAIN și tipul erorii, apoi ciclul se oprește.

Providerii plătiți sunt blocați în această versiune. Schimbarea plafonului nu
autorizează API-uri plătite. O extensie viitoare trebuie să integreze și poarta
existentă cu tarife verificate și aprobarea explicită a bugetului. Implicit:
0 USD, 0 apeluri API și cel mult 100.000 tokenuri locale per ciclu.

## Artefacte

Fiecare director de rulare conține:

- `probes.jsonl`: rezultatele fiecărei probe, cu identificatori, prompt,
  răspuns original, calificativ, evaluator, versiune, timestamp UTC și consum.
- `events.jsonl`: rezervări înainte de apel, răspunsuri și erori; util și dacă
  procesul se întrerupe între răspuns și evaluare.
- `report.json`: rezultatul complet serializabil, actualizat atomic după fiecare
  probă, cu rezumate pe nivel, matrice G/B/U, totaluri și motivul opririi.

Rezultatele parțiale au `status=incomplete`, numărul real de probe și motivul
opririi. Nu se completează rândurile lipsă cu rezultate inventate. Un proces
întrerupt în timpul unui apel păstrează rezervarea și `request_in_progress`;
nu se reia automat. O rulare nouă începe de la STRAIN cu un ID nou.

Prima verificare locală `romanian_levels_copycat_01` a folosit parserul inițial
foarte strict și limita de 16 tokenuri de ieșire; cele 25 de rezultate UNCERTAIN
sunt păstrate ca artefact istoric. `romanian_levels_copycat_02` folosește regulile
explicite de mai sus și limita de 64 tokenuri. Niciuna nu este o măsurare de progres
prin antrenare: nu a fost antrenat sau modificat modelul între rulări.
