"""One shared, durable bridge audio audit, including the original live request."""
from pathlib import Path

from .bridge import ApiError, BridgeClient
from .store import Store, Wait


def probe_audio(root, settings, model='gemini-web'):
    store = Store(Path(root) / 'data/shorts')
    identifier = store.create('Проверка аудиовыхода моста', {'kind': 'capability_audit', 'model': model},
                              'audio-capability-v1-' + model, initial_state='AUDIT')
    saved = store.read(identifier, 'audio-output-result')
    if saved:
        return saved
    client = BridgeClient(settings['baseUrl'], settings.get('token', ''), store)
    try:
        result = client.execute(identifier, 'audio-output', {'model': model, 'modalities': ['audio'],
            'prompt': 'Синтезируй русскую речь: «Маленький робот впервые увидел океан». Нужен настоящий аудиофайл, не описание, не картинка и не ссылка.'})
        value = {'state': 'completed', 'run_id': identifier, 'job_id': result['id'], 'public_result_fields': sorted(result),
                 'output_image_count': len(result.get('output_images', [])), 'text': result.get('output_text', '')[:1600],
                 'audio_download_supported': False, 'reason': 'No documented public audio artifact download route in current bridge contract'}
        store.artifact(identifier, 'audio-output-result', value)
        store.update(identifier, 'WAITING_CAPABILITY', 'AUDIO_PROBE', value['reason'])
        return value
    except Wait as exc:
        value = {'state': exc.state, 'run_id': identifier, 'message': str(exc), 'audio_download_supported': False}
        store.update(identifier, 'AUDIT' if exc.state == 'PENDING' else exc.state, 'AUDIO_PROBE', str(exc))
        return value
    except ApiError as exc:
        store.update(identifier, 'WAITING_PROVIDER', 'AUDIO_PROBE', str(exc))
        return {'state': 'WAITING_PROVIDER', 'run_id': identifier, 'message': str(exc), 'audio_download_supported': False}
