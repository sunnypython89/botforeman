"""25 controlled Romanian probes. Level names describe a draft test curriculum,
not a validated proficiency scale. The answer key is owned only by this evaluator.
"""

import re

from .base import ForemanBot
from ..levels.protocol import LEVELS, Probe
from ..protocol import TestCase
from ..result import EvaluationResult

# Each level uses five distinct two-choice tasks of roughly comparable difficulty.
# Tuples: task, A, B, correct option. No benchmarks/Gold are read or changed.
ITEMS = {
    "STRAIN": (
        ("Alege salutul potrivit dimineața.", "Bună dimineața!", "Noapte bună!", "A"),
        ("Alege formula de mulțumire.", "La revedere!", "Mulțumesc!", "B"),
        ("Alege răspunsul afirmativ la o întrebare.", "Da.", "Nu.", "A"),
        ("Alege formula folosită când pleci.", "Bine ai venit!", "La revedere!", "B"),
        ("Alege formula pentru a cere politicos ceva.", "Te rog.", "Pe curând.", "A"),
    ),
    "INCEPATOR": (
        ("Alege acordul corect.", "Eu merge la piață.", "Eu merg la piață.", "B"),
        ("Alege acordul corect.", "Fetele citesc.", "Fetele citește.", "A"),
        ("Alege acordul corect.", "O carte frumoși.", "O carte frumoasă.", "B"),
        ("Alege acordul corect.", "Noi suntem aici.", "Noi este aici.", "A"),
        ("Alege acordul corect.", "Două caiete nouă.", "Două caiete noi.", "B"),
    ),
    "INTERMEDIAR": (
        ("Ceri o factură unui furnizor necunoscut. Alege registrul profesional politicos.",
         "Trimite-mi factura, mă!", "Vă rog să-mi trimiteți factura.", "B"),
        ("Ceri unui prieten apropiat un încărcător, într-o conversație relaxată. Alege formularea potrivită.",
         "Îmi împrumuți încărcătorul, te rog?", "Vă solicit respectuos punerea la dispoziție a încărcătorului.", "A"),
        ("Scrii unei instituții. Alege formularea neutră și politicoasă.",
         "Hei, zi-mi programul vostru!", "Vă rog să-mi comunicați programul de lucru.", "B"),
        ("Refuzi politicos o invitație profesională. Alege răspunsul potrivit.",
         "Vă mulțumesc pentru invitație, dar nu voi putea participa.", "Nu vin, descurcați-vă!", "A"),
        ("Îi ceri unui vecin cunoscut să vorbească mai încet. Alege formularea politicoasă.",
         "Taci odată!", "Poți vorbi puțin mai încet, te rog?", "B"),
    ),
    "AVANSAT": (
        ("Păstrează exact condiția din «Intrăm numai dacă primim permisiunea».",
         "Fără permisiune, nu intrăm.", "Dacă primim permisiunea, intrăm neapărat.", "A"),
        ("Păstrează sensul din «Nu toate sertarele sunt goale».",
         "Niciun sertar nu este gol.", "Cel puțin un sertar nu este gol.", "B"),
        ("Păstrează sensul din «Doar Mircea a semnat».",
         "Mircea a semnat, iar ceilalți nu au semnat.", "Mircea și încă cineva au semnat.", "A"),
        ("Păstrează sensul din «Poate că trenul întârzie».",
         "Trenul întârzie sigur.", "Este posibil ca trenul să întârzie.", "B"),
        ("Păstrează sensul din «Au venit toți, cu excepția Corinei».",
         "Corina nu a venit; ceilalți au venit.", "A venit și Corina.", "A"),
    ),
    "NATIV": (
        ("Un coleg spune «Mai vedem» când îi propui o dată. Alege interpretarea prudentă.",
         "A confirmat definitiv data.", "Nu a luat încă un angajament ferm.", "B"),
        ("Un prieten spune «Nu prea mă încântă ideea». Alege interpretarea firească.",
         "Își exprimă rezervele într-un mod atenuat.", "Își exprimă entuziasmul fără rezerve.", "A"),
        ("După o explicație lămuritoare, cineva spune «Acum se leagă lucrurile». Alege sensul contextual.",
         "Obiectele sunt legate cu o sfoară.", "Informațiile au început să capete sens împreună.", "B"),
        ("«Nu m-a lăsat inima să-l refuz.» Alege sensul firesc în lipsa unui context medical.",
         "Din compasiune sau afecțiune, nu am putut să-l refuz.", "O problemă cardiacă m-a împiedicat fizic să vorbesc.", "A"),
        ("«Lasă, că nu intră zilele în sac.» Alege sensul uzual.",
         "Nu mai există deloc timp.", "Nu trebuie să ne grăbim; mai avem timp.", "B"),
    ),
}


class RomanianLevelsBot(ForemanBot):
    name = "romanian_levels.bot"
    version = "1.1-controlled-choice"

    def __init__(self):
        self._probes, self._answers, self._choices = [], {}, {}
        for level in LEVELS:
            for index, (task, a, b, answer) in enumerate(ITEMS[level], 1):
                prompt = f"{task}\nA: {a}\nB: {b}\nRăspunde cu A sau B; poți reda și varianta aleasă."
                self._probes.append(Probe(level, f"{level}_{index}", prompt))
                self._answers[prompt] = answer
                self._choices[prompt] = {"A": a, "B": b}

    def level_tests(self):
        return tuple(self._probes)

    def generate_tests(self, context=None):
        if context:
            raise ValueError("No context options for this fixed draft curriculum")
        return tuple(TestCase(p.example_id, p.input) for p in self._probes)

    def evaluate_rating(self, prompt, output):
        expected = self._answers.get(prompt)
        answer = output.strip()
        if expected is None:
            return "UNCERTAIN"
        letter = re.fullmatch(r"([AB])[.!]?", answer)
        if letter:
            selected = letter.group(1)
        else:
            labelled = re.fullmatch(r"([AB])\s*[:.)-]\s*(.+)", answer, re.DOTALL)
            if not labelled:
                return "UNCERTAIN"
            selected, text = labelled.groups()
            # Exact selected option apart from whitespace and final punctuation.
            # Do not infer from a prefix, free explanation or conflicting label.
            normalize = lambda s: " ".join(s.split()).rstrip(".!?")
            if normalize(text) != normalize(self._choices[prompt][selected]):
                return "UNCERTAIN"
        return "GOOD" if selected == expected else "BAD"

    def evaluate(self, prompt, output):
        """Compatibility with v0.1 only; level-cycle records have no scores."""
        rating = self.evaluate_rating(prompt, output)
        status = {"GOOD": "PASS", "BAD": "FAIL", "UNCERTAIN": "UNCERTAIN"}[rating]
        return EvaluationResult(self.name, status, None)
