# Context and Citation Guide

The context builder converts ranked retrieval hits into a bounded prompt payload.
It preserves retrieval order while removing repeated evidence and exposing only
the metadata required for answer citations.

## Context budget

`ContextBuilder(max_chars=...)` measures the final formatted context in
characters. The budget includes source headers such as `[S1]`, body text, and
blank-line separators. When one chunk is too long, the builder retains the
leading portion that fits and stops before lower-ranked chunks.

### Duplicate evidence

Hits are deduplicated first by `chunk_id` and then by a non-empty `content_hash`.
The first ranked occurrence wins. Duplicate removal never changes the relative
order of the remaining hits.

## Citation metadata

Each included block receives a stable identifier: `[S1]`, `[S2]`, and so on.
The `sources` list and `used_chunk_ids` follow exactly the same order.

### PDF citation

A PDF source contains the filename, parsed page number, and chunk ID. Page numbers
must come from parser metadata and must never be guessed from retrieval rank.

### Markdown citation

A Markdown source contains the filename, section, heading path, and chunk ID. If
`section` is absent, the full `heading_path` is used as the display location.

## Missing evidence

When retrieval returns no usable context, the RAG service returns a fixed message
that no sufficient document evidence was found. It does not call the LLM with an
empty context or invent a citation.

## Missing metadata

Missing page or section metadata degrades to the source filename. The builder does
not raise `KeyError` and does not infer locations from the chunk body.
