from iris.knowledge.sqlite_memory import SQLiteMemory


def test_remember_search_and_forget(tmp_path):
    memory = SQLiteMemory(tmp_path / "facts.db")
    fact = memory.remember("O email do Gabriel é gabriel@exemplo.com")
    memory.remember("O Gabriel mora em Osasco")

    assert any("gabriel@exemplo.com" in item for item in memory.search("ve meu email"))
    assert memory.forget(fact.id)
    assert not any("exemplo.com" in item for item in memory.search("email"))


def test_search_uses_full_text_when_memory_is_large(tmp_path):
    memory = SQLiteMemory(tmp_path / "facts.db", always_include_up_to=2)
    memory.remember("Servidor de testes é o 192.168.0.10")
    memory.remember("O usuário prefere respostas curtas")
    memory.remember("A cidade do usuário é Curitiba")

    found = memory.search("qual a cidade?")
    assert found == [item for item in found if "Curitiba" in item]
    assert len(found) == 1


def test_memory_persists_between_instances(tmp_path):
    SQLiteMemory(tmp_path / "facts.db").remember("Gosto de café")
    assert len(SQLiteMemory(tmp_path / "facts.db").all()) == 1
