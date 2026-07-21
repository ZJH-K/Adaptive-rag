# Notices

This project references RAG architecture and implementation ideas from
[GU-Cryptography/anykb](https://github.com/GU-Cryptography/anykb).

No AnyKB source code has been copied as part of the initial project setup.
Any future source adaptation must first confirm the upstream license and retain
all attribution required by that license.

For the document parser work, the AnyKB parser directory was reviewed at commit
`aa7c02e8d70a383c2535cd31109a43e11aa303bd`. Only its high-level minimal-cleanup
and parser-responsibility ideas were considered; the implementation in this
project was written independently for the local schemas and page-preservation
requirements.

As checked on 2026-07-22, the AnyKB README labels the project as MIT, but the
repository contains no root LICENSE file and GitHub exposes no detected license
metadata. No AnyKB source was copied in this task.

The baseline recursive chunker also references AnyKB's documented hierarchy of
paragraph, sentence, and character fallbacks. Its implementation, overlap
windowing, stable identifiers, schemas, and tests were independently written for
this project; no AnyKB source code was copied.
