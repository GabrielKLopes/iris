import pytest

from iris.application.intent import KeywordIntentClassifier
from iris.domain.intents import Intent

classifier = KeywordIntentClassifier()


@pytest.mark.parametrize(
    "text",
    [
        "iris",
        "íris",
        "oi iris",
        "ei íris",
        "abre a iris",
        "chama a íris aí",
        "bom dia iris",
        "preciso da iris",
        "Íris, vem cá",
        "abre o assistente",
    ],
)
def test_natural_phrases_open_the_app(text):
    assert classifier.classify(text) is Intent.OPEN_APP


@pytest.mark.parametrize(
    "text",
    [
        "",
        "abre o navegador",
        "a íris dos olhos dela é verde clarinho",
        "o pipeline quebrou de novo",
        "vamos almoçar",
        "eu acho que a iris da loja cento e trinta e dois ainda não respondeu aquele email de ontem",
    ],
)
def test_other_speech_does_not_open_the_app(text):
    assert classifier.classify(text) is Intent.NONE


def test_split_wake_extracts_question():
    from iris.ui.web_window import split_wake

    assert split_wake("boa noite iris [unk]", "boa noite iris qual a temperatura") == (True, "qual a temperatura")
    assert split_wake("iris", "iris") == (True, "")
    assert split_wake("bom dia iris", "bom dia íris") == (True, "")
    assert split_wake("[unk]", "qualquer coisa") == (False, "")


def test_wake_reply_mirrors_salutation():
    from iris.ui.web_window import greeting, wake_reply

    assert wake_reply("boa noite iris", "Gabriel", 21) == "Boa noite, Gabriel! Em que posso ajudar?"
    assert wake_reply("iris", "Gabriel", 9) == "Oi, Gabriel. Pode falar."
    assert greeting(9) == "Bom dia" and greeting(15) == "Boa tarde" and greeting(23) == "Boa noite"


def test_hold_phrases_keep_listening():
    from iris.application.intent import is_hold

    assert is_hold("Espera.") and is_hold("Não, não, espere, espere.") and is_hold("Calma.")
    assert not is_hold("Não.") and not is_hold("Abre o Chrome")


def test_echo_of_own_answer_is_ignored():
    from iris.application.intent import is_echo

    assert is_echo("Boa noite, Gabriel, tudo certo!", "Boa noite, Gabriel! Tudo certo por aqui.")
    assert not is_echo("Para, abre o Chrome", "Boa noite, Gabriel! Tudo certo por aqui.")
