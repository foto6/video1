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
from creator_orchestrator.shorts.bridge import BridgeClient, NoRedirect, PREFLIGHT_BUSY, InvalidModelResponse
from creator_orchestrator.shorts.production import Production
from creator_orchestrator.shorts.local_voice import LocalPiperVoice
from creator_orchestrator.shorts.server import Application, crypt, handler
from creator_orchestrator.shorts.store import Store, Wait, file_hash
from creator_orchestrator.shorts.voice import GeminiVoice
from creator_orchestrator.shorts.capabilities import validate_observation
from creator_orchestrator.shorts.stateful import chat_binding, normalized_reply
from growth_analytics.shorts_review import DIMENSIONS, validate_review


class BridgeHandler(BaseHTTPRequestHandler):
    posts = []
    jobs = []
    cancels = []
    busy_remaining = 0
    insert_timeout_remaining = 0
    def log_message(self, *args): pass
    def send(self, value, status=200):
        data = json.dumps(value).encode()
        self.send_response(status); self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_POST(self):
        value = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if self.path.endswith('/cancel'):
            type(self).cancels.append(self.path)
            job = next(j for j in type(self).jobs if self.path == '/v1/jobs/'+j['id']+'/cancel')
            job.update(status='cancelled',raw_status='cancelled')
            return self.send(job)
        type(self).posts.append(value)
        job = {'id': 'job-' + str(122 + len(type(self).posts)), 'status': 'completed', 'raw_status': 'completed', 'output_text': '{"ok":true}', 'task': {'idempotencyKey': value['idempotency_key']}}
        if self.path == '/v1/replies':
            job['output_text'] = json.dumps({'action': 'reply', 'messages': ['{"ok":true}'], 'reason': 'fixture'})
            job['kind'] = 'project_thread_reply'
        if type(self).busy_remaining:
            type(self).busy_remaining -= 1
            job.update(status='failed', raw_status='failed', error={'message': PREFLIGHT_BUSY}, output_text='')
        if type(self).insert_timeout_remaining:
            type(self).insert_timeout_remaining-=1
            job.update(status='failed',raw_status='failed',error={'message':'Input.insertText timed out'},output_text='')
            job['task'].update(apiRequest={'type':'project.reply'},metadata=value['metadata'],resolvedChatUrl=value['thread']['native_provider']['chat_url'])
        type(self).jobs.append(job)
        if self.path == '/v1/replies':
            return self.send({'id': 'run-' + job['id'][4:], 'status': 'queued', 'job': {'id': job['id'], 'status': 'queued'}})
        self.send({'id': job['id'], 'status': 'queued'})
    def do_GET(self):
        if self.path == '/v1/jobs?limit=200': return self.send({'data': type(self).jobs})
        if self.path.startswith('/v1/jobs/job-'):
            matches = [j for j in type(self).jobs if self.path.endswith(j['id'])]
            if matches: return self.send(matches[-1])
        if self.path.startswith('/v1/runs/run-'):
            matches = [j for j in type(self).jobs if self.path == '/v1/runs/run-' + j['id'][4:]]
            job = matches[-1]
            envelope = json.loads(job['output_text']) if job['output_text'] else {}
            body = next(x for x in type(self).posts if x['idempotency_key'] == job['task']['idempotencyKey'])
            binding = body['thread']['native_provider']
            return self.send({'id': 'run-' + job['id'][4:], 'job': job, 'status': job['status'], 'thread_id': 'fixture-thread',
                              'provider':binding['provider'], 'profile_id':body['thread'].get('profile_id',''),
                              'chat_url':binding.get('chat_url','https://chatgpt.com/'), **envelope})
        self.send({}, 404)


class ShortsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.id = self.store.create('Test fixture brief', {'version': 1}, 'same-request')
        BridgeHandler.posts, BridgeHandler.jobs, BridgeHandler.cancels, BridgeHandler.busy_remaining = [], [], [], 0
        BridgeHandler.insert_timeout_remaining=0
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), BridgeHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.client = BridgeClient(f'http://127.0.0.1:{self.server.server_port}/v1', 'fixture-not-a-real-key', self.store)
    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.tmp.cleanup()
    def test_request_key_is_bound_to_brief(self):
        self.assertEqual(self.id, self.store.create('Test fixture brief', {'version': 1}, 'same-request'))
        with self.assertRaises(ValueError): self.store.create('Different brief', {'version': 1}, 'same-request')
    def test_malformed_envelope_is_repaired_through_bridge_then_reused(self):
        production=Production(self.store,self.tmp.name,lambda:{})
        production.profile={'text_model':'chatgpt-web'}
        bad={'id':'job-bad','output_text':'{"action":"reply","messages":["broken "quotes"]}'}
        good={'id':'job-good','output_text':'{"ok":true}'}
        with patch.object(self.client,'execute',side_effect=[InvalidModelResponse('Invalid envelope',bad),good]) as execute:
            for _ in range(2):
                self.assertEqual(production.structured(self.client,self.id,'plan','Make plan',{'ok':True},lambda x:x),{'ok':True})
        self.assertEqual(execute.call_count,2)
        self.assertEqual(execute.call_args_list[1].args[1],'plan-format-repair-1')
        self.assertEqual(self.store.read(self.id,'plan-invalid-envelope'),bad)
    def test_format_repair_budget_survives_production_restart(self):
        production=Production(self.store,self.tmp.name,lambda:{})
        production.profile={'text_model':'chatgpt-web'}
        # Real BridgeClient journals each completed but invalid JSON response.
        payload={'ok':False}
        def reject(value):raise ValueError('Fixture schema requires different fields')
        for _ in range(2):
            with self.assertRaises(Wait) as caught:
                production.structured(self.client,self.id,'plan','Make plan',payload,reject)
            self.assertEqual(caught.exception.state,'NEEDS_REVIEW')
        self.assertEqual(len(BridgeHandler.posts),3)
    def test_stage_request_is_frozen_when_nested_json_order_changes(self):
        production=Production(self.store,self.tmp.name,lambda:{})
        production.profile={'text_model':'chatgpt-web'}
        original=self.client.execute
        def pending_after_send(*args):
            original(*args)
            raise Wait('PENDING','fixture pending acknowledgement')
        with patch.object(self.client,'execute',side_effect=pending_after_send):
            with self.assertRaises(Wait):production.structured(self.client,self.id,'plan',json.dumps({'title':'A','beats':[]}),{},lambda x:x)
        value=production.structured(self.client,self.id,'plan',json.dumps({'beats':[],'title':'A'}),{},lambda x:x)
        self.assertEqual(value,{'ok':True});self.assertEqual(len(BridgeHandler.posts),1)
    def test_pause_prevents_a_new_model_request(self):
        production=Production(self.store,self.tmp.name,lambda:{})
        production.profile={'text_model':'chatgpt-web'}
        self.store.update(self.id,'PAUSED','SCRIPT')
        with self.assertRaises(Wait) as caught:
            production.structured(self.client,self.id,'plan','Make plan',{},lambda x:x)
        self.assertEqual(caught.exception.state,'PAUSED');self.assertEqual(BridgeHandler.posts,[])
    def test_existing_text_operation_is_recovered_without_resubmitting_reordered_prompt(self):
        client=self.bound_client()
        payload={'model':'chatgpt-web','prompt':'Original order','attachments':[],'modalities':['text']}
        client.execute(self.id,'plan',payload)
        production=Production(self.store,self.tmp.name,lambda:{})
        production.profile={'text_model':'chatgpt-web'}
        value=production.structured(client,self.id,'plan','Reordered equivalent content',{},lambda x:x)
        self.assertEqual(value,{'ok':True});self.assertEqual(len(BridgeHandler.posts),1)
        self.assertEqual(self.store.read(self.id,'plan-request'),payload)
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
    def local_voice_manifest(self):
        import sys
        folder=Path(self.tmp.name)/'model';folder.mkdir()
        model=folder/'fixture.onnx';model.write_bytes(b'fixture model, not executable')
        config=folder/'fixture.onnx.json';config.write_text('{}')
        manifest=folder/'ready.json'
        manifest.write_text(json.dumps({'engine':'piper','engine_version':'1.8.0','python':sys.executable,'model_path':str(model),
                                       'model_sha256':file_hash(model),'config_sha256':file_hash(config)}))
        return manifest,model
    def test_local_voice_wav_receipt_survives_restart_without_new_synthesis(self):
        import subprocess
        manifest,model=self.local_voice_manifest()
        output=io.BytesIO()
        with wave.open(output,'wb') as f:
            f.setnchannels(1);f.setsampwidth(2);f.setframerate(22050);f.writeframes(b'\1\0'*22050)
        with patch('creator_orchestrator.shorts.local_voice.subprocess.run',return_value=subprocess.CompletedProcess([],0,output.getvalue(),b'')) as rendered:
            first=LocalPiperVoice(self.store,manifest).speak(self.id,'hook','Test narration',Path(self.tmp.name)/'voice')
            second=LocalPiperVoice(Store(self.tmp.name),manifest).speak(self.id,'hook','Test narration',Path(self.tmp.name)/'voice')
        self.assertEqual(first,second);self.assertEqual(first['voice_seconds'],1)
        self.assertEqual(first['provider'],'local_piper');self.assertEqual(rendered.call_count,1)
        model.write_bytes(b'changed')
        with self.assertRaises(ValueError):LocalPiperVoice(self.store,manifest)
    def test_audio_probe_is_shared_across_videos_and_restarts(self):
        from creator_orchestrator.shorts.audio_probe import probe_audio
        settings = {'baseUrl':self.client.base_url, 'token':self.client.token}
        first = probe_audio(self.tmp.name, settings)
        second = probe_audio(self.tmp.name, settings)
        self.assertEqual(first, second)
        self.assertEqual(first['job_id'], 'job-123')
        self.assertFalse(first['audio_download_supported'])
        self.assertEqual(len(BridgeHandler.posts), 1)
        self.assertEqual(BridgeHandler.posts[0]['model'], 'gemini-web')
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
    def bound_client(self):
        binding = chat_binding('https://chatgpt.com/c/11111111-2222-3333-4444-555555555555', 'Fixture Profile', 'a'*32)
        return BridgeClient(self.client.base_url, self.client.token, self.store, binding=binding)
    def test_stateful_uses_own_project_exact_chat_and_returns_inner_json(self):
        client = self.bound_client()
        response = client.execute(self.id, 'script', {'model': 'chatgpt-web', 'prompt': 'Make JSON', 'modalities': ['text']})
        self.assertEqual(json.loads(response['output_text']), {'ok': True})
        self.assertEqual(response['bridge_run_id'], 'run-123')
        body = BridgeHandler.posts[0]
        self.assertEqual(body['thread']['native_provider']['chat_url'], client.binding['chatUrl'])
        self.assertEqual(body['thread']['profile_id'], 'Fixture Profile')
        self.assertTrue(body['project']['id'].startswith('proj_video_'))
        self.assertFalse(body['bootstrap_memory']); self.assertFalse(body['allow_brain_consult']); self.assertFalse(body['defer_brain_sync'])
        self.assertFalse(body['project']['brain_chat_enabled']); self.assertFalse(body['project']['brain_sync_enabled'])
        self.assertEqual(body['delivery_mode'], 'return')
        self.assertFalse(body['metadata']['providerFallback'])
        client.execute(self.id, 'script', {'model': 'chatgpt-web', 'prompt': 'Make JSON', 'modalities': ['text']})
        self.assertEqual(len(BridgeHandler.posts), 1)
    def test_stateful_lost_ack_reconciles_public_job_without_second_reply(self):
        client = self.bound_client(); original = client.request
        def lost(route, body=None, binary=False):
            value = original(route, body, binary)
            if body is not None: raise Wait('WAITING_PROVIDER', 'fixture lost reply ACK')
            return value
        payload = {'model': 'chatgpt-web', 'prompt': 'Make JSON', 'modalities': ['text']}
        with patch.object(client, 'request', side_effect=lost):
            with self.assertRaises(Wait): client.execute(self.id, 'script', payload)
        response = self.bound_client().execute(self.id, 'script', payload)
        self.assertEqual(response['output_text'], '{"ok":true}'); self.assertEqual(len(BridgeHandler.posts), 1)
    def test_new_chat_is_profile_scoped_and_not_saved_as_conversation(self):
        from creator_orchestrator.shorts.stateful import new_chat_binding
        binding = new_chat_binding('11111111-2222-3333-4444-555555555555', 'a'*32)
        client = BridgeClient(self.client.base_url, self.client.token, self.store, binding=binding)
        client.execute(self.id, 'new-chat', {'model':'chatgpt-web','modalities':['text'],'prompt':'Initialize'})
        body = BridgeHandler.posts[0]
        self.assertEqual(body['thread']['profile_id'], binding['profileName'])
        self.assertFalse(body['thread']['native_provider']['enabled'])
        self.assertNotIn('chat_url', body['thread']['native_provider'])
        with self.assertRaises(ValueError): chat_binding(binding['chatUrl'], '', 'a'*32)
    def test_stateful_does_not_reuse_failed_generic_route(self):
        payload = {'model': 'chatgpt-web', 'prompt': 'Make JSON', 'modalities': ['text']}
        self.client.execute(self.id, 'script', payload)
        self.bound_client().execute(self.id, 'script', payload)
        self.assertEqual(len(BridgeHandler.posts), 2)
        self.assertNotEqual(BridgeHandler.posts[0]['idempotency_key'], BridgeHandler.posts[1]['idempotency_key'])
    def test_changed_route_is_rejected_even_when_result_completed(self):
        client = self.bound_client(); original = client.request
        def redirected(route, body=None, binary=False):
            result = original(route, body, binary)
            if route.startswith('/runs/'):
                result.update(provider='gemini', chat_url='https://gemini.google.com/app', profile_id='another')
            return result
        with patch.object(client,'request',side_effect=redirected):
            with self.assertRaises(Wait) as caught:
                client.execute(self.id,'script',{'model':'chatgpt-web','modalities':['text'],'prompt':'Make JSON'})
        self.assertEqual(caught.exception.state,'WAITING_PROVIDER')
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT state FROM operations').fetchone()[0],'blocked')
    def test_queued_fallback_is_cancelled_once_and_never_reposted_after_restart(self):
        client = self.bound_client(); original = client.request
        def redirected(route, body=None, binary=False):
            result = original(route, body, binary)
            if route.startswith('/jobs/job-') and body is None:
                result.update(status='queued',raw_status='pending')
            if route.startswith('/runs/'):
                result.update(provider='gemini',chat_url='https://gemini.google.com/app')
            return result
        payload = {'model':'chatgpt-web','modalities':['text'],'prompt':'Make JSON'}
        with patch.object(client,'request',side_effect=redirected):
            with self.assertRaises(Wait): client.execute(self.id,'script',payload)
        with self.assertRaises(Wait): self.bound_client().execute(self.id,'script',payload)
        self.assertEqual(BridgeHandler.cancels,['/v1/jobs/job-123/cancel'])
        self.assertEqual(len(BridgeHandler.posts),1)
    def test_legacy_accepted_request_keeps_its_key_without_resubmission(self):
        client=self.bound_client(); payload={'model':'chatgpt-web','modalities':['text'],'prompt':'Make JSON'}
        client.execute(self.id,'script',payload)
        with self.store.connect() as db:
            row=db.execute('SELECT key,request FROM operations').fetchone()
            previous=json.loads(row['request']); previous['metadata'].pop('providerFallback')
            db.execute('UPDATE operations SET request=? WHERE key=?',(json.dumps(previous),row['key']))
        self.bound_client().execute(self.id,'script',payload)
        self.assertEqual(len(BridgeHandler.posts),1)
    def test_binding_rejects_unknown_host_and_provider_mismatch_before_send(self):
        for url in ['http://chatgpt.com/c/'+'1'*36, 'https://untrusted.example/c/'+'1'*36, 'https://chatgpt.com/', 'https://chatgpt.com/c/'+'1'*36+'?token=x']:
            with self.assertRaises(ValueError): chat_binding(url, '', 'a'*32)
        with self.assertRaises(Wait): self.bound_client().execute(self.id, 'script', {'model':'gemini-web','prompt':'A'})
        self.assertEqual(BridgeHandler.posts, [])
    def test_stateful_ask_user_or_split_json_never_becomes_success(self):
        job = {'id': 'job-fixture', 'output_text': 'raw'}
        for changes in ({'action':'ask_user'}, {'messages':['{"a":','1}']}, {'id':'run-wrong'}):
            run = {'id':'run-fixture','job':job,'action':'reply','messages':['{"a":1}'],**changes}
            with self.assertRaises((Wait,ValueError)): normalized_reply(job,run)
    def test_image_only_artifact_accepts_empty_ignore_but_not_nonempty_refusal(self):
        job={'id':'job-fixture','output_text':'','output_images':[{'sha256':'a'*64}]}
        result={'id':'run-fixture','job':job,'action':'ignore','messages':[]}
        self.assertEqual(normalized_reply(job,result,True)['output_images'],job['output_images'])
        with self.assertRaises(Wait):normalized_reply({**job,'output_text':'I cannot help'},result,True)
    def failed_image_operation(self):
        from creator_orchestrator.shorts.stateful import build_reply
        client=self.bound_client();payload={'model':'chatgpt-web','modalities':['text','image'],'prompt':'Generate fixture image'}
        key=client.operation_key(self.id,'image',payload)
        self.store.prepare(key,self.id,'bridge',build_reply(client.binding,self.id,'image',payload,key))
        failed={'id':'job-source','raw_status':'failed','error':{'message':'ChatGPT did not start responding within 5 min; delivery is uncertain'},
                'task':{'resolvedChatUrl':client.binding['chatUrl'],'apiRequest':{'type':'project.reply'},'metadata':{'video_id':self.id}}}
        self.store.operation(key,'blocked','job-source',{'safe_error':'reader failed','result':failed})
        return client,payload
    def test_failed_image_capture_uses_read_only_recovery_without_resending_prompt(self):
        client,payload=self.failed_image_operation()
        result=client.execute_image(self.id,'image',payload)
        self.assertEqual(result['generation_job_id'],'job-source')
        self.assertEqual(len(BridgeHandler.posts),1)
        request=BridgeHandler.posts[0]
        self.assertTrue(request['metadata']['recoverExistingResult']);self.assertEqual(request['metadata']['video_recovery_of'],'job-source')
        self.assertEqual(request['attachments'],[])
        self.assertNotEqual(request['messages'][0]['content'],payload['prompt'])
        client.execute_image(self.id,'image',payload)
        self.assertEqual(len(BridgeHandler.posts),1)
    def test_newer_same_chat_operation_blocks_ambiguous_image_recovery(self):
        client,payload=self.failed_image_operation()
        client.execute(self.id,'another',{'model':'chatgpt-web','modalities':['text'],'prompt':'Another request'})
        with self.assertRaises(Wait) as caught:client.execute_image(self.id,'image',payload)
        self.assertEqual(caught.exception.state,'NEEDS_REVIEW');self.assertEqual(len(BridgeHandler.posts),1)
    def test_stateful_preserves_json_larger_than_public_message_limit(self):
        complete = json.dumps({'visual_prompt':'x'*12000})
        job = {'id':'job-fixture','output_text':json.dumps({'action':'reply','messages':[complete]})}
        run = {'id':'run-fixture','job':job,'action':'reply','messages':[complete[:10000]]}
        self.assertEqual(normalized_reply(job,run)['output_text'],complete)
    def test_explicit_unsent_busy_refusal_has_one_delayed_retry(self):
        BridgeHandler.busy_remaining = 1
        client = self.bound_client(); payload = {'model':'chatgpt-web','prompt':'Make JSON','modalities':['text']}
        for _ in range(2):
            with self.assertRaises(Wait) as caught: client.execute(self.id,'script',payload)
            self.assertEqual(caught.exception.state,'PENDING')
        self.assertEqual(len(BridgeHandler.posts),1)
        with self.store.connect() as db: db.execute('UPDATE operations SET updated=updated-31')
        self.assertEqual(client.execute(self.id,'script',payload)['output_text'],'{"ok":true}')
        self.assertEqual(len(BridgeHandler.posts),2)
        self.assertEqual(BridgeHandler.posts[1]['metadata']['preflight_retry_of'],'job-123')
        self.bound_client().execute(self.id,'script',payload)
        self.assertEqual(len(BridgeHandler.posts),2)
    def test_second_busy_refusal_stops_without_third_send_even_after_restart(self):
        BridgeHandler.busy_remaining = 2
        payload = {'model':'chatgpt-web','prompt':'Make JSON','modalities':['text']}
        with self.assertRaises(Wait): self.bound_client().execute(self.id,'script',payload)
        with self.store.connect() as db: db.execute('UPDATE operations SET updated=updated-31')
        for _ in range(2):
            with self.assertRaises(Wait) as caught: self.bound_client().execute(self.id,'script',payload)
            self.assertEqual(caught.exception.state,'WAITING_PROVIDER')
        self.assertEqual(len(BridgeHandler.posts),2)
    def test_proved_text_insertion_failure_has_one_delayed_retry(self):
        BridgeHandler.insert_timeout_remaining=1
        payload={'model':'chatgpt-web','prompt':'Make code','modalities':['text']}
        for _ in range(2):
            with self.assertRaises(Wait) as caught:self.bound_client().execute(self.id,'code',payload)
            self.assertEqual(caught.exception.state,'PENDING')
        self.assertEqual(len(BridgeHandler.posts),1)
        with self.store.connect() as db:db.execute('UPDATE operations SET updated=updated-31')
        self.assertEqual(self.bound_client().execute(self.id,'code',payload)['output_text'],'{"ok":true}')
        self.bound_client().execute(self.id,'code',payload)
        self.assertEqual(len(BridgeHandler.posts),2)
    def test_second_insertion_failure_never_gets_a_third_send(self):
        BridgeHandler.insert_timeout_remaining=2
        payload={'model':'chatgpt-web','prompt':'Make code','modalities':['text']}
        with self.assertRaises(Wait):self.bound_client().execute(self.id,'code',payload)
        with self.store.connect() as db:db.execute('UPDATE operations SET updated=updated-31')
        for _ in range(2):
            with self.assertRaises(Wait) as caught:self.bound_client().execute(self.id,'code',payload)
            self.assertEqual(caught.exception.state,'WAITING_PROVIDER')
        self.assertEqual(len(BridgeHandler.posts),2)
    def test_timeout_without_exact_presend_proof_is_not_retried(self):
        client=self.bound_client();payload={'model':'chatgpt-web','prompt':'Make code','modalities':['text']}
        result={'raw_status':'failed','error':{'message':'Input.insertText timed out'}}
        self.assertFalse(client.unsent_refusal(result,self.id,payload))
        result['task']={'apiRequest':{'type':'project.reply'},'metadata':{'video_id':self.id},'resolvedChatUrl':client.binding['chatUrl']}
        self.assertTrue(client.unsent_refusal(result,self.id,payload))
        result['task'].update(resolvedChatUrl='',chatUrl=client.binding['chatUrl'])
        self.assertTrue(client.unsent_refusal(result,self.id,payload))
        result['task']['chatUrl']='https://chatgpt.com/c/different'
        self.assertFalse(client.unsent_refusal(result,self.id,payload))
        result['task']['chatUrl']=client.binding['chatUrl']
        for message in ['Input.dispatchKeyEvent timed out','Runtime.evaluate timed out','ChatGPT did not start responding within 5 min; delivery is uncertain']:
            result['error']['message']=message
            self.assertFalse(client.unsent_refusal(result,self.id,payload))


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
