import unittest
from unittest.mock import patch, Mock
import requests
from services import gemini_service as svc

class ProviderTests(unittest.TestCase):
    def test_missing_key(self):
        with patch.dict('os.environ', {'GEMINI_API_KEY':'','GOOGLE_API_KEY':''}):
            with self.assertRaises(svc.ProviderError) as cm: next(svc.stream_chat([]))
            self.assertEqual((cm.exception.code, cm.exception.status), ('provider_configuration',503))
    def test_invalid_key(self):
        with patch.dict('os.environ', {'GEMINI_API_KEY':'ya29.invalid'}):
            with self.assertRaises(svc.ProviderError): next(svc.stream_chat([]))
    def test_retry_and_stream(self):
        fail=Mock(status_code=503, headers={}); ok=Mock(status_code=200)
        ok.iter_lines.return_value=[b'data: {"candidates":[{"content":{"parts":[{"text":"Hello"}]},"finishReason":"STOP"}]}']
        with patch.dict('os.environ', {'GEMINI_API_KEY':'test-only'}), patch.object(svc,'MAX_RETRIES',1), patch.object(svc.time,'sleep'), patch.object(svc.requests,'post',side_effect=[fail,ok]) as post:
            self.assertEqual(list(svc.stream_chat([])), ['Hello']); self.assertEqual(post.call_count,2)
            self.assertEqual(post.call_args.kwargs['timeout'],(4,15)); fail.close.assert_called_once(); ok.close.assert_called_once()
    def test_timeout(self):
        with patch.dict('os.environ', {'GEMINI_API_KEY':'test-only'}), patch.object(svc,'MAX_RETRIES',0), patch.object(svc.requests,'post',side_effect=requests.Timeout):
            with self.assertRaises(svc.ProviderError) as cm: next(svc.stream_chat([]))
            self.assertEqual(cm.exception.status,504)
    def test_http_403(self):
        fail=Mock(status_code=403, headers={})
        with patch.dict('os.environ', {'GEMINI_API_KEY':'test-only'}), patch.object(svc.requests,'post',return_value=fail) as post:
            with self.assertRaises(svc.ProviderError) as cm: next(svc.stream_chat([]))
            self.assertEqual(cm.exception.status,503); self.assertEqual(post.call_count,1)
