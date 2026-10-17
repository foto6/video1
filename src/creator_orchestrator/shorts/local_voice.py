"""Offline neural narration; source/model hashes are part of each receipt."""
import json
import os
from pathlib import Path
import subprocess

from .store import Wait, file_hash, fingerprint
from .voice import validate_wav

MANIFEST=Path('E:/AI-Video-Studio/models/piper-denis/ready.json')


class LocalPiperVoice:
    def __init__(self,store,manifest=MANIFEST):
        self.store=store
        path=Path(manifest)
        if not path.is_file():raise Wait('WAITING_CAPABILITY','Локальный русский нейроголос ещё устанавливается на E')
        self.config=json.loads(path.read_text(encoding='utf-8'))
        self.python=Path(self.config['python']);self.model=Path(self.config['model_path'])
        if self.config.get('engine')!='piper' or not self.python.is_file() or not self.model.is_file():
            raise Wait('WAITING_CAPABILITY','Установка локального голоса не завершена')
        if file_hash(self.model)!=self.config['model_sha256'] or file_hash(str(self.model)+'.json')!=self.config['config_sha256']:
            raise ValueError('Local voice model/config checksum mismatch')

    def speak(self,run_id,beat_id,transcript,folder):
        if not isinstance(transcript,str) or not transcript.strip() or len(transcript)>2000:
            raise ValueError('Invalid local narration')
        request={'text':transcript,'model_sha256':self.config['model_sha256'],'config_sha256':self.config['config_sha256'],
                 'engine':'piper','engine_version':self.config['engine_version'],'speaker':'Denis'}
        key='local-voice:'+run_id+':'+beat_id+':'+fingerprint(request)[:24]
        op=self.store.prepare(key,run_id,'local_piper',request)
        folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
        path=folder/(fingerprint(request)+'.wav')
        if op['state']=='completed':
            if not path.is_file() or file_hash(path)!=op['response']['sha256']:raise ValueError('Saved local voice changed')
            return op['response']
        if not path.exists():
            self.store.operation(key,'rendering')
            worker=Path(__file__).with_name('local_piper_worker.py')
            result=subprocess.run([str(self.python),str(worker)],input=json.dumps({'model_path':str(self.model),'text':transcript},ensure_ascii=False).encode('utf-8'),
                capture_output=True,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            if result.returncode:raise Wait('WAITING_CAPABILITY','Локальный синтез завершился ошибкой; проверь установку Piper')
            validate_wav(result.stdout)
            temporary=path.with_suffix('.tmp');temporary.write_bytes(result.stdout);temporary.replace(path)
        seconds=validate_wav(path.read_bytes())
        receipt={'path':str(path.resolve()),'sha256':file_hash(path),'voice_seconds':seconds,'provider':'local_piper',
                 'model':'ru_RU-denis-medium','voice':'Denis','model_sha256':self.config['model_sha256'],'runtime_version':self.config['engine_version'],
                 'word_timing':'not_available','beat_id':beat_id}
        self.store.operation(key,'completed',response=receipt)
        return receipt
