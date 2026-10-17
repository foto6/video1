"""Bridge-authored frame code, validated/rendered by the isolated Media runtime."""
import json
import math
import subprocess
from pathlib import Path

from . import contracts
from .store import Wait, file_hash, fingerprint


AUTHORING_RULES = '''Write a bespoke animated scene as one JavaScript function Scene({frame, fps, width, height, durationInFrames, palette}).
Return React JSX, no imports or exports. Canvas 1080x1920, 30 fps, local frame starts at zero. Use the supplied measured duration.
This is original motion design: animate actual vector objects, geometry, character poses, parallax, waves or light according to this beat.
Do not deliver a generic dashboard, progress bar, list of cards or static title slide. Match the shared character identity, art direction and story.
Keep important subjects within x=80..1000 and y=350..1350. Subtitles are overlaid separately at y=1480..1650. Put scene-specific titles at y=280..450 if useful.
Maintain a clear focal point, contrast, large readable typography, deliberate anticipation and a visible payoff. No tiny labels or unintended overflow.
Use const, arithmetic, ternaries, if/return, template strings, arrays and .map/.slice/.join/.toFixed, local pure helper functions.
Reusable local JSX components such as const Robot=({x,y})=><g>...</g> are supported inside Scene; keep recurring character proportions and colors identical between beats.
Allowed elements: div/span/p/strong/br; SVG svg/g/path/rect/circle/ellipse/line/polyline/polygon/text/tspan/defs/linearGradient/radialGradient/stop/clipPath/mask/filter/feGaussianBlur/feDropShadow/feColorMatrix/feBlend/feComposite/feMerge/feMergeNode.
SVG gradients/clips may use static local IDs with fill="url(#id)" or clipPath="url(#id)"; external resources are unavailable. Use a few deliberate layers; avoid costly large animated blur filters.
Use Math (except random); helpers clamp(value,min=0,max=1), range(n) capped at 64; interpolate(frame,[a,b],[x,y],{extrapolateLeft:'clamp',extrapolateRight:'clamp'}); spring({frame,fps,config:{damping:16}}).
Palette has background/accent/foreground. All animation must be a deterministic function of frame. No hooks, effects, CSS animation or transitions.
No loops, assignments, mutation, classes, new, async, DOM, browser/network/Node globals, computed property access, prototype access, imports, remote resources, event handlers, ref, href/src or spread syntax.
Use array.map((item,index)=>...) rather than array[index]. Helpers may be declared inside Scene. Local coordinates and transforms may be computed freely.
Output exactly the requested JSON with complete source string and concrete design_notes. Do not include markdown.'''


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
        if not (self.root/'media/remotion/node_modules/@remotion/renderer/package.json').is_file():
            raise Wait('WAITING_CAPABILITY','Не установлен локальный движок Remotion')
        beat=next(b for b in screenplay['beats'] if b['id']==shot['beat_id'])
        name=f'animation-code-{revision}-{shot["beat_id"]}'
        prompt=AUTHORING_RULES+'\n'+json.dumps({'title':screenplay['title'],'story':screenplay['beats'],'shared_style':plan['style'],
            'all_shots':plan['shots'],'current_beat':beat,'current_shot':shot,'measured_voice_seconds':voice['voice_seconds'],
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
