"""
Comprehensive End-to-End Test Suite for AST-Guided Neuro-Symbolic RAG Modernization Workbench.
Verifies all project requirements:
- Source ingestion & Copybook parsing
- Structured AST extraction & Def-Use dependency graph
- ChromaDB vector embeddings & Multi-hop graph retrieval
- Java migration generation (Deterministic AST Synthesizer & Multi-provider LLMs)
- Structural AST constraint verification (javalang)
- Cross-platform semantic drift detection (Docker COBOL vs Host JVM)
- 3-Way empirical benchmark evaluation
"""

import unittest
from starlette.testclient import TestClient
from web_studio.backend.server import app


class TestNeuroSymbolicPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_01_samples_endpoint(self):
        """Verify sample programs are exposed and valid."""
        res = self.client.get("/api/samples")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("samples", data)
        sample_names = [s["filename"] for s in data["samples"]]
        self.assertIn("PAYROLL.cbl", sample_names)
        self.assertIn("BILLING.cbl", sample_names)

    def test_02_ast_parsing_and_graph(self):
        """Verify structured AST parsing, copybook resolution, and def-use dependencies."""
        with open("web_studio/samples/PAYROLL.cbl", "r") as f:
            code = f.read()

        res = self.client.post("/api/parse", json={
            "filename": "PAYROLL.cbl",
            "source_code": code
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()

        # AST Root & Divisions
        self.assertIn("ast", data)
        self.assertEqual(data["ast"]["type"], "Program")

        # Paragraph Chunks — PAYROLL.cbl has MAIN-PARAGRAPH, COMPUTE-GROSS, COMPUTE-TAX etc.
        self.assertIn("chunks", data)
        chunk_names = [c["name"] for c in data["chunks"]]
        self.assertGreater(len(chunk_names), 0, "Expected at least one chunk paragraph")
        # At least one paragraph must be present (exact names vary by parser)
        self.assertTrue(
            any(kw in " ".join(chunk_names).upper() for kw in
                ["MAIN", "GROSS", "COMPUTE", "TAX", "NET", "PAYROLL", "DISPLAY"]),
            f"No recognizable paragraph found in: {chunk_names}"
        )

        # Variables & hierarchy
        self.assertIn("variables", data)
        var_names = [v["name"] for v in data["variables"]]
        self.assertIn("WS-HOURS-WORKED", var_names)
        self.assertIn("WS-GROSS-PAY", var_names)
        self.assertIn("WS-NET-PAY", var_names)

        # Def-Use edges
        self.assertIn("edges", data)
        edge_types = set(e["type"] for e in data["edges"])
        self.assertIn("CALLS", edge_types)
        self.assertTrue(any(t in edge_types for t in ["READS", "WRITES", "DEPENDS_ON"]))


    def test_03_dual_memory_rag_search(self):
        """Verify ChromaDB neural vector search + bounded graph closure expansion."""
        res = self.client.post("/api/rag-search", json={
            "query": "calculate gross pay and overtime hours",
            "top_k": 2,
            "max_hops": 2,
            "target_language": "Java"
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()

        # AST Retrieval Closure
        self.assertIn("ast_retrieval", data)
        bundle = data["ast_retrieval"]["bundle"]
        self.assertGreater(len(bundle), 0)

        # Baselines
        self.assertIn("baseline_a", data)
        self.assertIn("baseline_b", data)

        # Generated Prompt
        self.assertIn("constructed_prompt", data)
        self.assertIn("ARCHITECTURAL REQUIREMENTS", data["constructed_prompt"])

    def test_04_java_code_generation(self):
        """Verify deterministic AST-to-Java synthesis with BigDecimal precision."""
        with open("web_studio/samples/PAYROLL.cbl", "r") as f:
            code = f.read()

        res = self.client.post("/api/generate", json={
            "filename": "PAYROLL.cbl",
            "source_code": code,
            "query": "migrate payroll calculation to Java",
            "provider": "deterministic",
            "model": "deterministic"
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("success") or data.get("status") == "success")
        java_code = data["generated_code"]
        self.assertIn("public class", java_code)
        self.assertIn("BigDecimal", java_code)
        self.assertIn("computeGross", java_code)

    def test_05_constraint_verification(self):
        """Verify javalang AST verification of method signatures and call graphs."""
        with open("web_studio/samples/PAYROLL.cbl", "r") as f:
            code = f.read()

        gen_res = self.client.post("/api/generate", json={
            "filename": "PAYROLL.cbl",
            "source_code": code,
            "query": "migrate payroll",
            "provider": "deterministic"
        })
        java_code = gen_res.json()["generated_code"]

        res = self.client.post("/api/verify-constraints", json={
            "filename": "PAYROLL.cbl",
            "source_code": code,
            "java_code": java_code
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "PASS")
        self.assertEqual(data["compliance_score"], 100.0)
        self.assertEqual(data["violation_count"], 0)

    def test_06_docker_cobol_vs_jvm_drift(self):
        """Verify live execution in Docker COBOL container and host JVM with zero drift."""
        with open("web_studio/samples/PAYROLL.cbl", "r") as f:
            code = f.read()

        gen_res = self.client.post("/api/generate", json={
            "filename": "PAYROLL.cbl",
            "source_code": code,
            "query": "migrate payroll",
            "provider": "deterministic"
        })
        java_code = gen_res.json()["generated_code"]

        res = self.client.post("/api/validate-drift", json={
            "filename": "PAYROLL.cbl",
            "source_code": code,
            "java_code": java_code
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "BEHAVIORALLY_EQUIVALENT")
        self.assertEqual(data["drift_score"], 0.0)
        self.assertTrue(len(data["token_comparisons"]) > 0)
        for comp in data["token_comparisons"]:
            self.assertTrue(comp["matched"], f"Token mismatch: {comp}")

    def test_07_empirical_benchmark_evaluation(self):
        """Verify 3-way evaluation comparing Baseline A, Baseline B, and Proposed System."""
        with open("web_studio/samples/BILLING.cbl", "r") as f:
            code = f.read()

        res = self.client.post("/api/evaluate-benchmarks", json={
            "filename": "BILLING.cbl",
            "source_code": code,
            "query": "compute final billing amount"
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        table = data["evaluation_table"]
        self.assertEqual(len(table), 3)

        base_a = next(r for r in table if "Baseline A" in r["name"])
        base_b = next(r for r in table if "Baseline B" in r["name"])
        proposed = next(r for r in table if r["is_proposed"])

        # Proposed System must outperform Baseline A on recall and missing dependency rate
        self.assertGreater(proposed["retrieval_recall"], base_a["retrieval_recall"])
        self.assertLess(proposed["missing_dep_rate"], base_a["missing_dep_rate"])
        self.assertEqual(proposed["missing_dep_rate"], 0.0)
        self.assertEqual(proposed["javac_compile_success_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()
