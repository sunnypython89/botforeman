# BotForeman v0.1

Subsistem optional pentru distilare prin omisiune. Foloseste numai biblioteca
standard Python (3.10+). Nu importa Copycat, torch, transformers sau peft.

## Rulare din radacina proiectului

```sh
python -m botforeman.demo
python -m unittest discover -s tests -p "test_botforeman.py" -v
```

## Arhitectura si conectare

`protocol.py` defineste datele comune si limitele textului; `result.py` defineste
rezultatul serializabil si planul KEEP/OMIT/UNCERTAIN. `foreman.py` ataseaza si
detaseaza evaluatori, executa evaluarea si colecteaza planurile. Regulile de domeniu
raman exclusiv in `bots/`. Nu exista descoperire dinamica sau incarcare din text.

Integrarea Copycat este externa acestui repository; scripturile de compatibilitate sunt snapshoturi in `tests/fixtures/`. Punctul de conectare este
dupa `answer = tokenizer.decode(...).strip()` in `chat_copycat_04.py` sau
`chat_copycat_romana_01.py`. In evaluarile existente, echivalentul este dupa
`answer = generate(prompt)`. Aceste fisiere si benchmarkurile raman nemodificate.
Un consumator separat poate folosi raspunsuri deja produse:

```python
from botforeman import BotForeman
from botforeman.bots import CountingBot

foreman = BotForeman()
foreman.attach(CountingBot())
prompt = foreman.generate_tests("counting.bot")[0].prompt
# Trimite prompt catre Copycat separat; aici folosim un raspuns demonstrativ.
answer = "[1,2,3,4,5]"
results = foreman.evaluate(prompt, answer)
print(results[0].to_json())
foreman.detach("counting.bot")
```

`enabled=False` intoarce lista goala fara apelarea evaluatorilor. Cu zero
evaluatori, lista rezultatelor este goala. Nu exista agregare implicita intre
specialisti. Erorile evaluatorilor devin UNCERTAIN si nu intrerup ceilalti boti.
Argumentele non-text sau peste 65.536 caractere sunt respinse cu exceptii.

Evaluatorul experimental `nativ_roman.bot` implementeaza `ForemanBot` si se ataseaza explicit,
fara schimbari in orchestrator. `generate_tests(context)` apartine specialistului;
`evaluate(prompt, output)` produce verdictul; `omission_plan(...)` poate rafina
planul, implicit returnand planul evaluarii. Metodele trebuie sa fie fara efecte
secundare. Rezultatele sunt imuabile; `to_dict()` si `to_json()` produc date uzuale.

## Protocol counting.bot

Prompt strict: `COUNT <start> <stop> <step>` (de exemplu `COUNT 1 5 1`). Capetele
sunt inclusive, pasul nenul trebuie sa ajunga exact la stop. Sunt permise secvente
descrescatoare, pasi diferiti de unu si numere negative. Maximum 1.000 elemente;
valorile si pasul au modulul cel mult 1.000.000.000.

Raspunsul trebuie sa fie un array JSON de intregi: `[1,2,3,4,5]`. Nu sunt acceptate
booleene, numere reale sau explicatii alaturi de array. Formatele neacceptate si
cererile din afara protocolului produc UNCERTAIN, scor null, fara OMIT.

PASS are scor 1 si KEEP `exact_sequence`. FAIL are scor 0 si coduri OMIT:
`missing_element`, `duplicate_element`, `unexpected_element`, `wrong_order`,
`off_by_one`. Codurile pot coexista. Ordinea gresita inseamna o inversiune intre
elementele recunoscute. Off-by-one inseamna un singur capat lipsa/adaugat sau
intreaga secventa deplasata cu un pas. Nu reprezinta o explicatie cauzala despre
model. Erorile interne nu sunt etichetate automat off-by-one.

KEEP/OMIT sunt comportamente, nu instructiuni de stergere a unor fragmente din
raspuns. Nu rescriem raspunsul. La esec nu presupunem ca parti nevalidate sunt bune.
Scorurile altor evaluatori pot folosi orice valoare finita in [0,1], sau null cand
scorul nu este disponibil; nu sunt automat comparabile intre domenii.

## Limite si verificare

Sandboxul este un contract de procesare text/date, nu izolare OS pentru cod Python
ostil. Sunt acceptati numai evaluatori locali de incredere. Nu se executa textul,
nucleul de evaluare nu executa retea, subprocess, antrenare sau rescriere. Workflow-urile experimentale separate pot persista rapoarte si contin un experiment de antrenare cu porti explicite; vezi README-ul radacina.
`logs/` este rezervat; serializarea explicita poate fi colectata ulterior de apelant
impreuna cu promptul si outputul. Nu sunt modificate dataseturi sau adaptoare LoRA.

Testul de compatibilitate ruleaza cele doua scripturi reale de chat, blocheaza
importul BotForeman si simuleaza dependentele modelului. Verifica raspunsul afisat
si istoricul conversatiei. Nu este un test de inferenta GPU cu modelul real.
Demo-ul foloseste raspunsuri fixe, nu apeleaza Copycat.
