"""HYBRID chunking strategy: semantic split first, fixed split within large chunks."""
import re
from dataclasses import dataclass
from enum import Enum
from src.metadata.schema import DocumentMetadata

APPROX_TOKENS_PER_WORD = 1.33
MAX_TOKENS = 600
OVERLAP_TOKENS = 64

_SECTION_HEADER = re.compile(
    r'^(?:#{1,3}\s.+|(?:\d+\.)+\d*\s+[A-Z].+|[A-Z][A-Z\s]{4,}:)', re.MULTILINE
)


class ChunkStrategy(Enum):
    FIXED = "fixed"
    SEMANTIC = "semantic"
    HYBRID = "hybrid"


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    text: str
    token_count: int
    chunk_index: int
    section_header: str | None
    metadata: DocumentMetadata


def _approx_tokens(text: str) -> int:
    return int(len(text.split()) * APPROX_TOKENS_PER_WORD)


def _fixed_chunks(text: str, max_tokens: int = MAX_TOKENS, overlap: int = OVERLAP_TOKENS) -> list[str]:
    words = text.split()
    max_words = int(max_tokens / APPROX_TOKENS_PER_WORD)
    overlap_words = int(overlap / APPROX_TOKENS_PER_WORD)
    chunks = []
    start = 0
    while start < len(words):
        end = min(start + max_words, len(words))
        chunks.append(" ".join(words[start:end]))
        start += max_words - overlap_words
    return [c for c in chunks if c.strip()]


def _semantic_sections(text: str) -> list[tuple[str | None, str]]:
    """Split on section headers, return (header, body) pairs."""
    matches = list(_SECTION_HEADER.finditer(text))
    if not matches:
        return [(None, text)]

    sections: list[tuple[str | None, str]] = []
    for i, match in enumerate(matches):
        header = match.group(0).strip()
        body_start = match.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()
        if body:
            sections.append((header, body))

    # Capture any content before first header
    preamble = text[:matches[0].start()].strip() if matches else ""
    if preamble:
        sections.insert(0, (None, preamble))

    return sections


def chunk_document(
    text: str,
    meta: DocumentMetadata,
    strategy: ChunkStrategy = ChunkStrategy.HYBRID,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    index = 0

    if strategy == ChunkStrategy.FIXED:
        for raw in _fixed_chunks(text):
            chunks.append(_make_chunk(meta, raw, index, None))
            index += 1

    elif strategy == ChunkStrategy.SEMANTIC:
        for header, body in _semantic_sections(text):
            chunks.append(_make_chunk(meta, body, index, header))
            index += 1

    else:  # HYBRID
        for header, body in _semantic_sections(text):
            if _approx_tokens(body) > MAX_TOKENS:
                # Sub-chunk large sections with fixed strategy + overlap
                for raw in _fixed_chunks(body):
                    chunks.append(_make_chunk(meta, raw, index, header))
                    index += 1
            else:
                chunks.append(_make_chunk(meta, body, index, header))
                index += 1

    return chunks


def _make_chunk(meta: DocumentMetadata, text: str, index: int, header: str | None) -> Chunk:
    return Chunk(
        chunk_id=f"{meta.doc_id}::{index:04d}",
        doc_id=meta.doc_id,
        text=text.strip(),
        token_count=_approx_tokens(text),
        chunk_index=index,
        section_header=header,
        metadata=meta,
    )
