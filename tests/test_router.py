from iris.application.router import FastRouter


class FakeJev:
    def __init__(self, addressed=1.0, unsafe=0.0, intent="other", intent_confidence=0.95, app="none", app_confidence=0.95):
        self.answer = {
            "addressed": {"noul": addressed},
            "unsafe": {"noul": unsafe},
            "intent": {"choice": intent, "confidence": intent_confidence},
            "app": {"choice": app, "confidence": app_confidence},
        }
        self.calls = []

    def decide(self, state, questions):
        self.calls.append((state, questions))
        return self.answer


def build(jev):
    done = []
    actions = {name: (lambda *args, name=name: done.append((name, args))) for name in
               ["open_app", "close_app", "close_tab", "play_pause", "next", "volume_up", "volume_down", "hide"]}
    return FastRouter(jev, lambda: ["google chrome", "spotify"], actions), done


def test_runs_simple_commands_without_the_model():
    router, done = build(FakeJev(intent="open_app", app="spotify"))
    route = router.route("abre o spotify")
    assert route.kind == "done" and route.reply
    assert done == [("open_app", ("spotify",))]


def test_sends_everything_else_to_the_model():
    router, done = build(FakeJev(intent="other"))
    assert router.route("como funciona um pod no kubernetes?").kind == "llm"
    router, done = build(FakeJev(intent="open_app", app="none"))
    assert router.route("abre aquele programa").kind == "llm" and not done


def test_ignores_and_refuses():
    router, _ = build(FakeJev(addressed=0.02))
    assert router.route("e aí galera, bem-vindos ao canal").kind == "ignore"
    router, _ = build(FakeJev(unsafe=0.97))
    assert router.route("algo proibido").kind == "refuse"


def test_falls_back_to_the_model_when_jev_fails():
    class Broken:
        def decide(self, state, questions):
            raise TimeoutError("slow")

    router, done = build(Broken())
    assert router.route("abre o chrome").kind == "llm" and not done


def test_questions_list_the_installed_apps():
    jev = FakeJev()
    router, _ = build(jev)
    router.route("oi")
    criteria = jev.calls[0][1]["app"]["criteria"]
    assert {"google chrome", "spotify", "none"} == set(criteria)
