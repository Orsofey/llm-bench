import io
import unittest
import urllib.error
from unittest.mock import patch

import model_catalog as mc


class CatalogTests(unittest.TestCase):
    def sample_raw(self):
        return {
            "openai": {"name": "OpenAI", "models": {
                "gpt-x": {"id": "gpt-x", "name": "GPT X", "canonical_model_id": "openai/gpt-x",
                          "limit": {"context": 100000, "output": 4096}, "cost": {"input": 1, "output": 2},
                          "modalities": {"input": ["text"], "output": ["text"]}, "release_date": "2026-01-01"}}},
            "other": {"name": "Other", "models": {
                "gpt-x": {"id": "gpt-x", "name": "GPT X", "canonical_model_id": "openai/gpt-x",
                          "limit": {"context": 100000, "output": 4096}, "cost": {"input": 1, "output": 2},
                          "modalities": {"input": ["text"], "output": ["text"]}},
                "image-x": {"id": "image-x", "name": "Image X", "type": "image", "modalities": {"output": ["image"]}}}},
        }

    def test_deduplicate_and_filter(self):
        models = mc.normalize_models_dev(self.sample_raw())
        gpt = next(m for m in models if m["id"] == "openai/gpt-x")
        self.assertEqual(len(gpt["providers"]), 2)
        self.assertEqual(gpt["country"], "us")
        self.assertEqual(gpt["context"], 100000)
        self.assertFalse(any(m["id"].endswith("image-x") for m in models))
        self.assertEqual(sum(m["country"] == "ru" for m in models), 6)

    def test_benchmark_merge_exact(self):
        models = mc.normalize_models_dev(self.sample_raw())
        aa = {mc.norm("openai/gpt-x"): {"aa_intelligence": 55.5, "gpqa": 0.75}}
        arena = {mc.norm("GPT X"): {"arena": 1400, "arena_date": "2025-01-01"}}
        mc.merge_benchmarks(models, aa, arena)
        gpt = next(m for m in models if m["id"] == "openai/gpt-x")
        self.assertEqual(gpt["benchmarks"]["aa_intelligence"], 55.5)
        self.assertEqual(gpt["benchmarks"]["arena"], 1400)

    def test_arena_uses_latest_date(self):
        csv_text = "date,rank,model,score,ci95,votes,organization,license\n" \
                   "2025-01-01,2,X,1300,±1,10,Lab,MIT\n" \
                   "2025-03-01,1,X,1350,±1,20,Lab,MIT\n" \
                   "2024-12-01,3,X,1200,±1,5,Lab,MIT\n"
        with patch.object(mc, "get_text", return_value=csv_text):
            arena = mc.fetch_arena()
        self.assertEqual(arena[mc.norm("X")]["arena"], 1350)
        self.assertEqual(arena[mc.norm("X")]["arena_date"], "2025-03-01")

    def test_aa_free_fallback(self):
        def fake_get(url, key):
            if "/free" in url:
                return {"tier": "free", "pagination": {"has_more": False}, "data": [{
                    "name": "GPT X", "slug": "gpt-x", "openrouter_api_id": "openai/gpt-x",
                    "evaluations": {"artificial_analysis_intelligence_index": 52.5},
                    "pricing": {"price_1m_input_tokens": 1.0, "price_1m_output_tokens": 2.0},
                    "performance_v3": {"mean_output_tokens_per_second": 75.0}}]}
            raise urllib.error.HTTPError(url, 403, "pro required", {}, io.BytesIO(b"{}"))
        with patch.object(mc, "get_json", fake_get):
            aa, tier = mc.fetch_aa("test-key")
        self.assertEqual(tier, "free")
        self.assertEqual(aa[mc.norm("openai/gpt-x")]["aa_intelligence"], 52.5)
        self.assertEqual(aa[mc.norm("openai/gpt-x")]["aa_speed"], 75.0)

    def test_own_results_ignore_tag(self):
        models = mc.normalize_models_dev(self.sample_raw())
        own = {"label": "gpt-x [official]", "summary": {"TOTAL": 87}, "date": "2026-01-02"}
        mc.attach_own_results(models, [own])
        gpt = next(m for m in models if m["id"] == "openai/gpt-x")
        self.assertEqual(gpt["own"]["summary"]["TOTAL"], 87)


if __name__ == "__main__":
    unittest.main()
