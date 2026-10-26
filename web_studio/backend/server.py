"""
FastAPI Server for AST-Guided Neuro-Symbolic RAG & Enterprise Code Migration Studio
Exposes REST endpoints for:
- AST Parsing & Structural Dependency Extraction
- Dual-Memory Hybrid Retrieval (ChromaDB + NetworkX)
- LLM-Based Code Migration (Ollama / Cloud APIs / Synthesizer)
- Post-Generation Structural Constraint Verification (javalang AST)
- Behavioral Validation & Semantic Drift Detection (COBOL vs JVM execution)
- 3-Way Research Benchmark Evaluation
"""

import os
import shutil
import tempfile
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from web_studio.backend.cobol_ast_parser import CobolASTParser
from web_studio.backend.neuro_symbolic_rag import DualMemoryRAG
from web_studio.backend.llm_engine import LLMEngine
from web_studio.backend.constraint_verifier import StructuralConstraintVerifier
from web_studio.backend.drift_detector import SemanticDriftDetector
from web_studio.backend.research_evaluator import ResearchEvaluator

app = FastAPI(title="AST-Guided Neuro-Symbolic Migration Studio API")

# Prevent browser from serving stale frontend scripts and styles
@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path.lower()
    if path.endswith((".html", ".js", ".css")) or path == "/":
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# Enable CORS for local web interface
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Project directory paths
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SAMPLES_DIR = os.path.join(BASE_DIR, "web_studio", "samples")
FRONTEND_DIR = os.path.join(BASE_DIR, "web_studio", "frontend")
UPLOADS_DIR = os.path.join(BASE_DIR, "web_studio", "uploads")
GENERATED_JAVA_DIR = os.path.join(BASE_DIR, "web_studio", "generated_java")

os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(GENERATED_JAVA_DIR, exist_ok=True)

# Shared Core Engines
parser = CobolASTParser()
rag_engine = DualMemoryRAG()
llm_engine = LLMEngine()
verifier = StructuralConstraintVerifier()
drift_detector = SemanticDriftDetector()
research_evaluator = ResearchEvaluator(parser, rag_engine, llm_engine, verifier, drift_detector)

# Shared Runtime State
current_indexed_data: Dict[str, Any] = {}
current_source_code: str = ""
current_filename: str = ""
current_retrieval_result: Dict[str, Any] = {}
current_generated_java: str = ""

# Request Models
class ParseRequest(BaseModel):
    filename: str
    source_code: str

class RagQueryRequest(BaseModel):
    query: str
    top_k: int = 2
    max_hops: int = 2
    target_language: str = "Java"

class GenerateRequest(BaseModel):
    provider: str = "auto"
    model: Optional[str] = None
    api_key: Optional[str] = None
    target_language: str = "Java"
    query: Optional[str] = None
    filename: Optional[str] = None
    source_code: Optional[str] = None

class VerifyRequest(BaseModel):
    filename: Optional[str] = None
    source_code: Optional[str] = None
    java_code: Optional[str] = None

class DriftRequest(BaseModel):
    filename: Optional[str] = None
    source_code: Optional[str] = None
    java_code: Optional[str] = None

class CompileRequest(BaseModel):
    filename: str
    source_code: str

class BenchmarkRequest(BaseModel):
    filename: Optional[str] = None
    source_code: Optional[str] = None
    query: Optional[str] = None


def _ensure_parsed(source_code: str, filename: str) -> Dict[str, Any]:
    """
    Re-parse if the source has changed or no parsed data exists.
    Always returns a valid parsed data dict.
    """
    global current_indexed_data, current_source_code, current_filename, current_retrieval_result, current_generated_java

    if source_code and source_code != current_source_code:
        current_filename = filename or current_filename or "PROGRAM.cbl"
        current_source_code = source_code
        current_indexed_data = parser.parse_cobol_source(current_filename, current_source_code)
        rag_engine.index_parsed_code(current_indexed_data)
        current_retrieval_result = {}   # invalidate stale retrieval
        current_generated_java = ""    # invalidate stale java
    return current_indexed_data


def _ensure_retrieval(query: str = "migrate cobol program to java") -> Dict[str, Any]:
    """Run RAG retrieval if not cached or was invalidated."""
    global current_retrieval_result
    if not current_retrieval_result:
        if not current_indexed_data:
            raise HTTPException(status_code=400, detail="No COBOL code parsed yet.")
        current_retrieval_result = rag_engine.retrieve(
            query=query,
            top_k=2,
            max_hops=2
        )
    return current_retrieval_result


def _synthesize_java_safe(indexed_data: Dict[str, Any]) -> str:
    """
    Synthesize Java from parsed AST data with a correct call to synthesize_java_from_ast.
    Uses the full symbol table and all retrieved chunks.
    """
    program_id = indexed_data.get("program_id", "PROGRAM")
    all_variables = indexed_data.get("variables", [])
    chunks = indexed_data.get("chunks", [])

    # Build a minimal bundle from all parsed chunks (same shape as retrieval bundle)
    bundle = [
        {
            "id": c["id"],
            "type": "chunk",
            "source": c.get("source", ""),
            "score": 1.0,
            "reason": "synthesizer_direct",
            "statements": c.get("statements", [])
        }
        for c in chunks
    ]

    return llm_engine.synthesize_java_from_ast(
        program_id=program_id,
        bundle=bundle,
        constraints=[],
        all_variables=all_variables
    )


@app.get("/api/samples")
def get_samples():
    """Returns preloaded sample enterprise COBOL programs."""
    samples = []
    if os.path.exists(SAMPLES_DIR):
        for f in os.listdir(SAMPLES_DIR):
            if f.endswith((".cbl", ".cob")):
                path = os.path.join(SAMPLES_DIR, f)
                with open(path, "r", encoding="utf-8", errors="ignore") as fp:
                    content = fp.read()
                desc = "Enterprise billing, discount & tax system" if "BILLING" in f else (
                    "Enterprise payroll calculation & deductions" if "PAYROLL" in f else "Hello World baseline"
                )
                samples.append({
                    "filename": f,
                    "content": content,
                    "description": desc
                })
    return {"samples": samples}

@app.post("/api/upload")
async def upload_files(files: List[UploadFile] = File(...)):
    """Uploads one or more COBOL files or folder with path traversal protection."""
    saved_files = []
    uploads_root = os.path.abspath(UPLOADS_DIR)

    for f in files:
        raw_name = f.filename or "uploaded.cbl"
        # Strip drive letters on Windows (e.g., C: or D:)
        if ":" in raw_name:
            raw_name = raw_name.split(":")[-1]
        raw_name = raw_name.replace("\\", "/").lstrip("/")
        
        # Clean path parts to prevent directory traversal
        parts = [p for p in raw_name.split("/") if p and p != ".." and p != "."]
        if not parts:
            parts = [f"uploaded_{len(saved_files)+1}.cbl"]
            
        safe_rel_path = os.path.join(*parts)
        dest_path = os.path.abspath(os.path.join(uploads_root, safe_rel_path))
        
        # Fallback if somehow still outside uploads_root
        if not dest_path.startswith(uploads_root):
            dest_path = os.path.join(uploads_root, os.path.basename(raw_name))
            safe_rel_path = os.path.basename(dest_path)

        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        content = await f.read()
        with open(dest_path, "wb") as out:
            out.write(content)
        
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = content.decode("latin-1")
            except Exception:
                text = content.decode("utf-8", errors="replace")

        saved_files.append({
            "filename": os.path.basename(dest_path),
            "rel_path": safe_rel_path.replace("\\", "/"),
            "size": len(content),
            "content": text
        })
        
    return {
        "status": "success",
        "count": len(saved_files),
        "uploaded": saved_files
    }

@app.post("/api/parse")
def parse_code(req: ParseRequest):
    """
    Phase 1: Parse COBOL into structured AST, extract def-use dependencies, and resolve copybooks.
    Phase 2: Index into Dual-Memory (ChromaDB Vector Store + NetworkX Graph Store).
    Always resets state when new content is provided, preventing stale data contamination.
    """
    global current_indexed_data, current_source_code, current_filename
    global current_retrieval_result, current_generated_java

    # Always fully reset when parse is called with new content
    current_source_code = req.source_code
    current_filename = req.filename
    current_retrieval_result = {}
    current_generated_java = ""

    parsed = parser.parse_cobol_source(req.filename, req.source_code)
    current_indexed_data = parsed
    
    # Index Dual Memory (resets vector + graph stores internally)
    rag_engine.index_parsed_code(parsed)

    return {
        "status": "success",
        "program_id": parsed["program_id"],
        "filename": parsed["filename"],
        "line_count": parsed["line_count"],
        "ast": parsed["ast"],
        "chunks": parsed["chunks"],
        "edges": parsed["edges"],
        "variables": parsed["variables"],
        "diagnostics": parsed["diagnostics"],
        "copy_inclusions": parsed["copy_inclusions"]
    }

@app.post("/api/rag-search")
def run_rag_search(req: RagQueryRequest):
    """
    Phase 3: Dual-Memory Hybrid Retrieval (Neural Vector + Multi-Hop Graph).
    Also runs Baseline A and Baseline B for comparative evaluation.
    """
    global current_retrieval_result
    if not current_indexed_data:
        raise HTTPException(status_code=400, detail="No COBOL code has been parsed yet.")

    # 1. Structure-Aware Hybrid Retrieval
    ast_retrieval = rag_engine.retrieve(
        query=req.query,
        top_k=req.top_k,
        max_hops=req.max_hops
    )
    current_retrieval_result = ast_retrieval

    # 2. Baseline A (Fixed-size 4-line chunking, vector-only)
    baseline_a = rag_engine.baseline_a_retrieve(
        raw_source=current_source_code,
        query=req.query,
        window_size=4,
        top_k=req.top_k
    )

    # 3. Baseline B (AST chunks without graph expansion)
    baseline_b = rag_engine.baseline_b_retrieve(
        query=req.query,
        top_k=req.top_k
    )

    # 4. Phase 4: Construct Constrained Prompt
    prompt = rag_engine.generate_constrained_prompt(
        retrieval_result=ast_retrieval,
        target_language=req.target_language
    )

    return {
        "query": req.query,
        "ast_retrieval": ast_retrieval,
        "baseline_a": baseline_a,
        "baseline_b": baseline_b,
        "constructed_prompt": prompt,
        "stats": {
            "ast_chunks_retrieved": len(ast_retrieval["bundle"]),
            "structural_edges_identified": len(ast_retrieval["structural_edges"]),
            "constraints_count": len(ast_retrieval["constraint_lines"]),
            "baseline_a_windows": len(baseline_a["retrieved_windows"]),
            "baseline_b_chunks": len(baseline_b["retrieved_chunks"])
        }
    }

@app.post("/api/generate")
def generate_migration(req: GenerateRequest):
    """
    Phase 4: LLM-Based Code Migration (Requirement R7).
    Invokes LLM Engine with assembled structural context and constraints.
    Correctly re-parses and re-indexes when a new source file is provided.
    """
    global current_generated_java, current_retrieval_result, current_indexed_data, current_source_code, current_filename

    # Re-parse only if a different source is provided
    if req.source_code:
        _ensure_parsed(req.source_code, req.filename or current_filename or "PROGRAM.cbl")

    if not current_indexed_data:
        raise HTTPException(status_code=400, detail="No COBOL source code available.")

    retrieval = _ensure_retrieval(req.query or "migrate cobol program to java")

    prompt = rag_engine.generate_constrained_prompt(
        retrieval_result=retrieval,
        target_language=req.target_language
    )
    program_id = current_indexed_data.get("program_id", "MIGRATED_PROGRAM")

    gen_result = llm_engine.generate_java_migration(
        prompt=prompt,
        program_id=program_id,
        retrieval_bundle=retrieval["bundle"],
        constraints=retrieval["constraint_lines"],
        provider=req.provider,
        api_key=req.api_key,
        all_variables=current_indexed_data.get("variables", [])
    )

    current_generated_java = gen_result["generated_java"]

    # Persist generated Java to generated_java directory
    class_name = gen_result["class_name"]
    java_dest = os.path.join(GENERATED_JAVA_DIR, f"{class_name}.java")
    with open(java_dest, "w", encoding="utf-8") as jf:
        jf.write(current_generated_java)

    return {
        "status": "success",
        "success": True,
        "provider": gen_result["provider"],
        "latency_ms": gen_result["latency_ms"],
        "class_name": class_name,
        "generated_java": current_generated_java,
        "generated_code": current_generated_java,
        "prompt": prompt,
        "saved_path": java_dest
    }

@app.post("/api/verify-constraints")
def verify_constraints(req: VerifyRequest):
    """
    Structural Constraint Verification (Requirement R8).
    Parses generated Java AST and verifies that methods, call edges, and variables match.
    Correctly handles new files by re-parsing and regenerating Java if needed.
    """
    global current_generated_java, current_retrieval_result, current_indexed_data, current_source_code, current_filename

    if req.source_code:
        _ensure_parsed(req.source_code, req.filename or current_filename or "PROGRAM.cbl")

    if not current_indexed_data:
        raise HTTPException(status_code=400, detail="No COBOL code parsed.")

    retrieval = _ensure_retrieval("migrate cobol program to java")

    java_code = req.java_code or current_generated_java
    if not java_code:
        # Auto-regenerate using the correct synthesizer call
        java_code = _synthesize_java_safe(current_indexed_data)
        current_generated_java = java_code

    expected_routines = [
        item["id"].split("::")[-1]
        for item in retrieval.get("bundle", [])
        if item["type"] == "chunk"
    ]
    expected_edges = [
        e for e in retrieval.get("structural_edges", [])
        if e.get("type") == "CALLS"
    ]
    expected_vars = [
        item["id"].split("::")[-1]
        for item in retrieval.get("bundle", [])
        if "data_variable" in item["type"]
    ]

    verification = verifier.verify_java_code(
        java_code=java_code,
        expected_chunks=expected_routines,
        expected_call_edges=expected_edges,
        expected_variables=expected_vars
    )
    return verification

@app.post("/api/validate-drift")
def validate_drift(req: DriftRequest):
    """
    Code Validation & Semantic Drift Detection (Requirement R9).
    Executes original COBOL in Docker and generated Java on host JVM, comparing outputs.
    Correctly handles new files without stale data leakage.
    """
    global current_generated_java, current_source_code, current_filename, current_indexed_data

    if req.source_code:
        _ensure_parsed(req.source_code, req.filename or current_filename or "PROGRAM.cbl")

    if not current_source_code:
        raise HTTPException(status_code=400, detail="No COBOL source code available.")

    # Prefer explicitly supplied java; fall back to cached only when it belongs to same source
    java_code = req.java_code if req.java_code else current_generated_java
    if not java_code:
        # Auto-regenerate from the current (possibly new) COBOL source using correct call
        java_code = _synthesize_java_safe(current_indexed_data or {})
        current_generated_java = java_code

    program_id = (current_indexed_data or {}).get("program_id", "PROGRAM")
    drift_result = drift_detector.validate_and_compare(
        program_id=program_id,
        cobol_source=current_source_code,
        java_source=java_code
    )
    return drift_result

@app.post("/api/evaluate-benchmarks")
def evaluate_benchmarks(req: BenchmarkRequest):
    """
    Research Evaluation Suite (Section 6 of Project Requirements).
    Runs comparative evaluation of Baseline A, Baseline B, and Proposed Neuro-Symbolic RAG.
    """
    global current_source_code, current_filename
    if req.source_code:
        _ensure_parsed(req.source_code, req.filename or current_filename or "BENCHMARK.cbl")
    if not current_source_code:
        raise HTTPException(status_code=400, detail="Load a COBOL program first.")
    
    query = req.query or "calculate total amount and taxes"
    eval_result = research_evaluator.run_comparative_evaluation(
        filename=current_filename or "BENCHMARK.cbl",
        source_code=current_source_code,
        query=query
    )
    return eval_result

@app.post("/api/compile-and-run")
def compile_and_run(req: CompileRequest):
    """
    Executes original COBOL program using opensourcecobol4j Docker container (Reference Baseline).
    """
    result = drift_detector._execute_cobol(
        program_id=req.filename.replace(".cbl", "").replace(".cob", ""),
        source_code=req.source_code
    )
    return {
        "success": result["success"],
        "exit_code": result["exit_code"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "latency_ms": result["latency_ms"],
        "generated_java": result.get("generated_java", ""),
        "saved_files": result.get("saved_files", [])
    }

# Mount static frontend
if os.path.exists(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web_studio.backend.server:app", host="127.0.0.1", port=8000, reload=True)
