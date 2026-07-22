"""Generate the project-authored multi-page ingestion recovery PDF fixture."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = PROJECT_ROOT / "knowledge" / "pdf" / "ingestion_recovery_manual.pdf"


def _footer(canvas, document) -> None:
    """Draw a stable title and one-based page number on every page."""
    canvas.saveState()
    canvas.setFont("Helvetica", 9)
    canvas.setFillColor(HexColor("#52606D"))
    canvas.drawString(0.75 * inch, 0.5 * inch, "Adaptive RAG - Ingestion Recovery")
    canvas.drawRightString(
        7.75 * inch,
        0.5 * inch,
        f"Page {document.page}",
    )
    canvas.restoreState()


def generate(output_path: Path = OUTPUT_PATH) -> Path:
    """Write a deterministic three-page, text-extractable PDF fixture."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "FixtureTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=22,
        leading=27,
        textColor=HexColor("#17324D"),
        spaceAfter=18,
    )
    heading = ParagraphStyle(
        "FixtureHeading",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=15,
        leading=19,
        textColor=HexColor("#0B7285"),
        spaceBefore=10,
        spaceAfter=10,
    )
    body = ParagraphStyle(
        "FixtureBody",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=11,
        leading=16,
        textColor=HexColor("#243B53"),
        spaceAfter=10,
    )
    code = ParagraphStyle(
        "FixtureCode",
        parent=body,
        fontName="Courier",
        backColor=HexColor("#F0F4F8"),
        borderPadding=8,
        leftIndent=8,
        rightIndent=8,
        spaceBefore=6,
        spaceAfter=14,
    )

    story = [
        Paragraph("Ingestion Recovery Manual", title),
        Paragraph("Page 1 - Failure detection", heading),
        Paragraph(
            "The ingestion pipeline parses and chunks a complete document before "
            "requesting embeddings. Chroma is updated only after every vector in "
            "the document batch has been validated.",
            body,
        ),
        Paragraph(
            "If an embedding request fails, the pipeline reports the upstream "
            "error and performs no partial write. Operators should record the "
            "document ID, failed batch index, and source filename before retrying.",
            body,
        ),
        Paragraph("failure_state = EMBEDDING_FAILED", code),
        Paragraph(
            "Recovery continues on the next page with a stable retry token. The "
            "document must not be edited between failure detection and retry, "
            "because a content change produces a different document ID.",
            body,
        ),
        PageBreak(),
        Paragraph("Ingestion Recovery Manual", title),
        Paragraph("Page 2 - Retry token", heading),
        Paragraph(
            "Create the recovery marker INGEST_RETRY_TOKEN from the original "
            "document ID and failed batch index. Reuse this token for every retry "
            "of the same failed ingestion attempt.",
            body,
        ),
        Paragraph("INGEST_RETRY_TOKEN = document_id + ':' + batch_index", code),
        Paragraph(
            "A retry must use the same embedding model, vector dimension, chunk "
            "strategy, chunk size, and overlap. Changing these parameters starts "
            "a new ingestion representation rather than recovering the failed one.",
            body,
        ),
        Paragraph(
            "After all vectors are returned, the pipeline may upsert the complete "
            "chunk list. Verification continues on page 3 and must be completed "
            "before the recovery marker is cleared.",
            body,
        ),
        PageBreak(),
        Paragraph("Ingestion Recovery Manual", title),
        Paragraph("Page 3 - Verification", heading),
        Paragraph(
            "Compare the stored chunk count with the chunk count returned by the "
            "ingestion result. The values must match for the recovered document.",
            body,
        ),
        Paragraph(
            "Inspect at least one stored chunk from every PDF page. Each chunk must "
            "retain its source filename, source page metadata, content hash, and "
            "the chunk strategy used during recovery.",
            body,
        ),
        Paragraph(
            "Finally, run a dense retrieval query for INGEST_RETRY_TOKEN. Recovery "
            "is complete only when the relevant page 2 chunk is returned and the "
            "stored chunk count plus source page metadata checks both pass.",
            body,
        ),
        Paragraph("verification_status = RECOVERY_COMPLETE", code),
    ]

    document = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        rightMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        topMargin=0.7 * inch,
        bottomMargin=0.75 * inch,
        title="Ingestion Recovery Manual",
        author="Adaptive RAG Project",
        subject="Project-authored digital PDF fixture",
        invariant=1,
    )
    document.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return output_path


if __name__ == "__main__":
    print(generate())
