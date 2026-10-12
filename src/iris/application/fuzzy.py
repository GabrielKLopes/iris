import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher

TECH_TERMS = [
    "kubectl", "Kubernetes", "Keycloak", "Azure DevOps", "Docker", "Docker Swarm", "Harbor", "Portainer",
    "Grafana", "Prometheus", "PowerShell", "GitHub", "pipeline", "deploy", "namespace", "pod",
]
APP_NAMES = [
    "Google Chrome", "Microsoft Teams", "Visual Studio Code", "VS Code", "WhatsApp", "Spotify", "Outlook",
    "Excel", "YouTube", "Discord", "DBeaver", "Postman",
]
COMMON_ANCHORS = {"gogle", "mikrosoft", "visual", "dokker", "doker"}
PROPER_NAME = re.compile(r"\b[A-ZÀ-Ý][\wÀ-ÿ]+(?:\s+[A-ZÀ-Ý][\wÀ-ÿ]+){1,3}")
SOUND_RULES = [
    (r"ph", "f"), (r"ch", "x"), (r"sh", "x"), (r"lh", "li"), (r"nh", "ni"), (r"qu", "k"), (r"gu(?=[ei])", "g"),
    (r"c(?=[ei])", "s"), (r"c", "k"), (r"q", "k"), (r"w", "u"), (r"y", "i"), (r"z", "s"), (r"b", "v"),
    (r"h", ""), (r"ss", "s"), (r"(.)\1+", r"\1"),
]


def phonetic(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    plain = re.sub(r"[^a-z0-9 ]+", " ", plain)
    plain = re.sub(r"\s+", " ", plain).strip()
    for pattern, replacement in SOUND_RULES:
        plain = re.sub(pattern, replacement, plain)
    return plain


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, phonetic(a), phonetic(b)).ratio()


def names_in(texts: Iterable[str]) -> list[str]:
    found: list[str] = []
    for text in texts:
        for match in PROPER_NAME.findall(text):
            words = match.split()
            if words[0] in {"O", "A", "Os", "As", "No", "Na", "Em", "Gabriel"}:
                words = words[1:]
            name = " ".join(words)
            if len(words) >= 2 and name not in found:
                found.append(name)
    return found


@dataclass(frozen=True)
class Correction:
    heard: str
    replaced_by: str
    score: float


class TranscriptCorrector:
    def __init__(
        self,
        vocabulary: Callable[[], list[str]],
        threshold: float = 0.78,
        anchored_threshold: float = 0.68,
        single_word_threshold: float = 0.92,
    ):
        self.vocabulary = vocabulary
        self.threshold = threshold
        self.anchored_threshold = anchored_threshold
        self.single_word_threshold = single_word_threshold

    @staticmethod
    def _rest_matches(sounds: str, target: str, anchors: set[str], minimum: float = 0.5) -> bool:
        rest = " ".join(w for w in sounds.split() if w not in anchors)
        expected = " ".join(w for w in target.split() if w not in anchors)
        if not rest or not expected or len(rest) < 0.7 * len(expected):
            return False
        return SequenceMatcher(None, rest, expected).ratio() >= minimum

    def correct(self, text: str) -> tuple[str, list[Correction]]:
        tokens = re.findall(r"[\wÀ-ÿ'-]+|[^\w\s]", text)
        words = [i for i, t in enumerate(tokens) if re.match(r"[\wÀ-ÿ]", t)]
        corrections: list[Correction] = []
        for term in sorted(set(self.vocabulary()), key=lambda t: -len(t.split())):
            size = len(term.split())
            target = phonetic(term)
            if len(target) < 5:
                continue
            anchors = {w for w in target.split() if len(w) >= 5 and w not in COMMON_ANCHORS}
            best: tuple[float, int, int] | None = None
            for width in range(max(1, size - 1), size + 3):
                for start in range(0, len(words) - width + 1):
                    first, last = words[start], words[start + width - 1]
                    window = " ".join(tokens[i] for i in words[start : start + width])
                    sounds = phonetic(window)
                    score = 1.0 if sounds == target else SequenceMatcher(None, sounds, target).ratio()
                    shared = anchors & set(sounds.split())
                    if size == 1:
                        needed = self.single_word_threshold
                    elif shared and self._rest_matches(sounds, target, shared):
                        needed = self.anchored_threshold
                    else:
                        needed = self.threshold
                    if score >= needed and (best is None or score > best[0]):
                        best = (score, first, last)
            if best is None:
                continue
            score, first, last = best
            heard = " ".join(t for t in tokens[first : last + 1] if re.match(r"[\wÀ-ÿ]", t))
            if heard.lower() == term.lower():
                continue
            tokens[first : last + 1] = [term]
            words = [i for i, t in enumerate(tokens) if re.match(r"[\wÀ-ÿ]", t)]
            corrections.append(Correction(heard, term, round(score, 2)))
        rebuilt = ""
        for token in tokens:
            rebuilt += token if re.match(r"[^\w\s]", token) or not rebuilt else " " + token
        return rebuilt, corrections


def default_vocabulary(facts: Callable[[], list[str]]) -> Callable[[], list[str]]:
    def vocabulary() -> list[str]:
        return names_in(facts()) + APP_NAMES + TECH_TERMS

    return vocabulary
