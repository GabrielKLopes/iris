import re
import unicodedata

from iris.domain.intents import Intent

ASSISTANT_NAMES = {"iris", "ires", "iriz", "irys", "assistente"}
OPEN_WORDS = {
    "abre", "abra", "abrir", "abri", "chama", "chamar", "inicia", "iniciar", "liga", "ligar",
    "mostra", "mostrar", "traz", "trazer", "aparece", "acorda", "preciso", "quero", "cade",
    "bora", "vamos", "ativa", "ativar", "executa", "roda", "vem",
}
HOLD_PHRASES = {
    "espera", "espere", "pera", "perai", "peraí", "calma", "um momento", "so um momento",
    "um minuto", "so um minuto", "hum", "hmm", "ahn", "e", "entao", "deixa eu pensar", "nao nao",
    "espera espera", "espere espere", "nao espera", "calma calma",
}


def is_echo(heard: str, spoken: str) -> bool:
    words = normalize(heard).split()
    if not words:
        return True
    said = set(normalize(spoken).split())
    return sum(word in said for word in words) / len(words) >= 0.6


def is_hold(text: str) -> bool:
    clean = normalize(text)
    if clean in HOLD_PHRASES:
        return True
    words = clean.split()
    return bool(words) and words != ["nao"] and len(words) <= 6 and all(w in {"nao", "espera", "espere", "calma", "perai", "pera"} for w in words)


GREETINGS = {"ei", "oi", "ola", "ok", "hey", "e ai", "fala", "bom dia", "boa tarde", "boa noite"}


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]+", " ", without_accents).strip()


def _contains(text: str, terms: set[str]) -> bool:
    padded = f" {text} "
    return any(f" {term} " in padded for term in terms)


class KeywordIntentClassifier:
    def __init__(self, max_words: int = 12):
        self.max_words = max_words

    def classify(self, text: str) -> Intent:
        clean = normalize(text)
        words = clean.split()
        if not words or len(words) > self.max_words:
            return Intent.NONE
        if not _contains(clean, ASSISTANT_NAMES):
            return Intent.NONE
        if len(words) <= 2 or _contains(clean, OPEN_WORDS) or _contains(clean, GREETINGS):
            return Intent.OPEN_APP
        return Intent.NONE
