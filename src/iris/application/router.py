import logging
import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

log = logging.getLogger(__name__)


class DecisionClient(Protocol):
    def decide(self, state: str, questions: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]: ...


INTENTS = {
    "open_app": "Asks to open an application from the app list",
    "close_app": "Asks to close an application from the app list",
    "close_tab": "Asks to close the current browser tab",
    "play_pause": "Asks to pause or resume the video or music that is playing",
    "next": "Asks to skip to the next song or video",
    "volume_up": "Asks to turn the volume up",
    "volume_down": "Asks to turn the volume down",
    "hide": "Asks Iris to close, hide or minimize her own window",
    "other": "Anything else: questions, conversation, files, commands, YouTube, screen, several actions or unclear requests",
}

REPLIES = {
    "open_app": ["Abri o {app}.", "{app} aberto.", "Tá aberto."],
    "close_app": ["Fechei o {app}.", "{app} fechado."],
    "close_tab": ["Fechei a aba.", "Aba fechada."],
    "play_pause": ["Feito.", "Certo."],
    "next": ["Próxima.", "Pulei."],
    "volume_up": ["Aumentei o volume."],
    "volume_down": ["Abaixei o volume."],
    "hide": ["Até já.", "Tô por aqui."],
}


@dataclass(frozen=True)
class Route:
    kind: str
    reply: str = ""
    reason: str = ""


class FastRouter:
    def __init__(
        self,
        client: DecisionClient,
        apps: Callable[[], list[str]],
        actions: dict[str, Callable[..., Any]],
        confidence: float = 0.9,
    ):
        self.client = client
        self.apps = apps
        self.actions = actions
        self.confidence = confidence

    def questions(self) -> dict[str, dict[str, Any]]:
        apps = {name: f"The application {name}" for name in self.apps()[:200]}
        apps["none"] = "No application from this list is mentioned"
        return {
            "addressed": {
                "type": "noul",
                "instructions": (
                    "This transcribed speech is a request or remark directed at the voice assistant Iris, "
                    "not audio from a video or TV, not someone talking to another person, and not a meaningless fragment"
                ),
            },
            "unsafe": {
                "type": "noul",
                "instructions": "The request involves pornography or sexual content, racism, hate speech or slurs",
            },
            "intent": {"type": "choice", "instructions": "What the speaker wants Iris to do", "criteria": INTENTS},
            "app": {"type": "choice", "instructions": "Which application the request is about", "criteria": apps},
        }

    def route(self, text: str) -> Route:
        try:
            answers = self.client.decide(text, self.questions())
        except Exception as exc:
            log.warning("Fast router unavailable: %s", exc)
            return Route("llm", reason="router unavailable")
        addressed = float(answers["addressed"]["noul"])
        unsafe = float(answers["unsafe"]["noul"])
        intent = answers["intent"]["choice"]
        intent_confidence = float(answers["intent"].get("confidence", 0))
        app = answers["app"]["choice"]
        app_confidence = float(answers["app"].get("confidence", 0))
        log.info("Router: addressed=%.2f unsafe=%.2f intent=%s(%.2f) app=%s(%.2f)", addressed, unsafe, intent, intent_confidence, app, app_confidence)
        if unsafe >= 0.85:
            return Route("refuse", reason="unsafe")
        if addressed <= 0.1:
            return Route("ignore", reason="not addressed")
        if intent == "other" or intent_confidence < self.confidence or addressed < 0.7:
            return Route("llm", reason="needs the model")
        if intent in ("open_app", "close_app"):
            if app == "none" or app_confidence < self.confidence:
                return Route("llm", reason="app unclear")
            self.actions[intent](app)
            return Route("done", random.choice(REPLIES[intent]).format(app=app.title()))
        self.actions[intent]()
        return Route("done", random.choice(REPLIES[intent]))
