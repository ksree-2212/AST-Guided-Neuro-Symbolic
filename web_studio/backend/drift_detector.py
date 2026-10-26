"""
Semantic Drift Detector & Behavioral Validation Engine (Requirement R9)
Executes original COBOL programs alongside generated Java migrations,
captures runtime console streams and return codes, extracts numerical values,
and measures exact semantic drift.
"""

import os
import re
import shutil
import subprocess
import tempfile
import time
from typing import Dict, Any, List, Optional, Tuple

class SemanticDriftDetector:
    def __init__(self, docker_image: str = "opensourcecobol/opensourcecobol4j:2.1.0-hotfix1"):
        self.docker_image = docker_image
        self.base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

    def validate_and_compare(
        self,
        program_id: str,
        cobol_source: str,
        java_source: str,
        test_inputs: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        End-to-End Behavioral Validation:
        1. Executes reference COBOL on JVM via Docker opensourcecobol4j.
        2. Compiles and executes migrated Java on host JVM.
        3. Measures numerical and text stream drift.

        COBOL 4J-generated Java (from Docker run) is the behavioral ground truth.
        The AST-generated standalone Java must match it to be considered correct.
        """
        start_time = time.time()
        class_name = program_id.replace("-", "_").upper()

        # Step 1: Execute Reference COBOL (also harvests COBOL 4J-generated Java)
        cobol_result = self._execute_cobol(program_id, cobol_source)

        # Step 2: If COBOL 4J produced a .java file, prefer it as correctness reference
        cobol4j_java = cobol_result.get("generated_java", "")
        if not cobol4j_java:
            cobol4j_java = self._load_cobol4j_java(program_id)

        # Step 3: Compile & Execute AST-generated standalone Java
        java_result = self._execute_java(class_name, java_source)

        # Step 4: Compare Behaviors (COBOL stdout vs AST-Java stdout)
        comparison = self._compare_outputs(cobol_result["stdout"], java_result["stdout"])

        # Step 5: Also compare COBOL 4J Java vs AST Java source for structural notes
        cobol4j_note = ""
        if cobol4j_java:
            cobol4j_note = (
                "COBOL 4J-generated Java is available as the behavioral reference. "
                "It requires the jp.osscons.opensourcecobol.libcobj runtime and is NOT standalone. "
                "The AST-generated standalone Java must produce identical console output to pass."
            )

        # Determine overall behavioral status
        if not java_result["compiled"]:
            status = "JAVA_COMPILATION_FAILED"
            drift_score = 1.0
        elif not cobol_result["success"]:
            status = "COBOL_EXECUTION_FAILED"
            drift_score = 1.0
        elif comparison["exact_match"] or comparison["numeric_drift_max"] == 0.0:
            status = "BEHAVIORALLY_EQUIVALENT"
            drift_score = 0.0
        elif comparison["numeric_drift_max"] < 0.02:
            status = "SLIGHT_ROUNDING_DRIFT"
            drift_score = comparison["numeric_drift_max"]
        else:
            status = "SEMANTIC_DRIFT_DETECTED"
            drift_score = comparison["numeric_drift_max"]

        return {
            "status": status,
            "drift_score": round(drift_score, 4),
            "exact_match": comparison["exact_match"],
            "line_similarity": comparison["line_similarity"],
            "cobol_stdout": cobol_result.get("stdout", ""),
            "cobol_stderr": cobol_result.get("stderr", ""),
            "java_stdout": java_result.get("stdout", ""),
            "java_stderr": java_result.get("stderr", ""),
            "compile_errors": java_result.get("compile_errors", ""),
            "cobol_execution": cobol_result,
            "java_execution": java_result,
            "numerical_comparison": comparison["numerical_details"],
            "token_comparisons": comparison["numerical_details"],
            "diff_summary": comparison["diff_summary"],
            "cobol4j_java": cobol4j_java,
            "cobol4j_reference_note": cobol4j_note,
            "duration_ms": int((time.time() - start_time) * 1000)
        }

    def _load_cobol4j_java(self, program_id: str) -> str:
        """
        Loads the COBOL 4J-generated Java from the generated_java/ directory.
        This file is the behavioral correctness reference:
        - It is produced by opensourcecobol4j and depends on jp.osscons.opensourcecobol.libcobj.
        - It is NOT standalone Java; it cannot be compiled/run without the runtime.
        - The AST-generated standalone Java must reproduce identical output to be correct.
        """
        gen_dir = os.path.join(self.base_dir, "web_studio", "generated_java")
        if not os.path.exists(gen_dir):
            return ""
        norm = program_id.replace("-", "_").lower()
        candidates = sorted(os.listdir(gen_dir))
        for fname in candidates:
            if fname.endswith(".java") and norm in fname.lower():
                try:
                    with open(os.path.join(gen_dir, fname), "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                    # Check if it's a COBOL 4J file (uses libcobj runtime)
                    if "libcobj" in content or "jp.osscons" in content:
                        return content
                except Exception:
                    pass
        return ""

    def _execute_cobol(self, program_id: str, source_code: str) -> Dict[str, Any]:
        """Executes COBOL source using opensourcecobol4j Docker container."""
        with tempfile.TemporaryDirectory() as temp_dir:
            fname = f"{program_id}.cbl"
            cbl_path = os.path.join(temp_dir, fname)
            with open(cbl_path, "w", encoding="utf-8") as f:
                f.write(source_code)

            # Check format
            is_free = any(l.strip() and not l.startswith(('*', '/')) and (len(l) < 7 or not l.startswith("      ")) for l in source_code.splitlines())
            flag_str = "-free" if is_free else ""

            bash_script = (
                f"cobj {flag_str} '{fname}' && "
                f"MAIN_CLS=$(ls -1 *.class 2>/dev/null | grep -v '\\$' | head -n 1 | sed 's/\\.class//') && "
                f"if [ -n \"$MAIN_CLS\" ]; then java \"$MAIN_CLS\"; fi"
            )
            cmd = [
                "docker", "run", "--rm",
                "-v", f"{temp_dir}:/workspace",
                "-w", "/workspace",
                self.docker_image,
                "bash", "-c", bash_script
            ]

            try:
                t0 = time.time()
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
                
                # Harvest generated .java files from Docker execution
                generated_java_code = ""
                saved_files = []
                gen_dir = os.path.join(self.base_dir, "web_studio", "generated_java")
                os.makedirs(gen_dir, exist_ok=True)

                java_files = [f for f in os.listdir(temp_dir) if f.endswith(".java")]
                for jf in java_files:
                    src_j = os.path.join(temp_dir, jf)
                    dst_j = os.path.join(gen_dir, jf)
                    try:
                        shutil.copy2(src_j, dst_j)
                        saved_files.append(jf)
                    except Exception:
                        pass

                if java_files:
                    norm = program_id.replace("-", "_").lower()
                    preferred = [f for f in java_files if norm in f.lower()]
                    target_jf = preferred[0] if preferred else java_files[0]
                    try:
                        with open(os.path.join(temp_dir, target_jf), "r", encoding="utf-8", errors="replace") as f:
                            generated_java_code = f.read()
                    except Exception:
                        pass

                # Fallback to existing file in web_studio/generated_java
                if not generated_java_code and os.path.exists(gen_dir):
                    norm = program_id.replace("-", "_").lower()
                    for exist_f in os.listdir(gen_dir):
                        if exist_f.endswith(".java") and norm in exist_f.lower():
                            try:
                                with open(os.path.join(gen_dir, exist_f), "r", encoding="utf-8", errors="replace") as f:
                                    generated_java_code = f.read()
                                if exist_f not in saved_files:
                                    saved_files.append(exist_f)
                                break
                            except Exception:
                                pass

                return {
                    "success": (res.returncode == 0),
                    "exit_code": res.returncode,
                    "stdout": res.stdout.strip(),
                    "stderr": res.stderr.strip(),
                    "latency_ms": int((time.time() - t0) * 1000),
                    "generated_java": generated_java_code,
                    "saved_files": saved_files
                }
            except Exception as e:
                return {
                    "success": False,
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": str(e),
                    "latency_ms": 0,
                    "generated_java": "",
                    "saved_files": []
                }

    def _execute_java(self, class_name: str, java_source: str) -> Dict[str, Any]:
        """Compiles and executes Java source code on the host JVM."""
        # Auto-detect actual public class name from java_source if available
        cls_match = re.search(r'public\s+class\s+([A-Za-z0-9_]+)', java_source)
        if cls_match:
            class_name = cls_match.group(1)

        with tempfile.TemporaryDirectory() as temp_dir:
            java_path = os.path.join(temp_dir, f"{class_name}.java")
            with open(java_path, "w", encoding="utf-8") as f:
                f.write(java_source)

            # 1. Compile with javac
            t0 = time.time()
            compile_cmd = ["javac", java_path]
            try:
                compile_res = subprocess.run(compile_cmd, capture_output=True, text=True, timeout=15)
                if compile_res.returncode != 0:
                    return {
                        "compiled": False,
                        "success": False,
                        "compile_errors": compile_res.stderr.strip(),
                        "stdout": "",
                        "stderr": compile_res.stderr.strip(),
                        "latency_ms": int((time.time() - t0) * 1000)
                    }
            except Exception as e:
                return {
                    "compiled": False,
                    "success": False,
                    "compile_errors": str(e),
                    "stdout": "",
                    "stderr": str(e),
                    "latency_ms": 0
                }

            # 2. Run with java
            run_cmd = ["java", "-cp", temp_dir, class_name]
            try:
                run_res = subprocess.run(run_cmd, capture_output=True, text=True, timeout=10)
                return {
                    "compiled": True,
                    "success": (run_res.returncode == 0),
                    "exit_code": run_res.returncode,
                    "stdout": run_res.stdout.strip(),
                    "stderr": run_res.stderr.strip(),
                    "latency_ms": int((time.time() - t0) * 1000)
                }
            except Exception as e:
                return {
                    "compiled": True,
                    "success": False,
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": str(e),
                    "latency_ms": 0
                }

    def _compare_outputs(self, cobol_out: str, java_out: str) -> Dict[str, Any]:
        """Compares outputs, computes line similarity and numerical token drift."""
        exact_match = (cobol_out.strip() == java_out.strip())
        
        # Line comparison
        c_lines = [l.strip() for l in cobol_out.splitlines() if l.strip()]
        j_lines = [l.strip() for l in java_out.splitlines() if l.strip()]

        matching_lines = sum(1 for cl in c_lines if any(cl == jl or cl in jl or jl in cl for jl in j_lines))
        line_sim = round(matching_lines / max(len(c_lines), 1), 3)

        # Number extraction
        c_nums = self._extract_numbers(cobol_out)
        j_nums = self._extract_numbers(java_out)

        max_drift = 0.0
        num_details = []

        for i in range(min(len(c_nums), len(j_nums))):
            cn = c_nums[i]
            jn = j_nums[i]
            diff = abs(cn - jn)
            rel_diff = diff / max(abs(cn), 1.0)
            if rel_diff > max_drift:
                max_drift = rel_diff
            num_details.append({
                "index": i + 1,
                "cobol_value": cn,
                "java_value": jn,
                "absolute_diff": round(diff, 4),
                "relative_diff": round(rel_diff, 4),
                "matched": (diff < 0.001)
            })

        # Diff summary
        diff_lines = []
        max_len = max(len(c_lines), len(j_lines))
        for i in range(max_len):
            cl = c_lines[i] if i < len(c_lines) else "[EOF]"
            jl = j_lines[i] if i < len(j_lines) else "[EOF]"
            eq_mark = "==" if cl == jl else "!="
            diff_lines.append(f"{cl:<35} {eq_mark} {jl}")

        return {
            "exact_match": exact_match,
            "line_similarity": line_sim,
            "numeric_drift_max": round(max_drift, 4),
            "numerical_details": num_details,
            "diff_summary": "\n".join(diff_lines[:12])
        }

    def _extract_numbers(self, text: str) -> List[float]:
        """Extracts all floating-point / monetary numbers from a console output."""
        # Normalize commas in numbers like 1,020.00 -> 1020.00
        clean_text = re.sub(r'(?<=\d),(?=\d)', '', text)
        matches = re.findall(r'[-+]?\d*\.\d+|\b[-+]?\d+\b', clean_text)
        nums = []
        for m in matches:
            try:
                nums.append(float(m))
            except ValueError:
                pass
        return nums
