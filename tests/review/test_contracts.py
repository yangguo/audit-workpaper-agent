from review.contracts import (
    CellEvidence,
    EvidenceGraph,
    InputFile,
    ReviewManifest,
    SheetEvidence,
)


def test_review_manifest_serializes_optional_inputs():
    manifest = ReviewManifest(
        review_id="a" * 32,
        source="wp.xlsx",
        requested_sheets=["PE-6"],
        inputs=[
            InputFile(
                role="workpaper",
                path="assets/uploads/wp.xlsx",
                filename="wp.xlsx",
                sha256="b" * 64,
                size=12,
            )
        ],
    )

    payload = manifest.model_dump(mode="json")

    assert payload["schema_version"] == "2.0"
    assert payload["inputs"][0]["role"] == "workpaper"
    assert payload["requested_sheets"] == ["PE-6"]


def test_evidence_graph_serializes_captured_cell():
    cell = CellEvidence(
        evidence_id="ev:1",
        sheet_name="PE-6",
        coordinate="A1",
        value="标准审计程序",
        formula=None,
        data_type="s",
        content_hash="c" * 64,
    )
    graph = EvidenceGraph(
        source_sha256="d" * 64,
        sheets=[SheetEvidence(name="PE-6", sheet_hash="e" * 64, cells=[cell])],
        captured_cell_count=1,
        omitted_cell_count=0,
        capture_status="complete",
    )

    assert graph.model_dump(mode="json")["sheets"][0]["cells"][0]["evidence_id"] == "ev:1"
