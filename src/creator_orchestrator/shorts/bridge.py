"""Only documented public /v1 calls. Never reads bridge configuration."""
import json
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from .store import Wait, file_hash, fingerprint
from .stateful import build_reply, normalized_reply, validate_route


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class ApiError(RuntimeError):
    def __init__(self, status):
        self.status = status
        super().__init__(f'Bridge API HTTP {status}')


class InvalidModelResponse(Wait):
    def __init__(self, message, result):
        super().__init__('NEEDS_REVIEW', message)
        self.result = result


PREFLIGHT_BUSY = 'Provider is still generating; refusing to interrupt or send another request'


class BridgeClient:
    def __init__(self, base_url, token, store, timeout=30, binding=None):
        parsed = urllib.parse.urlparse(base_url)
        if parsed.scheme not in {'http', 'https'} or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path.rstrip('/') != '/v1':
            raise ValueError('Bridge base URL must end in /v1, without credentials')
        self.base_url, self.token, self.store, self.timeout = base_url.rstrip('/'), token, store, timeout
        self.http = urllib.request.build_opener(NoRedirect)
        self.binding = binding

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

    def operation_key(self,run_id,label,payload):
        stateful=bool(self.binding) and 'audio' not in payload.get('modalities',[])
        identity={'payload':payload,'binding':self.binding,'transport':'stateful_reply_v1'} if stateful else payload
        return 'shorts:'+run_id+':'+label+':'+fingerprint(identity)[:24]

    def saved_text_request(self,run_id,label):
        """Recover the first exact request of a logical stage from older journals.

        Only an identical operation key in this binding is eligible. This never
        reuses another profile/chat or a different model request as a fallback.
        """
        with self.store.connect() as db:
            rows=db.execute('SELECT key,request FROM operations WHERE run_id=? AND provider=? ORDER BY rowid',(run_id,'bridge')).fetchall()
        for row in rows:
            request=json.loads(row['request'])
            if request.get('metadata',{}).get('stage')!=label or request.get('metadata',{}).get('preflight_retry_of'):continue
            if 'thread' in request:
                payload={'model':request['model'],'prompt':request['messages'][0]['content'],
                         'attachments':request.get('attachments',[]),'modalities':['text']}
            else:
                payload={k:request[k] for k in ['model','prompt','attachments','modalities'] if k in request}
            if self.operation_key(run_id,label,payload)==row['key']:return payload
        return None

    def unsent_refusal(self,result,run_id,payload):
        error=result.get('error',{})
        message=error.get('message','') if isinstance(error,dict) else ''
        if message==PREFLIGHT_BUSY:return True
        task=result.get('task',{})
        # Audited worker ordering: insertTextReliable completes before the first
        # clickSendReliable. project.reply disables the post-send follow-up path.
        # Restrict this exact insertion failure to bound, attachment-free text;
        # a Send/response/HTTP timeout remains an uncertain outcome, never retry.
        return bool(message=='Input.insertText timed out' and self.binding
            and result.get('raw_status')=='failed' and not result.get('output_text') and not result.get('output_images')
            and payload.get('modalities')==['text'] and not payload.get('attachments')
            and task.get('apiRequest',{}).get('type')=='project.reply'
            and task.get('metadata',{}).get('video_id')==run_id
            and (task.get('resolvedChatUrl') or task.get('chatUrl'))==self.binding['chatUrl'])

    def execute(self, run_id, label, payload, _busy_retry_of=None):
        # Audio has no confirmed stateful artifact contract and keeps its explicit probe path.
        stateful = bool(self.binding) and 'audio' not in payload.get('modalities', [])
        key = self.operation_key(run_id,label,payload)
        request = build_reply(self.binding, run_id, label, payload, key) if stateful else {**payload, 'idempotency_key': key, 'metadata': {**payload.get('metadata', {}), 'video_id': run_id, 'stage': label}}
        if stateful:
            previous = self.store.op(key)
            # Preserve already-submitted wire requests from before the explicit
            # no-fallback option was added. Poll them; do not create a new key.
            if previous and 'providerFallback' not in previous['request'].get('metadata', {}):
                request['metadata'].pop('providerFallback', None)
        op = self.store.prepare(key, run_id, 'bridge', request)
        if op['state'] == 'completed':
            return op['response']
        if op['state'] == 'blocked':
            if op['response'].get('waiting_state') == 'NEEDS_REVIEW' and op['response'].get('job'):
                raise InvalidModelResponse(op['response']['safe_error'], op['response']['job'])
            result = op['response'].get('result', {})
            error = result.get('error', {})
            if not _busy_retry_of and self.unsent_refusal(result,run_id,payload):
                if time.time() - op['updated'] < 30:
                    raise Wait('PENDING', 'Подтверждён отказ до отправки. Единственный повтор будет разрешён через 30 секунд')
                retry = {**payload, 'metadata': {**payload.get('metadata', {}), 'preflight_retry_of': op['external_id']}}
                return self.execute(run_id, label, retry, _busy_retry_of=op['external_id'])
            raise Wait(op['response'].get('waiting_state', 'WAITING_PROVIDER'), op['response']['safe_error'])
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
                accepted = self.request('/replies' if stateful else '/jobs', request)
            except ApiError as exc:
                if exc.status in {400, 404, 405, 422}:
                    self.store.operation(key, 'rejected', response={'http_status': exc.status})
                    raise Wait('WAITING_CAPABILITY', f'Мост не принял этот тип запроса (HTTP {exc.status})') from None
                if exc.status in {401, 403, 429}:
                    self.store.operation(key, 'prepared')
                raise
            accepted_id = accepted.get('job', {}).get('id') if stateful else accepted['id']
            self.store.operation(key, 'accepted', self.job_id(accepted_id), response={'bridge_run_id': accepted.get('id')} if stateful else None)
            op = self.store.op(key)
        result = self.request('/jobs/' + self.job_id(op['external_id']))
        run_result = None
        if stateful:
            run_result = self.request('/runs/run-' + op['external_id'][4:])
            try:
                validate_route(self.binding, run_result)
            except Wait as exc:
                evidence = {'safe_error': str(exc), 'waiting_state': exc.state, 'job': result, 'run': run_result}
                if result.get('raw_status') in {'pending', 'buffered', 'delayed', 'leased', 'uploading'}:
                    # Persist before cancellation. An uncertain cancellation is
                    # never repeated; its outcome can be inspected by job ID.
                    evidence['route_cancel'] = 'submitting'
                    self.store.operation(key, 'blocked', response=evidence)
                    try:
                        cancelled = self.request('/jobs/' + op['external_id'] + '/cancel', {})
                        evidence['route_cancel'] = cancelled.get('raw_status', 'unknown')
                    except (Wait, ApiError):
                        evidence['route_cancel'] = 'unknown; inspect existing job ID, no blind retry'
                self.store.operation(key, 'blocked', response=evidence)
                raise
        if result.get('status') == 'completed' or result.get('raw_status') == 'completed':
            if stateful:
                # The public API maps job-<task UUID> to run-<task UUID>.
                try:
                    result = normalized_reply(result, run_result, 'image' in payload.get('modalities', []))
                except Wait as exc:
                    self.store.operation(key, 'blocked', response={'safe_error': str(exc), 'waiting_state': exc.state, 'job': result, 'run': run_result})
                    if exc.state == 'NEEDS_REVIEW':
                        raise InvalidModelResponse(str(exc), result) from None
                    raise
            self.store.operation(key, 'completed', response=result)
            return result
        if result.get('status') in {'failed', 'cancelled', 'requires_action'} or result.get('raw_status') in {'blocked', 'needs_login', 'needs_review', 'failed', 'cancelled'}:
            error = result.get('error', {})
            code = error.get('message', '') if isinstance(error, dict) else str(error)
            safe_code = 'Модель ещё генерирует; мост отказался отправлять новый запрос' if code == PREFLIGHT_BUSY else code if re.fullmatch(r'[A-Z0-9_]{4,160}', code) else result.get('raw_status') or result.get('status')
            message = f"Мост остановил задание {op['external_id']}: {safe_code}"
            self.store.operation(key, 'blocked', response={'safe_error': message, 'result': result})
            if self.unsent_refusal(result,run_id,payload) and not _busy_retry_of:
                raise Wait('PENDING', 'Подтверждён отказ до отправки. Ожидается пауза перед единственным повтором')
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
        return {'path': str(path.resolve()), 'sha256': digest, 'bridge_job_id': result['id'],
                **({'generation_job_id':result['generation_job_id'],'capture_recovery':True} if result.get('capture_recovery') else {}), 'kind': 'illustration'}

    def execute_image(self,run_id,label,payload):
        """One read-only capture after a proved post-send reader failure.

        Uses the bridge worker's existing recoverExistingResult metadata path;
        that path never resets the composer, uploads, types or presses Send.
        A newer task in this dedicated chat makes recovery ambiguous and stops.
        """
        try:return self.execute(run_id,label,payload)
        except Wait as original:
            if not self.binding or 'image' not in payload.get('modalities',[]):raise
            key=self.operation_key(run_id,label,payload)
            op=self.store.op(key) or {}
            failed=(op.get('response') or {}).get('result',{})
            task=failed.get('task',{})
            error=failed.get('error',{})
            message=error.get('message','') if isinstance(error,dict) else ''
            if not (failed.get('raw_status')=='failed' and message.startswith('ChatGPT did not start responding within ')
                    and 'delivery is uncertain' in message and task.get('resolvedChatUrl')==self.binding['chatUrl']
                    and task.get('apiRequest',{}).get('type')=='project.reply'
                    and task.get('metadata',{}).get('video_id')==run_id):raise
            with self.store.connect() as db:
                parent=db.execute('SELECT rowid FROM operations WHERE key=?',(key,)).fetchone()[0]
                newer=db.execute('SELECT request FROM operations WHERE rowid>? AND provider=? AND state!=?',(parent,'bridge','prepared')).fetchall()
            for row in newer:
                request=json.loads(row['request'])
                if request.get('metadata',{}).get('video_recovery_of')==op['external_id']:continue
                if request.get('thread',{}).get('native_provider',{}).get('chat_url')==self.binding['chatUrl']:
                    raise Wait('NEEDS_REVIEW','После неудачного чтения в этот чат уже отправлялась другая задача; автоматическое получение старого изображения неоднозначно') from None
            recovered=self.execute(run_id,label+'-capture-recovery',{'model':payload['model'],'modalities':['image'],
                'prompt':'Read-only capture of the existing generated image from operation '+op['external_id']+'. Do not submit another provider message.',
                'attachments':[],'metadata':{'recoverExistingResult':True,'video_recovery_of':op['external_id']}})
            return {**recovered,'generation_job_id':op['external_id'],'capture_recovery':True}
