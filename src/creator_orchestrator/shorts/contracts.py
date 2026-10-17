"""Small declarative production language; model output cannot execute code."""
import json
import math
import re


MODES = {'illustration', 'motion_graphics', 'kinetic_text', 'library_video', 'native_video'}
MOTIONS = {'push_in', 'pull_out', 'pan_left', 'pan_right', 'graphic_build', 'text_reveal', 'source_motion'}
PRESETS = {'cards', 'comparison', 'steps', 'stat', 'signal'}


def text(value, label, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or any(ord(c) < 32 and c != '\n' for c in value):
        raise ValueError(f'{label}: expected nonempty text, max {maximum} characters')
    return value.strip()


def number(value, label, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{label}: expected number between {low} and {high}')
    return value


def parse_json(response):
    value = response.get('output_text', '').strip()
    if value.startswith('```'):
        value = re.sub(r'^```(?:json)?\s*', '', value)
        value = re.sub(r'\s*```$', '', value)
    try:
        result = json.loads(value, parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
    except (ValueError, TypeError):
        raise ValueError('Model did not return one valid JSON object; original response was saved') from None
    if not isinstance(result, dict):
        raise ValueError('Expected JSON object')
    return result


def script(value):
    text(value.get('title'), 'title', 90)
    beats = value.get('beats')
    if not isinstance(beats, list) or not 3 <= len(beats) <= 10:
        raise ValueError('Script needs 3 to 10 semantic beats')
    seen = set()
    for beat in beats:
        identifier = text(beat.get('id'), 'beat id', 30)
        if not re.fullmatch(r'[a-z0-9-]+', identifier) or identifier in seen:
            raise ValueError('Beat IDs must be unique safe identifiers')
        seen.add(identifier)
        text(beat.get('purpose'), 'purpose', 250)
        text(beat.get('narration'), 'narration', 260)
        text(beat.get('screen_text'), 'screen text', 90)
    if sum(len(b['narration']) for b in beats) > 1100:
        raise ValueError('Narration exceeds the first Shorts profile')
    return value


def shot_plan(value, screenplay):
    style = value.get('style', {})
    text(style.get('description'), 'style description', 1200)
    for field in ('background', 'accent', 'foreground'):
        if not isinstance(style.get(field), str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', style[field]):
            raise ValueError('Palette must use #RRGGBB')
    shots = value.get('shots')
    beats = {b['id']: b for b in screenplay['beats']}
    if not isinstance(shots, list) or len(shots) != len(beats) or {s.get('beat_id') for s in shots} != set(beats):
        raise ValueError('Exactly one shot per beat is required by profile v1')
    # Preserve narrative order even when the director replies out of order.
    shots.sort(key=lambda s: list(beats).index(s['beat_id']))
    for shot in shots:
        if shot.get('mode') not in MODES or shot.get('motion') not in MOTIONS:
            raise ValueError('Unsupported visual mode or motion')
        text(shot.get('purpose'), 'shot purpose', 300)
        text(shot.get('visual_prompt'), 'visual prompt', 2200)
        if shot['mode'] == 'illustration' and shot['motion'] not in {'push_in', 'pull_out', 'pan_left', 'pan_right'}:
            raise ValueError('Still image cannot satisfy object motion')
        if shot['mode'] in {'library_video', 'native_video'} and shot['motion'] != 'source_motion':
            raise ValueError('Real video must retain source motion')
        if shot['mode'] == 'motion_graphics':
            if shot.get('preset') not in PRESETS or shot['motion'] != 'graphic_build':
                raise ValueError('Choose a supported animated graphic preset')
            labels = shot.get('labels')
            if not isinstance(labels, list) or not 1 <= len(labels) <= 4:
                raise ValueError('Graphics need 1 to 4 labels')
            for label in labels:
                text(label, 'graphic label', 60)
        if shot['mode'] == 'kinetic_text' and shot['motion'] != 'text_reveal':
            raise ValueError('Kinetic text requires text_reveal')
        if shot.get('requires_object_motion') and shot['mode'] not in {'native_video', 'library_video'}:
            raise ValueError('Object motion requires a real video source')
    if len({s['mode'] for s in shots}) < 2:
        raise ValueError('Dynamic Shorts profile requires at least two visual modes')
    return value


def edit_plan(value, measured):
    shots = value.get('shots')
    if not isinstance(shots, list) or [s.get('beat_id') for s in shots] != [s['beat_id'] for s in measured]:
        raise ValueError('Edit plan must preserve all measured beats in narrative order')
    for shot, timing in zip(shots, measured):
        number(shot.get('lead_seconds'), 'voice lead', 0.05, 0.5)
        number(shot.get('tail_seconds'), 'tail', 0.05, 0.7)
        if shot.get('transition') not in {'cut', 'fade'}:
            raise ValueError('Unsupported transition')
        if shot['lead_seconds'] + timing['voice_seconds'] + shot['tail_seconds'] > 14:
            raise ValueError('A beat exceeds 14 seconds; revise the narration')
    if value.get('music') not in {'procedural', 'none'}:
        raise ValueError('Unsupported music source')
    return value


SCRIPT_SCHEMA = {'title': 'Russian title', 'beats': [{'id': 'hook', 'purpose': 'why this beat exists', 'narration': 'exact Russian voice text', 'screen_text': 'short readable phrase'}]}
SHOT_SCHEMA = {'style': {'description': 'shared art direction, recurring character/object details', 'background': '#101827', 'accent': '#6E8EFF', 'foreground': '#FFFFFF'}, 'shots': [{'beat_id': 'hook', 'purpose': 'semantic reason', 'mode': 'motion_graphics', 'motion': 'graphic_build', 'preset': 'steps', 'labels': ['A', 'B'], 'visual_prompt': 'exact appearance/action', 'requires_object_motion': False}]}
EDIT_SCHEMA = {'music': 'procedural', 'shots': [{'beat_id': 'hook', 'lead_seconds': 0.15, 'tail_seconds': 0.2, 'transition': 'cut'}]}
