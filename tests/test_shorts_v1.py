import base64
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
import wave

from creator_orchestrator.shorts import contracts
from creator_orchestrator.shorts.bridge import BridgeClient, NoRedirect
from creator_orchestrator.shorts.server import Application, crypt, handler
from creator_orchestrator.shorts.store import Store, Wait, file_hash
from creator_orchestrator.shorts.voice import GeminiVoice
from creator_orchestrator.shorts.capabilities import validate_observation
from growth_analytics.shorts_review import DIMENSIONS, validate_review


class BridgeHandler(BaseHTTPRequestHandler):
    posts = []
    jobs = []
    def log_message(self, *args): pass
    def send(self, value, status=200):
        data = json.dumps(value).encode()
        self.send_response(status); self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_POST(self):
        value = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        type(self).posts.append(value)
        job = {'id': 'job-123', 'status': 'completed', 'raw_status': 'completed', 'output_text': '{"ok":true}', 'task': {'idempotencyKey': value['idempotency_key']}}
        type(self).jobs.append(job)
        self.send({'id': job['id'], 'status': 'queued'})
    def do_GET(self):
        if self.path == '/v1/jobs?limit=200': return self.send({'data': type(self).jobs})
        if self.path == '/v1/jobs/job-123': return self.send(type(self).jobs[-1])
        self.send({}, 404)


class ShortsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.id = self.store.create('Test fixture brief', {'version': 1}, 'same-request')
        BridgeHandler.posts, BridgeHandler.jobs = [], []
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), BridgeHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.client = BridgeClient(f'http://127.0.0.1:{self.server.server_port}/v1', 'fixture-not-a-real-key', self.store)
    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.tmp.cleanup()
    def test_request_key_is_bound_to_brief(self):
        self.assertEqual(self.id, self.store.create('Test fixture brief', {'version': 1}, 'same-request'))
        with self.assertRaises(ValueError): self.store.create('Different brief', {'version': 1}, 'same-request')
    def test_completed_operation_survives_restart_without_new_send(self):
        payload = {'model': 'fixture', 'prompt': 'A', 'modalities': ['text']}
        first = self.client.execute(self.id, 'script', payload)
        restarted = BridgeClient(self.client.base_url, self.client.token, Store(self.tmp.name))
        self.assertEqual(first, restarted.execute(self.id, 'script', payload))
        self.assertEqual(len(BridgeHandler.posts), 1)
    def test_lost_ack_reconciles_by_key_before_polling(self):
        original = self.client.request
        def lost(route, body=None, binary=False):
            value = original(route, body, binary)
            if body is not None: raise Wait('WAITING_PROVIDER', 'simulated lost acknowledgement')
            return value
        with patch.object(self.client, 'request', side_effect=lost):
            with self.assertRaises(Wait): self.client.execute(self.id, 'image', {'prompt': 'A'})
        self.assertEqual(self.client.execute(self.id, 'image', {'prompt': 'A'})['id'], 'job-123')
        self.assertEqual(len(BridgeHandler.posts), 1)
    def test_uncertain_submission_is_not_repeated_when_list_has_no_match(self):
        with patch.object(self.client, 'request', side_effect=Wait('WAITING_PROVIDER', 'offline')):
            with self.assertRaises(Wait): self.client.execute(self.id, 'image', {'prompt': 'B'})
        with self.assertRaises(Wait) as caught: self.client.execute(self.id, 'image', {'prompt': 'B'})
        self.assertEqual(caught.exception.state, 'WAITING_RECONCILIATION')
        self.assertEqual(BridgeHandler.posts, [])
    def test_no_token_does_not_mark_submission_uncertain(self):
        self.client.token = ''
        with self.assertRaises(Wait): self.client.execute(self.id, 'script', {'prompt': 'A'})
        with self.store.connect() as db: self.assertEqual(db.execute('SELECT state FROM operations').fetchone()[0], 'prepared')
    def test_image_uses_authenticated_route_and_real_extension(self):
        from PIL import Image
        buffer = io.BytesIO(); Image.new('RGB',(2,2),'blue').save(buffer,format='PNG')
        data = buffer.getvalue()
        import hashlib
        result = {'id':'job-fixture','output_images':[{'url':'https://untrusted.example/file','sha256':hashlib.sha256(data).hexdigest()}]}
        with patch.object(self.client,'request',return_value=data) as requested:
            saved = self.client.image(result, Path(self.tmp.name)/'asset.image')
        self.assertTrue(saved['path'].endswith('.png'))
        self.assertEqual(requested.call_args.args[0],'/jobs/job-fixture/images/0')
        result['output_images'][0]['sha256'] = '0'*64
        with patch.object(self.client,'request',return_value=data):
            with self.assertRaises(ValueError): self.client.image(result, Path(self.tmp.name)/'bad.image')
    def test_artifact_tampering_and_overwrite_are_rejected(self):
        self.store.artifact(self.id, 'plan', {'a': 1})
        with self.assertRaises(ValueError): self.store.artifact(self.id, 'plan', {'a': 2})
        with self.store.connect() as db: path = db.execute('SELECT path FROM artifacts').fetchone()[0]
        Path(path).write_text('{}')
        with self.assertRaises(ValueError): self.store.read(self.id, 'plan')
    def test_still_cannot_satisfy_required_object_motion(self):
        script = {'title': 'Title', 'beats': [{'id': str(i), 'purpose': 'p', 'narration': 'speech', 'screen_text': 'text'} for i in range(3)]}
        plan = {'style': {'description': 'style', 'background': '#101010', 'accent': '#4444FF', 'foreground': '#FFFFFF'}, 'shots': [
            {'beat_id': str(i), 'purpose': 'p', 'visual_prompt': 'p', 'mode': 'illustration' if i else 'kinetic_text', 'motion': 'push_in' if i else 'text_reveal'} for i in range(3)]}
        contracts.shot_plan(plan, script)
        plan['shots'][1]['requires_object_motion'] = True
        with self.assertRaises(ValueError): contracts.shot_plan(plan, script)
    def test_nonfinite_timing_and_arbitrary_transition_are_rejected(self):
        measured = [{'beat_id': 'a', 'voice_seconds': 3}]
        for lead, transition in [(float('nan'), 'cut'), (.1, 'run_shell')]:
            with self.assertRaises(ValueError): contracts.edit_plan({'music': 'none', 'shots': [{'beat_id': 'a', 'lead_seconds': lead, 'tail_seconds': .1, 'transition': transition}]}, measured)
    def review(self):
        return {'draft_sha256': 'a'*64, 'decision': 'approve', 'observed_modalities': ['video', 'audio'], 'dimensions': {d: {'status': 'pass', 'reason': 'fixture evidence'} for d in DIMENSIONS}, 'issues': [], 'patches': []}
    def check_review(self, value):
        return validate_review(value, bridge_job_id='job-fixture', draft_sha256='a'*64, scenes={'hook'}, duration=5, provided_modalities={'video','audio','image'})
    def test_frames_only_review_cannot_approve(self):
        value = self.review(); value['observed_modalities'] = ['image']
        with self.assertRaises(ValueError): self.check_review(value)
    def test_review_cannot_bind_to_different_file_or_outside_time(self):
        value = self.review(); value['draft_sha256'] = 'b'*64
        with self.assertRaises(ValueError): self.check_review(value)
        value = self.review(); value.update(decision='revise', issues=[{'beat_id': 'hook', 'seconds': 99, 'reason': 'problem'}], patches=[{'beat_id': 'hook', 'changes': {'screen_text': 'fix'}}])
        with self.assertRaises(ValueError): self.check_review(value)
    def test_unobserved_audio_cannot_pass_review(self):
        value = self.review(); value['dimensions']['audio']['status'] = 'unobserved'
        with self.assertRaises(ValueError): self.check_review(value)
    def test_gemini_unknown_send_never_repeats(self):
        voice = GeminiVoice(self.store, 'fixture-key')
        with patch('urllib.request.OpenerDirector.open', side_effect=urllib.error.URLError('fixture network failure')) as opened:
            with self.assertRaises(Wait): voice.speak(self.id, 'hook', 'Test', Path(self.tmp.name) / 'voice')
            with self.assertRaises(Wait) as caught: voice.speak(self.id, 'hook', 'Test', Path(self.tmp.name) / 'voice')
            self.assertEqual(caught.exception.state, 'WAITING_RECONCILIATION')
            self.assertEqual(opened.call_count, 1)
    def test_gemini_rest_decodes_real_wav_and_recovers_from_saved_response(self):
        output = io.BytesIO()
        with wave.open(output, 'wb') as f:
            f.setnchannels(1); f.setsampwidth(2); f.setframerate(24000); f.writeframes(b'\1\0' * 24000)
        value = {'id': 'interaction-fixture', 'steps': [{'type': 'model_output', 'content': [{'type': 'audio', 'data': base64.b64encode(output.getvalue()).decode()}]}]}
        response = io.BytesIO(json.dumps(value).encode())
        voice = GeminiVoice(self.store, 'fixture-key')
        with patch('urllib.request.OpenerDirector.open', return_value=response) as opened:
            first = voice.speak(self.id, 'hook', 'Test', Path(self.tmp.name) / 'voice')
            second = voice.speak(self.id, 'hook', 'Test', Path(self.tmp.name) / 'voice')
        self.assertEqual(first, second); self.assertEqual(opened.call_count, 1); self.assertEqual(first['voice_seconds'], 1)
    def test_dpapi_roundtrip(self):
        import os
        if os.name != 'nt': self.skipTest('Windows only')
        self.assertEqual(crypt(crypt('fixture-secret-123'), True), 'fixture-secret-123')
    def test_blind_perception_rejects_guessed_motion_and_missing_audio(self):
        expected = {'codes': ['187', '652', '309'], 'direction': 'left_to_right', 'spoken_text': 'Медный маяк, тихий остров'}
        actual = {**expected, 'observed_modalities': ['video', 'audio']}
        self.assertEqual(validate_observation(actual, expected), actual)
        for changes in ({'codes': ['187', '309', '652']}, {'direction': 'right_to_left'}, {'spoken_text': ''}, {'observed_modalities': ['image']}):
            with self.assertRaises(Wait): validate_observation({**actual, **changes}, expected)


class HttpTests(unittest.TestCase):
    def test_settings_redaction_origin_rejection_and_mp4_range(self):
        with tempfile.TemporaryDirectory() as temp:
            app = Application(data=temp)
            app.settings.save({'token': 'fixture-private-key', 'geminiKey': 'fixture-gemini-key'})
            run_id = app.store.create('HTTP fixture', {}, 'http-request')
            preview = app.store.folder(run_id) / 'preview.mp4'; preview.write_bytes(bytes(range(256)))
            app.store.artifact(run_id, 'media-0', {'preview': str(preview)})
            server = ThreadingHTTPServer(('127.0.0.1',0), handler(app))
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            base = f'http://127.0.0.1:{server.server_port}'
            try:
                with urllib.request.urlopen(base+'/api/connection') as r: data = r.read()
                self.assertNotIn(b'fixture-private-key', data); self.assertNotIn(b'fixture-gemini-key', data)
                req = urllib.request.Request(base+'/api/videos', data=b'{}', headers={'Content-Type':'application/json','Origin':'https://untrusted.example'})
                with self.assertRaises(urllib.error.HTTPError) as caught: urllib.request.urlopen(req)
                self.assertEqual(caught.exception.code, 400)
                req = urllib.request.Request(base+f'/api/videos/{run_id}/preview.mp4', headers={'Range':'bytes=10-19'})
                with urllib.request.urlopen(req) as r:
                    self.assertEqual(r.status,206); self.assertEqual(r.read(),bytes(range(10,20)))
            finally:
                server.shutdown(); server.server_close()


if __name__ == '__main__': unittest.main()
