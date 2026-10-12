import re
import unicodedata
from dataclasses import dataclass

LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})

SEXUAL_DOMAINS = (
    "pornhub", "xvideos", "xnxx", "redtube", "youporn", "xhamster", "brazzers", "onlyfans", "chaturbate",
    "spankbang", "porntube", "privacy.com.br", "camsoda", "stripchat", "bongacams", "rule34", "nhentai",
)
SEXUAL_TERMS = (
    "porn", "porno", "pornografia", "pornografico", "pornografica", "hentai", "nudes", "nude", "nudez",
    "putaria", "sexo explicito", "video de sexo", "videos de sexo", "filme de sexo", "filme adulto", "filmes adultos",
    "conteudo adulto", "site adulto", "sites adultos", "xxx", "camgirl", "striptease", "erotico", "erotica",
    "buceta", "punheta", "boquete", "transar", "transando", "sexo oral", "sexo anal", "mulher pelada",
    "foto intima", "fotos intimas", "sem roupa", "+18", "18+", "pelado", "peladas", "conteudo sexual", "masturbacao", "masturbar",
)
HATE_TERMS = (
    "crioulo", "macaco preto", "seu macaco", "preto macaco", "neguinha safada", "volta pra senzala", "lugar de preto",
    "raca inferior", "racas inferiores", "supremacia branca", "heil hitler", "sieg heil", "odeio negros", "odeio pretos",
    "odeio gays", "odeio judeus", "odeio nordestinos", "odeio mulheres", "odeio travestis", "morte aos gays",
    "viado", "traveco", "sapatao", "baiano burro", "paraiba burro", "judeu sujo", "macumbeiro", "retardado",
    "piada racista", "piadas racistas", "piada de preto", "piadas de preto", "piada homofobica",
)

REFUSAL = "Isso eu não faço. Posso te ajudar com outra coisa?"


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower().translate(LEET))
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9.+ ]+", " ", plain)).strip()


def _has_term(text: str, terms: tuple[str, ...]) -> str | None:
    padded = f" {text} "
    for term in terms:
        if f" {term} " in padded or (len(term) >= 5 and f" {term}s " in padded):
            return term
    return None


@dataclass(frozen=True)
class Violation:
    category: str
    match: str


class ContentPolicy:
    def check(self, text: str) -> Violation | None:
        if not text:
            return None
        clean = normalize(text)
        compact = clean.replace(" ", "")
        for domain in SEXUAL_DOMAINS:
            if domain in compact:
                return Violation("sexual", domain)
        if term := _has_term(clean, SEXUAL_TERMS):
            return Violation("sexual", term)
        if term := _has_term(clean, HATE_TERMS):
            return Violation("hate", term)
        return None
