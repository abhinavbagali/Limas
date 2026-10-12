from __future__ import annotations

import sys
import io
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from context_compressor.ingestion.chunker import chunk_pages
from context_compressor.ingestion.pdf_extractor import PageMetadata, PdfIngestionError, extract_pdf_pages
from context_compressor.retrieval.reranker import RerankedChunk
from context_compressor.retrieval.vector_store import VectorStore
from context_compressor.service import api
from context_compressor.service.groq_client import GenerationResult
from context_compressor.service.groq_client import estimate_prompt_tokens, fit_context_to_prompt_budget


class TinyCodec:
    def encode(self, text: str) -> list[str]:
        return text.split()

    def decode(self, tokens: list[str]) -> str:
        return " ".join(tokens)


class FakeReranker:
    def rerank(self, query, candidates, top_k=8):
        return [RerankedChunk(item.chunk, item.score, item.score, item.rank, rank) for rank, item in enumerate(candidates[:top_k], 1)]


def make_text_pdf(page_count: int) -> bytes:
    writer = PdfWriter()
    for number in range(1, page_count + 1):
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})
        })
        text = f"Page {number} explains solar panels and photovoltaic energy. " * 22
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 9 Tf 30 750 Td ({text}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


class RetrievalPipelineTests(unittest.TestCase):
    def test_pdf_extractor_rejects_corrupt_input_with_diagnostic(self):
        with self.assertRaisesRegex(PdfIngestionError, "corrupted"):
            extract_pdf_pages(b"not a pdf")

    def test_chunker_preserves_page_range_and_overlap(self):
        pages = [PageMetadata("doc", 1, "alpha beta gamma delta. epsilon zeta eta theta.", "success")]
        chunks = chunk_pages(pages, target_tokens=5, overlap_tokens=2, codec=TinyCodec())
        self.assertGreaterEqual(len(chunks), 2)
        self.assertTrue(all(chunk.page_start == 1 and chunk.page_end == 1 for chunk in chunks))
        self.assertTrue(set(chunks[0].text.split()[-2:]) & set(chunks[1].text.split()[:2]))

    def test_fifty_page_pdf_upload_and_chunking_keep_page_provenance(self):
        content = make_text_pdf(50)
        pages = extract_pdf_pages(content)
        self.assertEqual(len(pages), 50)
        self.assertTrue(all(page.extraction_status == "success" for page in pages))
        chunks = chunk_pages(pages, target_tokens=500, overlap_tokens=80, codec=TinyCodec())
        self.assertGreater(len(chunks), 10)
        self.assertEqual(min(chunk.page_start for chunk in chunks), 1)
        self.assertEqual(max(chunk.page_end for chunk in chunks), 50)
        self.assertTrue(all(chunk.token_count <= 500 for chunk in chunks))
        store = VectorStore()
        store._model = False
        store.index(pages[0].doc_id, chunks)
        retrieved = store.retrieve(pages[0].doc_id, "solar panels photovoltaic energy", top_k=30)
        self.assertTrue(retrieved)
        self.assertLessEqual(len(retrieved), 30)
        self.assertTrue(all(1 <= item.chunk.page_start <= item.chunk.page_end <= 50 for item in retrieved))

    def test_vector_store_caches_index_and_returns_ranked_provenance(self):
        pages = [PageMetadata("doc", 8, "solar panels convert sunlight into electrical energy.", "success")]
        chunks = chunk_pages(pages, target_tokens=100, overlap_tokens=10, codec=TinyCodec())
        store = VectorStore()
        store._model = False
        first = store.index("doc", chunks)
        second = store.index("doc", chunks)
        results = store.retrieve("doc", "solar panels sunlight", top_k=1)
        self.assertIs(first, second)
        self.assertEqual(results[0].chunk.page_start, 8)
        self.assertEqual(results[0].rank, 1)
        self.assertEqual(first.backend, "offline-hash-fallback")

    def test_preflight_budget_truncates_only_overflow_context(self):
        query = "solar energy"
        initial = ["solar energy context " * 300]
        budget = 150
        fitted, truncated = fit_context_to_prompt_budget(query, initial, budget)
        self.assertTrue(truncated)
        self.assertLessEqual(estimate_prompt_tokens(query, "\n\n".join(fitted)), budget)

    def test_upload_index_retrieve_and_doc_id_compress_routes(self):
        original_store = api.vector_store
        store = VectorStore()
        store._model = False
        try:
            with patch.object(api, "vector_store", store), patch.object(api, "_get_reranker", return_value=FakeReranker()), patch.object(api, "generate_answer", new=AsyncMock(return_value=GenerationResult("Solar panels use sunlight.", 10.0, 100, 12))), patch.object(api, "append_comparison_metrics", new=MagicMock()):
                client = TestClient(api.app)
                uploaded = client.post("/upload_pdf", files={"file": ("notes.txt", b"Solar panels convert sunlight into electricity.\n\nPhotovoltaic cells create electric current.", "text/plain")})
                self.assertEqual(uploaded.status_code, 200, uploaded.text)
                doc_id = uploaded.json()["doc_id"]
                indexed = client.post("/index", json={"doc_id": doc_id, "target_tokens": 100, "overlap_tokens": 10})
                self.assertEqual(indexed.status_code, 200, indexed.text)
                retrieved = client.post("/retrieve", json={"doc_id": doc_id, "query": "solar electricity", "top_k": 4})
                self.assertEqual(retrieved.status_code, 200, retrieved.text)
                self.assertTrue(retrieved.json()[0]["page_start"])
                compressed = client.post("/compress", json={"doc_id": doc_id, "query": "solar electricity"})
                self.assertEqual(compressed.status_code, 200, compressed.text)
                self.assertTrue(compressed.json()["sentence_audit"][0]["page_start"])
                compared = client.post("/compare", json={"doc_id": doc_id, "query": "solar electricity"})
                self.assertEqual(compared.status_code, 200, compared.text)
                self.assertEqual(compared.json()["baseline_preflight_prompt_tokens"] <= compared.json()["preflight_prompt_token_budget"], True)
                self.assertTrue(compared.json()["retrieved_chunks"])
                legacy = client.post("/compress", json={"query": "solar electricity", "documents": ["Solar panels convert sunlight."]})
                self.assertEqual(legacy.status_code, 200, legacy.text)
        finally:
            api.vector_store = original_store


if __name__ == "__main__":
    unittest.main()
