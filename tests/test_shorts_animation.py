import copy
from pathlib import Path
import tempfile
import unittest

from creator_orchestrator.shorts import contracts
from creator_orchestrator.shorts.server import Application
from creator_orchestrator.shorts.animation import AnimationAuthor
from creator_orchestrator.shorts.production import Production
from unittest.mock import patch

SCRIPT={'title':'Робот и океан','beats':[{'id':x,'purpose':'Показать событие','narration':'Робот увидел океан.','screen_text':'Океан'} for x in ['hook','body','payoff']]}
PLAN={'style':{'description':'Светлый робот с голубыми глазами, оранжевые ботинки, бирюзовая вода','background':'#101827','foreground':'#FFFFFF','accent':'#6E8EFF'},'shots':[{'beat_id':x['id'],'purpose':'Нарисовать событие','mode':'code_animation','motion':'procedural_motion','visual_prompt':'Робот поднимает руку, волны движутся','requires_object_motion':True} for x in SCRIPT['beats']]}

class AnimationProductionTests(unittest.TestCase):
    def test_vector_actions_are_supported_without_claiming_native_video(self):
        self.assertEqual(contracts.shot_plan(copy.deepcopy(PLAN),SCRIPT)['shots'][0]['motion'],'procedural_motion')
        bad=copy.deepcopy(PLAN);bad['shots'][0]['mode']='illustration';bad['shots'][0]['motion']='push_in'
        with self.assertRaises(ValueError):contracts.shot_plan(bad,SCRIPT)

    def test_new_version_reuses_real_script_and_keeps_parent_and_pause(self):
        with tempfile.TemporaryDirectory() as folder:
            app=Application(root=Path(folder),data=Path(folder)/'data',settings_root=Path(folder)/'settings')
            parent=app.store.create('Робот впервые увидел океан',{'version':1},'original-run',initial_state='PAUSED')
            app.store.artifact(parent,'script',SCRIPT)
            body={'topic':'Робот впервые увидел океан','idempotencyKey':'code-version-one','sourceVideoId':parent,'animationOnly':True}
            child=app.create_video(body)
            self.assertNotEqual(child,parent)
            self.assertEqual(app.store.read(child,'script'),SCRIPT)
            self.assertEqual(app.store.read(child,'script-provenance')['source_run_id'],parent)
            self.assertEqual(app.store.get(parent)['state'],'PAUSED')
            app.store.update(child,'PAUSED','SHOT_PLAN')
            self.assertEqual(app.create_video(body),child)
            self.assertEqual(app.store.get(child)['state'],'PAUSED')
            self.assertEqual(app.store.get(child)['profile']['visual_engine'],'remotion')

    def test_cannot_reuse_a_script_for_a_different_brief(self):
        with tempfile.TemporaryDirectory() as folder:
            app=Application(root=Path(folder),data=Path(folder)/'data')
            parent=app.store.create('Первый сюжет',{},'original-run')
            app.store.artifact(parent,'script',SCRIPT)
            with self.assertRaises(ValueError):app.create_video({'topic':'Совсем другой сюжет','idempotencyKey':'second-run','sourceVideoId':parent})

    def test_compact_author_migration_reuses_completed_scene_without_model_call(self):
        with tempfile.TemporaryDirectory() as folder:
            app=Application(root=Path(folder),data=Path(folder)/'data')
            identifier=app.store.create('Робот и океан',{},'original-run')
            source={'beat_id':'hook','source':'function Scene({frame}) { return <div>{frame}</div>; }','design_notes':'Робот'}
            app.store.artifact(identifier,'animation-code-0-hook',source)
            production=Production(app.store,folder,lambda:{})
            receipt={'request_sha256':'a'*64,'path':'rendered-scene.mp4'}
            with patch.object(AnimationAuthor,'render',return_value=receipt),patch.object(production,'structured') as model:
                self.assertEqual(AnimationAuthor(production).author(None,identifier,SCRIPT,PLAN,PLAN['shots'][0],{}, {},Path(folder)),receipt)
                model.assert_not_called()

if __name__=='__main__':unittest.main()
