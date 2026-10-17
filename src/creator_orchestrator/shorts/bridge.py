"""Only documented public /v1 calls. Never reads bridge configuration."""
import json
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request

from .store import Wait, file_hash, fingerprint


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class ApiError(RuntimeError):
    def __init__(self, status):
        self.status = status
        super().__init__(f'Bridge API HTTP {status}')


class BridgeClient:
    def __init__(self, base_url, token, store, timeout=30):
        parsed = urllib.parse.urlparse(base_url)
        if parsed.scheme not in {'http', 'https'} or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path.rstrip('/') != '/v1':
            raise ValueError('Bridge base URL must end in /v1, without credentials')
        self.base_url, self.token, self.store, self.timeout = base_url.rstrip('/'), token, store, timeout
        self.http = urllib.request.build_opener(NoRedirect)

    def request(self, route, body=None, binary=False):
        if not self.token:
            raise Wait('WAITING_INPUT', 'Введи API-токен моста в настройках видеоприложения')
        headers = {'Authorization': 'Bearer ' + self.token, 'Accept': 'application/json'}
        if body is not None:
            headers['Content-Type'] = 'application/json'
            if body.get('idempotency_key'):
                headers['Idempotency-Key'] = body['idempotency_key']
        request = urllib.request.Request(self.base_url + route, data=json.dumps(body, ensure_ascii=False).encode() if body is not None else None, headers=headers)
        try:
            with self.http.open(request, timeout=self.timeout) as response:
                data = response.read(26 * 1024 * 1024 + 1)
                if len(data) > 26 * 1024 * 1024:
                    raise ValueError('Bridge response exceeds 26 MB')
                return data if binary else json.loads(data)
        except urllib.error.HTTPError as exc:
            # Do not log provider bodies: they can contain URLs or secrets.
            raise ApiError(exc.code) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise Wait('WAITING_PROVIDER', 'Публичный API моста недоступен; сохранённое задание можно продолжить') from None

    def models(self):
        return self.request('/models')

    @staticmethod
    def job_id(value):
        if not isinstance(value, str) or not re.fullmatch(r'job-[A-Za-z0-9-]{1,100}', value):
            raise ValueError('Invalid bridge job ID')
        return value

    def execute(self, run_id, label, payload):
        key = 'shorts:' + run_id + ':' + label + ':' + fingerprint(payload)[:24]
        request = {**payload, 'idempotency_key': key, 'metadata': {**payload.get('metadata', {}), 'video_id': run_id, 'stage': label}}
        op = self.store.prepare(key, run_id, 'bridge', request)
        if op['state'] == 'completed':
            return op['response']
        if op['state'] == 'blocked':
            raise Wait('WAITING_PROVIDER', op['response']['safe_error'])
        if op['state'] == 'rejected':
            raise Wait('WAITING_CAPABILITY', 'Мост отклонил запрос: ' + str(op['response'].get('http_status')))
        if op['state'] == 'submitting' and not op['external_id']:
            listing = self.request('/jobs?limit=200')
            jobs = listing.get('data', listing.get('jobs', []))
            matches = [j for j in jobs if j.get('task', {}).get('idempotencyKey') == key or j.get('idempotency_key') == key]
            if len(matches) != 1:
                raise Wait('WAITING_RECONCILIATION', 'Ответ отправки потерян. Задание не пересоздавалось; нужна сверка idempotency key ' + key)
            self.store.operation(key, 'accepted', self.job_id(matches[0]['id']))
            op = self.store.op(key)
        if op['state'] == 'prepared':
            # Check credentials before recording a possible external side effect.
            if not self.token:
                raise Wait('WAITING_INPUT', 'Введи API-токен моста в настройках видеоприложения')
            self.store.operation(key, 'submitting')
            try:
                accepted = self.request('/jobs', request)
            except ApiError as exc:
                if exc.status in {400, 404, 405, 422}:
                    self.store.operation(key, 'rejected', response={'http_status': exc.status})
                    raise Wait('WAITING_CAPABILITY', f'Мост не принял этот тип запроса (HTTP {exc.status})') from None
                if exc.status in {401, 403, 429}:
                    self.store.operation(key, 'prepared')
                raise
            self.store.operation(key, 'accepted', self.job_id(accepted['id']))
            op = self.store.op(key)
        result = self.request('/jobs/' + self.job_id(op['external_id']))
        if result.get('status') == 'completed' or result.get('raw_status') == 'completed':
            self.store.operation(key, 'completed', response=result)
            return result
        if result.get('status') in {'failed', 'cancelled', 'requires_action'} or result.get('raw_status') in {'blocked', 'needs_login', 'needs_review', 'failed', 'cancelled'}:
            error = result.get('error', {})
            code = error.get('message', '') if isinstance(error, dict) else str(error)
            safe_code = code if re.fullmatch(r'[A-Z0-9_]{4,160}', code) else result.get('raw_status') or result.get('status')
            message = f"Мост остановил задание {op['external_id']}: {safe_code}"
            self.store.operation(key, 'blocked', response={'safe_error': message, 'result': result})
            raise Wait('WAITING_PROVIDER', message)
        raise Wait('PENDING', 'Ожидается результат моста: ' + op['external_id'])

    def image(self, result, destination):
        images = result.get('output_images') or []
        if not images:
            raise Wait('WAITING_CAPABILITY', 'Задание завершено, но мост не выдал изображение')
        metadata = images[0]
        data = self.request('/jobs/' + self.job_id(result['id']) + '/images/0', binary=True)
        import hashlib
        digest = hashlib.sha256(data).hexdigest()
        if metadata.get('sha256') and metadata['sha256'] != digest:
            raise ValueError('Bridge image checksum mismatch')
        if not (data.startswith(b'\x89PNG\r\n\x1a\n') or data.startswith(b'\xff\xd8\xff') or data[:4] == b'RIFF' and data[8:12] == b'WEBP'):
            raise ValueError('Bridge output is not a supported image')
        extension = '.png' if data.startswith(b'\x89PNG') else '.jpg' if data.startswith(b'\xff\xd8') else '.webp'
        path = Path(destination).with_suffix(extension)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if file_hash(path) != digest:
                raise ValueError('Existing image differs; refused overwrite')
        else:
            path.write_bytes(data)
        return {'path': str(path.resolve()), 'sha256': digest, 'bridge_job_id': result['id'], 'kind': 'illustration'}
