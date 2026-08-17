"""Relevé de décisions : extraction automatique à partir du verbatim.

Deux niveaux :

* **par règles** (par défaut) — repérage des décisions, actions, échéances,
  montants et questions ouvertes à partir de tournures françaises courantes.
  Aucune dépendance, aucun envoi de données. À relire : c'est une aide au
  dépouillement, pas une synthèse rédigée.
* **par modèle de langue local** (optionnel) — si Ollama tourne sur la machine,
  une vraie synthèse rédigée est produite en plus. Toujours hors ligne.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections import Counter

# --------------------------------------------------------------------------- #
#  Repères linguistiques
# --------------------------------------------------------------------------- #

DECISION_CUES = [
    "on décide", "nous décidons", "il est décidé", "la décision est prise",
    "on valide", "c'est validé", "on acte", "c'est acté", "on retient",
    "on part sur", "on part plutôt sur", "on garde", "on tranche", "on confirme",
    "on annule", "on reporte", "on repousse", "on décale", "on abandonne",
    "on lance", "feu vert", "c'est d'accord", "on est d'accord pour", "on convient",
]
ACTION_CUES = [
    "je m'occupe", "je me charge", "je prends en charge", "je prépare", "je t'envoie",
    "je vous envoie", "je reviens vers", "je regarde", "je relance", "je vérifie",
    "tu peux", "vous pouvez", "il faut que", "il faudra", "on doit", "il faudrait",
    "se charge de", "s'occupe de", "prend en charge", "est chargé de", "est chargée de",
    "à faire", "à prévoir", "penser à", "ne pas oublier", "doit envoyer", "doit préparer",
]
# Une échéance doit contenir un repère de temps explicite : « pour le comité de
# direction » n'en est pas une, « pour le 12 mars » oui.
_MOIS = ("janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|"
         "novembre|décembre")
_JOURS = "lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche"
_TEMPOREL = (
    rf"(?:{_JOURS})(?:\s+prochain)?|demain|après-demain|aujourd'hui|ce\s+soir|"
    rf"(?:la\s+)?semaine\s+prochaine|(?:le\s+)?mois\s+prochain|"
    rf"fin\s+(?:de\s+semaine|du\s+mois|de\s+mois|d'année|de\s+journée)|"
    rf"\d{{1,2}}(?:er)?\s+(?:{_MOIS})|\d{{1,2}}[/-]\d{{1,2}}(?:[/-]\d{{2,4}})?"
)
# Un nombre seul n'est une date que derrière « avant le / pour le » : sans cela
# « 42 000 euros » ou « sous 48 heures » seraient pris pour des échéances.
DEADLINE_PATTERNS = [
    rf"\b(?:d'ici|avant|au plus tard|pour)\s+(?:le\s+|la\s+)?(?:{_TEMPOREL})",
    rf"\b(?:d'ici|avant|au plus tard|pour)\s+(?:le|la)\s+\d{{1,2}}\b",
    r"\bsous\s+\d{1,3}\s*(?:h|heures|jours|semaines)\b",
    rf"\b(?:{_TEMPOREL})\b",
]

AMOUNT_RE = re.compile(
    r"\b\d[\d\s.,]*\s*(?:€|euros?|k€|K€|%|pour\s?cent|millions?|milliers?|jours?-homme)\b",
    re.I)

STOPWORDS = set("""
alors au aucun aussi autre avant avec avoir bon car ce cela ces ceux chaque chez ci
comme comment dans de des du dedans dehors depuis devrait doit donc dos droite début
elle elles en encore essai est et eu fait faites fois font force haut hors ici il ils
je juste la le les leur là ma maintenant mais mes mine moins mon mot même ni nommés
notre nous nouveaux ou où par parce parole pas personnes peut peu pièce plupart pour
pourquoi quand que quel quelle quelles quels qui sa sans ses seulement si sien son
sont sous soyez sujet sur ta tandis tellement tels tes ton tous tout trop très tu
valeur voie voient vont votre vous vu ça étaient état étions été être un une on ce
c'est y a d' l' n' s' qu' j' m' t' voilà donc ok oui non bien peut-être après avant
faire dire aller voir savoir falloir vouloir pouvoir devoir chose choses truc trucs
euh hein bah ben quoi vraiment un peu du coup en fait par contre c' ils elles
faut merci bonjour bonsoir alors voilà alors donc alors bref enfin ensuite après
d'être d'accord d'abord aussi encore toujours jamais beaucoup plutôt surtout
petit petite grand grande autres mêmes celui celle ceux celles dont lequel
avez avons êtes sommes serait seront avait avaient étaient puisque lorsque
""".split())

SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+")


def _sentences(segments):
    """Découpe les segments en phrases, en gardant l'horodatage et le locuteur."""
    out = []
    for s in segments:
        parts = [p.strip() for p in SENT_SPLIT.split(s.text.strip()) if p.strip()]
        if not parts:
            continue
        dur = max(0.1, s.end - s.start) / len(parts)
        for i, p in enumerate(parts):
            out.append(dict(start=round(s.start + i * dur, 1), speaker=s.speaker, text=p))
    return out


def _deadline(text: str) -> str | None:
    low = text.lower()
    for pat in DEADLINE_PATTERNS:
        m = re.search(pat, low)
        if m:
            return m.group(0).strip()
    return None


def _owner(sent: dict) -> str | None:
    """Porteur de l'action : le locuteur s'il parle à la première personne,
    sinon un prénom capitalisé mentionné dans la phrase."""
    low = sent["text"].lower()
    if re.search(r"\b(je|j')\s*(m'|me\s|vais|prends|prépare|fais|regarde|relance)", low):
        return sent.get("speaker")
    words = sent["text"].split()
    for i, w in enumerate(words):
        clean = w.strip(",.;:!?()")
        if (i > 0 and clean[:1].isupper() and clean.lower() not in STOPWORDS
                and len(clean) > 2 and clean.isalpha()):
            return clean
    return sent.get("speaker")


def _hhmmss(t: float) -> str:
    t = int(t)
    return f"{t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}"


def _keywords(texts, n=6):
    words = re.findall(r"[a-zà-ÿ'’-]{4,}", " ".join(texts).lower())
    words = [w for w in words if w not in STOPWORDS and not w.endswith("'")]
    return [w for w, _ in Counter(words).most_common(n)]


# --------------------------------------------------------------------------- #
#  Extraction
# --------------------------------------------------------------------------- #


def extract(segments, duration: float, speaking: dict | None = None,
            block_minutes: float = 8.0) -> dict:
    sents = _sentences(segments)
    decisions, actions, questions, chiffres = [], [], [], []

    seen: set[tuple[str, str]] = set()      # évite les doublons mot pour mot

    def keep(bucket: list, entry: dict, tag: str) -> None:
        key = (tag, entry["texte"].strip().lower())
        if key not in seen:
            seen.add(key)
            bucket.append(entry)

    for s in sents:
        low = s["text"].lower()
        entry = dict(temps=_hhmmss(s["start"]), intervenant=s.get("speaker"), texte=s["text"])
        if any(c in low for c in DECISION_CUES):
            keep(decisions, entry, "d")
        elif any(c in low for c in ACTION_CUES):
            keep(actions, dict(entry, porteur=_owner(s), echeance=_deadline(s["text"])), "a")
        if s["text"].rstrip().endswith("?") and len(s["text"].split()) > 4:
            keep(questions, entry, "q")
        if AMOUNT_RE.search(s["text"]):
            keep(chiffres, entry, "c")

    # plan de la réunion : mots saillants par tranche de temps
    sujets = []
    if sents and duration > 0:
        step = block_minutes * 60
        t = 0.0
        while t < duration:
            block = [s["text"] for s in sents if t <= s["start"] < t + step]
            if len(block) >= 3:
                sujets.append(dict(debut=_hhmmss(t), fin=_hhmmss(min(t + step, duration)),
                                   mots_cles=_keywords(block), nb_phrases=len(block)))
            t += step

    mots = sum(len(s["text"].split()) for s in sents)
    stats = dict(
        duree=_hhmmss(duration),
        nb_mots=mots,
        nb_phrases=len(sents),
        debit_mots_min=round(mots / max(duration / 60, 1e-9), 1),
    )
    if speaking:
        total = sum(speaking.values()) or 1.0
        stats["temps_parole"] = {k: dict(duree=_hhmmss(v), part=f"{100 * v / total:.0f} %")
                                 for k, v in speaking.items()}
    return dict(decisions=decisions, actions=actions, questions=questions,
                chiffres=chiffres, sujets=sujets, stats=stats)


# --------------------------------------------------------------------------- #
#  Synthèse rédigée par modèle de langue local (Ollama), optionnelle
# --------------------------------------------------------------------------- #

PROMPT = """Tu es secrétaire de séance. Voici la transcription brute d'une réunion.
Rédige un compte rendu en français, factuel et concis, structuré ainsi :

## Résumé (5 lignes maximum)
## Décisions prises
## Actions à mener (qui / quoi / pour quand)
## Points en suspens

N'invente rien : si une information est absente, ne la mentionne pas.

Transcription :
---
{texte}
---"""


def llm_available(host: str = "http://127.0.0.1:11434") -> bool:
    try:
        with urllib.request.urlopen(f"{host}/api/tags", timeout=1.5) as r:
            return r.status == 200
    except Exception:
        return False


def synthese_llm(segments, model: str = "llama3.1", host: str = "http://127.0.0.1:11434",
                 max_chars: int = 24000) -> str | None:
    """Compte rendu rédigé par un modèle local. Renvoie None si indisponible."""
    if not llm_available(host):
        return None
    texte = "\n".join(f"[{_hhmmss(s.start)}] {s.speaker or ''} {s.text}".strip()
                      for s in segments)[:max_chars]
    body = json.dumps(dict(model=model, prompt=PROMPT.format(texte=texte),
                           stream=False, options=dict(temperature=0.2))).encode()
    req = urllib.request.Request(f"{host}/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            return json.loads(r.read()).get("response", "").strip() or None
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None
