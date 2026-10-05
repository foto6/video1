from __future__ import annotations
import copy, json, tempfile, unittest
from pathlib import Path
from creator_orchestrator import proof_carrying_release_r36 as r36

class R36ProofCarryingReleaseTests(unittest.TestCase):
    def test_authority_envelope_exact_and_media_r25_not_consumed(self):
        a=r36.authority_envelope()
        self.assertEqual(a["creatorR35"]["producerSha"],"4793b7cb1735d21db6d211244018591b80c329a4")
        self.assertEqual(a["creatorR35"]["ciRunId"],37244869884)
        self.assertEqual(a["creatorR35"]["artifactId"],11318269083)
        self.assertEqual(a["creatorR35"]["artifactDigest"],"sha256:06753496d0d9cbe94d8b8a5218b10f5b38fa7455d98c89684374c6ba92965e0e")
        self.assertEqual(a["growthR34"]["producerSha"],"9ff243bc5ec6977bc5f0eb8f16cd5e51aa0dcdfc")
        self.assertEqual(a["growthR34"]["artifactId"],11318054384)
        self.assertEqual(a["bridgeR38"]["producerSha"],"f4f6070a975ac2c5bd8323777db1514c4733e427")
        self.assertEqual(a["qaR6"]["producerSha"],"aa415759795beb24f1333d190ff842451020be5f")
        self.assertEqual(a["qaR6"]["artifactId"],11318958558)
        self.assertEqual(a["mediaR25"]["status"],"UNACCEPTED")
        self.assertEqual(a["mediaR25"]["consumption"],"NOT_CONSUMED")
        self.assertFalse(a["mediaR25"]["laterBranchMovementTrusted"])

    def test_proof_graph_exact_order_and_content_addressed(self):
        b=r36.build_bundle()
        v=r36.verify_bundle(b)
        self.assertTrue(v["valid"])
        self.assertEqual([n["nodeType"] for n in b["proofGraph"]["nodes"]],list(r36.NODES))
        self.assertEqual(b["proofGraph"]["rootDigest"],b["proofGraph"]["nodes"][0]["nodeDigest"])
        self.assertEqual(b["proofGraph"]["finalDigest"],b["proofGraph"]["nodes"][-1]["nodeDigest"])
        for i,n in enumerate(b["proofGraph"]["nodes"]):
            self.assertEqual(n["nodeDigest"],r36._node_digest(n))
            self.assertEqual(n["evidenceDigest"],r36._sha(n["evidence"]))
            self.assertEqual(n["predecessorDigest"],"" if i==0 else b["proofGraph"]["nodes"][i-1]["nodeDigest"])

    def test_fake_provider_journal_has_zero_effects(self):
        b=r36.build_bundle()
        self.assertEqual(len(b["fakeProviderJournal"]),5)
        self.assertTrue(all(e["providerEffects"]==0 for e in b["fakeProviderJournal"]))
        self.assertTrue(all(e["networkEffects"]==0 for e in b["fakeProviderJournal"]))
        self.assertTrue(all(e["liveAuthorization"] is False for e in b["fakeProviderJournal"]))
        self.assertEqual(b["fakeProviderJournal"][1]["outcome"],"FAKE_UNKNOWN")
        self.assertEqual(b["fakeProviderJournal"][2]["phase"],"CANARY_RECONCILE")

    def test_unknown_effect_reconciles_without_retry(self):
        b=r36.build_bundle()
        canary=b["proofGraph"]["nodes"][3]["evidence"]
        reconcile=b["proofGraph"]["nodes"][4]["evidence"]
        self.assertTrue(canary["unknownRequiresReconciliation"])
        self.assertFalse(reconcile["blindRetry"])
        self.assertEqual(b["safety"]["provider_effects"],0)
        self.assertFalse(b["safety"]["blindRetryAfterUnknown"])

    def test_independent_verifier_rejects_each_adversarial_case(self):
        base=r36.build_bundle()
        self.assertGreaterEqual(len(r36.CASES),35)
        for name in r36.CASES:
            with self.subTest(name=name):
                with self.assertRaises(r36.ProofError):
                    r36.verify_bundle(r36._tamper(name,base))

    def test_authority_tuple_tamper_rejected(self):
        for top,key,val in [
            ("creatorR35","producerSha","0"*40),
            ("growthR34","artifactDigest","sha256:"+"0"*64),
            ("bridgeR38","ciRunId",1),
            ("qaR6","artifactId",1),
        ]:
            with self.subTest(top=top,key=key):
                b=r36.build_bundle(); b["authorityEnvelope"][top][key]=val
                with self.assertRaises(r36.ProofError): r36.verify_bundle(b)

    def test_media_r25_acceptance_or_consumption_fails_closed(self):
        for key,val in [("status","ACCEPTED"),("consumption","CONSUMED")]:
            b=r36.build_bundle(); b["authorityEnvelope"]["mediaR25"][key]=val
            with self.assertRaises(r36.ProofError): r36.verify_bundle(b)

    def test_graph_reorder_chain_and_evidence_tamper_fail(self):
        b=r36.build_bundle(); b["proofGraph"]["nodes"][1],b["proofGraph"]["nodes"][2]=b["proofGraph"]["nodes"][2],b["proofGraph"]["nodes"][1]
        with self.assertRaises(r36.ProofError): r36.verify_bundle(b)
        b=r36.build_bundle(); b["proofGraph"]["nodes"][4]["evidence"]["blindRetry"]=True
        with self.assertRaises(r36.ProofError): r36.verify_bundle(b)
        b=r36.build_bundle(); b["proofGraph"]["finalDigest"]="0"*64
        with self.assertRaises(r36.ProofError): r36.verify_bundle(b)

    def test_bundle_is_byte_stable(self):
        a=r36.build_bundle(); b=r36.build_bundle()
        self.assertEqual(a,b)
        self.assertEqual(r36._sha(a),r36._sha(b))

    def test_rehearsal_emits_full_bundle_journal_and_40_cases(self):
        with tempfile.TemporaryDirectory() as td:
            report=r36.run_chaos(td)
            root=Path(td)
            self.assertEqual(report["caseCount"],40)
            self.assertTrue(report["allCasesPassed"])
            self.assertFalse(report["unknownEffectProof"]["blindRetry"])
            self.assertEqual(report["provider_effects"],0)
            self.assertFalse(report["live_authorization"])
            for name in ["proof-bundle.r36.json","chaos-rehearsal.r36.json","fake-provider-journal.r36.json","verification.r36.json"]:
                self.assertTrue((root/name).is_file())
            bundle=json.loads((root/"proof-bundle.r36.json").read_text())
            self.assertTrue(r36.verify_bundle(bundle)["valid"])

    def test_readiness_source_ready_no_live_provider(self):
        r=r36.readiness()
        self.assertEqual(r["state"],"SOURCE_READY_NO_LIVE_PROVIDER")
        self.assertTrue(r["SOURCE_READY"])
        self.assertGreaterEqual(r["implementedAdversarialCases"],35)
        self.assertEqual(r["mediaR25"],{"status":"UNACCEPTED","consumption":"NOT_CONSUMED"})
        self.assertTrue(r["safety"]["fakeProviderOnly"])
        self.assertEqual(r["safety"]["provider_effects"],0)
        self.assertFalse(r["safety"]["live_authorization"])
        self.assertFalse(r["safety"]["blindRetryAfterUnknown"])

    def test_status_never_authorizes_live_effect(self):
        s=r36.status(r36.build_bundle())
        self.assertEqual(s["state"],"SOURCE_READY_NO_LIVE_PROVIDER")
        self.assertEqual(s["provider_effects"],0)
        self.assertFalse(s["live_authorization"])
        self.assertEqual(s["mediaR25"],"UNACCEPTED_NOT_CONSUMED")

if __name__=="__main__":
    unittest.main()
