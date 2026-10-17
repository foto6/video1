import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from creator_orchestrator import local_studio as studio


class StudioInputTests(unittest.TestCase):
    def fixture(self, root):
        image = root / "кадр.png"
        image.write_bytes(b"sealed-authoring-asset")
        manifest = {"version": 1, "title": "Проверка", "scenes": [{
            "image": image.name, "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
            "title": "Привет", "caption": "Титры без кракозябр", "narration": "Русская озвучка"}]}
        path = root / "сценарий.json"
        path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        return path, image, manifest

    def test_changed_asset_is_rejected_before_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, image, _ = self.fixture(Path(tmp))
            studio.checked_manifest(path)
            image.write_bytes(b"changed-after-authoring")
            with self.assertRaisesRegex(ValueError, "Image changed"):
                studio.checked_manifest(path)

    def test_external_asset_is_rejected_even_with_a_valid_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); child = root / "project"; child.mkdir()
            path, image, manifest = self.fixture(child)
            external = root / "other.png"; external.write_bytes(image.read_bytes())
            manifest["scenes"][0]["image"] = "../other.png"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "inside the storyboard"):
                studio.checked_manifest(path)

    def test_corrupt_video_cannot_pass_final_qa(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.mp4"; path.write_bytes(b"not-a-video")
            with self.assertRaises(RuntimeError): studio.validate_final(path, 5)


if __name__ == "__main__": unittest.main()
