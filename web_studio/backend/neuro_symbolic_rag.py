"""
Neuro-Symbolic Dual-Memory RAG Engine
Implements Phases 2, 3, and 4 from:
'AST-Guided Neuro-Symbolic Retrieval-Augmented Generation for Automated Code Analysis and Software Migration'
(Surya Nallam, CBIT)
"""

import re
import zlib
from typing import Dict, List, Any, Tuple, Optional
import numpy as np
import networkx as nx

def embed_text(text: str, dim: int = 128) -> np.ndarray:
    """
    Deterministic full-dimensional dense projection embedding
    as defined in Section 5.3.2 of the research paper.
    Uses zlib.crc32 seeding to ensure reproducibility without requiring an external model.
    """
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text.lower())
    vec = np.zeros(dim, dtype=np.float32)
    for tok in tokens:
        seed = zlib.crc32(tok.encode())
        rng = np.random.RandomState(seed)
        vec += rng.normal(size=dim).astype(np.float32)
    norm = np.linalg.norm(vec)
    return vec / norm if norm > 0 else vec

class VectorStore:
    """
    Neuro Memory (Semantic):
    Answers 'what code is this query conceptually about?'
    Stores dense embeddings of chunks and retrieves top-k closest matches by cosine similarity.
    """
    def __init__(self, dim: int = 128):
        self.dim = dim
        self.chunk_ids: List[str] = []
        self.embeddings: List[np.ndarray] = []

    def add(self, chunk_id: str, text: str):
        vec = embed_text(text, self.dim)
        self.chunk_ids.append(chunk_id)
        self.embeddings.append(vec)

    def search(self, query: str, top_k: int = 2) -> List[Tuple[str, float]]:
        if not self.embeddings:
            return []
        q_vec = embed_text(query, self.dim)
        scores = []
        for cid, emb in zip(self.chunk_ids, self.embeddings):
            sim = float(np.dot(q_vec, emb))
            scores.append((cid, sim))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

class GraphStore:
    """
    Symbolic Memory (Structural):
    Answers 'what is required?'
    Stores exact typed directed edges (CALLS, DEPENDS_ON) using NetworkX.
    Traverses dependencies up to max_hops.
    """
    def __init__(self):
        self.graph = nx.DiGraph()

    def add_node(self, node_id: str, **attrs):
        self.graph.add_node(node_id, **attrs)

    def add_edge(self, source: str, target: str, edge_type: str = "CALLS", **attrs):
        self.graph.add_edge(source, target, type=edge_type, **attrs)

    def dependencies(self, chunk_id: str, max_hops: int = 2) -> List[str]:
        """
        Bounded-depth graph traversal (Section 4.4, Figure 4.2).
        Expands outward from the entry point node along CALLS & DEPENDS_ON edges.
        """
        if chunk_id not in self.graph:
            return []
        
        visited = set()
        current_layer = {chunk_id}
        
        for _ in range(max_hops):
            next_layer = set()
            for node in current_layer:
                if node in self.graph:
                    for succ in self.graph.successors(node):
                        if succ != chunk_id and succ not in visited:
                            visited.add(succ)
                            next_layer.add(succ)
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
                    "relation": data.get("relation", "")
                })
        return sub_edges

class DualMemoryRAG:
    """
    Coordinates the Neuro-Symbolic Dual Memory Architecture.
    """
    def __init__(self):
        self.vector_store = VectorStore()
        self.graph_store = GraphStore()
        self.chunks_by_id: Dict[str, Dict[str, Any]] = {}
        self.data_by_id: Dict[str, Dict[str, Any]] = {}

    def index_parsed_code(self, parsed_data: Dict[str, Any]):
        self.vector_store = VectorStore()
        self.graph_store = GraphStore()
        self.chunks_by_id = {}
        self.data_by_id = {}

        # 1. Index Data Items into Symbolic Memory
        for var in parsed_data.get("variables", []):
            data_id = f"DATA::{var['name']}"
            self.data_by_id[data_id] = var
            self.graph_store.add_node(data_id, label="DataVariable", **var)

        # 2. Index Chunks into both Neuro & Symbolic Memory (Linked by Shared Chunk ID)
        for chunk in parsed_data.get("chunks", []):
            cid = chunk["id"]
            self.chunks_by_id[cid] = chunk
            # Neuro: dense vector embedding of the chunk source
            searchable_text = f"{chunk['name']} " + " ".join([s["text"] for s in chunk.get("statements", [])])
            self.vector_store.add(cid, searchable_text)
            # Symbolic: node in directed dependency graph
            self.graph_store.add_node(cid, label="Chunk", **chunk)

        # 3. Add Edges into Symbolic Memory
        for edge in parsed_data.get("edges", []):
            self.graph_store.add_edge(
                edge["source"],
                edge["target"],
                edge_type=edge["type"],
                relation=edge.get("relation", "")
            )

    def retrieve(self, query: str, top_k: int = 2, max_hops: int = 2) -> Dict[str, Any]:
        """
        Structure-Aware Hybrid Retrieval (Phase 3):
        1. Neuro vector search finds top-k entry points.
        2. Symbolic graph traversal expands dependencies up to max_hops.
        3. Bundle deduplication and structural constraints description.
        """
        hits = self.vector_store.search(query, top_k=top_k)
        bundle = {}
        vector_match_ids = []

        for chunk_id, score in hits:
            vector_match_ids.append(chunk_id)
            bundle[chunk_id] = {
                "id": chunk_id,
                "reason": "vector_match",
                "score": round(score, 3),
                "type": "chunk",
                "source": self.chunks_by_id.get(chunk_id, {}).get("source", "")
            }
            # Graph expansion
            deps = self.graph_store.dependencies(chunk_id, max_hops=max_hops)
            for dep_id in deps:
                if dep_id not in bundle:
                    is_chunk = dep_id in self.chunks_by_id
                    source_code = self.chunks_by_id[dep_id]["source"] if is_chunk else f"# External Data Symbol: {dep_id}"
                    bundle[dep_id] = {
                        "id": dep_id,
                        "reason": f"dependency_of::{chunk_id}",
                        "score": None,
                        "type": "chunk" if is_chunk else "data_symbol",
                        "source": source_code
                    }

        # Build structural constraints description lines (Section 4.4, 5.3.3)
        bundle_ids = list(bundle.keys())
        active_edges = self.graph_store.get_subgraph_edges(bundle_ids)
        constraint_lines = []
        for e in active_edges:
            src_name = e["source"].split("::")[-1]
            tgt_name = e["target"].split("::")[-1]
            if e["type"] == "CALLS":
                constraint_lines.append(f"{src_name} calls {tgt_name}")
            elif e["type"] == "DEPENDS_ON":
                constraint_lines.append(f"{src_name} depends on {tgt_name}")

        return {
            "query": query,
            "vector_entry_points": vector_match_ids,
            "bundle": list(bundle.values()),
            "total_retrieved": len(bundle),
            "structural_edges": active_edges,
            "constraint_lines": constraint_lines
        }

    def baseline_retrieve(self, raw_source: str, query: str, window_size: int = 4, top_k: int = 2) -> Dict[str, Any]:
        """
        Standard RAG Baseline (Section 5.3.5):
        Splits code into arbitrary fixed-size line windows (e.g. 4 lines),
        blind to function/paragraph boundaries, and runs vector-only retrieval.
        """
        lines = raw_source.splitlines()
        windows = []
        for i in range(0, len(lines), window_size):
            chunk_lines = lines[i : i + window_size]
            win_id = f"window_L{i+1}_to_L{min(i+window_size, len(lines))}"
            win_text = "\n".join(chunk_lines)
            windows.append({
                "id": win_id,
                "start_line": i + 1,
                "end_line": min(i + window_size, len(lines)),
                "text": win_text,
                "emb": embed_text(win_text)
            })

        q_vec = embed_text(query)
        scored = []
        for w in windows:
            sim = float(np.dot(q_vec, w["emb"]))
            scored.append((w, sim))
        scored.sort(key=lambda x: x[1], reverse=True)
        
        top_windows = scored[:top_k]
        return {
            "query": query,
            "retrieved_windows": [
                {
                    "id": item[0]["id"],
                    "start_line": item[0]["start_line"],
                    "end_line": item[0]["end_line"],
                    "score": round(item[1], 3),
                    "text": item[0]["text"]
                }
                for item in top_windows
            ]
        }

    def generate_constrained_prompt(self, retrieval_result: Dict[str, Any], target_language: str = "Java") -> str:
        """
        Phase 4: Constrained Generation (Section 4.5, Appendix A).
        Assembles retrieved context, dependencies, structural constraints, and strict preservation rules.
        """
        bundle = retrieval_result["bundle"]
        vector_ids = set(retrieval_result["vector_entry_points"])

        source_code_parts = []
        dependency_parts = []

        for item in bundle:
            cid = item["id"]
            if cid in vector_ids:
                source_code_parts.append(f"# {cid}\n{item['source']}")
            else:
                dependency_parts.append(f"# {cid}\n{item['source']}")

        constraints_text = "\n".join([f"- {c}" for c in retrieval_result["constraint_lines"]])
        if not constraints_text:
            constraints_text = "- None detected"

        prompt = f"""Translate the following COBOL code to {target_language}.

Migration request: {retrieval_result['query']}

Source code:
{chr(10).join(source_code_parts)}

Dependencies (must be preserved, do not inline or omit):
{chr(10).join(dependency_parts) if dependency_parts else "# No external dependencies required"}

Structural constraints (derived automatically from the dependency graph):
{constraints_text}

Requirements:
- Preserve the exact call relationships and data dependencies listed above.
- Do not change procedure/method signatures unless the target language requires it.
- In {target_language}, map COBOL paragraphs to clean methods and ensure data fields maintain equivalent precision (e.g. BigDecimal or libcobj CobolDecimal).
- Output only the translated {target_language} code, with brief comments noting any necessary language-specific adaptation.
"""
        return prompt
