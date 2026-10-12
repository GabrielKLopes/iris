import pytest

from iris.application.fuzzy import TranscriptCorrector, default_vocabulary, names_in, phonetic

FACTS = ["Kauã Miguel Dev é um canal de programação no YouTube que o Gabriel acompanha (@kc_1t)."]


@pytest.fixture
def corrector():
    return TranscriptCorrector(default_vocabulary(lambda: FACTS))


def test_phonetic_merges_similar_sounds():
    assert phonetic("Kauã") == phonetic("caua")
    assert phonetic("Bevy") == phonetic("vevi")


def test_names_come_from_memory_facts():
    assert names_in(FACTS) == ["Kauã Miguel Dev"]


@pytest.mark.parametrize(
    "heard",
    [
        "pesquise caua Miguel David no YouTube",
        "abre o canal do Caoi, Miguel Dave",
        "abre o YouTube do Kao-An, Miguel Dave",
        "o canal do Caê é Miguel Davey",
        "pesquise KW Miguel Dev",
    ],
)
def test_fixes_misheard_channel_name(corrector, heard):
    fixed, corrections = corrector.correct(heard)
    assert "Kauã Miguel Dev" in fixed and corrections


def test_fixes_app_and_tech_names(corrector):
    assert corrector.correct("roda o cubectl get pods")[0] == "roda o kubectl get pods"
    assert corrector.correct("abre o visual estúdio code")[0] == "abre o Visual Studio Code"


@pytest.mark.parametrize(
    "sentence",
    [
        "Boa noite, Iris, tudo bom?",
        "O Miguel Silva mandou mensagem",
        "abre o google e pesquisa receita",
        "Iris, abre o vídeo no YouTube, por favor.",
    ],
)
def test_leaves_normal_sentences_alone(corrector, sentence):
    assert corrector.correct(sentence)[1] == []
