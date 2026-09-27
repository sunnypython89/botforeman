"""Draft contextual probes and explicit rubrics, owned by the native evaluator.

These are controlled recognition tasks, not a native-language certification.
No Gold or frozen benchmark material is loaded here.
"""

from dataclasses import dataclass
import hashlib
import json

CATEGORIES = ("IDIOM", "PRAGMATICS", "REGISTER", "COLLOCATION_NATURALNESS", "IMPLICIT_MEANING")
POOL_VERSION = "native-context-1"
PROPERTIES = {
    "IDIOM": ("semantic_correctness", "idiomatic_naturalness"),
    "PRAGMATICS": ("pragmatic_interpretation", "semantic_correctness"),
    "REGISTER": ("correct_register", "instruction_fidelity"),
    "COLLOCATION_NATURALNESS": ("idiomatic_naturalness", "absence_of_obvious_translation_artifacts"),
    "IMPLICIT_MEANING": ("pragmatic_interpretation", "semantic_correctness"),
}


@dataclass(frozen=True)
class NativeSpec:
    probe_id: str
    category: str
    context: str
    task: str
    criterion: str
    # Each tuple is (option text, rating, short internal explanation).
    options: tuple


def spec(category, number, context, task, criterion, good, bad, uncertain=None):
    options = [(good, "GOOD", criterion), (bad, "BAD", "Contrazice criteriul contextual: " + criterion)]
    if uncertain:
        options.append((uncertain, "UNCERTAIN", "Variantă nativă plauzibilă; contextul sau variația de uz nu decid sigur."))
    return NativeSpec(f"{category}_{number:02d}", category, context, task, criterion, tuple(options))


POOL = (
    spec("IDIOM", 1, "După a treia amânare, Lia spune: «Mă tot duce cu zăhărelul; promite și nu face nimic».",
         "Ce exprimă aici «mă duce cu zăhărelul»?", "Recunoaște amăgirea prin promisiuni, nu o deplasare sau un aliment.",
         "Mă amăgește cu promisiuni.", "Mă conduce undeva oferindu-mi zahăr."),
    spec("IDIOM", 2, "Discuția se repetă de o oră fără concluzii. «Iar batem apa-n piuă», spune Dan.",
         "Alege sensul expresiei în această discuție.", "Recunoaște vorbirea repetitivă fără rezultat.",
         "Repetăm inutil aceleași idei.", "Pregătim efectiv apă într-un vas."),
    spec("IDIOM", 3, "A auzit câinele lătrând în spate și «a luat-o la sănătoasa».",
         "Ce a făcut persoana?", "Recunoaște fuga, nu îmbunătățirea sănătății.",
         "A fugit repede.", "A început un tratament medical."),
    spec("IDIOM", 4, "Un coleg încearcă să ascundă greșeala, dar explicația lui «dă cu bâta-n baltă».",
         "Ce se spune despre explicație?", "Recunoaște o gafă care agravează situația.",
         "Face o gafă și înrăutățește situația.", "Descrie o lovitură dată unei bălți reale."),
    spec("IDIOM", 5, "«Știu că ai pregătit interviul. Îți țin pumnii!» îi scrie Ada prietenei sale.",
         "Ce transmite Ada?", "Recunoaște susținerea și urarea de succes.",
         "Îi dorește succes și o susține.", "O amenință cu o bătaie."),

    spec("PRAGMATICS", 1, "Radu sosește cu 45 de minute întârziere. Colega, vizibil iritată, spune: «Ce punctual ești!»",
         "Cum se interpretează replica în acest context?", "Recunoaște reproșul ironic susținut de întârziere și iritare.",
         "Îi reproșează ironic întârzierea.", "Îl laudă sincer pentru punctualitate."),
    spec("PRAGMATICS", 2, "În cameră e frig, fereastra e deschisă. Gazda se uită spre ea și îi spune invitatului: «Cam trage curentul aici». Invitatul stă lângă fereastră.",
         "Ce intenție este plauzibilă, fără a o prezenta drept certitudine?", "Identifică o posibilă cerere indirectă și păstrează incertitudinea.",
         "Poate sugera să fie închisă fereastra.", "Îi ordonă explicit să deschidă toate ferestrele.",
         "Poate fi doar o observație despre frig."),
    spec("PRAGMATICS", 3, "Cineva varsă cafeaua pe documentele abia tipărite. Autorul lor oftează: «Minunat, exact asta ne lipsea!»",
         "Ce exprimă replica?", "Identifică nemulțumirea ironică, nu bucuria literală.",
         "Exprimă ironic nemulțumirea.", "Se bucură sincer că documentele sunt pătate."),
    spec("PRAGMATICS", 4, "Muzica e foarte tare. Vecina spune calm: «Aș vrea să pot adormi și eu în seara asta». Se uită către boxe.",
         "Alege interpretarea contextuală prudentă.", "Recunoaște cererea indirectă de reducere a zgomotului, fără agresivitate inventată.",
         "Sugerează să fie dată muzica mai încet.", "Cere explicit ca muzica să fie dată mai tare."),
    spec("PRAGMATICS", 5, "Un coleg îi atribuie altuia meritele muncii tale. Tu răspunzi pe un ton ironic: «Da, eu doar am stat și m-am uitat». Contextul arată că ai făcut cea mai mare parte a muncii.",
         "Care este intenția replicii?", "Recunoaște contestarea ironică a lipsei de contribuție.",
         "Atragi ironic atenția că ai contribuit mult.", "Confirmi sincer că nu ai contribuit deloc."),

    spec("REGISTER", 1, "Scrii unui prieten apropiat pe chat. Vrei o rugăminte familiară, politicoasă, fără ton administrativ.",
         "Alege mesajul potrivit pentru a cere puțin ajutor.", "Păstrează registrul familiar cerut, fără formulă birocratică.",
         "Îmi dai o mână de ajutor, te rog?", "Vă solicit respectuos acordarea sprijinului dumneavoastră."),
    spec("REGISTER", 2, "Scrii pentru prima dată unei instituții. Ți se cere o solicitare formală și sobră, fără familiaritate.",
         "Alege mesajul pentru a cere confirmarea primirii unui document.", "Respectă registrul formal și adresarea politicoasă.",
         "Vă rog să confirmați primirea documentului.", "Hei, zi-mi și mie dacă ți-a ajuns hârtia!"),
    spec("REGISTER", 3, "Un coleg apropiat are necazuri. Vrei să-i trimiți un mesaj cald și firesc, nu o adresă oficială.",
         "Alege formularea potrivită.", "Păstrează apropierea și căldura, fără formalism instituțional.",
         "Sunt aici dacă ai nevoie de mine.", "Vă notific disponibilitatea mea pentru asistență."),
    spec("REGISTER", 4, "Într-un dialog fictiv, personajul e furios și vorbește colocvial, ușor vulgar. Se cere păstrarea acestui registru, nu îndulcirea replicii.",
         "Alege replica despre un aparat care s-a stricat din nou.", "Respectă registrul colocvial-vulgar cerut explicit, fără formalizare.",
         "La dracu, iar s-a stricat!", "Regret să constat o nouă defecțiune a aparatului."),
    spec("REGISTER", 5, "Vrei un mesaj scurt și colocvial pentru un vecin cunoscut. Nu este precizată regiunea sau generația vorbitorilor.",
         "Alege o rugăminte pentru a închide poarta.", "Preferă o rugăminte colocvială; nu condamnă automat o variantă regională plauzibilă.",
         "Închizi poarta, te rog?", "Prin prezenta vă solicit închiderea porții.",
         "Închizi oleacă poarta, te rog?"),

    spec("COLLOCATION_NATURALNESS", 1, "Îi spui cuiva drag că îi simți lipsa, după o lună în care nu v-ați văzut. Nu vorbești despre ratarea unei ținte.",
         "Alege formularea firească pentru acest sens.", "Folosește expresia românească pentru dor; evită traducerea literală a lui «miss».",
         "Mi-e dor de tine.", "Te ratez."),
    spec("COLLOCATION_NATURALNESS", 2, "Un coleg va afla rezultatul unei cereri mâine. Îi ceri să te informeze când apar noutăți.",
         "Alege formularea firească în română.", "Recunoaște «a ține la curent», evitând calcul literal «keep me posted».",
         "Ține-mă la curent, te rog.", "Ține-mă postat, te rog."),
    spec("COLLOCATION_NATURALNESS", 3, "Îți spui vârsta într-o conversație obișnuită în română. Ai 28 de ani.",
         "Alege formularea firească.", "Exprimă vârsta fără traducerea literală a lui «years old».",
         "Am 28 de ani.", "Sunt 28 de ani vechi."),
    spec("COLLOCATION_NATURALNESS", 4, "Un plan este logic și inteligibil. Vorbiți informal; grupul și generația nu sunt precizate.",
         "Alege o formulare românească neutră pentru această idee.", "Recunoaște forma neutră; tratează «face sens» ca uz discutabil, nu ca eroare sigură.",
         "Planul are sens.", "Planul este alcătuit din zahăr.",
         "Planul face sens."),
    spec("COLLOCATION_NATURALNESS", 5, "Termenul pentru predare a sosit; vrei să spui că nu mai ai timp disponibil. Nu vorbești despre locul în care te afli.",
         "Alege expresia potrivită în română.", "Exprimă lipsa timpului fără traducerea literală a lui «out of time».",
         "Nu mai am timp.", "Sunt afară de timp."),

    spec("IMPLICIT_MEANING", 1, "La o propunere de întâlnire, Irina răspunde: «Mai vedem». Nu oferă altă confirmare.",
         "Ce poți concluziona prudent?", "Nu transformă un răspuns neangajant într-o confirmare fermă.",
         "Întâlnirea nu este încă confirmată.", "Irina a confirmat definitiv întâlnirea."),
    spec("IMPLICIT_MEANING", 2, "Primești doar mesajul «Interesant», fără ton, emoji sau alte informații.",
         "Ce poți spune despre atitudinea expeditorului?", "Păstrează ambiguitatea contextuală; aprecierea sau rezerva pot fi lecturi native rezonabile.",
         "Nu pot stabili sigur atitudinea doar din acest mesaj.", "Este cu siguranță încântat.",
         "Ar putea exprima apreciere."),
    spec("IMPLICIT_MEANING", 3, "După ce află un preț mare, cumpărătorul spune «Mă mai gândesc» și nu face comanda.",
         "Ce informație este susținută de context?", "Recunoaște lipsa angajamentului; nu echivalează automat cu refuzul definitiv.",
         "Nu s-a angajat încă să cumpere.", "A comandat deja și a promis plata.",
         "Poate fi un refuz politicos."),
    spec("IMPLICIT_MEANING", 4, "«Nu prea mă încântă ideea», spune o colegă, fără să accepte propunerea.",
         "Care este lectura firească?", "Recunoaște rezerva exprimată atenuat.",
         "Își exprimă rezervele față de idee.", "Își exprimă entuziasmul fără rezerve."),
    spec("IMPLICIT_MEANING", 5, "La invitația pentru diseară, răspunsul este «Mâine mă trezesc la cinci». Nu urmează nici da, nici nu.",
         "Care este o interpretare posibilă, formulată fără certitudine excesivă?", "Recunoaște posibilul refuz indirect, fără a exclude simpla informare.",
         "Poate sugera că nu va veni sau că nu va sta târziu.", "A acceptat explicit să rămână toată noaptea.",
         "Poate doar să comunice ora la care se trezește."),
)


def pool_fingerprint():
    return hashlib.sha256(json.dumps([vars(p) for p in POOL], ensure_ascii=False,
                                      sort_keys=True).encode("utf-8")).hexdigest()


def select_probes(cycle_index):
    if type(cycle_index) is not int or cycle_index < 0:
        raise ValueError("cycle_index must be a nonnegative integer")
    selected = []
    for category_index, category in enumerate(CATEGORIES):
        candidates = [p for p in POOL if p.category == category]
        item = candidates[cycle_index % len(candidates)]
        offset = (cycle_index + category_index) % len(item.options)
        options = item.options[offset:] + item.options[:offset]
        labels = {chr(65 + i): option for i, option in enumerate(options)}
        question = (f"Context: {item.context}\n{item.task}\n"
                    + "\n".join(f"{key}: {value[0]}" for key, value in labels.items())
                    + "\nAlege o singură variantă. Răspunde cu litera sau cu textul variantei alese.")
        selected.append({"probe_id": item.probe_id, "category": category, "context": item.context,
                         "prompt": question, "answer_options": {k: v[0] for k, v in labels.items()},
                         "evaluator_criterion": item.criterion,
                         "tested_properties": list(dict.fromkeys((*PROPERTIES[category], "instruction_fidelity"))),
                         "rubric": {k: {"result": v[1], "explanation": v[2]} for k, v in labels.items()}})
    return selected
