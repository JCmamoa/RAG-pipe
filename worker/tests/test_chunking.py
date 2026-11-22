from dataclasses import dataclass

from chunking import chunk_pages, split_text


@dataclass
class P:
    number: int
    text: str


LONG = " ".join(f"Frase número {i} com algum conteúdo relevante para o teste." for i in range(400))


def test_short_text_is_single_chunk():
    assert split_text("texto curto", 100, 20) == ["texto curto"]


def test_chunks_respect_size_and_overlap():
    chunks = split_text(LONG, size=500, overlap=80)
    assert len(chunks) > 3
    assert all(0 < len(c) <= 500 for c in chunks)
    for prev, nxt in zip(chunks, chunks[1:]):
        assert prev[-40:].split(" ")[-2] in nxt[:200]  # há sobreposição real entre vizinhos


def test_no_text_is_lost():
    chunks = split_text(LONG, size=500, overlap=0)
    assert "".join(chunks).replace(" ", "").replace("\n", "") == LONG.replace(" ", "").replace("\n", "")


def test_hard_cut_when_no_separator():
    chunks = split_text("x" * 1000, size=300, overlap=0)
    assert [len(c) for c in chunks] == [300, 300, 300, 100]


def test_pages_are_preserved_and_indices_are_sequential():
    pages = [P(1, LONG[:1200]), P(2, "curto"), P(3, LONG[:900])]
    chunks = chunk_pages(pages, size=500, overlap=50, min_chars=40)
    assert [c.index for c in chunks] == list(range(len(chunks)))
    assert {c.page for c in chunks} == {1, 3}  # página 2 só tem ruído (< min_chars)
    assert chunks == sorted(chunks, key=lambda c: c.index)


def test_deterministic():
    assert split_text(LONG, 500, 80) == split_text(LONG, 500, 80)
