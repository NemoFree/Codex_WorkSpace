import math
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from libs.common_embedding import chunk_text, embed_text, to_vector_literal


class CommonEmbeddingTests(unittest.TestCase):
    def test_chunk_text_returns_empty_for_blank(self) -> None:
        self.assertEqual(chunk_text("   "), [])

    def test_chunk_text_splits_with_overlap(self) -> None:
        text = " ".join(f"w{i}" for i in range(20))
        chunks = chunk_text(text, max_words=8, overlap_words=2)
        self.assertEqual(len(chunks), 3)
        self.assertTrue(chunks[0].endswith("w7"))
        self.assertTrue(chunks[1].startswith("w6"))

    def test_embed_text_is_deterministic_and_normalized(self) -> None:
        vec1 = embed_text("Alpha beta alpha")
        vec2 = embed_text("Alpha beta alpha")
        self.assertEqual(vec1, vec2)

        norm = math.sqrt(sum(v * v for v in vec1))
        self.assertAlmostEqual(norm, 1.0, places=6)

    def test_to_vector_literal(self) -> None:
        literal = to_vector_literal([0.125, -0.5, 1.0])
        self.assertEqual(literal, "[0.12500000,-0.50000000,1.00000000]")

    def test_embed_text_uses_remote_when_litellm_configured(self) -> None:
        fake_response = MagicMock()
        fake_response.json.return_value = {"data": [{"embedding": [0.25, -0.75]}]}
        fake_response.raise_for_status.return_value = None

        fake_client = MagicMock()
        fake_client.post.return_value = fake_response

        fake_client_cm = MagicMock()
        fake_client_cm.__enter__.return_value = fake_client
        fake_client_cm.__exit__.return_value = False

        with (
            patch.dict(
                os.environ,
                {
                    "LITELLM_URL": "http://litellm.local",
                    "EMBEDDING_MODEL": "embed-model",
                },
                clear=False,
            ),
            patch(
                "libs.common_embedding.embed.httpx.Client", return_value=fake_client_cm
            ),
        ):
            vec = embed_text("hello", dim=2)

        self.assertEqual(vec, [0.25, -0.75])
        fake_client.post.assert_called_once()

    def test_embed_text_falls_back_on_remote_error(self) -> None:
        fake_client = MagicMock()
        fake_client.post.side_effect = RuntimeError("network failed")

        fake_client_cm = MagicMock()
        fake_client_cm.__enter__.return_value = fake_client
        fake_client_cm.__exit__.return_value = False

        with (
            patch.dict(
                os.environ,
                {
                    "LITELLM_URL": "http://litellm.local",
                    "EMBEDDING_FALLBACK_ON_ERROR": "true",
                },
                clear=False,
            ),
            patch(
                "libs.common_embedding.embed.httpx.Client", return_value=fake_client_cm
            ),
        ):
            vec = embed_text("hello", dim=8)

        self.assertEqual(len(vec), 8)
        self.assertNotEqual(sum(abs(v) for v in vec), 0.0)


if __name__ == "__main__":
    unittest.main()
