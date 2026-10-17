"""Single resumable Creator pipeline. Model calls use BridgeClient, except TTS."""
import copy
import json
import math
from pathlib import Path

from creator_orchestrator.local_studio import make_score, run
from growth_analytics.shorts_review import DIMENSIONS, validate_review
from . import contracts
from .bridge import BridgeClient
from .audio_probe import probe_audio
from .capabilities import ensure_perception
from .store import Wait, file_hash, fingerprint
from .voice import GeminiVoice


class Production:
    def __init__(self, store, root, settings):
        self.store, self.root, self.settings = store, Path(root), settings

    def stage(self, identifier, stage, message):
        previous = self.store.get(identifier)
        if previous['state'] == 'PAUSED':
            raise Wait('PAUSED', 'Производство приостановлено')
        order = ['BRIEF', 'SCRIPT', 'SHOT_PLAN', 'ASSETS', 'VOICE_TIMING', 'EDIT_PLAN', 'PREVIEW', 'REVIEW', 'FINAL_QA', 'READY']
        if previous['stage'] in order and stage in order and order.index(stage) < order.index(previous['stage']):
            return
        if previous['stage'] != stage or previous['state'] != 'running':
            self.store.update(identifier, 'running', stage)
            self.store.event(identifier, stage, message)

    def structured(self, bridge, identifier, name, prompt, schema, validate, attachments=()):
        saved = self.store.read(identifier, name)
        if saved is not None:
            return validate(saved)
        response = bridge.execute(identifier, name, {'model': self.profile['text_model'],
            'prompt': prompt + '\nReturn only ONE JSON object, no markdown. Schema example (adapt content):\n' + json.dumps(schema, ensure_ascii=False),
            'attachments': [{'path': str(p)} for p in attachments], 'modalities': ['text']})
        self.store.artifact(identifier, name + '-raw', response)
        value = validate(contracts.parse_json(response))
        return self.store.artifact(identifier, name, value)

    def advance(self, identifier):
        entry = self.store.get(identifier)
        if entry['state'] == 'READY':
            return entry['result']
        self.profile = entry['profile']
        config = self.settings()
        bridge = BridgeClient(config['baseUrl'], config.get('token', ''), self.store, binding=config.get('binding'))
        if not config.get('token'):
            raise Wait('WAITING_INPUT', 'Введи API-токен моста в настройках видеоприложения')
        folder = self.store.folder(identifier)
        library = config.get('library', {})
        self.stage(identifier, 'SCRIPT', 'Сценарист: смысловые фрагменты и текст озвучки')
        screenplay = self.structured(bridge, identifier, 'script',
            'Create an original Russian dynamic Short, target 30-45 seconds. Topic: ' + entry['topic'] +
            '\nStart with a concrete hook, develop one clear idea, finish with a payoff. 4-7 beats, short sentences, about 70-95 Russian words total.'
            '\nIf the topic is factual, avoid unsupported statistics and citations. Do not invent research. Use a fictional demonstration when the topic asks for a demo.',
            contracts.SCRIPT_SCHEMA, contracts.script)
        self.stage(identifier, 'SHOT_PLAN', 'Режиссёр: общий стиль и способ визуализации каждого фрагмента')
        plan = self.structured(bridge, identifier, 'shot-plan',
            'Direct this Short. Script:\n' + json.dumps(screenplay, ensure_ascii=False) +
            '\nChoose each visual mode by semantic purpose, with at least two different modes. Available: illustration (AI image + camera push_in/pull_out/pan_left/pan_right), '
            'motion_graphics (graphic_build, presets cards/comparison/steps/stat/signal, 1-4 short labels), kinetic_text (text_reveal). '
            'library_video (source_motion) ONLY using these registered assets: ' + json.dumps({k: {'description': v['description'], 'duration': v['duration']} for k, v in library.items()}, ensure_ascii=False) +
            '. Put chosen ID in library_asset_id. Native video output is not confirmed: if actual object action is essential and library cannot supply it, use native_video/source_motion and requires_object_motion=true; this will wait for the capability. '
            'Do not claim a moving still is real object motion. Define a shared style and recurring character/object descriptions. One shot per beat in script order. '
            'Screen text and graphic labels must remain short and readable on a phone.',
            contracts.SHOT_SCHEMA, lambda v: contracts.shot_plan(v, screenplay))
        self.stage(identifier, 'ASSETS', 'Получение иллюстраций и проверка исходников для сцен')
        assets = {}
        references = []
        for shot in plan['shots']:
            beat_id = shot['beat_id']
            if shot['mode'] == 'native_video':
                raise Wait('WAITING_CAPABILITY', f'Сцене {beat_id} нужно действие внутри видеокадра. Выход видео через мост пока не подтверждён')
            if shot['mode'] == 'library_video':
                asset = library.get(shot.get('library_asset_id'))
                if not asset:
                    raise Wait('WAITING_INPUT', f'Не добавлен исходный видеоклип для сцены {beat_id}')
                if file_hash(asset['path']) != asset['sha256']:
                    raise ValueError('Library video changed')
                assets[beat_id] = asset
            elif shot['mode'] == 'illustration':
                name = 'image-' + beat_id + '-' + fingerprint({'shot': shot, 'style': plan['style']})[:20]
                saved = self.store.read(identifier, name)
                if saved:
                    if file_hash(saved['path']) != saved['sha256']:
                        raise ValueError('Illustration changed')
                    assets[beat_id] = saved
                else:
                    result = bridge.execute(identifier, name, {'model': self.profile['image_model'], 'modalities': ['text', 'image'],
                        'prompt': 'Generate one vertical 9:16 illustration, no captions or letters. Keep clear areas for overlay at top and bottom.\nSHARED STYLE: ' +
                        plan['style']['description'] + '\nSCENE: ' + shot['visual_prompt'] + '\nIf reference attached, preserve identity/style; create the new scene.',
                        'attachments': [{'path': x} for x in references[:1]]})
                    asset = bridge.image(result, folder / 'assets' / (name + '.image'))
                    assets[beat_id] = self.store.artifact(identifier, name, asset)
                references.append(assets[beat_id]['path'])
        self.stage(identifier, 'VOICE_TIMING', 'Озвучка: реальные аудиофайлы и измерение длительности')
        # Reuse the account-wide audit instead of submitting another audio task
        # per video or sending an already-known-broken generic ChatGPT request.
        voice_source = self.profile.get('voice_source', 'auto')
        if voice_source in {'auto', 'bridge'}:
            probe = probe_audio(self.root, config)
            if voice_source == 'bridge':
                if probe['state'] == 'PENDING':
                    raise Wait('PENDING', probe['message'])
                raise Wait('WAITING_CAPABILITY', 'Аудиовыход моста не подтверждён: нет проверенного публичного получения аудиофайла')
            if not config.get('geminiKey'):
                pending = ' Проба Gemini web ещё ожидает обработки.' if probe['state'] == 'PENDING' else ''
                raise Wait('WAITING_INPUT', 'Голос пока не готов: локальная модель скачивается, ключ Gemini TTS не настроен.' + pending)
        speech = GeminiVoice(self.store, config.get('geminiKey', ''), voice=self.profile.get('voice', 'Kore'))
        measured = [speech.speak(identifier, beat['id'], beat['narration'], folder / 'voice') for beat in screenplay['beats']]
        measured_duration = sum(x['voice_seconds'] for x in measured)
        if measured_duration > 60:
            raise Wait('NEEDS_REVIEW', 'Измеренная озвучка длиннее 60 секунд; нужен сокращённый сценарий')
        self.store.artifact(identifier, 'voice-timing', measured)
        self.stage(identifier, 'EDIT_PLAN', 'Монтажёр: паузы и переходы по измеренной речи')
        edit = self.structured(bridge, identifier, 'edit-plan', 'Create a declarative edit plan for this script and measured voice. Do not trim or change spoken words. '
            'lead_seconds 0.05-0.5, tail_seconds 0.05-0.7, transition cut/fade, music procedural/none. Preserve narrative order.\n' +
            json.dumps({'script': screenplay, 'shots': plan, 'measured_voice': measured}, ensure_ascii=False), contracts.EDIT_SCHEMA,
            lambda v: contracts.edit_plan(v, measured))
        for revision in range(3):
            if revision:
                saved = self.store.read(identifier, f'patch-state-{revision}')
                plan, screenplay, edit, assets = saved['plan'], saved['script'], saved['edit'], saved['assets']
            self.stage(identifier, 'PREVIEW', f'Сборка смешанных сцен, версия {revision + 1}')
            bundle = self.bundle(identifier, screenplay, plan, edit, assets, measured, folder)
            bundle_path = folder / f'bundle-{revision}.json'
            encoded = json.dumps(bundle, ensure_ascii=False, sort_keys=True, indent=2)
            if bundle_path.exists() and bundle_path.read_text(encoding='utf-8') != encoded:
                raise ValueError('Render bundle changed on resume')
            bundle_path.write_text(encoded, encoding='utf-8')
            output = folder / f'render-{revision}'
            result = json.loads(run(['node', self.root / 'media/tools/render-dynamic-shorts-v1.mjs', bundle_path, output], timeout=600))
            self.store.artifact(identifier, f'media-{revision}', result)
            self.stage(identifier, 'REVIEW', 'Критик проверяет настоящий черновик, движение и звук')
            ensure_perception(bridge, self.store, identifier, self.profile['text_model'], config.get('revision', 0), folder)
            review = self.structured(bridge, identifier, f'review-{revision}',
                'Review the ACTUAL attached preview video, audio and scene frames. State only modalities you actually perceived, not merely received. '
                'If video motion or audio could not be inspected, mark relevant dimensions unobserved, decision blocked. '
                'Do not approve from stills alone. Evaluate ' + ', '.join(sorted(DIMENSIONS)) + '. '
                'Issues and patches need beat_id and seconds inside this exact draft. Supported patch fields: screen_text, visual_prompt, motion, preset, labels, lead_seconds, tail_seconds, transition. '
                'Do not change narration; request blocked if it needs rewriting. Approve only if every dimension passes and no issues remain.\n' +
                json.dumps({'draft_sha256': result['final']['sha256'], 'script': screenplay, 'plan': plan, 'scene_timing': result['scenes'],
                            'duration': result['duration'], 'caption_timing': result['caption_timing']}, ensure_ascii=False),
                {'draft_sha256': result['final']['sha256'], 'decision': 'blocked', 'observed_modalities': [],
                 'dimensions': {d: {'status': 'unobserved', 'reason': 'specific evidence or limitation'} for d in sorted(DIMENSIONS)},
                 'issues': [], 'patches': []},
                lambda v: self.review(v, identifier, revision, result), [result['preview'], result['audio'], *result['frames']])
            if review['decision'] == 'approve':
                self.stage(identifier, 'FINAL_QA', 'Повторная проверка хеша проверенного финального файла')
                if file_hash(result['final']['path']) != result['final']['sha256'] or not result['technical_qa']['passed']:
                    raise ValueError('Reviewed final file changed or failed QA')
                delivery = {'version': 'shorts.delivery.v1', 'final': result['final'], 'media': result, 'review': review, 'revision': revision,
                            'model_operations': 'recorded in production.sqlite3', 'voice_source': 'gemini_tts', 'published': False}
                self.store.artifact(identifier, 'delivery', delivery)
                self.store.update(identifier, 'READY', 'READY', result=delivery)
                self.store.event(identifier, 'READY', 'MP4 прошёл техническую и творческую проверку')
                return delivery
            if review['decision'] == 'blocked' or revision == 2:
                raise Wait('NEEDS_REVIEW', 'Черновик сохранён. Критик не подтвердил качество или достигнут лимит двух исправлений')
            patch_state = self.store.read(identifier, f'patch-state-{revision+1}')
            if patch_state is None:
                plan, screenplay, edit, assets = self.patch(bridge, identifier, revision, review, plan, screenplay, edit, assets, folder)
                self.store.artifact(identifier, f'patch-state-{revision+1}', {'plan': plan, 'script': screenplay, 'edit': edit, 'assets': assets})

    def review(self, value, identifier, revision, media):
        raw = self.store.read(identifier, f'review-{revision}-raw')
        return validate_review(value, bridge_job_id=raw['id'], draft_sha256=media['final']['sha256'], scenes={s['beat_id'] for s in media['scenes']},
                               duration=media['duration'], provided_modalities={'video', 'audio', 'image'})

    def bundle(self, identifier, screenplay, plan, edit, assets, measured, folder):
        duration = sum(math.ceil((t['voice_seconds'] + e['lead_seconds'] + e['tail_seconds']) * 30) / 30 for t, e in zip(measured, edit['shots']))
        music = None
        if edit['music'] == 'procedural':
            path = folder / ('score-' + fingerprint(duration)[:20] + '.wav')
            if not path.exists():
                make_score(path, duration + .1)
            music = {'path': str(path), 'sha256': file_hash(path), 'source': 'deterministic_procedural_score'}
        return {'version': 1, 'id': identifier, 'style': plan['style'], 'music': music,
                'scenes': [{**shot, 'screen_text': beat['screen_text'], 'narration': beat['narration'], 'voice': voice, **editing, 'asset': assets.get(beat['id'])}
                           for beat, shot, voice, editing in zip(screenplay['beats'], plan['shots'], measured, edit['shots'])]}

    def patch(self, bridge, identifier, revision, review, plan, screenplay, edit, assets, folder):
        plan, screenplay, edit, assets = copy.deepcopy((plan, screenplay, edit, assets))
        for patch in review['patches']:
            index = next(i for i, b in enumerate(screenplay['beats']) if b['id'] == patch['beat_id'])
            changes = patch['changes']
            if 'screen_text' in changes:
                screenplay['beats'][index]['screen_text'] = changes['screen_text']
            for field in ('visual_prompt', 'motion', 'preset', 'labels'):
                if field in changes:
                    plan['shots'][index][field] = changes[field]
            for field in ('lead_seconds', 'tail_seconds', 'transition'):
                if field in changes:
                    edit['shots'][index][field] = changes[field]
        # Validate ALL patches before the first external generation.
        contracts.script(screenplay)
        contracts.shot_plan(plan, screenplay)
        measured = self.store.read(identifier, 'voice-timing')
        contracts.edit_plan(edit, measured)
        for patch in review['patches']:
            index = next(i for i, b in enumerate(screenplay['beats']) if b['id'] == patch['beat_id'])
            changes = patch['changes']
            if 'visual_prompt' in changes and plan['shots'][index]['mode'] == 'illustration':
                old = assets[patch['beat_id']]
                result = bridge.execute(identifier, f'patch-image-{revision}-{index}', {'model': self.profile['image_model'], 'modalities': ['text', 'image'],
                    'prompt': 'Edit this reference illustration. Preserve style and identity. New scene requirement: ' + changes['visual_prompt'],
                    'attachments': [{'path': old['path']}]})
                name = fingerprint({'request': changes, 'job': result['id']})
                assets[patch['beat_id']] = bridge.image(result, folder / 'assets' / (name + '.image'))
        return plan, screenplay, edit, assets
