"""
COBOL Abstract Syntax Tree (AST) & Structural Dependency Extractor
Implements Phase 1 (Parsing & Structural Extraction) as described in Section 4.2 & 8.5
of 'AST-Guided Neuro-Symbolic Retrieval-Augmented Generation for Automated Code Analysis and Software Migration'
"""

import os
import re
from typing import Dict, List, Any, Tuple, Optional, Set

class ASTNode:
    """Base class for structured syntax representations"""
    def __init__(self, node_type: str, name: str, start_line: int, end_line: int, **attrs):
        self.node_type = node_type
        self.name = name
        self.start_line = start_line
        self.end_line = end_line
        self.attrs = attrs
        self.children: List['ASTNode'] = []

    def add_child(self, child: 'ASTNode'):
        self.children.append(child)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": f"{self.node_type}::{self.name}::{self.start_line}",
            "name": self.name,
            "type": self.node_type,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "attrs": self.attrs,
            "children": [c.to_dict() for c in self.children]
        }

class CobolASTParser:
    """
    Structured COBOL Parser supporting:
    - Fixed (columns 1-6 sequence, 7 indicator, 8-72 code) & Free format COBOL
    - COPY copybook resolution and inlining
    - Full variable hierarchy (01-49, 77, 88, REDEFINES, OCCURS, PIC, VALUE, USAGE)
    - Procedure Division paragraphs & structured statement decomposition (COMPUTE, MOVE, PERFORM, IF, DISPLAY, CALL)
    - True Def-Use dependency analysis (distinguishing READS vs WRITES vs CALLS)
    - Syntax error detection & non-fatal diagnostics
    """
    def __init__(self, copybook_dirs: Optional[List[str]] = None):
        self.copybook_dirs = copybook_dirs or []
        # Add default copybook locations
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        self.copybook_dirs.extend([
            os.path.join(base_dir, "copy"),
            os.path.join(base_dir, "web_studio", "samples"),
            os.path.join(base_dir, "web_studio", "uploads")
        ])

    def resolve_copybooks(self, content: str, source_filepath: str) -> Tuple[str, List[Dict[str, Any]]]:
        """Resolves COPY <copybook> statements by searching configured copybook directories."""
        resolved_lines = []
        copy_inclusions = []
        source_dir = os.path.dirname(os.path.abspath(source_filepath)) if source_filepath else ""

        for line_idx, line in enumerate(content.splitlines()):
            copy_match = re.search(r'\bCOPY\s+["\']?([A-Za-z0-9_-]+)["\']?\s*\.?', line, re.IGNORECASE)
            if copy_match and not line.strip().startswith(('*', '/')):
                cpy_name = copy_match.group(1)
                found_path = None
                
                # Check candidate locations
                candidate_dirs = [source_dir] + self.copybook_dirs
                for d in candidate_dirs:
                    if not d or not os.path.exists(d):
                        continue
                    for ext in [".cpy", ".CPY", ".cbl", ".CBL", ".cob", ""]:
                        cand = os.path.join(d, f"{cpy_name}{ext}")
                        if os.path.isfile(cand):
                            found_path = cand
                            break
                    if found_path:
                        break

                if found_path:
                    try:
                        with open(found_path, "r", encoding="utf-8", errors="ignore") as f:
                            cpy_content = f.read()
                        copy_inclusions.append({
                            "copybook": cpy_name,
                            "path": found_path,
                            "line": line_idx + 1,
                            "status": "resolved"
                        })
                        resolved_lines.append(f"      *> --- BEGIN COPYBOOK {cpy_name} ---")
                        resolved_lines.extend(cpy_content.splitlines())
                        resolved_lines.append(f"      *> --- END COPYBOOK {cpy_name} ---")
                        continue
                    except Exception as e:
                        copy_inclusions.append({
                            "copybook": cpy_name,
                            "line": line_idx + 1,
                            "status": f"read_error: {str(e)}"
                        })
                else:
                    copy_inclusions.append({
                        "copybook": cpy_name,
                        "line": line_idx + 1,
                        "status": "unresolved_missing_file"
                    })
            resolved_lines.append(line)

        return "\n".join(resolved_lines), copy_inclusions

    def parse(self, filename: str, content: Optional[str] = None) -> Dict[str, Any]:
        """Convenience alias for parse_cobol_source. Accepts (filename, content) or (code_or_path)."""
        if content is None:
            if os.path.exists(filename):
                with open(filename, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            else:
                content = filename
                filename = "PROGRAM.cbl"
        return self.parse_cobol_source(filename, content)

    def parse_cobol_source(self, filename: str, content: str) -> Dict[str, Any]:
        """
        Parses COBOL source code and builds:
        1. Hierarchical syntax tree (Program -> Divisions -> Sections -> Paragraphs -> Statements)
        2. Functional Chunks (Paragraphs / Sections) with source spans
        3. Structural Graph with exact def-use edges (CALLS, READS, WRITES, DEFINES)
        4. Syntax validation diagnostics
        """
        diagnostics = []
        
        # 1. Resolve copybooks
        expanded_content, copy_inclusions = self.resolve_copybooks(content, filename)

        # 2. Normalize lines
        raw_lines = expanded_content.splitlines()
        normalized_lines = []
        is_free_format = False

        for i, raw_line in enumerate(raw_lines):
            line_str = raw_line
            is_comment = False
            
            # Indicator column check
            if len(raw_line) >= 7 and raw_line[6] in ('*', '/'):
                is_comment = True
            elif raw_line.strip().startswith(('*', '/')):
                is_comment = True
            
            clean_text = raw_line
            # If standard fixed format with 6-digit sequence numbers
            if len(raw_line) > 6 and not is_comment:
                if re.match(r'^\d{6}', raw_line[:6]):
                    clean_text = raw_line[7:72]
                elif raw_line.startswith("      "):
                    clean_text = raw_line[6:]

            clean_stripped = clean_text.strip()
            normalized_lines.append({
                "line_num": i + 1,
                "raw": raw_line,
                "clean": clean_stripped,
                "is_comment": is_comment
            })

        # 3. Detect Program ID
        program_id = "UNKNOWN"
        has_ident_div = False
        has_proc_div = False

        for item in normalized_lines:
            if not item["is_comment"]:
                upper = item["clean"].upper()
                if "IDENTIFICATION DIVISION" in upper:
                    has_ident_div = True
                if "PROCEDURE DIVISION" in upper:
                    has_proc_div = True
                m = re.search(r'PROGRAM-ID\.\s+([A-Za-z0-9_-]+)', item["clean"], re.IGNORECASE)
                if m:
                    program_id = m.group(1).rstrip('.').strip()

        if not has_ident_div:
            diagnostics.append({"level": "warning", "line": 1, "message": "Missing IDENTIFICATION DIVISION header."})
        if not has_proc_div:
            diagnostics.append({"level": "warning", "line": 1, "message": "Missing PROCEDURE DIVISION header."})

        # 4. Parse DATA DIVISION (Variables, Level Numbers, Records, Picture Clauses, Types)
        variables: Dict[str, Dict[str, Any]] = {}
        in_data_div = False
        in_proc_div = False
        data_start_line = 0
        current_section = "WORKING-STORAGE"

        for item in normalized_lines:
            if item["is_comment"]:
                continue
            upper = item["clean"].upper()
            line_num = item["line_num"]

            if "DATA DIVISION" in upper:
                in_data_div = True
                in_proc_div = False
                data_start_line = line_num
                continue
            elif "PROCEDURE DIVISION" in upper:
                in_data_div = False
                in_proc_div = True
                continue

            if in_data_div:
                if "WORKING-STORAGE SECTION" in upper:
                    current_section = "WORKING-STORAGE"
                    continue
                elif "FILE SECTION" in upper:
                    current_section = "FILE"
                    continue
                elif "LINKAGE SECTION" in upper:
                    current_section = "LINKAGE"
                    continue

                # Level numbered data item: 01-49, 77, 88
                var_match = re.match(r'^(0[1-9]|[1-4][0-9]|77|88)\s+([A-Za-z0-9_-]+)(.*)$', item["clean"], re.IGNORECASE)
                if var_match:
                    level = var_match.group(1)
                    var_name = var_match.group(2).rstrip('.').upper()
                    rest = var_match.group(3)

                    pic = ""
                    val = ""
                    redefines = ""
                    occurs = 1
                    usage = "DISPLAY"

                    # PIC clause
                    pic_m = re.search(r'PIC\s+([A-Za-z0-9()Vv\.\-\+$,*]+)', rest, re.IGNORECASE)
                    if pic_m:
                        pic = pic_m.group(1).rstrip('.')

                    # VALUE clause
                    val_m = re.search(r'VALUE\s+(["\'].*?["\']|[0-9a-zA-Z_\.\-]+)', rest, re.IGNORECASE)
                    if val_m:
                        val = val_m.group(1).rstrip('.')

                    # REDEFINES clause
                    redef_m = re.search(r'REDEFINES\s+([A-Za-z0-9_-]+)', rest, re.IGNORECASE)
                    if redef_m:
                        redefines = redef_m.group(1).rstrip('.').upper()

                    # OCCURS clause
                    occurs_m = re.search(r'OCCURS\s+(\d+)', rest, re.IGNORECASE)
                    if occurs_m:
                        occurs = int(occurs_m.group(1))

                    # USAGE clause (COMP, COMP-3, BINARY)
                    usage_m = re.search(r'\b(COMP-3|COMP-1|COMP-2|COMP-4|COMP-5|COMP|BINARY|PACKED-DECIMAL)\b', rest, re.IGNORECASE)
                    if usage_m:
                        usage = usage_m.group(1).upper()

                    # Deduce data type
                    data_type = self._infer_data_type(pic, val, usage)

                    variables[var_name] = {
                        "name": var_name,
                        "level": level,
                        "pic": pic,
                        "value": val,
                        "type": data_type,
                        "usage": usage,
                        "redefines": redefines,
                        "occurs": occurs,
                        "section": current_section,
                        "line": line_num,
                        "file": filename,
                        "raw": item["raw"].strip()
                    }

        # 5. Parse PROCEDURE DIVISION into Paragraphs and Statements
        paragraphs: List[Dict[str, Any]] = []
        current_para: Optional[Dict[str, Any]] = None
        current_stmts: List[Dict[str, Any]] = []

        para_header_regex = re.compile(r'^([A-Za-z0-9_-]+)\.\s*(.*)$')
        reserved_division_words = {
            "IDENTIFICATION", "ENVIRONMENT", "DATA", "PROCEDURE",
            "WORKING-STORAGE", "FILE", "LINKAGE", "LOCAL-STORAGE",
            "PROGRAM-ID", "AUTHOR", "DATE-WRITTEN", "INSTALLATION", "SECURITY",
            "DATE-COMPILED", "REMARKS"
        }
        # COBOL verbs that can start a statement line (not a paragraph header)
        cobol_verbs = {
            "MOVE", "COMPUTE", "ADD", "SUBTRACT", "MULTIPLY", "DIVIDE",
            "PERFORM", "IF", "ELSE", "END-IF", "EVALUATE", "WHEN", "END-EVALUATE",
            "DISPLAY", "ACCEPT", "READ", "WRITE", "REWRITE", "DELETE", "OPEN",
            "CLOSE", "CALL", "STOP", "GOBACK", "EXIT", "STRING", "UNSTRING",
            "INSPECT", "INITIALIZE", "SET", "SORT", "MERGE", "RETURN",
            "GO", "ALTER", "CONTINUE", "NOT", "ON", "AT", "END-READ",
            "END-WRITE", "END-CALL", "END-PERFORM", "END-EVALUATE"
        }

        # CRITICAL FIX: Reset in_proc_div before the second pass through normalized_lines
        in_proc_div = False
        continuation_buf: List[str] = []  # buffer for multi-line statements

        def flush_continuation(buf: List[str], line_num: int):
            """Join continuation lines and parse as one statement.
            Stops at the first period so we do not cross statement boundaries.
            """
            if not buf:
                return None
            merged = " ".join(b.strip() for b in buf)
            # If the merged text has multiple period-terminated sentences,
            # only take the first one (avoids absorbing next paragraph header)
            first_stmt = re.split(r'\.(\s|$)', merged, maxsplit=1)[0]
            return self._parse_statement(first_stmt.strip(), line_num)

        for item in normalized_lines:
            text = item["clean"]
            upper_text = text.upper()
            line_num = item["line_num"]

            if "PROCEDURE DIVISION" in upper_text:
                in_proc_div = True
                continue

            if not in_proc_div or item["is_comment"]:
                continue

            # Skip SECTION declarations inside procedure (e.g., MAIN SECTION.)
            if re.match(r'^[A-Za-z0-9_-]+\s+SECTION\.?\s*$', text, re.IGNORECASE):
                continue

            # Detect paragraph header: WORD. (optionally followed by a statement)
            m = para_header_regex.match(text)
            if m:
                potential_name = m.group(1).upper()
                remainder = m.group(2).strip()

                # Reject if it looks like a reserved word or a verb at the start of a stmt
                is_reserved = any(w in potential_name for w in reserved_division_words)
                is_end_terminator = potential_name.startswith("END-")
                # A name is a verb only if the WHOLE name is a bare COBOL verb.
                # Hyphenated names like COMPUTE-GROSS or DISPLAY-PAYROLL are valid paragraph names.
                is_verb = (
                    potential_name in cobol_verbs
                    or is_end_terminator
                )
                looks_like_para = (
                    not is_reserved
                    and not is_verb
                    and "SECTION" not in upper_text
                    and re.match(r'^[A-Za-z][A-Za-z0-9_-]*$', potential_name)
                )


                if looks_like_para:
                    # Flush any pending continuation before starting new paragraph
                    if continuation_buf and current_para:
                        stmt = flush_continuation(continuation_buf, line_num - 1)
                        if stmt:
                            current_stmts.append(stmt)
                        continuation_buf = []

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
                    if remainder:
                        continuation_buf = [remainder]
                    continue

            if current_para:
                current_para["lines"].append(item["raw"])
                if text:
                    # Multi-line continuation: if no leading verb, accumulate
                    first_word = text.strip().split()[0].upper().rstrip('.') if text.strip() else ""
                    is_new_stmt = first_word in cobol_verbs

                    if is_new_stmt:
                        # Flush buffered continuation as one statement
                        if continuation_buf:
                            stmt = flush_continuation(continuation_buf, line_num - 1)
                            if stmt:
                                current_stmts.append(stmt)
                        continuation_buf = [text]
                    else:
                        # Continuation of previous statement
                        continuation_buf.append(text)

        # Flush final continuation buffer
        if continuation_buf and current_para:
            stmt = flush_continuation(continuation_buf, normalized_lines[-1]["line_num"])
            if stmt:
                current_stmts.append(stmt)

        if current_para:
            current_para["end_line"] = normalized_lines[-1]["line_num"]
            current_para["statements"] = current_stmts
            paragraphs.append(current_para)

        # 6. Form Chunks
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

        # 7. True Structural Dependency & Def-Use Analysis (R3)
        edges: List[Dict[str, Any]] = []
        para_names = {p["name"]: f"{filename}::{p['name']}" for p in paragraphs}
        var_names = set(variables.keys())

        for p in paragraphs:
            source_id = f"{filename}::{p['name']}"
            
            for stmt in p["statements"]:
                stype = stmt["stmt_type"]
                line = stmt["line"]

                # A. CALLS / PERFORMS relationships
                if stype == "PERFORM":
                    target = stmt.get("target_para", "").upper()
                    thru_target = stmt.get("thru_para", "").upper()
                    
                    if target in para_names:
                        edges.append({
                            "type": "CALLS",
                            "source": source_id,
                            "target": para_names[target],
                            "relation": "PERFORMS",
                            "line": line
                        })
                    elif target and target not in {"UNTIL", "VARYING"}:
                        edges.append({
                            "type": "CALLS",
                            "source": source_id,
                            "target": f"EXTERNAL::{target}",
                            "relation": "PERFORMS_UNRESOLVED",
                            "line": line
                        })

                    if thru_target and thru_target in para_names:
                        edges.append({
                            "type": "CALLS",
                            "source": source_id,
                            "target": para_names[thru_target],
                            "relation": "PERFORMS_THRU",
                            "line": line
                        })

                elif stype == "CALL":
                    subprogram = stmt.get("subprogram", "").upper()
                    edges.append({
                        "type": "CALLS",
                        "source": source_id,
                        "target": f"EXTERNAL::{subprogram}",
                        "relation": "CALLS_EXTERNAL",
                        "line": line
                    })

                # B. Def-Use Relationships: Explicit READS and WRITES
                # Variables Written
                for w_var in stmt.get("writes", []):
                    if w_var in var_names:
                        edges.append({
                            "type": "WRITES",
                            "source": source_id,
                            "target": f"DATA::{w_var}",
                            "relation": f"WRITES_{stype}",
                            "line": line
                        })

                # Variables Read
                for r_var in stmt.get("reads", []):
                    if r_var in var_names:
                        edges.append({
                            "type": "READS",
                            "source": source_id,
                            "target": f"DATA::{r_var}",
                            "relation": f"READS_{stype}",
                            "line": line
                        })

        # Deduplicate edges preserving line info
        unique_edges = []
        seen = set()
        for e in edges:
            key = (e["type"], e["source"], e["target"], e["relation"])
            if key not in seen:
                seen.add(key)
                unique_edges.append(e)

        # 8. Build Full Hierarchical Abstract Syntax Tree (R2)
        ast_root = ASTNode("Program", program_id, 1, len(normalized_lines), filename=filename)
        
        # Identification Division
        ident_div = ASTNode("IdentificationDivision", "IDENTIFICATION DIVISION", 1, 3)
        ident_div.add_child(ASTNode("ProgramIdStatement", f"PROGRAM-ID: {program_id}", 2, 2))
        ast_root.add_child(ident_div)

        # Data Division
        data_div = ASTNode("DataDivision", "DATA DIVISION", data_start_line, data_start_line)
        ws_sec = ASTNode("Section", "WORKING-STORAGE SECTION", data_start_line, data_start_line)
        for var in variables.values():
            var_node = ASTNode(
                "DataDeclaration",
                f"{var['level']} {var['name']} {('PIC ' + var['pic']) if var['pic'] else ''} {('VALUE ' + var['value']) if var['value'] else ''}".strip(),
                var["line"], var["line"],
                level=var["level"], pic=var["pic"], value=var["value"], data_type=var["type"], usage=var["usage"]
            )
            ws_sec.add_child(var_node)
        data_div.add_child(ws_sec)
        ast_root.add_child(data_div)

        # Procedure Division
        proc_div = ASTNode("ProcedureDivision", "PROCEDURE DIVISION", 
                            paragraphs[0]["start_line"] if paragraphs else len(normalized_lines),
                            normalized_lines[-1]["line_num"])
        for p in paragraphs:
            para_node = ASTNode("Paragraph", p["name"], p["start_line"], p["end_line"], chunk_id=f"{filename}::{p['name']}")
            for s in p["statements"]:
                stmt_desc = s["text"][:50] + ("..." if len(s["text"]) > 50 else "")
                stmt_node = ASTNode(
                    f"Statement_{s['stmt_type']}",
                    stmt_desc,
                    s["line"], s["line"],
                    stmt_type=s["stmt_type"],
                    reads=s.get("reads", []),
                    writes=s.get("writes", []),
                    full_text=s["text"]
                )
                para_node.add_child(stmt_node)
            proc_div.add_child(para_node)
        ast_root.add_child(proc_div)

        return {
            "program_id": program_id,
            "filename": filename,
            "line_count": len(raw_lines),
            "chunks": chunks,
            "edges": unique_edges,
            "variables": list(variables.values()),
            "ast": ast_root.to_dict(),
            "diagnostics": diagnostics,
            "copy_inclusions": copy_inclusions
        }

    def _infer_data_type(self, pic: str, val: str, usage: str) -> str:
        """Infers logical high-level type for COBOL data item"""
        if not pic:
            return "GROUP"
        pic_u = pic.upper()
        if "X" in pic_u or "A" in pic_u:
            return "String"
        if "V" in pic_u or "." in pic_u:
            return "BigDecimal"
        if "9" in pic_u:
            digits = sum(int(m) if m else 1 for m in re.findall(r'9(?:\((\d+)\))?', pic_u))
            if digits <= 9 and usage in ("COMP", "COMP-4", "COMP-5", "BINARY"):
                return "int"
            elif digits <= 18:
                return "long"
            return "BigDecimal"
        return "String"

    def _parse_statement(self, text: str, line_num: int) -> Dict[str, Any]:
        """Decomposes an imperative statement into typed AST fields and extracts READ/WRITE sets."""
        clean = text.strip()
        upper = clean.upper()

        stmt_type = "GENERIC"
        reads = []
        writes = []
        target_para = ""
        thru_para = ""
        subprogram = ""

        if upper.startswith("PERFORM"):
            stmt_type = "PERFORM"
            # Matches PERFORM TARGET-PARA [THRU OTHER-PARA]
            m = re.search(r'\bPERFORM\s+([A-Za-z0-9_-]+)(?:\s+THRU\s+([A-Za-z0-9_-]+))?', clean, re.IGNORECASE)
            if m:
                target_para = m.group(1).upper()
                if m.group(2):
                    thru_para = m.group(2).upper()
            
            # Check for PERFORM ... VARYING var FROM val BY val UNTIL cond
            varying_m = re.search(r'\bVARYING\s+([A-Za-z0-9_-]+)\s+FROM\s+([A-Za-z0-9_-]+)\s+BY\s+([A-Za-z0-9_-]+)', clean, re.IGNORECASE)
            if varying_m:
                writes.append(varying_m.group(1).upper())
                reads.extend([varying_m.group(2).upper(), varying_m.group(3).upper()])

            until_m = re.search(r'\bUNTIL\s+(.*)$', clean, re.IGNORECASE)
            if until_m:
                reads.extend(self._extract_identifiers(until_m.group(1)))

        elif upper.startswith("COMPUTE"):
            stmt_type = "COMPUTE"
            # COMPUTE TARGET = EXPR
            m = re.match(r'COMPUTE\s+([A-Za-z0-9_-]+)\s*=\s*(.*)', clean, re.IGNORECASE)
            if m:
                target = m.group(1).upper()
                writes.append(target)
                expr = m.group(2)
                reads.extend(self._extract_identifiers(expr))

        elif upper.startswith("MOVE"):
            stmt_type = "MOVE"
            # MOVE SOURCE TO TARGET [TARGET2 ...]
            m = re.match(r'MOVE\s+(.+?)\s+TO\s+(.+)', clean, re.IGNORECASE)
            if m:
                source_part = m.group(1)
                target_part = m.group(2)
                reads.extend(self._extract_identifiers(source_part))
                for tgt in re.split(r'[\s,]+', target_part):
                    t = tgt.rstrip('.').strip().upper()
                    if t and t not in {"TO", "CORRESPONDING", "CORR"}:
                        writes.append(t)

        elif upper.startswith("ADD"):
            stmt_type = "ADD"
            # ADD X [Y ...] TO TARGET [GIVING RESULT]
            giving_m = re.match(r'ADD\s+(.+?)\s+TO\s+(.+?)\s+GIVING\s+(.+)', clean, re.IGNORECASE)
            if giving_m:
                reads.extend(self._extract_identifiers(giving_m.group(1)))
                reads.extend(self._extract_identifiers(giving_m.group(2)))
                for t in re.split(r'[\s,]+', giving_m.group(3).rstrip('.')):
                    t = t.strip().upper()
                    if t:
                        writes.append(t)
            else:
                m = re.match(r'ADD\s+(.+?)\s+TO\s+(.+)', clean, re.IGNORECASE)
                if m:
                    reads.extend(self._extract_identifiers(m.group(1)))
                    for t in re.split(r'[\s,]+', m.group(2).rstrip('.')):
                        t = t.strip().upper()
                        if t:
                            writes.append(t)
                            reads.append(t)  # target is also read (accumulate)

        elif upper.startswith("SUBTRACT"):
            stmt_type = "SUBTRACT"
            giving_m = re.match(r'SUBTRACT\s+(.+?)\s+FROM\s+(.+?)\s+GIVING\s+(.+)', clean, re.IGNORECASE)
            if giving_m:
                reads.extend(self._extract_identifiers(giving_m.group(1)))
                reads.extend(self._extract_identifiers(giving_m.group(2)))
                for t in re.split(r'[\s,]+', giving_m.group(3).rstrip('.')):
                    t = t.strip().upper()
                    if t:
                        writes.append(t)
            else:
                m = re.match(r'SUBTRACT\s+(.+?)\s+FROM\s+(.+)', clean, re.IGNORECASE)
                if m:
                    reads.extend(self._extract_identifiers(m.group(1)))
                    for t in re.split(r'[\s,]+', m.group(2).rstrip('.')):
                        t = t.strip().upper()
                        if t:
                            writes.append(t)
                            reads.append(t)

        elif upper.startswith("MULTIPLY"):
            stmt_type = "MULTIPLY"
            # MULTIPLY A BY B [GIVING C]
            giving_m = re.match(r'MULTIPLY\s+(.+?)\s+BY\s+(.+?)\s+GIVING\s+(.+)', clean, re.IGNORECASE)
            if giving_m:
                reads.extend(self._extract_identifiers(giving_m.group(1)))
                reads.extend(self._extract_identifiers(giving_m.group(2)))
                writes.extend(self._extract_identifiers(giving_m.group(3)))
            else:
                m = re.match(r'MULTIPLY\s+(.+?)\s+BY\s+(.+)', clean, re.IGNORECASE)
                if m:
                    reads.extend(self._extract_identifiers(m.group(1)))
                    target = m.group(2).rstrip('.').strip().upper()
                    writes.append(target)
                    reads.append(target)

        elif upper.startswith("DIVIDE"):
            stmt_type = "DIVIDE"
            # DIVIDE A INTO B [GIVING C [REMAINDER R]]
            giving_m = re.match(r'DIVIDE\s+(.+?)\s+(?:INTO|BY)\s+(.+?)\s+GIVING\s+(.+)', clean, re.IGNORECASE)
            if giving_m:
                reads.extend(self._extract_identifiers(giving_m.group(1)))
                reads.extend(self._extract_identifiers(giving_m.group(2)))
                rem_m = re.search(r'REMAINDER\s+([A-Za-z0-9_-]+)', giving_m.group(3), re.IGNORECASE)
                if rem_m:
                    writes.append(rem_m.group(1).upper())
                giving_part = re.sub(r'REMAINDER.*', '', giving_m.group(3)).strip()
                writes.extend(self._extract_identifiers(giving_part))
            else:
                m = re.match(r'DIVIDE\s+(.+?)\s+(?:INTO|BY)\s+(.+)', clean, re.IGNORECASE)
                if m:
                    reads.extend(self._extract_identifiers(m.group(1)))
                    target = m.group(2).rstrip('.').strip().upper()
                    writes.append(target)
                    reads.append(target)

        elif upper.startswith("DISPLAY"):
            stmt_type = "DISPLAY"
            # Strip literal strings and extract remaining variable identifiers
            non_strings = re.sub(r'["\'].*?["\']', '', clean)
            reads.extend(self._extract_identifiers(non_strings))

        elif upper.startswith("ACCEPT"):
            stmt_type = "ACCEPT"
            m = re.match(r'ACCEPT\s+([A-Za-z0-9_-]+)', clean, re.IGNORECASE)
            if m:
                writes.append(m.group(1).upper())

        elif upper.startswith("IF") or upper.startswith("ELSE") or upper.startswith("END-IF"):
            stmt_type = "IF_CONTROL"
            non_strings = re.sub(r'["\'].*?["\']', '', clean)
            reads.extend(self._extract_identifiers(non_strings))

        elif upper.startswith("EVALUATE") or upper.startswith("WHEN") or upper.startswith("END-EVALUATE"):
            stmt_type = "EVALUATE"
            non_strings = re.sub(r'["\'].*?["\']', '', clean)
            reads.extend(self._extract_identifiers(non_strings))

        elif upper.startswith("INITIALIZE"):
            stmt_type = "INITIALIZE"
            for tok in clean.split()[1:]:
                t = tok.rstrip('.').upper()
                if t:
                    writes.append(t)

        elif upper.startswith("SET"):
            stmt_type = "SET"
            m = re.match(r'SET\s+(.+?)\s+TO\s+(.+)', clean, re.IGNORECASE)
            if m:
                reads.extend(self._extract_identifiers(m.group(2)))
                writes.extend(self._extract_identifiers(m.group(1)))

        elif upper.startswith("STRING"):
            stmt_type = "STRING"
            into_m = re.search(r'\bINTO\s+([A-Za-z0-9_-]+)', clean, re.IGNORECASE)
            if into_m:
                writes.append(into_m.group(1).upper())
            non_strings = re.sub(r'["\'].*?["\']', '', clean)
            reads.extend(self._extract_identifiers(non_strings))

        elif upper.startswith("CALL"):
            stmt_type = "CALL"
            m = re.search(r'\bCALL\s+["\']([A-Za-z0-9_-]+)["\'](?:\s+USING\s+(.*))?', clean, re.IGNORECASE)
            if m:
                subprogram = m.group(1).upper()
                if m.group(2):
                    reads.extend(self._extract_identifiers(m.group(2)))
            else:
                # CALL with identifier (variable holding program name)
                m2 = re.match(r'CALL\s+([A-Za-z0-9_-]+)', clean, re.IGNORECASE)
                if m2:
                    subprogram = m2.group(1).upper()

        elif upper.startswith("STOP") or upper.startswith("GOBACK") or upper.startswith("EXIT"):
            stmt_type = "TERMINAL"

        elif upper.startswith("CONTINUE"):
            stmt_type = "CONTINUE"

        # Filter out common COBOL noise keywords from read/write lists
        noise = {
            "PERFORM", "THRU", "THROUGH", "COMPUTE", "MOVE", "TO", "DISPLAY",
            "IF", "ELSE", "END-IF", "END-EVALUATE", "END-PERFORM", "END-READ",
            "END-WRITE", "END-CALL", "ADD", "SUBTRACT", "MULTIPLY", "DIVIDE",
            "FROM", "BY", "INTO", "GIVING", "REMAINDER",
            "CALL", "USING", "STOP", "RUN", "GOBACK", "EXIT",
            "VALUE", "PIC", "NOT", "EQUAL", "GREATER", "LESS", "THAN",
            "ZERO", "ZEROS", "ZEROES", "SPACE", "SPACES",
            "HIGH-VALUE", "HIGH-VALUES", "LOW-VALUE", "LOW-VALUES",
            "TRUE", "FALSE", "WHEN", "EVALUATE", "OTHER", "ALSO",
            "SECTION", "VARYING", "UNTIL", "AFTER", "BEFORE", "CONTINUE",
            "INITIALIZE", "INSPECT", "SET", "STRING", "UNSTRING", "ACCEPT",
            "ON", "SIZE", "ERROR", "OVERFLOW", "POINTER"
        }
        reads = [r for r in dict.fromkeys(reads) if r not in noise and not r.isdigit()]
        writes = [w for w in dict.fromkeys(writes) if w not in noise and not w.isdigit()]

        return {
            "line": line_num,
            "text": clean,
            "stmt_type": stmt_type,
            "reads": reads,
            "writes": writes,
            "target_para": target_para,
            "thru_para": thru_para,
            "subprogram": subprogram
        }

    def _extract_identifiers(self, expr: str) -> List[str]:
        """Extracts valid COBOL variable identifiers from an expression string."""
        tokens = re.findall(r'\b[A-Za-z][A-Za-z0-9_-]*\b', expr)
        return [t.upper() for t in tokens]
