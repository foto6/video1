"""Audio-only exception authorized by the owner: Gemini REST TTS.

No direct visual/text creative calls are allowed here. The local model download
does not imply a working inference runtime. Windows TTS is fixture-only.
"""
import base64
import io
import json
from pathlib import Path
import re
import urllib.error
import urllib.request
import wave

from .bridge import NoRedirect
from .store import Wait, file_hash, fingerprint


def validate_wav(data):
    if not data.startswith(b'RIFF') or data[8:12] != b'WAVE':
        raise ValueError('TTS response is not WAV audio')
    with wave.open(io.BytesIO(data), 'rb') as source:
        seconds = source.getnframes() / source.getframerate()
        if source.getnchannels() not in {1, 2} or source.getsampwidth() != 2 or not .1 <= seconds <= 20:
            raise ValueError('Unsupported TTS format or duration')
        frames = source.readframes(source.getnframes())
        if len(frames) != source.getnframes() * source.getnchannels() * 2:
            raise ValueError('Truncated WAV audio')
    return seconds


class GeminiVoice:
    def __init__(self, store, key, model='gemini-3.8-flash-tts', voice='Kore'):
        if model not in {'gemini-3.8-flash-tts', 'gemini-3.8-flash-lite-tts'}:
            raise ValueError('Unsupported Gemini TTS model')
        if not re.fullmatch(r'[A-Za-z]{2,30}', voice):
            raise ValueError('Choose a named prebuilt voice')
        self.store, self.key, self.model, self.voice = store, key, model, voice

    def speak(self, run_id, beat_id, transcript, folder, style='Natural, energetic Russian narration. Clear pronunciation; no background music.'):
        if not self.key:
            raise Wait('WAITING_INPUT', 'Для озвучки нужен ключ Gemini API в настройках. Локальная TTS ещё не подключена')
        request = {'model': self.model, 'input': [{'type': 'user_input', 'content': [{'type': 'text', 'text': transcript, 'annotations': [{'type': 'speech_metadata', 'style': style}]}]}],
                   'response_format': {'type': 'audio', 'mime_type': 'audio/wav'}, 'generation_config': {'speech_config': [{'voice': self.voice}]}}
        key = 'voice:' + run_id + ':' + beat_id + ':' + fingerprint(request)[:24]
        operation = self.store.prepare(key, run_id, 'gemini_tts', request)
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (fingerprint(request) + '.wav')
        if operation['state'] == 'completed':
            receipt = operation['response']
            if not path.is_file() or file_hash(path) != receipt['sha256']:
                raise ValueError('Saved TTS output changed')
            return receipt
        response_path = folder / (fingerprint(request) + '.response.json')
        if operation['state'] in {'submitting', 'unknown'} and not response_path.exists():
            raise Wait('WAITING_RECONCILIATION', 'Ответ Gemini TTS потерян. Платный запрос автоматически не повторялся')
        if operation['state'] == 'prepared':
            self.store.operation(key, 'submitting')
            req = urllib.request.Request('https://generativelanguage.googleapis.com/v1beta/interactions',
                                         data=json.dumps(request, ensure_ascii=False).encode(),
                                         headers={'Content-Type': 'application/json', 'x-goog-api-key': self.key})
            try:
                with urllib.request.build_opener(NoRedirect).open(req, timeout=120) as response:
                    raw = response.read(20 * 1024 * 1024 + 1)
                if len(raw) > 20 * 1024 * 1024:
                    raise ValueError('TTS response exceeds 20 MB')
                # Save before decoding: crash recovery never silently requests again.
                with response_path.open('xb') as f:
                    f.write(raw)
            except urllib.error.HTTPError as exc:
                if exc.code in {400, 401, 403, 404, 429}:
                    self.store.operation(key, 'prepared')
                raise Wait('WAITING_PROVIDER', f'Gemini TTS HTTP {exc.code}; проверь ключ, модель и лимиты') from None
            except (urllib.error.URLError, TimeoutError, OSError):
                self.store.operation(key, 'unknown')
                raise Wait('WAITING_RECONCILIATION', 'Связь с Gemini TTS прервана; автоматического повтора нет') from None
        result = json.loads(response_path.read_text(encoding='utf-8'))
        audio = [part for step in result.get('steps', []) if step.get('type') == 'model_output'
                 for part in step.get('content', []) if part.get('type') == 'audio']
        if not audio:
            raise Wait('WAITING_CAPABILITY', 'Gemini API не вернул аудиофайл; ответ сохранён')
        data = base64.b64decode(audio[-1]['data'], validate=True)
        seconds = validate_wav(data)
        if path.exists() and path.read_bytes() != data:
            raise ValueError('Refused to overwrite existing speech')
        path.write_bytes(data)
        receipt = {'path': str(path.resolve()), 'sha256': file_hash(path), 'voice_seconds': seconds, 'provider': 'gemini_tts',
                   'model': self.model, 'voice': self.voice, 'interaction_id': result.get('id'), 'word_timing': 'not_available', 'beat_id': beat_id}
        self.store.operation(key, 'completed', result.get('id'), receipt)
        return receipt
