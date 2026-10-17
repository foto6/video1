"""Blind input-perception calibration. Answers are never included in the prompt."""
import json
from pathlib import Path
import re
import secrets
import unicodedata

from creator_orchestrator.local_studio import font_filter, narration, run
from .contracts import parse_json
from .store import Wait, file_hash


def normalized(value):
    return re.sub(r'[^\w]+', '', unicodedata.normalize('NFKC', str(value)).lower().replace('ё', 'е'))


def validate_observation(value, expected):
    if value.get('codes') != expected['codes'] or value.get('direction') != expected['direction']:
        raise Wait('WAITING_CAPABILITY', 'Модель не прошла скрытую проверку последовательности и движения видео')
    if normalized(value.get('spoken_text', '')) != normalized(expected['spoken_text']):
        raise Wait('WAITING_CAPABILITY', 'Модель не прошла скрытую проверку прослушивания звука')
    if not {'video', 'audio'} <= set(value.get('observed_modalities', [])):
        raise Wait('WAITING_CAPABILITY', 'Модель не подтвердила просмотр видео и прослушивание звука')
    return value


def ensure_perception(bridge, store, run_id, model, connection_revision, folder):
    evidence_name = 'perception-' + str(connection_revision)
    evidence = store.read(run_id, evidence_name)
    if evidence:
        if evidence['model'] != model or evidence['base_url'] != bridge.base_url:
            raise Wait('WAITING_CAPABILITY', 'Изменилось подключение критика; требуется новая проверка восприятия')
        return evidence
    challenge_name = evidence_name + '-challenge'
    challenge = store.read(run_id, challenge_name)
    work = Path(folder) / evidence_name
    if challenge is None:
        work.mkdir(exist_ok=True)
        codes = [str(secrets.randbelow(900) + 100) for _ in range(3)]
        words = ['медный', 'тихий', 'лунный', 'ясный', 'северный', 'алый']
        nouns = ['маяк', 'остров', 'берег', 'сигнал', 'ветер', 'парус']
        phrase = secrets.choice(words) + ' ' + secrets.choice(nouns) + ', ' + secrets.choice(words) + ' ' + secrets.choice(nouns)
        direction = secrets.choice(['left_to_right', 'right_to_left'])
        seconds = max(6, narration({'narration': phrase}, work, work / 'render.log') + .5)
        step = seconds / 3
        filters = []
        for i, code in enumerate(codes):
            (work / f'code-{i}.txt').write_text(code, encoding='utf-8')
            filters.append(f"drawtext=fontfile='{font_filter('arialbd.ttf')}':textfile=code-{i}.txt:expansion=none:fontsize=100:fontcolor=white:x=(w-text_w)/2:y=100:enable='gte(t,{i*step})*lt(t,{(i+1)*step})'")
        (work / 'marker.txt').write_text('●', encoding='utf-8')
        x = f'80+340*t/{seconds}' if direction == 'left_to_right' else f'420-340*t/{seconds}'
        filters.append(f"drawtext=fontfile='{font_filter('arialbd.ttf')}':textfile=marker.txt:expansion=none:fontsize=80:fontcolor=white:x='{x}':y=600")
        run(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-f', 'lavfi', '-i', f'color=c=0x102030:s=540x960:r=24:d={seconds}',
             '-i', 'voice.wav', '-vf', ','.join(filters), '-af', 'apad', '-t', str(seconds), '-c:v', 'libx264', '-preset', 'veryfast',
             '-c:a', 'aac', '-movflags', '+faststart', 'input.mp4'], cwd=work, log=work / 'render.log')
        challenge = store.artifact(run_id, challenge_name, {'codes': codes, 'direction': direction, 'spoken_text': phrase,
            'path': str(work / 'input.mp4'), 'sha256': file_hash(work / 'input.mp4'), 'purpose': 'synthetic input calibration, not production assets'})
    if file_hash(challenge['path']) != challenge['sha256']:
        raise ValueError('Calibration input changed')
    result = bridge.execute(run_id, evidence_name, {'model': model, 'modalities': ['text'], 'attachments': [{'path': challenge['path']}],
        'prompt': 'Inspect the ACTUAL attached MP4, both video and sound. Return ONLY JSON: '
                  '{"codes":["the three digit code at the beginning","the code in the middle","the code at the end"],'
                  '"direction":"left_to_right OR right_to_left for the white circle",'
                  '"spoken_text":"exact audible Russian words, no extra commentary",'
                  '"observed_modalities":["video","audio"]}. '
                  'If you cannot inspect a modality, do not guess; return an empty field and omit that modality.'})
    store.artifact(run_id, evidence_name + '-raw', result)
    validate_observation(parse_json(result), challenge)
    return store.artifact(run_id, evidence_name, {'passed': True, 'model': model, 'base_url': bridge.base_url, 'connection_revision': connection_revision,
        'bridge_job_id': result['id'], 'input_sha256': challenge['sha256'], 'verified': ['video_sequence', 'marker_direction', 'audio_transcription'],
        'scope': 'synthetic smoke calibration; final creative review still required'})
