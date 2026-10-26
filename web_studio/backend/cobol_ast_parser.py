"""
COBOL Abstract Syntax Tree (AST) & Structural Dependency Extractor
Implements Phase 1 (Parsing & Structural Extraction) as described in Section 4.2 & 8.5
of 'AST-Guided Neuro-Symbolic Retrieval-Augmented Generation for Automated Code Analysis and Software Migration'
"""

import re
from typing import Dict, List, Any, Tuple, Optional

class CobolASTParser:
    def __init__(self):
        pass

    def parse_cobol_source(self, filename: str, content: str) -> Dict[str, Any]:
        """
        Parses COBOL source code and builds:
        1. Hierarchical AST (Program -> Divisions -> Sections/Paragraphs -> Statements/Data)
        2. Functional Chunks (Paragraphs / Sections)
        3. Structural Graph (Nodes & Typed Edges: CALLS, DEPENDS_ON)
        """
        lines = content.splitlines()
        normalized_lines = []
        for i, raw_line in enumerate(lines):
            # Clean standard COBOL columns if present:
            # Columns 1-6 are sequence numbers, Col 7 is indicator (* or - or space)
            # Col 8-72 is Area A and Area B
            line_str = raw_line
            is_comment = False
            if len(raw_line) >= 7 and raw_line[6] in ('*', '/'):
                is_comment = True
            elif raw_line.strip().startswith('*') or raw_line.strip().startswith('/'):
                is_comment = True
            
            clean_text = raw_line
            if len(raw_line) > 6 and not is_comment:
                # If traditional fixed format with sequence numbers
                if re.match(r'^\d{6}', raw_line[:6]):
                    clean_text = raw_line[7:72]
            
            normalized_lines.append({
                "line_num": i + 1,
                "raw": raw_line,
                "clean": clean_text.strip(),
                "is_comment": is_comment
            })

        # 1. Extract Program ID
        program_id = "UNKNOWN"
        for item in normalized_lines:
            if not item["is_comment"]:
                m = re.search(r'PROGRAM-ID\.\s+([A-Za-z0-9_-]+)', item["clean"], re.IGNORECASE)
                if m:
                    program_id = m.group(1).rstrip('.')
                    break

        # 2. Extract Data Division items (Variables, Records, Constants)
        variables = {}
        in_data_div = False
        in_proc_div = False
        
        for item in normalized_lines:
            text = item["clean"].upper()
            if "DATA DIVISION" in text:
                in_data_div = True
                in_proc_div = False
                continue
            elif "PROCEDURE DIVISION" in text:
                in_data_div = False
                in_proc_div = True
                continue

            if in_data_div and not item["is_comment"]:
                # Matches: 01 WS-TAX-RATE PIC V99 VALUE .08.
                var_match = re.search(r'^(01|05|10|15|77|88)\s+([A-Za-z0-9_-]+)(.*)$', item["clean"], re.IGNORECASE)
                if var_match:
                    level = var_match.group(1)
                    var_name = var_match.group(2).rstrip('.').upper()
                    rest = var_match.group(3)
                    
                    pic = ""
                    val = ""
                    pic_m = re.search(r'PIC\s+([A-Za-z0-9()Vv\.\-\+]+)', rest, re.IGNORECASE)
                    if pic_m:
                        pic = pic_m.group(1).rstrip('.')
                    val_m = re.search(r'VALUE\s+(["\'].*?["\']|[^\.\s]+)', rest, re.IGNORECASE)
                    if val_m:
                        val = val_m.group(1).rstrip('.')

                    variables[var_name] = {
                        "name": var_name,
                        "level": level,
                        "pic": pic,
                        "value": val,
                        "line": item["line_num"],
                        "file": filename,
                        "raw": item["raw"]
                    }

        # 3. Extract Procedure Division Paragraphs (Functional Chunks)
        paragraphs = []
        current_para = None
        current_stmts = []

        para_header_regex = re.compile(r'^([A-Za-z0-9_-]+)\.\s*(.*)$')
        reserved_division_words = {
            "IDENTIFICATION", "ENVIRONMENT", "DATA", "PROCEDURE", 
            "WORKING-STORAGE", "FILE", "LINKAGE", "LOCAL-STORAGE",
            "PROGRAM-ID", "AUTHOR", "DATE-WRITTEN", "INSTALLATION", "SECURITY"
        }

        for item in normalized_lines:
            text = item["clean"]
            upper_text = text.upper()
            line_num = item["line_num"]

            if "PROCEDURE DIVISION" in upper_text:
                in_proc_div = True
                continue

            if not in_proc_div or item["is_comment"]:
                continue

            m = para_header_regex.match(text)
            if m:
                potential_name = m.group(1).upper()
                # Ensure it's not a DIVISION or SECTION keyword
                if not any(w in potential_name for w in reserved_division_words) and "SECTION" not in upper_text:
                    if current_para:
                        current_para["end_line"] = line_num - 1
                        current_para["statements"] = current_stmts
                        paragraphs.append(current_para)
                    
                    current_para = {
                        "name": potential_name,
                        "file": filename,
                        "start_line": line_num,
                        "end_line": line_num,
                        "lines": [item["raw"]],
                        "statements": []
                    }
                    current_stmts = []
                    rem = m.group(2).strip()
                    if rem:
                        current_stmts.append({"line": line_num, "text": rem})
                    continue

            if current_para:
                current_para["lines"].append(item["raw"])
                if text:
                    current_stmts.append({"line": line_num, "text": text})

        if current_para:
            current_para["end_line"] = normalized_lines[-1]["line_num"]
            current_para["statements"] = current_stmts
            paragraphs.append(current_para)

        # 4. Form Chunks according to the research paper specification
        # id: "<file>::<paragraph_name>"
        chunks = []
        chunks_by_id = {}
        for p in paragraphs:
            chunk_id = f"{filename}::{p['name']}"
            source_code = "\n".join(p["lines"])
            chunk_obj = {
                "id": chunk_id,
                "file": filename,
                "name": p["name"],
                "start_line": p["start_line"],
                "end_line": p["end_line"],
                "source": source_code,
                "statements": p["statements"]
            }
            chunks.append(chunk_obj)
            chunks_by_id[chunk_id] = chunk_obj

        # 5. Extract Call-Graph edges (PERFORM, CALL) and Data-Dependency edges
        edges = []
        para_names = {p["name"]: f"{filename}::{p['name']}" for p in paragraphs}
        var_names = set(variables.keys())

        for p in paragraphs:
            source_id = f"{filename}::{p['name']}"
            para_text = " ".join([s["text"] for s in p["statements"]])

            # A. CALLS edges: PERFORM <paragraph>
            # Matches PERFORM TARGET-PARA or PERFORM TARGET-PARA THRU OTHER
            perform_matches = re.findall(r'\bPERFORM\s+([A-Za-z0-9_-]+)', para_text, re.IGNORECASE)
            for target_name in perform_matches:
                target_upper = target_name.upper()
                if target_upper in para_names and target_upper != p["name"]:
                    edges.append({
                        "type": "CALLS",
                        "source": source_id,
                        "target": para_names[target_upper],
                        "relation": "PERFORMS"
                    })

            # CALL "subprogram"
            call_matches = re.findall(r'\bCALL\s+["\']([A-Za-z0-9_-]+)["\']', para_text, re.IGNORECASE)
            for sub_name in call_matches:
                edges.append({
                    "type": "CALLS",
                    "source": source_id,
                    "target": f"EXTERNAL::{sub_name.upper()}",
                    "relation": "CALLS_EXTERNAL"
                })

            # B. DEPENDS_ON edges: variable identifiers referenced in the paragraph
            for var in var_names:
                # Match identifier boundary
                pattern = r'\b' + re.escape(var) + r'\b'
                if re.search(pattern, para_text, re.IGNORECASE):
                    edges.append({
                        "type": "DEPENDS_ON",
                        "source": source_id,
                        "target": f"DATA::{var}",
                        "relation": "READS_WRITES"
                    })

        # Deduplicate edges
        unique_edges = []
        seen_edges = set()
        for e in edges:
            key = (e["type"], e["source"], e["target"])
            if key not in seen_edges:
                seen_edges.add(key)
                unique_edges.append(e)

        # 6. Build the Visual Hierarchical Abstract Syntax Tree (AST)
        # Root -> Divisions -> Sections / Paragraphs -> Statements
        ast_root = {
            "id": f"prog::{program_id}",
            "name": f"PROGRAM: {program_id}",
            "type": "program",
            "children": [
                {
                    "id": f"div::ident::{program_id}",
                    "name": "IDENTIFICATION DIVISION",
                    "type": "division",
                    "children": [
                        {"id": f"node::pid::{program_id}", "name": f"PROGRAM-ID: {program_id}", "type": "entry"}
                    ]
                },
                {
                    "id": f"div::data::{program_id}",
                    "name": "DATA DIVISION",
                    "type": "division",
                    "children": [
                        {
                            "id": f"sec::ws::{program_id}",
                            "name": "WORKING-STORAGE SECTION",
                            "type": "section",
                            "children": [
                                {
                                    "id": f"DATA::{v['name']}",
                                    "name": f"{v['level']} {v['name']} {('PIC ' + v['pic']) if v['pic'] else ''} {('VALUE ' + v['value']) if v['value'] else ''}".strip(),
                                    "type": "data_field",
                                    "meta": v
                                }
                                for v in variables.values()
                            ]
                        }
                    ]
                },
                {
                    "id": f"div::proc::{program_id}",
                    "name": "PROCEDURE DIVISION",
                    "type": "division",
                    "children": [
                        {
                            "id": f"{filename}::{p['name']}",
                            "name": f"PARAGRAPH: {p['name']}",
                            "type": "paragraph_chunk",
                            "start_line": p["start_line"],
                            "end_line": p["end_line"],
                            "children": [
                                {
                                    "id": f"stmt::{p['name']}::{idx}",
                                    "name": s["text"][:45] + ("..." if len(s["text"]) > 45 else ""),
                                    "type": self._classify_stmt(s["text"]),
                                    "full_text": s["text"],
                                    "line": s["line"]
                                }
                                for idx, s in enumerate(p["statements"])
                            ]
                        }
                        for p in paragraphs
                    ]
                }
            ]
        }

        return {
            "program_id": program_id,
            "filename": filename,
            "line_count": len(lines),
            "chunks": chunks,
            "edges": unique_edges,
            "variables": list(variables.values()),
            "ast": ast_root
        }

    def _classify_stmt(self, text: str) -> str:
        t = text.upper().strip()
        if t.startswith("PERFORM"):
            return "stmt_perform"
        elif t.startswith("COMPUTE") or t.startswith("ADD") or t.startswith("SUBTRACT") or t.startswith("MULTIPLY"):
            return "stmt_math"
        elif t.startswith("MOVE"):
            return "stmt_move"
        elif t.startswith("DISPLAY"):
            return "stmt_display"
        elif t.startswith("IF") or t.startswith("ELSE") or t.startswith("END-IF"):
            return "stmt_control"
        elif t.startswith("STOP") or t.startswith("EXIT") or t.startswith("GOBACK"):
            return "stmt_terminal"
        return "stmt_generic"
