from pathlib import Path

import numpy as np

from iris.knowledge.library import SQLiteLibrary, chunks

CONCEPTS = {"carro": 0, "automóvel": 0, "veículo": 0, "pão": 1, "queijo": 1, "receita": 1, "docker": 2, "compose": 2, "container": 2}


class ConceptEmbedder:
    dimensions = 4

    def embed(self, texts):
        vectors = np.zeros((len(texts), self.dimensions), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in text.lower().replace("?", " ").replace(".", " ").split():
                if word in CONCEPTS:
                    vectors[row, CONCEPTS[word]] += 1
            vectors[row, 3] += 0.01
        return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


def library(tmp_path: Path, url=None, embedder=None) -> SQLiteLibrary:
    return SQLiteLibrary(tmp_path / "library.db", lambda raw: Path(raw), lambda: url, embedder)


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_learns_a_document_and_finds_it_ignoring_accents(tmp_path):
    doc = write(tmp_path, "keycloak.md", "Configuração do Keycloak\n\nO realm principal se chama empresa e usa LDAP para os usuários.")
    lib = library(tmp_path)

    assert "1 excerpts" in lib.learn(str(doc))
    found = lib.search("qual realm o keycloak usa? configuracao")
    assert "realm principal" in found and "keycloak" in found


def test_meaning_search_finds_synonyms_keyword_search_misses(tmp_path):
    lib = library(tmp_path, embedder=ConceptEmbedder())
    assert lib.vectors
    lib.learn(str(write(tmp_path, "manual.txt", "O automóvel precisa de revisão a cada dez mil quilômetros.")))
    lib.learn(str(write(tmp_path, "receita.txt", "Pão de queijo leva polvilho azedo.")))

    assert "automóvel" in lib.search("quando levar o carro")

    keyword_only = tmp_path / "keyword"
    keyword_only.mkdir()
    plain = library(keyword_only)
    plain.learn(str(tmp_path / "manual.txt"))
    assert "automóvel" not in plain.search("quando levar o carro")


def test_hybrid_search_still_ranks_exact_terms(tmp_path):
    lib = library(tmp_path, embedder=ConceptEmbedder())
    lib.learn(str(write(tmp_path, "a.txt", "Use depends_on com condition service_healthy no compose.")))
    lib.learn(str(write(tmp_path, "b.txt", "O docker roda containers isolados.")))

    first = lib.search("depends_on service_healthy").split("\n\n")[0]
    assert "service_healthy" in first


def test_learning_again_replaces_the_old_excerpts_and_vectors(tmp_path):
    lib = library(tmp_path, embedder=ConceptEmbedder())
    doc = write(tmp_path, "notas.txt", "versão antiga do texto sobre carro")
    lib.learn(str(doc))
    doc.write_text("versão nova do texto sobre carro", encoding="utf-8")
    lib.learn(str(doc))

    found = lib.search("carro")
    assert "nova" in found and "antiga" not in found
    assert lib.db.execute("SELECT count(*) FROM passage_vectors").fetchone()[0] == 1


def test_forget_removes_source(tmp_path):
    lib = library(tmp_path, embedder=ConceptEmbedder())
    doc = write(tmp_path, "notas.txt", "texto sobre carro")
    lib.learn(str(doc))

    assert lib.forget(str(doc))
    assert lib.search("carro") == "Nothing in the library about this"
    assert lib.sources() == []


def test_learns_a_whole_folder(tmp_path):
    folder = tmp_path / "docs"
    (folder / "node_modules").mkdir(parents=True)
    write(folder, "um.md", "Primeiro documento sobre docker.")
    write(folder, "dois.txt", "Segundo documento sobre receita.")
    write(folder / "node_modules", "lixo.md", "não deve entrar")

    assert "Saved 2 documents" in library(tmp_path).learn(str(folder))


def test_index_missing_backfills_old_passages(tmp_path):
    library(tmp_path).learn(str(write(tmp_path, "velho.txt", "texto antigo sobre carro")))
    upgraded = library(tmp_path, embedder=ConceptEmbedder())

    assert upgraded.index_missing() == 1
    assert "antigo" in upgraded.search("automóvel")


def test_current_page_without_browser_asks_for_the_link(tmp_path):
    assert "Ask the user for the link" in library(tmp_path).learn("current_page")


def test_unknown_topic(tmp_path):
    assert library(tmp_path).search("receita de bolo") == "Nothing in the library about this"


def test_chunks_keep_code_blocks_whole():
    code = "```yaml\nservices:\n  db:\n    image: postgres\n```"
    parts = chunks("a" * 800 + "\n\n" + code + "\n\n" + "b" * 300, size=900)
    assert any(code in part for part in parts)


def test_chunks_overlap_between_parts():
    parts = chunks("primeira parte " * 60 + "\n\n" + "segunda parte " * 60, size=900)
    assert len(parts) >= 2 and "primeira parte" in parts[1][:60]
