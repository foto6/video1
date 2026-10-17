"""Bridge-authored frame code, validated/rendered by the isolated Media runtime."""
import json
import math
import subprocess
from pathlib import Path

from . import contracts
from .store import Wait, file_hash, fingerprint


AUTHORING_RULES = '''Create bespoke narrative vector animation, 1080x1920/30fps. Return ONE function Scene({frame,fps,width,height,durationInFrames,palette}) returning JSX, no imports/exports.
Match the shared identity and previous scenes in this conversation. Animate meaningful character poses/objects, waves, parallax/light with anticipation and payoff; no generic dashboard, cards or static slide.
Safe subject area x80..1000/y350..1350; separate subtitles occupy y1480..1650. Titles, if useful, y280..450. Keep strong composition and readable contrast.
Allowed: const, pure helper/local JSX components, if/return, arithmetic, ternaries, template strings, arrays .map/.slice/.join/.toFixed; standard SVG shapes/groups/text/gradients/clipPath/mask and div/span. Local url(#id) supported. Avoid expensive blur.
Globals: Math except random; clamp(v,a=0,b=1); range(n), capped64; interpolate(frame,[a,b],[x,y],{extrapolateLeft:'clamp',extrapolateRight:'clamp'}); spring({frame,fps,config:{damping:16}}). Palette: background/accent/foreground.
Pure deterministic frame code only: no hooks, effects, CSS animation/transition, loops, mutation, assignment, classes/new/async, DOM/network/Node globals, imports, computed property/prototype access, event handlers/ref/href/src, resources or spread. Use .map rather than array[index].
Return complete source and concrete design_notes in requested JSON, no markdown.'''


class AnimationAuthor:
    def __init__(self, production):
        self.production=production
        self.store,self.root=production.store,production.root

    def render(self, identifier, value, shot, voice, editing, style, folder):
        contracts.animation(value,shot['beat_id'])
        frames=math.ceil((voice['voice_seconds']+editing['lead_seconds']+editing['tail_seconds'])*30)
        request={'source':value['source'],'frames':frames,'palette':{k:style[k] for k in ['background','accent','foreground']},
                 'renderer_sha256':file_hash(self.root/'media/remotion/render.mjs'),'policy_sha256':file_hash(self.root/'media/remotion/validate.mjs')}
        target=folder/'animation'/shot['beat_id']/fingerprint(request)
        target.mkdir(parents=True,exist_ok=True)
        request_path=target/'request.json'
        request_path.write_text(json.dumps(request,ensure_ascii=False),encoding='utf-8')
        self.production.active(identifier)
        cached=target/'animation-receipt.json'
        if cached.is_file():
            receipt=json.loads(cached.read_text(encoding='utf-8'))
            if receipt.get('request_sha256')!=fingerprint(request) or file_hash(receipt['path'])!=receipt['sha256'] or any(file_hash(x['path'])!=x['sha256'] for x in receipt['sample_frames']):
                raise Wait('NEEDS_REVIEW','Сохранённый рендер анимации изменён; автоматическая перегенерация не выполняется')
            return {**receipt,'kind':'code_animation','source':value['source'],'design_notes':value['design_notes']}
        try:
            result=subprocess.run(['node',str(self.root/'media/remotion/render.mjs'),str(request_path),str(target)],
                capture_output=True,encoding='utf-8',errors='replace',timeout=480,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except subprocess.TimeoutExpired:
            raise Wait('NEEDS_REVIEW','Превышено время рендера анимации; код и запрос сохранены, новый модельный запрос автоматически не отправляется') from None
        (target/'render.log').write_text(result.stderr,encoding='utf-8')
        if result.returncode:
            raise ValueError('Animation preview execution failed: '+result.stderr[-2200:])
        try:
            receipt=json.loads(result.stdout)
        except ValueError:
            raise ValueError('Animation runtime did not return a valid receipt') from None
        if file_hash(receipt['path'])!=receipt['sha256'] or receipt['frames']!=frames:
            raise ValueError('Animation receipt/file mismatch')
        return {**receipt,'kind':'code_animation','source':value['source'],'design_notes':value['design_notes']}

    def author(self,bridge,identifier,screenplay,plan,shot,voice,editing,folder,revision=0,prior=None):
        legacy=f'animation-code-{revision}-{shot["beat_id"]}'
        saved=self.store.read(identifier,legacy)
        if saved is not None:
            rendered=self.render(identifier,saved,shot,voice,editing,plan['style'],folder)
            return self.store.artifact(identifier,legacy+'-render-'+rendered['request_sha256'][:16],rendered)
        if not (self.root/'media/remotion/node_modules/@remotion/renderer/package.json').is_file():
            raise Wait('WAITING_CAPABILITY','Не установлен локальный движок Remotion')
        beat=next(b for b in screenplay['beats'] if b['id']==shot['beat_id'])
        name=f'animation-code-v2-{revision}-{shot["beat_id"]}'
        prompt=AUTHORING_RULES+'\n'+json.dumps({'title':screenplay['title'],'story':[b['narration'] for b in screenplay['beats']],'shared_style':plan['style'],
            'current_beat':beat,'current_shot':shot,'measured_voice_seconds':voice['voice_seconds'],
            'editing':editing,'total_frames':math.ceil((voice['voice_seconds']+editing['lead_seconds']+editing['tail_seconds'])*30),
            'previous_scene_source_to_revise':prior.get('source') if prior else None},ensure_ascii=False)
        def validate(value):
            contracts.animation(value,shot['beat_id'])
            # A successful source artifact always has a real three-frame preview
            # and MP4. Resumed validation reuses content-addressed output.
            self.render(identifier,value,shot,voice,editing,plan['style'],folder)
            return value
        code=self.production.structured(bridge,identifier,name,prompt,{**contracts.ANIMATION_SCHEMA,'beat_id':shot['beat_id']},validate)
        rendered=self.render(identifier,code,shot,voice,editing,plan['style'],folder)
        return self.store.artifact(identifier,name+'-render-'+rendered['request_sha256'][:16],rendered)
