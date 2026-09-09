import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from starlette.requests import Request

import web_app


class FakeCommunicate:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def stream(self):
        yield {"type": "WordBoundary", "offset": 0}
        yield {"type": "audio", "data": b"first"}
        yield {"type": "audio", "data": b"second"}


class WebAppTests(unittest.IsolatedAsyncioTestCase):
    def local_request(self) -> Request:
        return Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/test",
                "headers": [],
                "client": ("127.0.0.1", 8000),
            }
        )

    def test_presets_follow_the_supported_contract(self):
        presets = web_app._load_presets()
        self.assertEqual(21, len(presets))
        self.assertEqual(len(presets), len({preset.id for preset in presets}))
        self.assertTrue(all(preset.voice in web_app.VOICE_IDS for preset in presets))

    def test_unicode_filename_has_utf8_download_header(self):
        filename = web_app._safe_filename("中文 测试.mp3")
        header = web_app._content_disposition(filename)
        self.assertIn('filename="test_audio.mp3"', header)
        self.assertIn("filename*=UTF-8''%E4%B8%AD%E6%96%87_%E6%B5%8B%E8%AF%95.mp3", header)

    def test_percent_and_voice_validation_reject_invalid_values(self):
        with self.assertRaises(HTTPException) as rate_error:
            web_app._validate_percent("+101%", "语速")
        self.assertEqual(400, rate_error.exception.status_code)

    def test_generation_prompt_has_a_safe_fictional_testing_constraint(self):
        prompt = web_app._generation_prompt(
            web_app.GenerateTextRequest(provider="agnes", category="public_safety")
        )
        self.assertIn("虚构测试内容", prompt)
        self.assertIn("不得提供暴力实施", prompt)
        self.assertIn('JSON 对象 `{"text":"..."}`', prompt)

    def test_generated_script_must_match_the_json_contract(self):
        self.assertEqual("测试文案", web_app._parse_generated_script('{"text":"测试文案"}'))
        with self.assertRaises(web_app.AIProviderError):
            web_app._parse_generated_script("这不是 JSON")

    def test_gemini_defaults_to_its_current_flash_model(self):
        gemini = next(config for config in web_app.MODEL_CONFIGS if config["id"] == "gemini")
        self.assertEqual("gemini-3.8-flash", gemini["model"])
        self.assertEqual("openai", gemini["protocol"])

    async def test_generate_text_uses_a_configured_server_side_provider(self):
        request = web_app.GenerateTextRequest(provider="agnes", category="financial_fraud")
        with patch.dict("os.environ", {"AGNES_API_KEY": "test-key"}), patch.object(
            web_app,
            "_generate_with_model",
            AsyncMock(return_value="这是虚构的测试文案。"),
        ) as generate:
            result = await web_app.generate_text(request, self.local_request())

        self.assertEqual("这是虚构的测试文案。", result["text"])
        self.assertEqual("agnes", result["provider"])
        self.assertEqual("0-20s", result["case"]["risk_window"])
        generate.assert_awaited_once()

    async def test_generate_text_rejects_an_unconfigured_provider(self):
        with patch.dict("os.environ", {}, clear=True), self.assertRaises(HTTPException) as error:
            await web_app.generate_text(
                web_app.GenerateTextRequest(provider="agnes", category="financial_fraud"),
                self.local_request(),
            )
        self.assertEqual(400, error.exception.status_code)

    async def test_generate_text_requires_a_long_enough_duration_for_its_window(self):
        with self.assertRaises(HTTPException) as error:
            await web_app.generate_text(
                web_app.GenerateTextRequest(
                    provider="agnes",
                    category="financial_fraud",
                    risk_window="40-60s",
                    target_duration_s=30,
                ),
                self.local_request(),
            )
        self.assertEqual(400, error.exception.status_code)

    async def test_model_connection_uses_the_configured_server_side_provider(self):
        with patch.dict("os.environ", {"AGNES_API_KEY": "test-key"}), patch.object(
            web_app,
            "_generate_with_model",
            AsyncMock(return_value="ok"),
        ) as generate:
            result = await web_app.test_model_connection("agnes", self.local_request())

        self.assertEqual("ok", result["status"])
        generate.assert_awaited_once()

    async def test_synthesis_streams_audio_and_returns_safe_header(self):
        original_communicate = web_app.edge_tts.Communicate
        web_app.edge_tts.Communicate = FakeCommunicate
        try:
            response = await web_app.synthesize(
                web_app.SynthesizeRequest(text="hello", filename="中文.mp3"), self.local_request()
            )
            chunks = [chunk async for chunk in response.body_iterator]
        finally:
            web_app.edge_tts.Communicate = original_communicate

        self.assertEqual([b"first", b"second"], chunks)
        self.assertIn("filename*=UTF-8''%E4%B8%AD%E6%96%87.mp3", response.headers["content-disposition"])

    async def test_synthesis_rejects_unknown_voice_before_calling_provider(self):
        with self.assertRaises(HTTPException) as error:
            await web_app.synthesize(
                web_app.SynthesizeRequest(text="hello", voice="unknown"), self.local_request()
            )
        self.assertEqual(400, error.exception.status_code)


if __name__ == "__main__":
    unittest.main()
