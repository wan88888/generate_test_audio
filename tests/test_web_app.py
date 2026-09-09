import unittest

from fastapi import HTTPException

import web_app


class FakeCommunicate:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def stream(self):
        yield {"type": "WordBoundary", "offset": 0}
        yield {"type": "audio", "data": b"first"}
        yield {"type": "audio", "data": b"second"}


class WebAppTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_synthesis_streams_audio_and_returns_safe_header(self):
        original_communicate = web_app.edge_tts.Communicate
        web_app.edge_tts.Communicate = FakeCommunicate
        try:
            response = await web_app.synthesize(
                web_app.SynthesizeRequest(text="hello", filename="中文.mp3")
            )
            chunks = [chunk async for chunk in response.body_iterator]
        finally:
            web_app.edge_tts.Communicate = original_communicate

        self.assertEqual([b"first", b"second"], chunks)
        self.assertIn("filename*=UTF-8''%E4%B8%AD%E6%96%87.mp3", response.headers["content-disposition"])

    async def test_synthesis_rejects_unknown_voice_before_calling_provider(self):
        with self.assertRaises(HTTPException) as error:
            await web_app.synthesize(web_app.SynthesizeRequest(text="hello", voice="unknown"))
        self.assertEqual(400, error.exception.status_code)


if __name__ == "__main__":
    unittest.main()
