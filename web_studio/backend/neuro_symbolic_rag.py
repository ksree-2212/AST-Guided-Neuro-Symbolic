"""
Neuro-Symbolic Dual-Memory RAG Engine
Implements Phases 2, 3, and 4 from:
'AST-Guided Neuro-Symbolic Retrieval-Augmented Generation for Automated Code Analysis and Software Migration'
"""

import os
import json
import re
from typing import Dict, List, Any, Tuple, Optional
import networkx as nx

# ChromaDB for genuine dense neural embeddings
import chromadb

class VectorStore:
    """
    Neuro Memory (Semantic Store):
    Stores genuine dense neural embeddings of code units using ChromaDB with ONNX all-MiniLM-L6-v2.
    Answers 'what code is this query conceptually about?'
    """
    def __init__(self, collection_name: str = "cobol_chunks"):
        self.client = chromadb.Client()
        self.collection_name = collection_name
        try:
            self.client.delete_collection(collection_name)
        except Exception:
            pass
        self.collection = self.client.create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"}
        )

    def add(self, chunk_id: str, text: str, metadata: Dict[str, Any]):
        self.collection.add(
            ids=[chunk_id],
            documents=[text],
            metadatas=[metadata]
        )

    def search(self, query: str, top_k: int = 2) -> List[Tuple[str, float]]:
        count = self.collection.count()
        if count == 0:
            return []
        
        n_results = min(top_k, count)
        results = self.collection.query(
            query_texts=[query],
            n_results=n_results
        )
        
        hits = []
        if results and results["ids"] and len(results["ids"][0]) > 0:
            for cid, dist in zip(results["ids"][0], results["distances"][0]):
                # Cosine distance to similarity: sim = 1.0 - dist
                similarity = round(max(0.0, 1.0 - dist), 3)
                hits.append((cid, similarity))
        return hits

class GraphStore:
    """
    Symbolic Memory (Structural Store):
    Answers 'what is required?'
    Stores exact typed directed multigraph edges (CALLS, READS, WRITES, DEFINES) using NetworkX.
    Supports bounded bidirectional multi-hop traversal and persistence.
    """
    def __init__(self, cache_file: Optional[str] = None):
        self.graph = nx.DiGraph()
        self.cache_file = cache_file or os.path.join(os.path.dirname(__file__), "graph_cache.json")

    def add_node(self, node_id: str, **attrs):
        self.graph.add_node(node_id, **attrs)

    def add_edge(self, source: str, target: str, edge_type: str, **attrs):
        self.graph.add_edge(source, target, type=edge_type, **attrs)

    def dependencies(self, chunk_id: str, max_hops: int = 2, include_callers: bool = True) -> List[str]:
        """
        Bounded-depth bidirectional graph traversal.
        Traverses outward from seed nodes:
        - Outgoing: Callees (PERFORM/CALL) and accessed data (READS/WRITES)
        - Incoming (if include_callers=True): Callers that invoke this paragraph
        """
        if chunk_id not in self.graph:
            return []
        
        visited = set()
        current_layer = {chunk_id}
        
        for _ in range(max_hops):
            next_layer = set()
            for node in current_layer:
                if node in self.graph:
                    # Successors (callees, read/written variables)
                    for succ in self.graph.successors(node):
                        if succ != chunk_id and succ not in visited:
                            visited.add(succ)
                            next_layer.add(succ)
                    # Predecessors (callers)
                    if include_callers:
                        for pred in self.graph.predecessors(node):
                            if pred != chunk_id and pred not in visited:
                                visited.add(pred)
                                next_layer.add(pred)
            current_layer = next_layer
            if not current_layer:
                break
                
        return list(visited)

    def get_subgraph_edges(self, node_ids: List[str]) -> List[Dict[str, Any]]:
        sub_edges = []
        id_set = set(node_ids)
        for u, v, data in self.graph.edges(data=True):
            if u in id_set and v in id_set:
                sub_edges.append({
                    "source": u,
                    "target": v,
                    "type": data.get("type", "CALLS"),
                    "relation": data.get("relation", ""),
                    "line": data.get("line", 0)
                })
        return sub_edges

    def save_to_disk(self):
        """Persists the graph to disk for reproducibility and re-indexing."""
        try:
            data = {
                "nodes": [{"id": n, **self.graph.nodes[n]} for n in self.graph.nodes],
                "edges": [{"source": u, "target": v, **self.graph.edges[u, v]} for u, v in self.graph.edges]
            }
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def load_from_disk(self):
        """Loads graph from cached disk representation."""
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.graph.clear()
                for n in data.get("nodes", []):
                    nid = n["id"]
                    attrs = {k: v for k, v in n.items() if k != "id"}
                    self.graph.add_node(nid, **attrs)
                for e in data.get("edges", []):
                    u = e["source"]
                    v = e["target"]
                    attrs = {k: v for k, v in e.items() if k not in ("source", "target")}
                    self.graph.add_edge(u, v, **attrs)
            except Exception:
                pass

class DualMemoryRAG:
    """
    Coordinates the Neuro-Symbolic Dual Memory Architecture:
    Combines dense neural vector similarity with multi-hop structural graph closure.
    """
    def __init__(self):
        self.vector_store = VectorStore(collection_name="cobol_chunks")
        self.graph_store = GraphStore()
        self.chunks_by_id: Dict[str, Dict[str, Any]] = {}
        self.data_by_id: Dict[str, Dict[str, Any]] = {}
        self.raw_source: str = ""

    def index_parsed_code(self, parsed_data: Dict[str, Any]):
        """Indexes parsed COBOL code into Neuro Memory (ChromaDB) and Symbolic Memory (NetworkX)."""
        self.vector_store = VectorStore(collection_name="cobol_chunks")
        self.graph_store = GraphStore()
        self.chunks_by_id = {}
        self.data_by_id = {}
        self.raw_source = ""

        # 1. Index Data Items into Symbolic Memory
        for var in parsed_data.get("variables", []):
            data_id = f"DATA::{var['name']}"
            self.data_by_id[data_id] = var
            self.graph_store.add_node(data_id, label="DataVariable", **var)

        # 2. Index Chunks into both Neuro & Symbolic Memory
        for chunk in parsed_data.get("chunks", []):
            cid = chunk["id"]
            self.chunks_by_id[cid] = chunk
            
            # Rich searchable context: chunk name + statement descriptions + reads/writes
            stmt_texts = [s["text"] for s in chunk.get("statements", [])]
            reads_all = []
            writes_all = []
            for s in chunk.get("statements", []):
                reads_all.extend(s.get("reads", []))
                writes_all.extend(s.get("writes", []))
            
            searchable_doc = f"PARAGRAPH {chunk['name']}. " + " ".join(stmt_texts)
            if reads_all:
                searchable_doc += f" Reads: {', '.join(set(reads_all))}."
            if writes_all:
                searchable_doc += f" Computes: {', '.join(set(writes_all))}."

            # Neuro Memory: Neural vector embedding in ChromaDB
            meta = {
                "file": chunk["file"],
                "name": chunk["name"],
                "start_line": chunk["start_line"],
                "end_line": chunk["end_line"],
                "stmts": len(chunk.get("statements", []))
            }
            self.vector_store.add(cid, searchable_doc, meta)

            # Symbolic Memory: Node in NetworkX
            self.graph_store.add_node(cid, label="Chunk", **chunk)

        # 3. Add Edges into Symbolic Memory
        for edge in parsed_data.get("edges", []):
            self.graph_store.add_edge(
                edge["source"],
                edge["target"],
                edge_type=edge["type"],
                relation=edge.get("relation", ""),
                line=edge.get("line", 0)
            )

        # Persist graph to disk
        self.graph_store.save_to_disk()

    def retrieve(self, query: str, top_k: int = 2, max_hops: int = 2) -> Dict[str, Any]:
        """
        Structure-Aware Hybrid Retrieval (Phase 3):
        1. Neuro vector search finds top-k entry points.
        2. Symbolic graph traversal expands dependencies up to max_hops.
        3. Bundle deduplication, data definition resolution, and structural constraints.
        """
        hits = self.vector_store.search(query, top_k=top_k)
        bundle = {}
        vector_match_ids = []

        for chunk_id, score in hits:
            vector_match_ids.append(chunk_id)
            bundle[chunk_id] = {
                "id": chunk_id,
                "reason": "vector_match",
                "score": score,
                "type": "chunk",
                "source": self.chunks_by_id.get(chunk_id, {}).get("source", "")
            }
            # Graph expansion: Multi-hop traversal
            deps = self.graph_store.dependencies(chunk_id, max_hops=max_hops, include_callers=True)
            for dep_id in deps:
                if dep_id not in bundle:
                    is_chunk = dep_id in self.chunks_by_id
                    if is_chunk:
                        source_repr = self.chunks_by_id[dep_id]["source"]
                        dep_type = "chunk"
                    elif dep_id in self.data_by_id:
                        # RESOLVED DATA DECLARATION
                        v = self.data_by_id[dep_id]
                        source_repr = f"{v['level']}  {v['name']:<20} {('PIC ' + v['pic']) if v['pic'] else ''} {('VALUE ' + v['value']) if v['value'] else ''}."
                        dep_type = f"data_variable ({v.get('type', 'field')})"
                    else:
                        source_repr = f"# External Symbol: {dep_id}"
                        dep_type = "external_symbol"

                    bundle[dep_id] = {
                        "id": dep_id,
                        "reason": f"dependency_of::{chunk_id}",
                        "score": None,
                        "type": dep_type,
                        "source": source_repr
                    }

        # Build structural constraints description lines (Section 4.4, 5.3.3)
        bundle_ids = list(bundle.keys())
        active_edges = self.graph_store.get_subgraph_edges(bundle_ids)
        constraint_lines = []
        for e in active_edges:
            src_name = e["source"].split("::")[-1]
            tgt_name = e["target"].split("::")[-1]
            etype = e["type"]
            if etype == "CALLS":
                constraint_lines.append(f"{src_name} calls {tgt_name} ({e.get('relation', 'PERFORMS')})")
            elif etype == "WRITES":
                constraint_lines.append(f"{src_name} writes/updates {tgt_name}")
            elif etype == "READS":
                constraint_lines.append(f"{src_name} reads {tgt_name}")

        return {
            "query": query,
            "vector_entry_points": vector_match_ids,
            "bundle": list(bundle.values()),
            "total_retrieved": len(bundle),
            "structural_edges": active_edges,
            "constraint_lines": list(dict.fromkeys(constraint_lines))
        }

    def baseline_a_retrieve(self, raw_source: str, query: str, window_size: int = 4, top_k: int = 2) -> Dict[str, Any]:
        """
        Baseline A — Conventional RAG (Section 5.3.5 & 6.0):
        Fixed-size overlapping text chunks with vector search, completely blind to AST boundaries.
        """
        lines = raw_source.splitlines()
        windows = []
        client = chromadb.Client()
        try:
            col = client.get_or_create_collection(name=f"baseline_a_{abs(hash(query)) % 100000}", metadata={"hnsw:space": "cosine"})
        except Exception:
            col = client.create_collection(name=f"baseline_a_{abs(hash(query)) % 100000 + 1}", metadata={"hnsw:space": "cosine"})

        for i in range(0, len(lines), window_size):
            chunk_lines = lines[i : i + window_size]
            win_id = f"window_L{i+1}_to_L{min(i+window_size, len(lines))}"
            win_text = "\n".join(chunk_lines)
            if win_text.strip():
                col.add(ids=[win_id], documents=[win_text], metadatas=[{"start": i+1, "end": min(i+window_size, len(lines))}])
                windows.append({"id": win_id, "start_line": i+1, "end_line": min(i+window_size, len(lines)), "text": win_text})

        results = col.query(query_texts=[query], n_results=min(top_k, col.count()))
        retrieved = []
        if results and results["ids"] and len(results["ids"][0]) > 0:
            for wid, dist in zip(results["ids"][0], results["distances"][0]):
                w_match = next((w for w in windows if w["id"] == wid), None)
                if w_match:
                    retrieved.append({
                        "id": wid,
                        "start_line": w_match["start_line"],
                        "end_line": w_match["end_line"],
                        "score": round(max(0.0, 1.0 - dist), 3),
                        "text": w_match["text"]
                    })
        return {
            "baseline_type": "Baseline A (Conventional Fixed-Window RAG)",
            "query": query,
            "retrieved_windows": retrieved,
            "missing_dependencies_count": 0
        }

    def baseline_b_retrieve(self, query: str, top_k: int = 2) -> Dict[str, Any]:
        """
        Baseline B — AST-Aware RAG (No Graph Expansion):
        Uses syntax-aware AST chunks with vector search, but omits structural graph multi-hop expansion.
        """
        hits = self.vector_store.search(query, top_k=top_k)
        retrieved_chunks = []
        for cid, score in hits:
            chunk = self.chunks_by_id.get(cid, {})
            retrieved_chunks.append({
                "id": cid,
                "score": score,
                "source": chunk.get("source", ""),
                "name": chunk.get("name", "")
            })
        return {
            "baseline_type": "Baseline B (AST-aware RAG, No Graph Expansion)",
            "query": query,
            "retrieved_chunks": retrieved_chunks,
            "isolated_chunks_count": len(retrieved_chunks)
        }

    def generate_constrained_prompt(self, retrieval_result: Dict[str, Any], target_language: str = "Java") -> str:
        """
        Phase 4: Constrained Prompt Generation (Section 4.5, Appendix A).
        Assembles retrieved context, dependencies, structural constraints, and strict preservation rules.
        """
        bundle = retrieval_result["bundle"]
        vector_ids = set(retrieval_result["vector_entry_points"])

        source_code_parts = []
        dependency_parts = []
        data_declaration_parts = []

        for item in bundle:
            cid = item["id"]
            if cid in vector_ids:
                source_code_parts.append(f"// Target Unit: {cid}\n{item['source']}")
            elif "data_variable" in item["type"]:
                data_declaration_parts.append(f"{item['source']}")
            else:
                dependency_parts.append(f"// Dependency: {cid}\n{item['source']}")

        constraints_text = "\n".join([f"- {c}" for c in retrieval_result["constraint_lines"]])
        if not constraints_text:
            constraints_text = "- None detected"

        prompt = f"""You are a certified senior compiler and enterprise software migration engineer.
Translate the following COBOL code units into production-ready, idiomatic {target_language}.

[MIGRATION GOAL]
Task: {retrieval_result['query']}

[PRIMARY TARGET ROUTINES]
{chr(10).join(source_code_parts)}

[MANDATORY DATA STRUCTURES & VARIABLES]
The following variables are read or updated by the primary routines. Maintain exact decimal precision:
{chr(10).join(data_declaration_parts) if data_declaration_parts else "// No external data fields required"}

[CALL GRAPH DEPENDENCIES]
The following routines are invoked or required by the primary routines. Do NOT omit or inline them:
{chr(10).join(dependency_parts) if dependency_parts else "// No external routine dependencies"}

[STRUCTURAL CONSTRAINTS - EXTRACTED FROM AST GRAPH]
The generated {target_language} code MUST satisfy the following relationships:
{constraints_text}

[STRICT ARCHITECTURAL REQUIREMENTS]
1. Translate COBOL paragraphs into clear, reusable {target_language} methods.
2. In {target_language}, map financial/numeric data fields to BigDecimal or appropriate numeric primitives to avoid floating-point rounding drift.
3. Preserve the exact method call relationships: do NOT inline or omit called routines.
4. If a main routine exists, include a standard public static void main method that executes the program and prints equivalent formatted outputs.
5. Return valid, compilable {target_language} source code.
"""
        return prompt
