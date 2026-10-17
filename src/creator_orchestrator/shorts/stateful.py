"""Public stateful reply transport for an explicitly chosen provider chat.

Only the application's own namespaced project/thread records are upserted.
Brain sync, bootstrap, consultation and outbox delivery are disabled.
"""
import json
import re
import urllib.parse

from .store import Wait, fingerprint


def chat_binding(chat_url, profile_name='', namespace=''):
    if not isinstance(chat_url, str):
        raise ValueError('Expected provider chat URL')
    parsed = urllib.parse.urlsplit(chat_url.strip())
    if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.port:
        raise ValueError('Use a plain HTTPS conversation URL without query or credentials')
    provider = None
    if parsed.hostname in {'chatgpt.com', 'chat.openai.com'} and re.fullmatch(r'/c/[a-fA-F0-9-]{36}/?', parsed.path):
        provider = 'chatgpt'
        url = 'https://chatgpt.com' + parsed.path.rstrip('/')
    elif parsed.hostname == 'gemini.google.com' and re.fullmatch(r'/app/[a-zA-Z0-9_-]{8,100}/?', parsed.path):
        provider = 'gemini'
        url = 'https://gemini.google.com' + parsed.path.rstrip('/')
    else:
        raise ValueError('Use an existing ChatGPT /c/… or Gemini /app/… conversation')
    if not isinstance(profile_name, str) or len(profile_name) > 160 or any(ord(c) < 32 for c in profile_name):
        raise ValueError('Invalid bridge profile name')
    if not re.fullmatch(r'[a-f0-9]{32}', namespace):
        raise ValueError('The video application needs its own persistent namespace')
    return {'chatUrl': url, 'profileName': profile_name.strip(), 'provider': provider, 'namespace': namespace}


def new_chat_binding(profile_id, namespace):
    """Transient public reply route into an existing blank tab in one known profile.

    This is never accepted as a saved production conversation binding. The
    bridge retains its own existing-tab and draft/generation safeguards.
    """
    if not isinstance(profile_id, str) or not re.fullmatch(r'[a-f0-9-]{36}', profile_id):
        raise ValueError('An explicit public bridge profile ID is required')
    if not re.fullmatch(r'[a-f0-9]{32}', namespace):
        raise ValueError('The video application needs its own persistent namespace')
    return {'chatUrl': 'https://chatgpt.com/', 'profileName': profile_id,
            'provider': 'chatgpt', 'namespace': namespace, 'newChat': True}


def build_reply(binding, run_id, label, payload, key):
    model = payload.get('model', '')
    if not isinstance(model, str) or not model.startswith(binding['provider']):
        raise Wait('WAITING_CAPABILITY', 'Выбранная модель и привязанный чат относятся к разным провайдерам')
    operation_tag = fingerprint({'key': key})[:32]
    project_id = 'proj_video_' + binding['namespace'][:20] + '_' + fingerprint(binding['chatUrl'])[:12]
    native = {'enabled': True, 'provider': binding['provider'], 'mode': 'manual', 'chat_url': binding['chatUrl']}
    if binding.get('newChat'):
        native = {'enabled': False, 'provider': 'chatgpt', 'mode': 'manual'}
    policy = {'ignore_short_ack': False, 'buffer_seconds': 0, 'min_delay_seconds': 0, 'max_delay_seconds': 0, 'max_output_messages': 1}
    images = 'image' in payload.get('modalities', [])
    thread = {'id': 'thread_video_' + operation_tag, 'external_id': 'video-operation-' + operation_tag,
              'title': 'AI Video Studio: ' + label[:80], 'model': model, 'native_provider': native,
              'instructions': 'This is a private video production operation, not a human conversation. Perform only the current task. '
                              'For JSON requests, encode the requested complete JSON object as the single string in messages[0] of the bridge reply envelope. '
                              'Do not split it, paraphrase it, or send a reply to anyone. For image requests, generate the actual image file, then use action=reply and one short status message.',
              'policy': policy, 'delivery': {'mode': 'return'}}
    if binding['profileName']:
        thread['profile_id'] = binding['profileName']
    return {'project': {'id': project_id, 'name': 'AI Video Studio', 'default_model': model,
                        'instructions': 'Create original video assets/plans for the local owner. This API returns data to the video application only. '
                                        'Follow the bridge action/messages envelope, keeping the complete task result in one message.',
                        'brain_chat_enabled': False, 'brain_sync_enabled': False, 'brain_consult_enabled': False,
                        'policy': policy, 'delivery': {'mode': 'return'},
                        'metadata': {'owner_app': 'AI-Video-Studio', 'namespace': binding['namespace']}},
            'thread': thread,
            'messages': [{'external_id': 'input-' + operation_tag, 'role': 'user', 'content': payload['prompt']}],
            'attachments': payload.get('attachments', []), 'model': model,
            'metadata': {**payload.get('metadata', {}), 'video_id': run_id, 'stage': label,
                         'providerFallback': False,
                         'expectsImages': images, 'requiredSurface': 'chat' if binding['provider'] == 'chatgpt' else 'gemini_images' if images else 'chat'},
            'policy': policy, 'context_limit': 1, 'memory_limit': 1,
            'bootstrap_memory': False, 'allow_brain_consult': False, 'defer_brain_sync': False,
            'delivery_mode': 'return', 'sync': False, 'idempotency_key': key}


def normalized_reply(job, run_result, expects_images=False):
    expected_run = 'run-' + job['id'][4:]
    if run_result.get('id') != expected_run or run_result.get('job', {}).get('id') != job['id']:
        raise ValueError('Stateful run and job identity mismatch')
    if run_result.get('action') != 'reply':
        # A genuine image artifact can stand alone; plain text cannot bypass the envelope.
        artifact_only=expects_images and job.get('output_images') and not job.get('output_text','').strip() and run_result.get('action') in {'','ignore'}
        if not artifact_only:
            raise Wait('NEEDS_REVIEW', 'Мост вернул stateful-ответ без action=reply; исходный ответ сохранён')
    messages = run_result.get('messages', [])
    if not expects_images and (not isinstance(messages, list) or len(messages) != 1 or not isinstance(messages[0], str) or not messages[0].strip()):
        raise Wait('NEEDS_REVIEW', 'Stateful-ответ должен содержать один полный результат в messages[0]')
    text = messages[0] if messages else ''
    if not expects_images:
        # Public run messages are capped at 10,000 characters. Preserve the full
        # original JSON string from the same job instead of silently truncating it.
        try:
            envelope = json.loads(job.get('output_text', ''))
            raw_messages = envelope.get('messages')
        except (ValueError, AttributeError):
            raise Wait('NEEDS_REVIEW', 'Исходный stateful-ответ не соответствует JSON-конверту bridge reply') from None
        if envelope.get('action') != 'reply' or not isinstance(raw_messages, list) or len(raw_messages) != 1 or not isinstance(raw_messages[0], str):
            raise Wait('NEEDS_REVIEW', 'В исходном ответе нет одного полного JSON-результата в messages[0]')
        complete = raw_messages[0].strip()
        if not complete.startswith(text):
            raise ValueError('Public run message does not match original job envelope')
        text = complete
    return {**job, 'output_text': text, 'raw_envelope_text': job.get('output_text', ''),
            'bridge_run_id': run_result['id'], 'bridge_transport': 'stateful_reply_v1',
            'bridge_reply_action': run_result.get('action'), 'bridge_thread_id': run_result.get('thread_id')}


def validate_route(binding, run_result):
    """A bridge fallback is observable and must not silently change a chosen chat."""
    if run_result.get('provider') != binding['provider']:
        raise Wait('WAITING_PROVIDER', 'Мост сменил выбранного провайдера; результат другого маршрута не принимается')
    explicit = binding.get('profileName', '')
    if re.fullmatch(r'[a-f0-9-]{36}', explicit) and run_result.get('profile_id') != explicit:
        raise Wait('WAITING_PROVIDER', 'Мост сменил явно выбранный профиль; операция требует проверки')
    actual = run_result.get('chat_url', '')
    if binding.get('newChat'):
        parsed = urllib.parse.urlsplit(actual)
        matches = parsed.scheme == 'https' and parsed.hostname == 'chatgpt.com'
    else:
        matches = actual.rstrip('/') == binding['chatUrl'].rstrip('/')
    if not matches:
        raise Wait('WAITING_PROVIDER', 'Мост сменил выделенный чат; операция требует проверки')
