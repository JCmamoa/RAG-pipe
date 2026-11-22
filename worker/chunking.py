"""Divisão de texto em chunks com overlap, preservando o número da página para citações.

Módulo puro (sem dependências externas): fácil de testar.
"""
from dataclasses import dataclass

_SEPARATORS = ("\n\n", "\n", ". ", "; ", ", ", " ")


@dataclass
class Chunk:
    index: int
    page: int
    content: str


def _atomize(text: str, size: int, seps: tuple[str, ...] = _SEPARATORS) -> list[str]:
    """Quebra recursivamente (parágrafo > linha > frase > palavra > corte seco), mantendo o separador."""
    if len(text) <= size:
        return [text]
    for i, sep in enumerate(seps):
        if sep in text:
            parts = text.split(sep)
            out: list[str] = []
            for j, part in enumerate(parts):
                piece = part + (sep if j < len(parts) - 1 else "")
                out.extend(_atomize(piece, size, seps[i + 1:]) if len(piece) > size else [piece])
            return out
    return [text[k:k + size] for k in range(0, len(text), size)]


def _tail(text: str, overlap: int) -> str:
    if overlap <= 0:
        return ""
    tail = text[-overlap:]
    space = tail.find(" ")
    return tail[space + 1:] if 0 <= space < len(tail) - 1 else tail  # não começa no meio de uma palavra


def split_text(text: str, size: int = 2400, overlap: int = 300) -> list[str]:
    assert 0 <= overlap < size, "overlap deve ser menor que size"
    chunks: list[str] = []
    current = ""
    for piece in _atomize(text, size):
        if current and len(current) + len(piece) > size:
            chunks.append(current.strip())
            seeded = _tail(current, overlap) + piece
            current = seeded if len(seeded) <= size else piece
        else:
            current += piece
    if current.strip():
        chunks.append(current.strip())
    return [c for c in chunks if c]


def chunk_pages(pages, size: int = 2400, overlap: int = 300, min_chars: int = 40) -> list[Chunk]:
    """`pages`: iterável de objetos com .number e .text. Cada chunk pertence a UMA página."""
    chunks: list[Chunk] = []
    for page in pages:
        for content in split_text(page.text, size, overlap):
            if len(content) >= min_chars:  # descarta ruído (número de página, cabeçalhos soltos)
                chunks.append(Chunk(index=len(chunks), page=page.number, content=content))
    return chunks
