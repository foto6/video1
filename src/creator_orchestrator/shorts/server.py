"""Loopback-only UI facade. Python Creator is the sole production owner."""
import argparse
import concurrent.futures
import ctypes
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import re
import shutil
import threading
import time
import urllib.parse
import uuid

from creator_orchestrator.local_studio import ROOT, probe
from .bridge import ApiError, BridgeClient
from .production import Production
from .store import Store, Wait, file_hash
from .stateful import chat_binding


class Blob(ctypes.Structure):
    _fields_ = [('length', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def crypt(value, decrypt=False):
    if os.name != 'nt':
        raise ValueError('Saved secrets require Windows DPAPI; use environment variables on other systems')
    import base64
    raw = base64.b64decode(value) if decrypt else value.encode('utf-8')
    buffer = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    if decrypt:
        ok = ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output))
    else:
        ok = ctypes.windll.crypt32.CryptProtectData(ctypes.byref(source), 'AI Video Studio', None, None, None, 1, ctypes.byref(output))
    if not ok:
        raise ValueError('Windows could not protect/unprotect the application credential')
    try:
        result = ctypes.string_at(output.data, output.length)
        return result.decode('utf-8') if decrypt else base64.b64encode(result).decode('ascii')
    finally:
        ctypes.windll.kernel32.LocalFree(output.data)


class Settings:
    def __init__(self, root):
        self.path = Path(root) / 'connection.json'
        self.lock = threading.RLock()

    def read(self):
        with self.lock:
            value = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {}
            return {**value, 'baseUrl': value.get('baseUrl', 'http://127.0.0.1:17448/v1'),
                    'token': crypt(value['bridgeProtected'], True) if value.get('bridgeProtected') else os.getenv('WEB_AI_BRIDGE_TOKEN', ''),
                    'geminiKey': crypt(value['geminiProtected'], True) if value.get('geminiProtected') else os.getenv('GEMINI_API_KEY', '')}

    def public(self):
        value = self.read()
        return {'baseUrl': value['baseUrl'], 'configured': bool(value['token']), 'geminiConfigured': bool(value['geminiKey']), 'library': value.get('library', {}),
                'chatUrl': value.get('binding', {}).get('chatUrl', ''), 'profileName': value.get('binding', {}).get('profileName', ''),
                'audio': 'Gemini TTS available when key is configured; bridge output requires probe', 'nativeVideo': 'not_verified'}

    def save(self, updates):
        with self.lock:
            old = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {}
            previous_base = old.get('baseUrl', 'http://127.0.0.1:17448/v1')
            previous_binding = old.get('binding')
            for field, storage in [('token', 'bridgeProtected'), ('geminiKey', 'geminiProtected')]:
                value = updates.get(field)
                if value:
                    if not isinstance(value, str) or len(value) > 8192 or any(ord(c) < 33 for c in value):
                        raise ValueError('Invalid credential')
                    old[storage] = crypt(value)
            if 'baseUrl' in updates:
                BridgeClient(updates['baseUrl'], '', None)
                old['baseUrl'] = updates['baseUrl'].rstrip('/')
            if updates.get('token') or updates.get('baseUrl') and updates['baseUrl'] != previous_base:
                old['revision'] = int(old.get('revision', 0)) + 1
            if 'library' in updates:
                old['library'] = updates['library']
            if 'chatUrl' in updates or 'profileName' in updates:
                chat_url = updates.get('chatUrl', old.get('binding', {}).get('chatUrl', ''))
                profile_name = updates.get('profileName', old.get('binding', {}).get('profileName', ''))
                if chat_url:
                    namespace = old.setdefault('instanceId', uuid.uuid4().hex)
                    old['binding'] = chat_binding(chat_url, profile_name, namespace)
                else:
                    old.pop('binding', None)
                if old.get('binding') != previous_binding:
                    old['revision'] = int(old.get('revision', 0)) + 1
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix('.tmp')
            temp.write_text(json.dumps(old, ensure_ascii=False), encoding='utf-8')
            temp.replace(self.path)


class Application:
    def __init__(self, root=ROOT, data=None, settings_root=None):
        self.root = Path(root)
        self.store = Store(data or self.root / 'data/shorts')
        self.settings = Settings(settings_root or self.store.root)
        self.stop = threading.Event()
        self.worker = threading.Thread(target=self.work, daemon=True, name='creator-production')

    def work(self):
        while not self.stop.is_set():
            for entry in self.store.list()[::-1]:
                if entry['state'] not in {'queued', 'running'} or entry['profile'].get('kind') == 'capability_audit':
                    continue
                identifier = entry['id']
                try:
                    Production(self.store, self.root, self.settings.read).advance(identifier)
                except Wait as exc:
                    previous = self.store.get(identifier)
                    if previous['state'] == 'PAUSED':
                        continue
                    state = 'running' if exc.state == 'PENDING' else exc.state
                    self.store.update(identifier, state, previous['stage'], error=str(exc))
                    if previous.get('error') != str(exc):
                        self.store.event(identifier, previous['stage'], str(exc))
                except ApiError as exc:
                    self.store.update(identifier, 'WAITING_PROVIDER', self.store.get(identifier)['stage'], str(exc))
                except Exception as exc:
                    # All provider transport errors are sanitized at their boundary.
                    self.store.update(identifier, 'FAILED', self.store.get(identifier)['stage'], str(exc)[:1200])
            self.stop.wait(4)

    def visible(self, entry):
        result = entry.get('result')
        final = {'sha256': result['final']['sha256'], 'url': '/api/videos/' + entry['id'] + '/final.mp4'} if result else None
        draft = None
        for revision in range(3):
            if self.store.read(entry['id'], f'media-{revision}'):
                draft = {'url': f"/api/videos/{entry['id']}/preview.mp4", 'revision': revision}
        return {k: entry[k] for k in ('id', 'topic', 'state', 'stage', 'error', 'events', 'created', 'updated')} | {'status': entry['state'], 'final': final, 'draft': draft}


def handler(app):
    class Handler(BaseHTTPRequestHandler):
        server_version = 'AI-Video-Studio/1'

        def log_message(self, *args):
            pass

        def secure(self, mutating=False):
            allowed = {'127.0.0.1', 'localhost'}
            host = urllib.parse.urlsplit('http://' + self.headers.get('Host', '')).hostname
            if host not in allowed:
                raise ValueError('Invalid local Host')
            origin = self.headers.get('Origin')
            if origin and origin not in {f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'}:
                raise ValueError('Cross-origin requests are not allowed')
            if mutating and self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                raise ValueError('Use application/json')

        def body(self):
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 <= length <= 65536:
                raise ValueError('Request body limit is 64 KB')
            value = json.loads(self.rfile.read(length) or b'{}')
            if not isinstance(value, dict):
                raise ValueError('Expected JSON object')
            return value

        def json(self, value, status=200):
            data = json.dumps(value, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(data)

        def file(self, path):
            path = Path(path)
            size = path.stat().st_size
            start, end = 0, size - 1
            requested = self.headers.get('Range')
            if requested:
                match = re.fullmatch(r'bytes=(\d+)-(\d*)', requested)
                if not match:
                    self.send_error(416)
                    return
                start = int(match[1])
                end = min(int(match[2]) if match[2] else end, end)
                if start > end or start >= size:
                    self.send_error(416)
                    return
            self.send_response(206 if requested else 200)
            self.send_header('Content-Type', mimetypes.guess_type(path)[0] or 'application/octet-stream')
            self.send_header('Content-Length', str(end-start+1))
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('X-Content-Type-Options', 'nosniff')
            if requested:
                self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
            self.end_headers()
            with path.open('rb') as f:
                f.seek(start)
                remaining = end-start+1
                while remaining:
                    chunk = f.read(min(65536, remaining))
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

        def do_GET(self):
            try:
                self.secure()
                route = urllib.parse.urlsplit(self.path).path
                if route == '/':
                    return self.file(app.root / 'ui/index.html')
                if route == '/api/health':
                    return self.json({'app': 'AI Video Studio', 'owner': 'Creator Python', 'version': 'shorts.v1', 'production_verified': False,
                                      'tools': {t: bool(shutil.which(t)) for t in ('node', 'ffmpeg', 'ffprobe')}})
                if route == '/api/connection':
                    return self.json(app.settings.public())
                if route == '/api/videos':
                    return self.json({'videos': [app.visible(x) for x in app.store.list() if x['profile'].get('kind') != 'capability_audit']})
                if route == '/api/capabilities':
                    return self.json({'audits': [{k: x[k] for k in ('id', 'state', 'stage', 'error')} for x in app.store.list() if x['profile'].get('kind') == 'capability_audit']})
                if route == '/api/voice-download':
                    status = Path('E:/AI-Video-Studio/models/voice-download-watch.json')
                    if not status.exists():
                        status = Path('E:/AI-Video-Studio/models/voice-download-status.json')
                    return self.json(json.loads(status.read_text(encoding='utf-8')) if status.exists() else {'status': 'not_started'})
                match = re.fullmatch(r'/api/videos/(vid-[a-f0-9]{32})/(final|preview)\.mp4', route)
                if match:
                    entry = app.store.get(match[1])
                    if match[2] == 'final' and entry['state'] == 'READY':
                        return self.file(entry['result']['final']['path'])
                    if match[2] == 'preview':
                        for revision in (2, 1, 0):
                            media = app.store.read(entry['id'], f'media-{revision}')
                            if media:
                                return self.file(media['preview'])
                self.json({'error': 'Not found'}, 404)
            except (KeyError, FileNotFoundError):
                self.json({'error': 'Not found'}, 404)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as exc:
                self.json({'error': str(exc)}, 400)

        def do_PUT(self):
            return self.mutate('PUT')

        def do_POST(self):
            return self.mutate('POST')

        def mutate(self, method):
            try:
                self.secure(True)
                route, body = urllib.parse.urlsplit(self.path).path, self.body()
                if method == 'PUT' and route == '/api/connection':
                    # Save independently: temporary provider failure must not lose the user's key.
                    app.settings.save({k: body[k] for k in ('baseUrl', 'token', 'geminiKey', 'chatUrl', 'profileName') if k in body})
                    return self.json(app.settings.public())
                if method == 'POST' and route == '/api/connection/check':
                    settings = app.settings.read()
                    models = BridgeClient(settings['baseUrl'], settings['token'], app.store).models()
                    return self.json({'ok': True, 'models': [m['id'] for m in models.get('data', [])]})
                if method == 'POST' and route == '/api/app/shutdown':
                    if any(x['state'] in {'queued', 'running'} for x in app.store.list()):
                        return self.json({'error': 'Сначала приостанови активные задания'}, 409)
                    self.json({'ok': True, 'message': 'Видеоприложение завершает работу; модельные задания сохранены'})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return
                if method == 'POST' and route == '/api/library':
                    path = Path(body.get('path', '')).resolve()
                    if not path.is_file() or path.suffix.lower() not in {'.mp4', '.mov', '.mkv', '.webm'}:
                        raise ValueError('Укажи полный путь к своему видеоклипу')
                    info = probe(path)
                    if not any(x.get('codec_type') == 'video' for x in info['streams']):
                        raise ValueError('В файле нет видеопотока')
                    asset_id = 'clip-' + file_hash(path)[:20]
                    library = app.settings.read().get('library', {})
                    library[asset_id] = {'path': str(path), 'sha256': file_hash(path), 'description': str(body.get('description', path.stem))[:300], 'duration': float(info['format']['duration']), 'rights': 'user_supplied'}
                    app.settings.save({'library': library})
                    return self.json({'id': asset_id, **library[asset_id]})
                if method == 'POST' and route == '/api/videos':
                    topic = body.get('topic', '').strip()
                    if not 5 <= len(topic) <= 1500:
                        raise ValueError('Тема должна содержать 5–1500 символов')
                    key = body.get('idempotencyKey')
                    if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}', key):
                        raise ValueError('Invalid request key')
                    voice_source = body.get('voiceSource', 'auto')
                    if voice_source not in {'auto', 'bridge', 'gemini'}:
                        raise ValueError('Invalid voice source')
                    profile = {'version': 1, 'text_model': 'chatgpt-web', 'image_model': 'chatgpt-web', 'voice_source': voice_source, 'voice': 'Kore'}
                    identifier = app.store.create(topic, profile, key)
                    return self.json(app.visible(app.store.get(identifier)), 202)
                match = re.fullmatch(r'/api/videos/(vid-[a-f0-9]{32})/resume', route)
                if method == 'POST' and match:
                    entry = app.store.get(match[1])
                    if entry['state'] == 'READY':
                        return self.json(app.visible(entry))
                    app.store.update(entry['id'], 'queued', entry['stage'])
                    return self.json({'ok': True})
                match = re.fullmatch(r'/api/videos/(vid-[a-f0-9]{32})/pause', route)
                if method == 'POST' and match:
                    entry = app.store.get(match[1])
                    if entry['state'] == 'READY':
                        raise ValueError('Completed production does not need pausing')
                    app.store.update(entry['id'], 'PAUSED', entry['stage'], 'Приостановлено в видеоприложении; принятое задание моста сохранено')
                    return self.json({'ok': True})
                return self.json({'error': 'Not found'}, 404)
            except Exception as exc:
                return self.json({'error': str(exc)[:1200]}, 400)
    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=17462)
    parser.add_argument('--data', type=Path, default=ROOT / 'data/production')
    parser.add_argument('--settings', type=Path, default=ROOT / 'data/shorts')
    args = parser.parse_args()
    app = Application(data=args.data, settings_root=args.settings)
    app.worker.start()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler(app))
    server.daemon_threads = True
    try:
        server.serve_forever()
    finally:
        app.stop.set()
        server.server_close()


if __name__ == '__main__':
    main()
