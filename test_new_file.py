"""
End-to-end test: upload a new COBOL file and verify parser → LLM → verifier pipeline works.
"""
import sys
sys.path.insert(0, '.')

def test_new_file_pipeline():
    from web_studio.backend.cobol_ast_parser import CobolASTParser
    from web_studio.backend.llm_engine import LLMEngine
    from web_studio.backend.constraint_verifier import StructuralConstraintVerifier

    cobol = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INVENTORY.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-ITEM-CODE   PIC X(10) VALUE SPACES.
       01 WS-QUANTITY    PIC 9(5)  VALUE 0.
       01 WS-UNIT-PRICE  PIC 9(7)V99 VALUE 0.
       01 WS-TOTAL-VALUE PIC 9(9)V99 VALUE 0.
       01 WS-TAX-RATE    PIC 9(3)V99 VALUE 0.18.
       01 WS-TAX-AMOUNT  PIC 9(7)V99 VALUE 0.
       01 WS-GRAND-TOTAL PIC 9(9)V99 VALUE 0.
       01 WS-DISCOUNT    PIC 9(5)V99 VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM INIT-PARA.
           PERFORM CALC-VALUE-PARA.
           PERFORM CALC-TAX-PARA.
           PERFORM APPLY-DISCOUNT-PARA.
           PERFORM DISPLAY-PARA.
           STOP RUN.
       INIT-PARA.
           MOVE 'ITEM-001' TO WS-ITEM-CODE.
           MOVE 100 TO WS-QUANTITY.
           MOVE 25 TO WS-UNIT-PRICE.
           MOVE 0 TO WS-TOTAL-VALUE WS-TAX-AMOUNT WS-GRAND-TOTAL.
       CALC-VALUE-PARA.
           MULTIPLY WS-QUANTITY BY WS-UNIT-PRICE
               GIVING WS-TOTAL-VALUE.
       CALC-TAX-PARA.
           MULTIPLY WS-TOTAL-VALUE BY WS-TAX-RATE
               GIVING WS-TAX-AMOUNT.
       APPLY-DISCOUNT-PARA.
           IF WS-TOTAL-VALUE > 1000
               COMPUTE WS-DISCOUNT = WS-TOTAL-VALUE * 0.05
           END-IF.
           SUBTRACT WS-DISCOUNT FROM WS-TOTAL-VALUE
               GIVING WS-GRAND-TOTAL.
           ADD WS-TAX-AMOUNT TO WS-GRAND-TOTAL.
       DISPLAY-PARA.
           DISPLAY 'Item: ' WS-ITEM-CODE.
           DISPLAY 'Total Value: ' WS-TOTAL-VALUE.
           DISPLAY 'Tax Amount: ' WS-TAX-AMOUNT.
           DISPLAY 'Grand Total: ' WS-GRAND-TOTAL.
    """

    print("=" * 60)
    print("TEST: New COBOL File → Parser → LLM Synthesizer → Verifier")
    print("=" * 60)

    # ── 1. Parse ────────────────────────────────────────────────────
    p = CobolASTParser()
    parsed = p.parse_cobol_source("INVENTORY.cbl", cobol)
    print(f"\n[1] PARSER")
    print(f"    program_id : {parsed['program_id']}")
    print(f"    chunks     : {len(parsed['chunks'])}")
    print(f"    variables  : {len(parsed['variables'])}")
    print(f"    edges      : {len(parsed['edges'])}")
    print(f"    diagnostics: {parsed['diagnostics']}")
    for c in parsed['chunks']:
        print(f"       chunk '{c['name']}' → {len(c['statements'])} stmts")
        for s in c['statements']:
            print(f"           [{s['stmt_type']}] {s['text'][:60]}")

    assert parsed['program_id'] == 'INVENTORY', "program_id mismatch"
    assert len(parsed['chunks']) >= 5, f"Expected ≥5 chunks, got {len(parsed['chunks'])}"
    assert len(parsed['variables']) >= 7, f"Expected ≥7 variables, got {len(parsed['variables'])}"
    print("    ✓ Parser assertions passed")

    # ── 2. Synthesize Java ──────────────────────────────────────────
    llm = LLMEngine()
    bundle = [
        {
            "id": f"INVENTORY::{c['name']}",
            "type": "chunk",
            "source": c.get("source", ""),
            "score": 1.0,
            "reason": "test",
            "statements": c.get("statements", [])
        }
        for c in parsed['chunks']
    ]
    java_code = llm.synthesize_java_from_ast(
        program_id=parsed['program_id'],
        bundle=bundle,
        constraints=[],
        all_variables=parsed['variables']
    )
    print(f"\n[2] JAVA SYNTHESIZER")
    print(f"    Generated {len(java_code)} bytes of Java")

    assert "class INVENTORY" in java_code, "Missing class declaration"
    assert "BigDecimal" in java_code, "Missing BigDecimal for decimal fields"
    assert "wsTotalValue" in java_code or "WsTotalValue" in java_code.replace(' ', ''), "Missing WS-TOTAL-VALUE field"
    assert "mainPara" in java_code or "main" in java_code.lower(), "Missing main method"
    print("    ✓ Synthesizer assertions passed")
    print("\n    --- GENERATED JAVA (first 1000 chars) ---")
    print(java_code[:1000])

    # ── 3. Constraint Verifier ──────────────────────────────────────
    verifier = StructuralConstraintVerifier()
    expected_chunks = [c['name'] for c in parsed['chunks']]
    result = verifier.verify_java_code(
        java_code=java_code,
        expected_chunks=expected_chunks,
        expected_call_edges=[],
        expected_variables=[]
    )
    print(f"\n[3] CONSTRAINT VERIFIER")
    print(f"    status           : {result['status']}")
    print(f"    compliance_score : {result['compliance_score']}%")
    print(f"    passed_checks    : {result['passed_checks']}/{result['total_checks']}")
    if result.get('ast_parse_warning'):
        print(f"    WARNING: {result['ast_parse_warning']}")
    for v in result['violations']:
        print(f"    VIOLATION: {v['message']}")
    for vc in result['verified_constraints']:
        print(f"    ✓ {vc}")

    assert result['compliance_score'] >= 50.0, \
        f"Compliance score too low: {result['compliance_score']}%"
    print("    ✓ Verifier assertions passed")

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED ✓")
    print("=" * 60)


if __name__ == "__main__":
    test_new_file_pipeline()
