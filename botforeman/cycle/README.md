# Primul ciclu asistat — nativ_roman.bot

## Ce s-a executat efectiv

- Modelul de bază din cache local, cu adaptorul existent `copycat_07_epoch1_adapter`,
  a produs 10 răspunsuri noi. Inferența este offline, fără BotForeman atașat.
- BotForeman a analizat ulterior textul răspunsurilor. Toate verdictele sunt
  UNCERTAIN, nu etichete Gold și nu scoruri de competență nativă.
- Șase probe sunt pentru lecție; patru sunt rezervate evaluării. Nu există încă Gold validat.
- Zero apeluri API, zero tokenuri API, zero USD API. Zero antrenări.
- Prima încercare a salvat un singur răspuns și s-a oprit la afișarea diacriticelor
  în terminalul Windows. `baseline_new.jsonl` este incomplet și nu este folosit.
  `baseline_new_v2.jsonl` este rularea completă, cu metadate și SHA-256.

Fișierele produse sunt în `experiments/botforeman_nr01/`. Deschide `review.md`
pentru răspunsul Copycat, fragmentele KEEP/OMIT/UNCERTAIN, motive și candidați.
`evaluations.jsonl` include toate cele cinci criterii și pozițiile exacte ale
fragmentelor; `review_queue.jsonl` include numai cele șase probe pentru lecție.

## Interfața evaluatorului

`NativRomanBot(probes)` implementează `ForemanBot`: `generate_tests`, `evaluate`
și `omission_plan` moștenit. `analyze` adaugă detalii pentru sens, naturalețe,
registru, intervenții necerute și incertitudine. Orchestratorul v0.1 nu a fost
modificat. Evaluatorul nu apelează modelul, API-uri sau procese externe.

Regulile locale sunt indicii limitate: ancore lexicale, formule de adresare,
prefixe explicative și câteva marcaje de condiție/incertitudine/diacritice.
Prezența unei ancore nu certifică sensul; absența poate fi o flexiune corectă.
Chiar și OMIT rămâne o propunere de revizuit. KEEP și UNCERTAIN pot acoperi
același fragment fiindcă dovada lexicală nu rezolvă criteriile semantice.
Acesta nu este un judecător sigur al românei native.

## Alegerea checkpointului și experimentul

Sursa: `RAPORT_COPYCAT_10_CONSOLIDARE.md`, păstrată prin hash în
`historical_baseline.json`. Copycat 07 are L06=14/24, L07=17/24, L08=17/32,
L09=22/32, cu minim normalizat 53,1%, față de 50% pentru Copycat 10.
Am ales 07 pentru baza mai echilibrată, nu pentru o superioritate nativă dovedită.
Unele scorere istorice conțin liste fixe de ID-uri: NU se rulează pe răspunsuri noi.

Configurație propusă: o epocă, learning rate 5e-6, seed 42, batch 1, acumulare 4,
lungime maximă 384, r=8, alpha=16, dropout=0,05, q_proj/v_proj; cuantizare NF4
ca în proiectul existent. Cu șase exemple confirmate: două actualizări de optimizator.
Sunt permise doar exemplele revizuite; nu se completează automat cu Gold vechi,
benchmarkuri, rezultate de benchmark sau răspunsuri ale evaluatorului.
Acesta este un pilot foarte mic; generalizarea și uitarea trebuie măsurate.

Ieșirea este exclusiv `adapter_candidate/` în directorul ciclului, cu refuz de
suprascriere și fără promovare automată. Revenirea înseamnă folosirea în continuare
a adaptorului 07 original. Nu se face merge în modelul de bază.

## Comenzi exacte (PowerShell, din rădăcina proiectului)

Verificări fără API, inferență sau antrenare:

```powershell
python -m unittest discover -s tests -p "test_botforeman*.py" -v
python -m botforeman.cycle.experiment experiments/botforeman_nr01
```

Reproducerea pregătirii și a inferenței într-un director NOU:

```powershell
python -m botforeman.cycle prepare experiments/botforeman_nr01_repeat
python -m botforeman.cycle infer experiments/botforeman_nr01_repeat experiments/botforeman_nr01_repeat/baseline_new.jsonl
python -m botforeman.cycle review experiments/botforeman_nr01_repeat experiments/botforeman_nr01_repeat/baseline_new.jsonl
```

Nu există fallback de rețea: modelul trebuie să fie în cache, CUDA disponibil,
iar torch/transformers/peft/bitsandbytes instalate. Nu am instalat alte frameworkuri.

## Revizuire umană și Gold

Poți comunica în conversație `NR01: confirm`, `NR02: correct — textul dorit`,
`NR03: reject`. Nu a fost completată nicio confirmare în numele tău.
Alternativ, copiază șablonul într-un fișier nou:

```powershell
Copy-Item experiments/botforeman_nr01/review_template.jsonl experiments/botforeman_nr01/human_decisions.jsonl
```

Editează fiecare rând: `decision` este `pending`, `confirm`, `correct` sau `reject`.
`confirm` acceptă **candidatul**, nu implicit răspunsul Copycat. Pentru `correct`,
completează `target`. Pentru orice decizie finală completează `reviewer`,
`reviewed_at` în format ISO-8601 și, preferabil, `notes`. Păstrează `queue_sha256`.
Nu copia decizii din testele sintetice: acestea trăiesc numai în directoare temporare.

```powershell
python -m botforeman.cycle export-gold experiments/botforeman_nr01 experiments/botforeman_nr01/human_decisions.jsonl experiments/botforeman_nr01/gold_validated.jsonl
```

Exportul refuză setul gol, ID-uri duplicate/necunoscute, revizuiri vechi, probe
rezervate sau suprapuneri cu Gold/benchmarkuri. Fiecare exemplu păstrează promptul,
răspunsul-model prin sursa cu hash, versiunea evaluatorului, autorul candidatului,
decizia umană și hash-urile cozii și deciziilor. Semnătura criptografică a persoanei
nu este implementată: fișierul deciziilor este un document local de încredere.
Verificarea suprapunerilor este textuală normalizată, nu o garanție de independență
semantică; probele rezervate sunt intenționat din aceleași familii de competențe.

## Regresii și pornire explicită a antrenării

Înainte de antrenare trebuie produs un baseline complet, fără evaluator atașat:
196 probe înghețate + 10 probe noi. Referințele benchmarkurilor sunt citite doar
pentru evaluare, niciodată exportate în Gold. Comanda este pregătită, dar nu a fost
executată în prima trecere; cele 10 probe noi sunt deja măsurate separat.

```powershell
python -m botforeman.cycle infer experiments/botforeman_nr01 experiments/botforeman_nr01/baseline_all.jsonl --regression
python -m botforeman.cycle.experiment experiments/botforeman_nr01 --gold experiments/botforeman_nr01/gold_validated.jsonl --baseline experiments/botforeman_nr01/baseline_all.jsonl
```

Ultima comandă afișează configurația și dimensiunea reală a Gold-ului. Nu antrenează.
Doar după revizuire și verificarea planului se poate folosi comanda explicită:

```powershell
python -m botforeman.cycle.experiment experiments/botforeman_nr01 --gold experiments/botforeman_nr01/gold_validated.jsonl --baseline experiments/botforeman_nr01/baseline_all.jsonl --execute
```

Aceasta rămâne blocată dacă Gold-ul, revizuirea sau baseline-ul lipsesc ori nu mai
corespund hash-urilor. Secvențele prea lungi sunt respinse, nu trunchiate în tăcere.
Antrenorul a fost pregătit și porțile validate prin teste; calea GPU de backward
nu a fost executată, conform interdicției de antrenare înainte de validarea Gold.

După antrenare, măsurarea este din nou Copycat singur:

```powershell
python -m botforeman.cycle infer experiments/botforeman_nr01 experiments/botforeman_nr01/after_all.jsonl --adapter experiments/botforeman_nr01/adapter_candidate --regression
python -m botforeman.cycle.compare experiments/botforeman_nr01/baseline_all.jsonl experiments/botforeman_nr01/after_all.jsonl experiments/botforeman_nr01/comparison.json
```

Comparația separă lecția expusă la training de cele patru probe rezervate și de
fiecare benchmark vechi. Produce diferențe și o coadă nouă de judecăți semantice
și de traseu. Exact match este doar un diagnostic pentru răspunsuri deschise.
`null` în judecăți înseamnă incertitudine; nu este convertit în eșec/succes.
Nu se pretinde progres până la existența ambelor rulări și revizuirea rezultatelor.

După completarea de către om a cozii `comparison.json.review.jsonl`:

```powershell
python -m botforeman.cycle.compare experiments/botforeman_nr01/baseline_all.jsonl experiments/botforeman_nr01/after_all.jsonl experiments/botforeman_nr01/comparison_reviewed.json --judgments experiments/botforeman_nr01/comparison.json.review.jsonl
```

Orice regresie semantică sau de traseu este listată explicit. Acceptarea unui
compromis și promovarea adaptorului sunt manuale; nu se ascund regresii într-o medie.

## Costuri și limite

`api_policy.json`: enabled=false, model=null, tarife=null, plafon=0 USD,
maximum 0 apeluri și 0 tokenuri. `api_usage.jsonl` consemnează consumul zero.
Pasul următor propus este local: cost API estimat 0 USD; curentul și timpul GPU
nu sunt incluse. Rularea completă are maximum 206 × 384 = 79.104 tokenuri generate
local; durata nu este garantată. Niciun abonament ChatGPT nu este tratat drept credit API.

Nu există transport API în această implementare. `budget.py` este infrastructura
de contabilizare pentru o extensie viitoare, testată numai cu tarife sintetice.
Nu am ales un model plătit și nu am verificat tarife, fiindcă nu se propune un apel.
Înainte de orice extensie plătită trebuie prezentate modelul exact, URL-ul oficial
și tarifele verificate recent, limitele de apeluri/tokenuri, estimarea maximă și
plafonul concret; este obligatorie aprobarea ta explicită a acelui plan.

Contabilizarea refuză lipsa/expirarea tarifelor (24 ore), lipsa aprobării legate de
hash-ul politicii, depășirea plafonului și repetarea unui ID de cerere. Rezervă
costul maxim înaintea apelului, jurnalizează consumul și păstrează rezervarea
pentru rezultate necunoscute; nu există retry automat. Transportul viitor trebuie
să numere toate tokenurile de intrare înainte de trimitere, să impună limita de
ieșire inclusiv reasoning și să nu activeze tool-uri sau alte taxe. Un răspuns cu
consum peste limite blochează orice cerere ulterioară; contabilizarea singură nu
poate controla un furnizor care nu respectă limita transmisă. Verificarea URL-ului
și tarifului este o responsabilitate explicită înaintea aprobării, nu o presupunere
făcută de parserul JSON. Un lock rămas după crash necesită inspecție manuală.

## Fișiere de cod noi

- `botforeman/bots/nativ_roman_bot.py`
- `botforeman/cycle/__init__.py`, `__main__.py`, `probes.jsonl`
- `botforeman/cycle/workflow.py`, `local_model.py`, `budget.py`
- `botforeman/cycle/experiment.py`, `compare.py`, `README.md`
- `tests/test_botforeman_cycle.py`

Niciun fișier existent nu trebuie modificat. Nu există `copycat.py` în spațiul
inspectat; scripturile reale `chat_copycat_04.py` și `chat_copycat_romana_01.py`
rămân intacte, iar testele lor fără BotForeman continuă să treacă.
