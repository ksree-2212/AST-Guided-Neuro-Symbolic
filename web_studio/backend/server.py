"""
FastAPI Server for AST-Guided Neuro-Symbolic RAG & COBOL-to-Java Migration Studio
"""

import os
import shutil
import subprocess
import tempfile
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from web_studio.backend.cobol_ast_parser import CobolASTParser
from web_studio.backend.neuro_symbolic_rag import DualMemoryRAG

app = FastAPI(title="AST-Guided Neuro-Symbolic RAG Studio")

# Enable CORS for easy local browser communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Project paths
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SAMPLES_DIR = os.path.join(BASE_DIR, "web_studio", "samples")
FRONTEND_DIR = os.path.join(BASE_DIR, "web_studio", "frontend")
UPLOADS_DIR = os.path.join(BASE_DIR, "web_studio", "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)

# Shared in-memory RAG coordinator
parser = CobolASTParser()
rag_engine = DualMemoryRAG()
current_indexed_data = {}
current_source_code = ""
current_filename = ""

class ParseRequest(BaseModel):
    filename: str
    source_code: str

class RagQueryRequest(BaseModel):
    query: str
    top_k: int = 2
    max_hops: int = 2
    target_language: str = "Java"

class CompileRequest(BaseModel):
    filename: str
    source_code: str

@app.get("/api/samples")
def get_samples():
    """List preloaded samples"""
    samples = []
    if os.path.exists(SAMPLES_DIR):
        for f in os.listdir(SAMPLES_DIR):
            if f.endswith((".cbl", ".cob")):
                path = os.path.join(SAMPLES_DIR, f)
                with open(path, "r", encoding="utf-8", errors="ignore") as fp:
                    content = fp.read()
                samples.append({
                    "filename": f,
                    "content": content,
                    "description": "Research paper billing & tax evaluation" if "BILLING" in f else "Hello World sample"
                })
    return {"samples": samples}

@app.post("/api/upload")
async def upload_files(files: List[UploadFile] = File(...)):
    """Upload one or more COBOL files or an entire folder"""
    saved_files = []
    for f in files:
        # Preserve relative directory structure if passed
        rel_path = f.filename.replace("\\", "/")
        dest_path = os.path.join(UPLOADS_DIR, rel_path)
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        
        content = await f.read()
        with open(dest_path, "wb") as out:
            out.write(content)
        
        text = content.decode("utf-8", errors="ignore")
        saved_files.append({
            "filename": os.path.basename(dest_path),
            "rel_path": rel_path,
            "size": len(content),
            "content": text
        })
        
    return {"uploaded": saved_files}

@app.post("/api/parse")
def parse_code(req: ParseRequest):
    """
    Phase 1: Parse COBOL into AST, extract functional chunks (paragraphs)
    and dependency edges (CALLS, DEPENDS_ON).
    Also indexes both Neuro and Symbolic memories (Phase 2).
    """
    global current_indexed_data, current_source_code, current_filename
    current_source_code = req.source_code
    current_filename = req.filename

    parsed = parser.parse_cobol_source(req.filename, req.source_code)
    current_indexed_data = parsed
    
    # Phase 2: Index into Dual-Memory (VectorStore + GraphStore)
    rag_engine.index_parsed_code(parsed)

    return {
        "status": "success",
        "program_id": parsed["program_id"],
        "filename": parsed["filename"],
        "line_count": parsed["line_count"],
        "ast": parsed["ast"],
        "chunks": parsed["chunks"],
        "edges": parsed["edges"],
        "variables": parsed["variables"]
    }

@app.post("/api/rag-search")
def run_rag_search(req: RagQueryRequest):
    """
    Phase 3: Dual-Memory Structure-Aware Retrieval & Baseline Comparison.
    Phase 4: Constrained Prompt Generation.
    """
    if not current_indexed_data:
        raise HTTPException(status_code=400, detail="No COBOL code has been parsed yet.")

    # 1. Structure-Aware Hybrid Retrieval
    ast_retrieval = rag_engine.retrieve(
        query=req.query,
        top_k=req.top_k,
        max_hops=req.max_hops
    )

    # 2. Baseline Standard RAG (fixed 4-line window chunking, vector-only)
    baseline_retrieval = rag_engine.baseline_retrieve(
        raw_source=current_source_code,
        query=req.query,
        window_size=4,
        top_k=req.top_k
    )

    # 3. Phase 4: Construct Constrained Prompt
    prompt = rag_engine.generate_constrained_prompt(
        retrieval_result=ast_retrieval,
        target_language=req.target_language
    )

    return {
        "query": req.query,
        "ast_retrieval": ast_retrieval,
        "baseline_retrieval": baseline_retrieval,
        "constructed_prompt": prompt,
        "stats": {
            "ast_chunks_retrieved": len(ast_retrieval["bundle"]),
            "structural_edges_identified": len(ast_retrieval["structural_edges"]),
            "baseline_windows_retrieved": len(baseline_retrieval["retrieved_windows"])
        }
    }

GENERATED_JAVA_DIR = os.path.join(BASE_DIR, "web_studio", "generated_java")
os.makedirs(GENERATED_JAVA_DIR, exist_ok=True)

@app.post("/api/compile-and-run")
def compile_and_run(req: CompileRequest):
    """
    Compiles COBOL program using opensourcecobol4j Docker container.
    Supports both free-format and fixed-format COBOL with auto-detection.
    Dynamically discovers the mangled Java class name (handling hyphens and casing)
    and executes it on the JVM. Persists the generated .java code into web_studio/generated_java/.
    """
    with tempfile.TemporaryDirectory(dir=UPLOADS_DIR) as temp_dir:
        fname = req.filename if req.filename.endswith((".cbl", ".cob")) else f"{req.filename}.cbl"
        cobol_file = os.path.join(temp_dir, fname)
        with open(cobol_file, "w", encoding="utf-8") as f:
            f.write(req.source_code)

        # Detect if source starts before column 7 (needs -free format flag)
        is_free_format = False
        for line in req.source_code.splitlines():
            sline = line.strip()
            if sline and not sline.startswith(("*", "/")):
                if len(line) >= 7 and not line[:6].isspace() and not line[:6].isdigit():
                    is_free_format = True
                    break
                elif len(line) < 7 or not line.startswith("      "):
                    is_free_format = True
                    break

        def execute_cobj(free_flag: bool):
            flag_str = "-free" if free_flag else ""
            bash_script = (
                f"cobj {flag_str} '{fname}' && "
                f"MAIN_CLS=$(ls -1 *.class 2>/dev/null | grep -v '\\$' | head -n 1 | sed 's/\\.class//') && "
                f"if [ -n \"$MAIN_CLS\" ]; then java \"$MAIN_CLS\"; fi"
            )
            cmd = [
                "docker", "run", "--rm",
                "-v", f"{temp_dir}:/workspace",
                "-w", "/workspace",
                "opensourcecobol/opensourcecobol4j:2.1.0-hotfix1",
                "bash", "-c", bash_script
            ]
            return subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        try:
            res = execute_cobj(is_free_format)
            if res.returncode != 0 and not is_free_format:
                if "Invalid indicator" in res.stderr or "syntax error" in res.stderr:
                    res = execute_cobj(True)

            if res.returncode != 0 and any(err in res.stderr for err in ["failed to connect to the docker API", "Cannot connect to the Docker daemon", "dockerDesktopLinuxEngine"]):
                res = subprocess.CompletedProcess(
                    args=res.args,
                    returncode=res.returncode,
                    stdout=res.stdout,
                    stderr=(
                        "[!] Docker daemon is currently not running.\n\n"
                        "Live COBOL-to-Java compilation uses the Docker image:\n"
                        "  opensourcecobol/opensourcecobol4j:2.1.0-hotfix1\n\n"
                        "To compile & run COBOL live on the JVM:\n"
                        "1. Start Docker Desktop on Windows.\n"
                        "2. Click 'Compile & Run' again.\n\n"
                        f"Original error:\n{res.stderr.strip()}"
                    )
                )

            # Discover all generated .java files in the directory
            java_files = [f for f in os.listdir(temp_dir) if f.endswith(".java")]
            java_code = ""
            saved_paths = []

            for jf_name in java_files:
                src_path = os.path.join(temp_dir, jf_name)
                dest_path = os.path.join(GENERATED_JAVA_DIR, jf_name)
                shutil.copy2(src_path, dest_path)
                saved_paths.append(dest_path)
                if not java_code:
                    with open(src_path, "r", encoding="utf-8", errors="ignore") as jfp:
                        java_code = jfp.read()

            return {
                "success": (res.returncode == 0),
                "exit_code": res.returncode,
                "stdout": res.stdout,
                "stderr": res.stderr,
                "generated_java": java_code,
                "saved_files": [os.path.basename(p) for p in saved_paths],
                "saved_directory": GENERATED_JAVA_DIR
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": "Compilation timed out after 30 seconds",
                "generated_java": "",
                "saved_files": []
            }
        except Exception as e:
            return {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": str(e),
                "generated_java": "",
                "saved_files": []
            }

# Mount static files for web frontend
if os.path.exists(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web_studio.backend.server:app", host="127.0.0.1", port=8000, reload=True)

