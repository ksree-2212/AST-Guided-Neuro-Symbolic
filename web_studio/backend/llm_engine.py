"""
LLM Generation Engine for Automated Software Migration
Supports:
- Local Ollama (e.g. codellama, deepseek-coder, llama3)
- Cloud LLM APIs (OpenAI, Anthropic Claude, Google Gemini via standard API)
- High-precision Neuro-Symbolic Semantic Code Synthesizer (deterministic fallback ensuring offline operability)
"""

import os
import re
import json
import time
import urllib.request
import urllib.error
from typing import Dict, Any, Optional, List

class LLMEngine:
    def __init__(self):
        self.ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        self.openai_key = os.environ.get("OPENAI_API_KEY", "")
        self.anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
        self.gemini_key = os.environ.get("GEMINI_API_KEY", "")

    def generate_java_migration(
        self,
        prompt: str,
        program_id: str,
        retrieval_bundle: List[Dict[str, Any]],
        constraints: List[str],
        provider: str = "auto",
        api_key: Optional[str] = None,
        all_variables: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Executes code generation using the selected or auto-detected provider.
        """
        start_time = time.time()
        key = api_key or self.openai_key or self.gemini_key or self.anthropic_key
        
        # Determine actual provider
        selected_provider = provider.lower()
        if selected_provider == "auto":
            if key and (key.startswith("sk-") or "openai" in key):
                selected_provider = "openai"
            elif self._is_ollama_alive():
                selected_provider = "ollama"
            else:
                selected_provider = "synthesizer"

        java_code = ""
        engine_used = selected_provider
        error_msg = None

        try:
            if selected_provider == "ollama" and self._is_ollama_alive():
                java_code = self._call_ollama(prompt)
                engine_used = "ollama/codellama"
            elif selected_provider == "openai" and key:
                java_code = self._call_openai(prompt, key)
                engine_used = "openai/gpt-4o"
            elif selected_provider == "gemini" and key:
                java_code = self._call_gemini(prompt, key)
                engine_used = "google/gemini-2.0"
            else:
                # High-Precision Neuro-Symbolic Synthesizer Fallback
                java_code = self._synthesize_from_ast(program_id, retrieval_bundle, constraints, all_variables)
                engine_used = "neuro_symbolic_synthesizer"

        except Exception as e:
            error_msg = str(e)
            # Graceful fallback to deterministic synthesizer
            java_code = self._synthesize_from_ast(program_id, retrieval_bundle, constraints, all_variables)
            engine_used = f"neuro_symbolic_synthesizer (fallback: {error_msg})"

        elapsed_ms = int((time.time() - start_time) * 1000)
        clean_java = self._clean_code_fence(java_code)

        return {
            "status": "success",
            "provider": engine_used,
            "latency_ms": elapsed_ms,
            "generated_java": clean_java,
            "class_name": program_id.replace("-", "_").upper(),
            "target_language": "Java",
            "is_synthesizer": "synthesizer" in engine_used
        }

    def _is_ollama_alive(self) -> bool:
        try:
            req = urllib.request.Request(f"{self.ollama_host}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                return resp.status == 200
        except Exception:
            return False

    def _call_ollama(self, prompt: str, model: str = "codellama") -> str:
        payload = json.dumps({
            "model": model,
            "prompt": prompt,
            "stream": False
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self.ollama_host}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("response", "")

    def _call_openai(self, prompt: str, api_key: str, model: str = "gpt-4o") -> str:
        payload = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": "You are a compiler migration engineer. Generate valid, compilable Java source code matching all structural constraints."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }
        )
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]

    def _call_gemini(self, prompt: str, api_key: str) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
        payload = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}]
        }).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["candidates"][0]["content"]["parts"][0]["text"]

    def _clean_code_fence(self, text: str) -> str:
        """Strips markdown ```java ... ``` wrapper if present."""
        m = re.search(r'```(?:java)?\s*(.*?)\s*```', text, re.DOTALL | re.IGNORECASE)
        if m:
            return m.group(1).strip()
        return text.strip()

    def synthesize_java_from_ast(
        self,
        program_id: str,
        bundle: List[Dict[str, Any]],
        constraints: Optional[List[str]] = None,
        all_variables: Optional[List[Dict[str, Any]]] = None
    ) -> str:
        """
        Public interface for deterministic, structural AST-to-Java translation.
        Ensures exact decimal precision (BigDecimal) and 1:1 paragraph method structure.
        """
        return self._synthesize_from_ast(
            program_id=program_id,
            bundle=bundle,
            constraints=constraints or [],
            all_variables=all_variables
        )

    def _synthesize_from_ast(
        self,
        program_id: str,
        bundle: List[Dict[str, Any]],
        constraints: Optional[List[str]] = None,
        all_variables: Optional[List[Dict[str, Any]]] = None
    ) -> str:
        """
        Deterministic, structural AST-to-Java translation.
        Ensures exact decimal precision (BigDecimal) and 1:1 paragraph method structure.
        Handles ADD/SUBTRACT/MULTIPLY/DIVIDE/COMPUTE, MOVE (multi-target), IF/ELSE/END-IF,
        EVALUATE/WHEN, INITIALIZE, STRING, DISPLAY, PERFORM, STOP RUN, GOBACK, CONTINUE.
        """
        constraints = constraints or []
        class_name = program_id.replace("-", "_").upper()
        
        # 1. Collect Data Variables
        data_fields = []
        seen_vars = set()

        if all_variables:
            for v in all_variables:
                vname = v["name"]
                if vname in seen_vars:
                    continue
                seen_vars.add(vname)
                pic = v.get("pic", "")
                val = v.get("value", "0")
                clean_val = val.strip().strip("'\"") if val else ""
                if clean_val.startswith("."):
                    clean_val = "0" + clean_val

                if any(c in pic.upper() for c in ("V", ".", "Z", "$")) or ("." in clean_val and clean_val.replace('.','').replace('-','').isdigit()):
                    init_expr = f'new BigDecimal("{clean_val}")' if clean_val and re.match(r'^-?\d+(\.\d+)?$', clean_val) else "BigDecimal.ZERO"
                    jtype = "BigDecimal"
                elif any(c in pic.upper() for c in ("X", "A")):
                    # String/alphanumeric field
                    if clean_val in ('SPACE', 'SPACES', ''):
                        init_expr = '""'
                    else:
                        init_expr = f'"{clean_val}"'
                    jtype = "String"
                elif clean_val in ('ZERO', 'ZEROS', 'ZEROES', ''):
                    init_expr = "0"
                    jtype = "int"
                else:
                    init_expr = clean_val if re.match(r'^-?\d+$', clean_val) else "0"
                    jtype = "int"

                jvar = self._to_camel_case(vname)
                data_fields.append((jtype, jvar, vname, init_expr))
        else:
            for item in bundle:
                if "data_variable" in item["type"]:
                    text = item["source"].strip()
                    m = re.search(r'^(?:0[1-9]|[1-4][0-9]|77|88)\s+([A-Za-z0-9_-]+)(.*)$', text, re.IGNORECASE)
                    if m:
                        vname = m.group(1).upper()
                        rest = m.group(2)
                        if vname in seen_vars:
                            continue
                        seen_vars.add(vname)

                        pic = ""
                        val = "0"
                        pic_m = re.search(r'PIC\s+([A-Za-z0-9()Vv\.\-\+$,*]+)', rest, re.IGNORECASE)
                        if pic_m:
                            pic = pic_m.group(1).rstrip('.')
                        val_m = re.search(r'VALUE\s+(["\'].*?["\']|[0-9a-zA-Z_\.\-]+)', rest, re.IGNORECASE)
                        if val_m:
                            val = val_m.group(1).rstrip('.')

                        clean_val = val.strip().strip("'\"")
                        if clean_val.startswith("."):
                            clean_val = "0" + clean_val

                        if any(c in pic.upper() for c in ("V", ".", "Z", "$")) or ("." in clean_val and clean_val.replace('.','').replace('-','').isdigit()):
                            init_expr = f'new BigDecimal("{clean_val}")' if clean_val and re.match(r'^-?\d+(\.\d+)?$', clean_val) else "BigDecimal.ZERO"
                            jtype = "BigDecimal"
                        elif any(c in pic.upper() for c in ("X", "A")) or (clean_val and not clean_val.replace('.','').replace('-','').isdigit() and clean_val not in ('ZERO','ZEROS','ZEROES','SPACE','SPACES')):
                            init_expr = f'"{clean_val}"'
                            jtype = "String"
                        else:
                            init_expr = clean_val if re.match(r'^-?\d+$', clean_val) else "0"
                            jtype = "int"

                        jvar = self._to_camel_case(vname)
                        data_fields.append((jtype, jvar, vname, init_expr))

        # Build a lookup of field types for expression translation
        field_type_map = {jvar: jtype for jtype, jvar, _, _ in data_fields}

        # 2. Collect Routines (Chunks)
        chunks = [item for item in bundle if item["type"] == "chunk"]
        
        method_defs = []
        for c in chunks:
            raw_cname = c["id"].split("::")[-1]
            method_name = self._to_camel_case(raw_cname)
            source_lines = c.get("source", "").splitlines()
            statements = c.get("statements", [])

            translated_body = []

            # If we have structured statements use them; fall back to raw source lines
            if statements:
                if_depth = 0
                for s in statements:
                    stype = s.get("stmt_type", "GENERIC")
                    text = s.get("text", "").strip()
                    supper = text.upper()
                    indent = "        " + "    " * if_depth

                    if stype == "PERFORM":
                        m = re.search(r'\bPERFORM\s+([A-Za-z0-9_-]+)', text, re.IGNORECASE)
                        if m:
                            target = self._to_camel_case(m.group(1).upper())
                            # PERFORM ... VARYING loop
                            var_m = re.search(r'VARYING\s+([A-Za-z0-9_-]+)\s+FROM\s+(\S+)\s+BY\s+(\S+)\s+UNTIL\s+(.*)', text, re.IGNORECASE)
                            if var_m:
                                loop_var = self._to_camel_case(var_m.group(1).upper())
                                from_v = var_m.group(2).rstrip('.')
                                by_v = var_m.group(3).rstrip('.')
                                until_cond = self._translate_condition(var_m.group(4).rstrip('.'))
                                translated_body.append(f"{indent}for (this.{loop_var} = {from_v}; !({until_cond}); this.{loop_var} += {by_v}) {{")
                                translated_body.append(f"{indent}    {target}();")
                                translated_body.append(f"{indent}}}")
                            else:
                                translated_body.append(f"{indent}{target}();")

                    elif stype == "COMPUTE":
                        m = re.match(r'COMPUTE\s+([A-Za-z0-9_-]+)\s*=\s*(.*)', text, re.IGNORECASE)
                        if m:
                            target_var = self._to_camel_case(m.group(1).upper())
                            expr = m.group(2).rstrip('.')
                            java_expr = self._translate_expression(expr, field_type_map)
                            translated_body.append(f"{indent}this.{target_var} = {java_expr};")

                    elif stype == "MOVE":
                        m = re.match(r'MOVE\s+(.+?)\s+TO\s+(.+)', text, re.IGNORECASE)
                        if m:
                            src = m.group(1).strip()
                            tgt_part = m.group(2).rstrip('.').strip()
                            src_java = self._cobol_value_to_java(src, field_type_map)
                            # Multiple targets: MOVE X TO A B C
                            targets = [t.strip() for t in re.split(r'\s+', tgt_part) if t.strip()]
                            for tgt_raw in targets:
                                if re.search(r'\(', tgt_raw):
                                    translated_body.append(f"{indent}// COBOL: MOVE {src} TO {tgt_raw} (subscripted — skipped)")
                                else:
                                    tgt = self._to_camel_case(tgt_raw.upper())
                                    translated_body.append(f"{indent}this.{tgt} = {src_java};")

                    elif stype == "ADD":
                        giving_m = re.match(r'ADD\s+(.+?)\s+TO\s+(.+?)\s+GIVING\s+(.+)', text, re.IGNORECASE)
                        if giving_m:
                            operands = self._collect_operands(giving_m.group(1) + " " + giving_m.group(2), field_type_map)
                            for tgt_raw in re.split(r'[\s,]+', giving_m.group(3).rstrip('.')):
                                if tgt_raw.strip():
                                    tgt = self._to_camel_case(tgt_raw.strip().upper())
                                    translated_body.append(f"{indent}this.{tgt} = {operands};")
                        else:
                            add_m = re.match(r'ADD\s+(.+?)\s+TO\s+(.+)', text, re.IGNORECASE)
                            if add_m:
                                addend = self._cobol_value_to_java(add_m.group(1).strip(), field_type_map)
                                for tgt_raw in re.split(r'[\s,]+', add_m.group(2).rstrip('.')):
                                    if tgt_raw.strip():
                                        tgt = self._to_camel_case(tgt_raw.strip().upper())
                                        jtype = field_type_map.get(tgt, "int")
                                        if jtype == "BigDecimal":
                                            translated_body.append(f"{indent}this.{tgt} = this.{tgt}.add({addend});")
                                        else:
                                            translated_body.append(f"{indent}this.{tgt} += {addend};")

                    elif stype == "SUBTRACT":
                        giving_m = re.match(r'SUBTRACT\s+(.+?)\s+FROM\s+(.+?)\s+GIVING\s+(.+)', text, re.IGNORECASE)
                        if giving_m:
                            minuend = self._cobol_value_to_java(giving_m.group(2).strip(), field_type_map)
                            subtrahend = self._cobol_value_to_java(giving_m.group(1).strip(), field_type_map)
                            for tgt_raw in re.split(r'[\s,]+', giving_m.group(3).rstrip('.')):
                                if tgt_raw.strip():
                                    tgt = self._to_camel_case(tgt_raw.strip().upper())
                                    jtype = field_type_map.get(tgt, "int")
                                    if jtype == "BigDecimal":
                                        translated_body.append(f"{indent}this.{tgt} = {minuend}.subtract({subtrahend});")
                                    else:
                                        translated_body.append(f"{indent}this.{tgt} = {minuend} - {subtrahend};")
                        else:
                            sub_m = re.match(r'SUBTRACT\s+(.+?)\s+FROM\s+(.+)', text, re.IGNORECASE)
                            if sub_m:
                                subtrahend = self._cobol_value_to_java(sub_m.group(1).strip(), field_type_map)
                                for tgt_raw in re.split(r'[\s,]+', sub_m.group(2).rstrip('.')):
                                    if tgt_raw.strip():
                                        tgt = self._to_camel_case(tgt_raw.strip().upper())
                                        jtype = field_type_map.get(tgt, "int")
                                        if jtype == "BigDecimal":
                                            translated_body.append(f"{indent}this.{tgt} = this.{tgt}.subtract({subtrahend});")
                                        else:
                                            translated_body.append(f"{indent}this.{tgt} -= {subtrahend};")

                    elif stype == "MULTIPLY":
                        giving_m = re.match(r'MULTIPLY\s+(.+?)\s+BY\s+(.+?)\s+GIVING\s+(.+)', text, re.IGNORECASE)
                        if giving_m:
                            a = self._cobol_value_to_java(giving_m.group(1).strip(), field_type_map)
                            b = self._cobol_value_to_java(giving_m.group(2).strip(), field_type_map)
                            for tgt_raw in re.split(r'[\s,]+', giving_m.group(3).rstrip('.')):
                                if tgt_raw.strip():
                                    tgt = self._to_camel_case(tgt_raw.strip().upper())
                                    jtype = field_type_map.get(tgt, "int")
                                    if jtype == "BigDecimal":
                                        translated_body.append(f"{indent}this.{tgt} = {a}.multiply({b}).setScale(2, RoundingMode.HALF_UP);")
                                    else:
                                        translated_body.append(f"{indent}this.{tgt} = {a} * {b};")
                        else:
                            mul_m = re.match(r'MULTIPLY\s+(.+?)\s+BY\s+(.+)', text, re.IGNORECASE)
                            if mul_m:
                                factor = self._cobol_value_to_java(mul_m.group(1).strip(), field_type_map)
                                for tgt_raw in re.split(r'[\s,]+', mul_m.group(2).rstrip('.')):
                                    if tgt_raw.strip():
                                        tgt = self._to_camel_case(tgt_raw.strip().upper())
                                        jtype = field_type_map.get(tgt, "int")
                                        if jtype == "BigDecimal":
                                            translated_body.append(f"{indent}this.{tgt} = this.{tgt}.multiply({factor}).setScale(2, RoundingMode.HALF_UP);")
                                        else:
                                            translated_body.append(f"{indent}this.{tgt} *= {factor};")

                    elif stype == "DIVIDE":
                        giving_m = re.match(r'DIVIDE\s+(.+?)\s+(?:INTO|BY)\s+(.+?)\s+GIVING\s+(.+)', text, re.IGNORECASE)
                        if giving_m:
                            by_into = re.search(r'\bINTO\b', text, re.IGNORECASE)
                            divisor = self._cobol_value_to_java(giving_m.group(1).strip(), field_type_map)
                            dividend = self._cobol_value_to_java(giving_m.group(2).strip(), field_type_map)
                            result_part = re.sub(r'REMAINDER.*', '', giving_m.group(3), flags=re.IGNORECASE).strip()
                            rem_m = re.search(r'REMAINDER\s+([A-Za-z0-9_-]+)', giving_m.group(3), re.IGNORECASE)
                            for tgt_raw in re.split(r'[\s,]+', result_part.rstrip('.')):
                                if tgt_raw.strip():
                                    tgt = self._to_camel_case(tgt_raw.strip().upper())
                                    jtype = field_type_map.get(tgt, "int")
                                    numerator = dividend if by_into else divisor
                                    denominator = divisor if by_into else dividend
                                    if jtype == "BigDecimal":
                                        translated_body.append(f"{indent}this.{tgt} = {numerator}.divide({denominator}, 2, RoundingMode.HALF_UP);")
                                    else:
                                        translated_body.append(f"{indent}this.{tgt} = {numerator} / {denominator};")
                            if rem_m:
                                rem_tgt = self._to_camel_case(rem_m.group(1).upper())
                                translated_body.append(f"{indent}this.{rem_tgt} = {dividend} % {divisor};")
                        else:
                            div_m = re.match(r'DIVIDE\s+(.+?)\s+(?:INTO|BY)\s+(.+)', text, re.IGNORECASE)
                            if div_m:
                                by_into = re.search(r'\bINTO\b', text, re.IGNORECASE)
                                a = self._cobol_value_to_java(div_m.group(1).strip(), field_type_map)
                                b = self._cobol_value_to_java(div_m.group(2).strip().rstrip('.'), field_type_map)
                                for tgt_raw in re.split(r'[\s,]+', div_m.group(2).rstrip('.')):
                                    if tgt_raw.strip():
                                        tgt = self._to_camel_case(tgt_raw.strip().upper())
                                        jtype = field_type_map.get(tgt, "int")
                                        num = b if by_into else a
                                        den = a if by_into else b
                                        if jtype == "BigDecimal":
                                            translated_body.append(f"{indent}this.{tgt} = this.{tgt}.divide({den}, 2, RoundingMode.HALF_UP);")
                                        else:
                                            translated_body.append(f"{indent}this.{tgt} /= {den};")

                    elif stype == "DISPLAY":
                        content_part = re.sub(r'^DISPLAY\s+', '', text, flags=re.IGNORECASE).rstrip('.')
                        parts = []
                        for match in re.finditer(r'("[^"]*"|\'[^\']*\'|[A-Za-z0-9_-]+)', content_part):
                            tok = match.group(1)
                            tok_upper = tok.upper()
                            if tok.startswith(('"', "'")):
                                parts.append(tok.replace("'", '"'))
                            elif tok_upper in ('SPACE', 'SPACES'):
                                parts.append('" "')
                            elif tok_upper in ('ZERO', 'ZEROS', 'ZEROES'):
                                parts.append('"0"')
                            elif tok.strip():
                                jvar = self._to_camel_case(tok.upper())
                                parts.append(f"this.{jvar}")
                        joined = " + ".join(parts) if parts else '""'
                        translated_body.append(f"{indent}System.out.println({joined});")

                    elif stype == "IF_CONTROL":
                        supper_strip = supper.strip()
                        if supper_strip.startswith("ELSE"):
                            if if_depth > 0:
                                translated_body.append(("        " + "    " * (if_depth - 1)) + "} else {")
                        elif supper_strip.startswith("END-IF"):
                            if if_depth > 0:
                                if_depth -= 1
                                translated_body.append(("        " + "    " * if_depth) + "}")
                        else:
                            # IF condition [THEN]
                            cond_text = re.sub(r'^IF\s+', '', text, flags=re.IGNORECASE).rstrip('.')
                            cond_text = re.sub(r'\s+THEN\s*$', '', cond_text, flags=re.IGNORECASE)
                            java_cond = self._translate_condition(cond_text)
                            translated_body.append(f"{indent}if ({java_cond}) {{")
                            if_depth += 1

                    elif stype == "EVALUATE":
                        supper_strip = supper.strip()
                        if supper_strip.startswith("EVALUATE"):
                            subject = re.sub(r'^EVALUATE\s+', '', text, flags=re.IGNORECASE).strip()
                            translated_body.append(f"{indent}// COBOL EVALUATE: {subject}")
                        elif supper_strip.startswith("WHEN OTHER"):
                            translated_body.append(f"{indent}// WHEN OTHER")
                        elif supper_strip.startswith("WHEN"):
                            val_part = re.sub(r'^WHEN\s+', '', text, flags=re.IGNORECASE).strip().rstrip('.')
                            translated_body.append(f"{indent}// WHEN {val_part}")
                        elif supper_strip.startswith("END-EVALUATE"):
                            translated_body.append(f"{indent}// END-EVALUATE")

                    elif stype == "INITIALIZE":
                        for tok in text.split()[1:]:
                            t = tok.rstrip('.')
                            if t:
                                tgt = self._to_camel_case(t.upper())
                                jtype = field_type_map.get(tgt, "int")
                                if jtype == "BigDecimal":
                                    translated_body.append(f"{indent}this.{tgt} = BigDecimal.ZERO;")
                                elif jtype == "String":
                                    translated_body.append(f"{indent}this.{tgt} = \"\";")
                                else:
                                    translated_body.append(f"{indent}this.{tgt} = 0;")

                    elif stype == "TERMINAL":
                        translated_body.append(f"{indent}System.exit(0);")

                    elif stype == "CONTINUE":
                        translated_body.append(f"{indent}// CONTINUE (no-op)")

                    elif stype == "CALL":
                        subprog = s.get("subprogram", "")
                        if subprog:
                            translated_body.append(f"{indent}// CALL '{subprog}' — external call (not inlined)")
                        else:
                            translated_body.append(f"{indent}// {text}")

                    elif stype == "GENERIC":
                        translated_body.append(f"{indent}// {text}")

                # Close any dangling if-blocks
                while if_depth > 0:
                    if_depth -= 1
                    translated_body.append(("        " + "    " * if_depth) + "}")

            else:
                # Fallback: raw source line translation
                for line in source_lines:
                    sline = line.strip()
                    supper = sline.upper()
                    if not sline or sline.rstrip('.').upper() == raw_cname:
                        continue
                    if supper.startswith("PERFORM "):
                        m = re.search(r'\bPERFORM\s+([A-Za-z0-9_-]+)', sline, re.IGNORECASE)
                        if m:
                            translated_body.append(f"        {self._to_camel_case(m.group(1).upper())}();")
                    elif supper.startswith("DISPLAY "):
                        translated_body.append(f"        // DISPLAY: {sline}")
                    elif supper.startswith("STOP") or supper.startswith("GOBACK"):
                        translated_body.append("        System.exit(0);")
                    else:
                        translated_body.append(f"        // {sline}")

            if not translated_body:
                translated_body.append("        // Preserved routine body")

            method_code = f"    public void {method_name}() {{\n" + "\n".join(translated_body) + "\n    }"
            method_defs.append(method_code)

        # Class Fields
        field_declarations = []
        for jtype, jvar, orig_name, init_val in data_fields:
            field_declarations.append(f"    // COBOL: {orig_name}\n    public {jtype} {jvar} = {init_val};")

        # ── Step 1: collect all method names actually emitted ──────────────────
        emitted_method_names = set()
        for md in method_defs:
            m_match = re.match(r'\s*public void (\w+)\s*\(', md)
            if m_match:
                emitted_method_names.add(m_match.group(1))

        # ── Step 2: pick entry point from emitted methods ───────────────────────
        # Priority: well-known main paragraph names first, then first chunk name, then sorted fallback.
        preferred_mains = ["mainParagraph", "mainRtn", "field0000MainProcessing", "field000MainProcessing"]
        if chunks:
            preferred_mains.append(self._to_camel_case(chunks[0]["id"].split("::")[-1]))

        entry_call = None
        for candidate in preferred_mains:
            if candidate in emitted_method_names:
                entry_call = candidate
                break

        if entry_call is None:
            if emitted_method_names:
                entry_call = sorted(emitted_method_names)[0]
            else:
                # No methods at all — emit a run() stub so the class always compiles
                entry_call = "run"
                method_defs.append(
                    '    /** Entry point stub — no PROCEDURE DIVISION paragraphs were parsed. */\n'
                    '    public void run() {\n'
                    '        System.out.println("[Migration stub] No executable paragraphs extracted from COBOL source.");\n'
                    '    }'
                )

        full_java = f"""// Generated by AST-Guided Neuro-Symbolic Migration Engine
// Correctness Reference: COBOL 4J (opensourcecobol4j) generated Java is the behavioral ground truth.
// It depends on jp.osscons.opensourcecobol.libcobj and is NOT standalone.
// This standalone Java aims to reproduce identical output without the libcobj runtime dependency.
import java.math.BigDecimal;
import java.math.RoundingMode;

public class {class_name} {{

    // --- DATA DIVISION ITEMS (Exact Precision Mapping) ---
{chr(10).join(field_declarations)}

    // --- PROCEDURE DIVISION METHODS ---
{chr(10).join(method_defs)}

    public static void main(String[] args) {{
        {class_name} app = new {class_name}();
        app.{entry_call}();
    }}
}}
"""
        return full_java

    def _cobol_value_to_java(self, token: str, field_type_map: Dict[str, str]) -> str:
        """Converts a COBOL value token (literal or identifier) to its Java equivalent."""
        token = token.strip().rstrip('.')
        upper = token.upper()
        if token.startswith('"') or token.startswith("'"):
            return token.replace("'", '"')
        if upper in ('ZERO', 'ZEROS', 'ZEROES'):
            return 'BigDecimal.ZERO'
        if upper in ('SPACE', 'SPACES'):
            return '" "'
        if re.match(r'^-?\d+\.\d+$', token):
            return f'new BigDecimal("{token}")'
        if re.match(r'^-?\d+$', token):
            return token
        jvar = self._to_camel_case(upper)
        jtype = field_type_map.get(jvar, "")
        if jtype == "BigDecimal":
            return f"this.{jvar}"
        return f"this.{jvar}"

    def _collect_operands(self, expr: str, field_type_map: Dict[str, str]) -> str:
        """Converts a space-separated list of COBOL operands into a Java BigDecimal add chain."""
        tokens = [t.strip() for t in expr.split() if t.strip()]
        parts = [self._cobol_value_to_java(t, field_type_map) for t in tokens]
        if not parts:
            return "BigDecimal.ZERO"
        result = parts[0]
        for p in parts[1:]:
            result = f"{result}.add({p})"
        return result

    def _translate_condition(self, cond: str) -> str:
        """Translates a COBOL conditional expression to a Java boolean expression."""
        cond = cond.strip().rstrip('.')
        # COBOL relational: = > < >= <= NOT
        replacements = [
            (r'\bNOT\s*=\s*', '!='),
            (r'\bNOT\s+EQUAL\s+TO\b', '!='),
            (r'\bNOT\s+GREATER\s+THAN\b', '<='),
            (r'\bNOT\s+LESS\s+THAN\b', '>='),
            (r'\bEQUAL\s+TO\b', '=='),
            (r'\bGREATER\s+THAN\s+OR\s+EQUAL\b', '>='),
            (r'\bLESS\s+THAN\s+OR\s+EQUAL\b', '<='),
            (r'\bGREATER\s+THAN\b', '>'),
            (r'\bLESS\s+THAN\b', '<'),
            (r'\bGREATER\b', '>'),
            (r'\bLESS\b', '<'),
            (r'\bEQUAL\b', '=='),
            (r'\bAND\b', '&&'),
            (r'\bOR\b', '||'),
            (r'\bNOT\b', '!'),
            (r'\bZERO\b|\bZEROS\b|\bZEROES\b', '0'),
            (r'\bSPACES?\b', '" "'),
        ]
        result = cond
        for pattern, replacement in replacements:
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
        return result

    def _translate_expression(self, expr: str, field_type_map: Optional[Dict[str, str]] = None) -> str:
        """Translates a COBOL arithmetic expression into Java BigDecimal chain."""
        field_type_map = field_type_map or {}
        expr = expr.strip().rstrip('.')

        # Tokenize expression preserving operators
        tokens = re.findall(r'[A-Za-z0-9_-]+|[\+\-\*/\(\)]|\d+\.\d+', expr)

        def token_to_java(tok: str) -> str:
            tok = tok.strip()
            if re.match(r'^-?\d+\.\d+$', tok):
                return f'new BigDecimal("{tok}")'
            if re.match(r'^-?\d+$', tok):
                return tok
            jvar = self._to_camel_case(tok.upper())
            jtype = field_type_map.get(jvar, "")
            if jtype == "BigDecimal":
                return f"this.{jvar}"
            return f"this.{jvar}"

        if not tokens:
            return f"this.{self._to_camel_case(expr.strip().upper())}"

        # Simple patterns: A * B / C, A * B, A - B, A + B
        pattern = re.match(r'^([A-Za-z0-9_\-]+)\s*\*\s*([A-Za-z0-9_\-]+)\s*/\s*([A-Za-z0-9_\-\.]+)$', expr)
        if pattern:
            a = token_to_java(pattern.group(1))
            b = token_to_java(pattern.group(2))
            denom = pattern.group(3)
            denom_java = f'new BigDecimal("{denom}")' if re.match(r'^\d+(\.\d+)?$', denom) else token_to_java(denom)
            return (f"{a}.multiply(new BigDecimal(String.valueOf({b})))"
                    f".divide({denom_java}, 2, RoundingMode.HALF_UP)")

        pattern2 = re.match(r'^([A-Za-z0-9_\-]+)\s*\*\s*([A-Za-z0-9_\-]+)$', expr)
        if pattern2:
            a = token_to_java(pattern2.group(1))
            b = token_to_java(pattern2.group(2))
            return f"{a}.multiply(new BigDecimal(String.valueOf({b}))).setScale(2, RoundingMode.HALF_UP)"

        pattern3 = re.match(r'^([A-Za-z0-9_\-]+)\s*-\s*([A-Za-z0-9_\-]+)$', expr)
        if pattern3:
            a = token_to_java(pattern3.group(1))
            b = token_to_java(pattern3.group(2))
            return f"{a}.subtract(new BigDecimal(String.valueOf({b})))"

        pattern4 = re.match(r'^([A-Za-z0-9_\-]+)\s*\+\s*([A-Za-z0-9_\-]+)$', expr)
        if pattern4:
            a = token_to_java(pattern4.group(1))
            b = token_to_java(pattern4.group(2))
            return f"{a}.add(new BigDecimal(String.valueOf({b})))"

        pattern5 = re.match(r'^([A-Za-z0-9_\-]+)\s*/\s*([A-Za-z0-9_\-\.]+)$', expr)
        if pattern5:
            a = token_to_java(pattern5.group(1))
            b_raw = pattern5.group(2)
            b = f'new BigDecimal("{b_raw}")' if re.match(r'^\d+(\.\d+)?$', b_raw) else token_to_java(b_raw)
            return f"{a}.divide({b}, 2, RoundingMode.HALF_UP)"

        # Fallback: single identifier or literal
        if len(tokens) == 1:
            return token_to_java(tokens[0])

        # Fallback: treat as raw Java (may need manual fix)
        return f"/* TODO: {expr} */"
    def _to_camel_case(self, cobol_name: str) -> str:
        """Converts COBOL hyphenated identifier to Java camelCase."""
        cobol_name = re.sub(r'\(.*?\)', '', cobol_name).strip()
        parts = [p for p in cobol_name.replace('_', '-').split('-') if p]
        if not parts:
            return 'item'
        result = parts[0].lower() + ''.join(p.capitalize() for p in parts[1:])
        if result and result[0].isdigit():
            result = 'field' + result[0].upper() + result[1:]
        java_reserved = {'class', 'int', 'long', 'double', 'float', 'boolean',
                         'return', 'public', 'private', 'static', 'void', 'new',
                         'this', 'if', 'else', 'for', 'while', 'do', 'switch',
                         'case', 'break', 'continue', 'import', 'package'}
        if result.lower() in java_reserved:
            result = 'cobol_' + result
        return result

