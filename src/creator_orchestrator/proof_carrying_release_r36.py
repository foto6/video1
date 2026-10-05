from __future__ import annotations
import argparse, copy, hashlib, json
from pathlib import Path
from typing import Any, Mapping, Sequence
from . import autonomous_reels as reels

CONTRACT_VERSION="creator.proof_carrying_release_rehearsal.r36.v1"
GRAPH_VERSION="creator.proof_graph.r36.v1"
STATUS_VERSION="creator.proof_carrying_release_status.r36.v1"
READINESS_VERSION="creator.proof_carrying_release_readiness.r36.v1"
CHAOS_VERSION="creator.proof_carrying_release_chaos.r36.v1"
NODES=("INTENT_FROZEN","AUTHORITY_VERIFIED","ESCROW_REHEARSED","CANARY_REHEARSED","CANARY_RECONCILED","EXPANSION_REHEARSED","FINAL_REHEARSAL_VERDICT")

R35={"repository":"foto6/video1","producerSha":"4793b7cb1735d21db6d211244018591b80c329a4","ciRunId":37244869884,"artifactId":11318269083,"artifactName":"creator-r35-release-escrow-canary-4793b7cb1735d21db6d211244018591b80c329a4","artifactDigest":"sha256:06753496d0d9cbe94d8b8a5218b10f5b38fa7455d98c89684374c6ba92965e0e","contract":"creator.release_escrow_canary.r35.v1","blobs":{"runtime":"5a565ee384cf767cd47125d9101b607c927d8818","tests":"1dd211439c502fd8c5f0bdc34f1ba1ab283c55c7","schema":"8bcd58df2b38bb83301f676b2ea4a82cef274976","authority":"2e25dcb9e5d588120fbbcea3d316fd79655a0707","manifest":"baa7d6bb9368d2d60ac0b4146d5125c1cfca810b","readiness":"9eb4502dae33026156921d2d46a6dc3af752c54b","docs":"accf3723cd34073f78cd3172921de0d048f99bf9"}}
GROWTH_R34={"repository":"foto6/video3","producerSha":"9ff243bc5ec6977bc5f0eb8f16cd5e51aa0dcdfc","ciRunId":37244660304,"artifactId":11318054384,"artifactName":"growth-r34-counterfactual-policy-promotion","artifactDigest":"sha256:6fc329964c14ce7c11f27fd2dd47235912470a377c6a1f5a6f3e66f4481f5ac9","contract":"growth.counterfactual_policy_promotion.r34.v1","blobs":{"authority":"ef6d2d636a651a927702e106609084e405124d22","contract":"d65858f6644d8445d6ba1665e793b371f5d93d7b","candidatePolicySchema":"8ec92c37761c5b8104739fcb894ac6c01f8ede19","corpusSchema":"722104d2ac77448a1db09b81d1bb3fa6266ad9ef","creatorEnvelopeSchema":"2ee8dc030ea418b4e25cc986288dbdee738df398","decisionSchema":"1199664fb0226a68449ec1a380734851896ecd79","policy":"c9ef96296d0883852df32b2a90ee6271474e033f","implementation":"74c847fe925375561a045b86f076498b85aafe8c","tests":"cd435e80096f5b2492ad4afff3b961d49767c76b","docs":"2ebbc64638ef7a6edf7ed8472ad6d9671fb8455b"},"advisoryOnly":True}
BRIDGE_R38={"repository":"foto6/WebAIBridge","producerSha":"f4f6070a975ac2c5bd8323777db1514c4733e427","ciRunId":37244988343,"contract":"bridge.agent_dag_orchestrator.r38.v1","artifacts":[{"id":11318149497,"name":"r38-reboot-resilient-agent-dag-ubuntu-latest","digest":"sha256:aaca65ba7f3beaa9f7cb393325a7f44872b5874fe6881c586dab7c56e79bdbe4"},{"id":11318049994,"name":"r38-reboot-resilient-agent-dag-windows-latest","digest":"sha256:384c0cdcc6759541953d415dab0ad96dffdef48bd467017b9ea5a6047615da85"}],"blobs":{"workflow":"d738d85554607d585c6ceeb351bad315a5dfaa6b","runtime":"052a463a3d507fd6c9e014500513dcc06d5d47d4","tests":"095d5296e841741add9c649d0d1960c4d8cfa614","nodeSchema":"cfdd64ccad7ee1c0a9924e5d86ea217b29d842a3","orchestratorSchema":"3cc5645eb9667ec5bff91fa7c734691a4b74fad2","journalSchema":"1daaffa185317add81ed67b188e1caebfd51b609","statusSchema":"ffbeea3e39dcdddfc63e0f3713516ba61e424232","chaos":"c4075b2492d0e841c3dad6b470b8e770243af89f","rehearsal":"054e0923b1b7dded89201ee736188de87f34d92e","status":"fe4a91767e85725dac707b2caae8964d3ef5ea90","readiness":"a131cc06241791a1b7fe2581999b6055e3c7cb93","docs":"96f57d53e6c29bd13a2ce46b4bf8ee62370d2253"}}
QA_R6={"repository":"foto6/boss","producerSha":"aa415759795beb24f1333d190ff842451020be5f","ciRunId":37245738748,"artifactId":11318958558,"artifactName":"hard-wave-acceptance-r6-aa415759795beb24f1333d190ff842451020be5f","artifactDigest":"sha256:5f2132293ecede7aa44bcf869fba42cd441454e778c361c3f49789cd7814fb8a","disposition":{"creatorR35":"ACCEPTED","growthR34":"ACCEPTED","bridgeR38":"ACCEPTED","mediaR25":"WAITING_EXACT_GREEN"},"blobs":{"authorityFixture":"294e45c35babf48f8d753d09e98d9f3963195c3c","runtime":"8c425c1f236ad86d61585956b4b9eafc88ec7d4c","tests":"c8e56af550d90ff3aa5286088aba2f9b6d55e3ae","docs":"0850908e8682f016a3fce5a4b5727f1f3e391f87","checkpoint":"2899763f83d4fe67b068e333cb9866e334202013","matrix":"d14d51941c8cd722e06fcd2b4ae074e871c67915","rejectedFaults":"eaae862f6f3f943be0348a80ae1ab8b9ac075b17"}}
MEDIA_R25={"status":"UNACCEPTED","consumption":"NOT_CONSUMED","repository":"foto6/video2","contract":"media.multicandidate_round.r25.v1","qaR6CutoffSha":"7ef00d9eec4b125f5ee7bcd28fc47cd390d82d86","qaR6CutoffCiRunId":37245663074,"qaR6CutoffCiStatus":"queued","qaR6Disposition":"WAITING_EXACT_GREEN","laterBranchMovementTrusted":False}

class ProofError(ValueError): pass

def _clone(v): return json.loads(reels.canonical_json(v))
def _sha(v): return reels.sha256_json(v)
def _node_digest(node):
    x=_clone(node); x["nodeDigest"]=""; return _sha(x)
def authority_envelope():
    v={"contractVersion":"creator.proof_carrying_release_authority.r36.v1","creatorR35":_clone(R35),"growthR34":_clone(GROWTH_R34),"bridgeR38":_clone(BRIDGE_R38),"qaR6":_clone(QA_R6),"mediaR25":_clone(MEDIA_R25)}
    v["authorityDigest"]=_sha(v); return v

def _validate_authority(a):
    expected=authority_envelope()
    if a!=expected: raise ProofError("authority envelope drift")
    if a["mediaR25"]["status"]!="UNACCEPTED" or a["mediaR25"]["consumption"]!="NOT_CONSUMED": raise ProofError("Media R25 must remain unaccepted/not-consumed")
    if a["qaR6"]["disposition"]!={"creatorR35":"ACCEPTED","growthR34":"ACCEPTED","bridgeR38":"ACCEPTED","mediaR25":"WAITING_EXACT_GREEN"}: raise ProofError("QA R6 disposition drift")
    return _clone(a)

def _journal():
    entries=[]
    prev=""
    for seq,(phase,outcome) in enumerate([
        ("ESCROW","FROZEN"),("CANARY_SEND","FAKE_UNKNOWN"),("CANARY_RECONCILE","FAKE_CONFIRMED"),
        ("EXPANSION_TIKTOK","FAKE_CONFIRMED"),("EXPANSION_YOUTUBE","FAKE_CONFIRMED")],1):
        e={"sequence":seq,"phase":phase,"operationId":"r36fake:"+_sha({"phase":phase})[:24],"outcome":outcome,"providerEffects":0,"networkEffects":0,"liveAuthorization":False,"previousEntryDigest":prev,"entryDigest":""}
        e["entryDigest"]=_sha({**e,"entryDigest":""}); prev=e["entryDigest"]; entries.append(e)
    return entries

def build_bundle():
    auth=authority_envelope()
    intent={"sourceSha256":"a"*64,"tournamentId":"r32t:"+"b"*64,"winnerRenderSha256":"c"*64,"winnerRenderSize":646823,"r35ReleaseOperationId":"r35release:"+("d"*64),"growthDecisionDigest":"e"*64,"policyDigest":"f"*64,"platforms":["instagram_reels","tiktok","youtube_shorts"],"revisionId":1}
    journal=_journal()
    evidence=[
      {"authorityDigest":auth["authorityDigest"],"intentDigest":_sha(intent)},
      {"qaR6Digest":_sha(QA_R6),"acceptedTupleDigest":_sha({"r35":R35,"growth":GROWTH_R34,"bridge":BRIDGE_R38})},
      {"escrowJournalDigest":journal[0]["entryDigest"],"renderHash":intent["winnerRenderSha256"]},
      {"canaryJournalDigest":journal[1]["entryDigest"],"unknownRequiresReconciliation":True},
      {"reconcileJournalDigest":journal[2]["entryDigest"],"blindRetry":False},
      {"expansionJournalDigest":_sha(journal[3:]),"platformCount":3},
      {"verdict":"SOURCE_READY_NO_LIVE_PROVIDER","provider_effects":0,"live_authorization":False,"mediaR25Consumed":False}
    ]
    graph=[]; prev=""
    for kind,payload in zip(NODES,evidence):
        node={"nodeType":kind,"predecessorDigest":prev,"evidence":payload,"evidenceDigest":_sha(payload),"nodeDigest":""}
        node["nodeDigest"]=_node_digest(node); prev=node["nodeDigest"]; graph.append(node)
    bundle={"contractVersion":CONTRACT_VERSION,"authorityEnvelope":auth,"intent":intent,"proofGraph":{"contractVersion":GRAPH_VERSION,"nodes":graph,"rootDigest":graph[0]["nodeDigest"],"finalDigest":graph[-1]["nodeDigest"]},"fakeProviderJournal":journal,"safety":{"provider_effects":0,"network_effects":0,"live_authorization":False,"fakeProviderOnly":True,"blindRetryAfterUnknown":False,"mediaR25Consumed":False},"verdict":"SOURCE_READY_NO_LIVE_PROVIDER","bundleDigest":""}
    bundle["bundleDigest"]=_sha({**bundle,"bundleDigest":""})
    return bundle

def verify_bundle(bundle: Mapping[str,Any]):
    required={"contractVersion","authorityEnvelope","intent","proofGraph","fakeProviderJournal","safety","verdict","bundleDigest"}
    if set(bundle)!=required or bundle["contractVersion"]!=CONTRACT_VERSION: raise ProofError("bundle shape/version mismatch")
    _validate_authority(bundle["authorityEnvelope"])
    if bundle["verdict"]!="SOURCE_READY_NO_LIVE_PROVIDER": raise ProofError("verdict drift")
    safety=bundle["safety"]
    if safety!={"provider_effects":0,"network_effects":0,"live_authorization":False,"fakeProviderOnly":True,"blindRetryAfterUnknown":False,"mediaR25Consumed":False}: raise ProofError("safety boundary drift")
    j=bundle["fakeProviderJournal"]
    if len(j)!=5: raise ProofError("journal length mismatch")
    prev=""
    for i,e in enumerate(j,1):
        if e["sequence"]!=i or e["previousEntryDigest"]!=prev or e["providerEffects"]!=0 or e["networkEffects"]!=0 or e["liveAuthorization"] is not False: raise ProofError("journal chain/effect drift")
        if _sha({**e,"entryDigest":""})!=e["entryDigest"]: raise ProofError("journal digest mismatch")
        prev=e["entryDigest"]
    g=bundle["proofGraph"]
    if g["contractVersion"]!=GRAPH_VERSION or len(g["nodes"])!=len(NODES): raise ProofError("proof graph shape mismatch")
    prev=""
    for expected,node in zip(NODES,g["nodes"]):
        if node["nodeType"]!=expected or node["predecessorDigest"]!=prev: raise ProofError("proof graph order/chain mismatch")
        if node["evidenceDigest"]!=_sha(node["evidence"]) or node["nodeDigest"]!=_node_digest(node): raise ProofError("proof node digest mismatch")
        prev=node["nodeDigest"]
    if g["rootDigest"]!=g["nodes"][0]["nodeDigest"] or g["finalDigest"]!=g["nodes"][-1]["nodeDigest"]: raise ProofError("proof graph root/final mismatch")
    if g["nodes"][3]["evidence"]["unknownRequiresReconciliation"] is not True or g["nodes"][4]["evidence"]["blindRetry"] is not False: raise ProofError("unknown-effect reconciliation boundary drift")
    if g["nodes"][-1]["evidence"]["provider_effects"]!=0 or g["nodes"][-1]["evidence"]["live_authorization"] is not False: raise ProofError("final verdict safety drift")
    if _sha({**bundle,"bundleDigest":""})!=bundle["bundleDigest"]: raise ProofError("bundle digest mismatch")
    return {"valid":True,"bundleDigest":bundle["bundleDigest"],"finalProofDigest":g["finalDigest"],"provider_effects":0,"live_authorization":False}

CASES=[
"r35_sha_drift","r35_ci_drift","r35_artifact_drift","r35_digest_drift","r35_contract_drift",
"growth_sha_drift","growth_ci_drift","growth_artifact_drift","growth_digest_drift","growth_not_advisory",
"bridge_sha_drift","bridge_ci_drift","bridge_ubuntu_digest_drift","bridge_windows_digest_drift","bridge_contract_drift",
"qa_sha_drift","qa_ci_drift","qa_artifact_drift","qa_digest_drift","qa_disposition_drift",
"media_r25_marked_accepted","media_r25_consumed","proof_node_reordered","proof_predecessor_drift","proof_evidence_drift",
"proof_node_digest_drift","proof_final_digest_drift","journal_sequence_drift","journal_previous_digest_drift","journal_entry_digest_drift",
"journal_provider_effect_nonzero","journal_network_effect_nonzero","journal_live_authorization_true","safety_provider_effect_nonzero","safety_live_authorization_true",
"safety_blind_retry_true","intent_render_hash_drift","intent_platform_set_drift","bundle_digest_drift","verdict_live_ready"
]

def _tamper(name,b):
    x=_clone(b)
    m={
      "r35_sha_drift":lambda: x["authorityEnvelope"]["creatorR35"].__setitem__("producerSha","0"*40),
      "r35_ci_drift":lambda: x["authorityEnvelope"]["creatorR35"].__setitem__("ciRunId",1),
      "r35_artifact_drift":lambda: x["authorityEnvelope"]["creatorR35"].__setitem__("artifactId",1),
      "r35_digest_drift":lambda: x["authorityEnvelope"]["creatorR35"].__setitem__("artifactDigest","sha256:"+"0"*64),
      "r35_contract_drift":lambda: x["authorityEnvelope"]["creatorR35"].__setitem__("contract","bad"),
      "growth_sha_drift":lambda: x["authorityEnvelope"]["growthR34"].__setitem__("producerSha","0"*40),
      "growth_ci_drift":lambda: x["authorityEnvelope"]["growthR34"].__setitem__("ciRunId",1),
      "growth_artifact_drift":lambda: x["authorityEnvelope"]["growthR34"].__setitem__("artifactId",1),
      "growth_digest_drift":lambda: x["authorityEnvelope"]["growthR34"].__setitem__("artifactDigest","sha256:"+"0"*64),
      "growth_not_advisory":lambda: x["authorityEnvelope"]["growthR34"].__setitem__("advisoryOnly",False),
      "bridge_sha_drift":lambda: x["authorityEnvelope"]["bridgeR38"].__setitem__("producerSha","0"*40),
      "bridge_ci_drift":lambda: x["authorityEnvelope"]["bridgeR38"].__setitem__("ciRunId",1),
      "bridge_ubuntu_digest_drift":lambda: x["authorityEnvelope"]["bridgeR38"]["artifacts"][0].__setitem__("digest","sha256:"+"0"*64),
      "bridge_windows_digest_drift":lambda: x["authorityEnvelope"]["bridgeR38"]["artifacts"][1].__setitem__("digest","sha256:"+"0"*64),
      "bridge_contract_drift":lambda: x["authorityEnvelope"]["bridgeR38"].__setitem__("contract","bad"),
      "qa_sha_drift":lambda: x["authorityEnvelope"]["qaR6"].__setitem__("producerSha","0"*40),
      "qa_ci_drift":lambda: x["authorityEnvelope"]["qaR6"].__setitem__("ciRunId",1),
      "qa_artifact_drift":lambda: x["authorityEnvelope"]["qaR6"].__setitem__("artifactId",1),
      "qa_digest_drift":lambda: x["authorityEnvelope"]["qaR6"].__setitem__("artifactDigest","sha256:"+"0"*64),
      "qa_disposition_drift":lambda: x["authorityEnvelope"]["qaR6"]["disposition"].__setitem__("creatorR35","REJECTED"),
      "media_r25_marked_accepted":lambda: x["authorityEnvelope"]["mediaR25"].__setitem__("status","ACCEPTED"),
      "media_r25_consumed":lambda: x["authorityEnvelope"]["mediaR25"].__setitem__("consumption","CONSUMED"),
      "proof_node_reordered":lambda: x["proofGraph"]["nodes"].reverse(),
      "proof_predecessor_drift":lambda: x["proofGraph"]["nodes"][2].__setitem__("predecessorDigest","0"*64),
      "proof_evidence_drift":lambda: x["proofGraph"]["nodes"][3]["evidence"].__setitem__("unknownRequiresReconciliation",False),
      "proof_node_digest_drift":lambda: x["proofGraph"]["nodes"][1].__setitem__("nodeDigest","0"*64),
      "proof_final_digest_drift":lambda: x["proofGraph"].__setitem__("finalDigest","0"*64),
      "journal_sequence_drift":lambda: x["fakeProviderJournal"][1].__setitem__("sequence",9),
      "journal_previous_digest_drift":lambda: x["fakeProviderJournal"][2].__setitem__("previousEntryDigest","0"*64),
      "journal_entry_digest_drift":lambda: x["fakeProviderJournal"][0].__setitem__("entryDigest","0"*64),
      "journal_provider_effect_nonzero":lambda: x["fakeProviderJournal"][1].__setitem__("providerEffects",1),
      "journal_network_effect_nonzero":lambda: x["fakeProviderJournal"][1].__setitem__("networkEffects",1),
      "journal_live_authorization_true":lambda: x["fakeProviderJournal"][1].__setitem__("liveAuthorization",True),
      "safety_provider_effect_nonzero":lambda: x["safety"].__setitem__("provider_effects",1),
      "safety_live_authorization_true":lambda: x["safety"].__setitem__("live_authorization",True),
      "safety_blind_retry_true":lambda: x["safety"].__setitem__("blindRetryAfterUnknown",True),
      "intent_render_hash_drift":lambda: x["intent"].__setitem__("winnerRenderSha256","0"*64),
      "intent_platform_set_drift":lambda: x["intent"].__setitem__("platforms",["instagram_reels"]),
      "bundle_digest_drift":lambda: x.__setitem__("bundleDigest","0"*64),
      "verdict_live_ready":lambda: x.__setitem__("verdict","LIVE_READY"),
    }
    m[name](); return x

def run_chaos(out_dir):
    root=Path(out_dir); root.mkdir(parents=True,exist_ok=True)
    base=build_bundle(); verify_bundle(base)
    cases={}
    for name in CASES:
        rejected=False
        try: verify_bundle(_tamper(name,base))
        except ProofError: rejected=True
        cases[name]={"passed":rejected,"expected":"REJECTED"}
    report={"reportVersion":CHAOS_VERSION,"caseCount":len(cases),"allCasesPassed":all(v["passed"] for v in cases.values()),"cases":cases,"unknownEffectProof":{"canaryOutcome":"FAKE_UNKNOWN","nextNode":"CANARY_RECONCILED","blindRetry":False,"provider_effects":0},"provider_effects":0,"network_effects":0,"live_authorization":False,"mediaR25":"UNACCEPTED_NOT_CONSUMED","verdict":"SOURCE_READY_NO_LIVE_PROVIDER","reportDigest":""}
    report["reportDigest"]=_sha({**report,"reportDigest":""})
    (root/"proof-bundle.r36.json").write_text(json.dumps(base,indent=2,sort_keys=True)+"\n")
    (root/"chaos-rehearsal.r36.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    (root/"fake-provider-journal.r36.json").write_text(json.dumps(base["fakeProviderJournal"],indent=2,sort_keys=True)+"\n")
    verification=verify_bundle(base)
    (root/"verification.r36.json").write_text(json.dumps(verification,indent=2,sort_keys=True)+"\n")
    return report

def readiness():
    v={"reportVersion":READINESS_VERSION,"state":"SOURCE_READY_NO_LIVE_PROVIDER","SOURCE_READY":True,"contract":CONTRACT_VERSION,"authorityEnvelope":authority_envelope(),"proofGraphNodes":list(NODES),"minimumAdversarialCases":35,"implementedAdversarialCases":len(CASES),"mediaR25":{"status":"UNACCEPTED","consumption":"NOT_CONSUMED"},"safety":{"fakeProviderOnly":True,"provider_effects":0,"network_effects":0,"live_authorization":False,"blindRetryAfterUnknown":False,"livePublish":False},"blockers":[{"code":"LIVE_PROVIDER_OUT_OF_SCOPE_R36"}]}
    v["reportDigest"]=_sha(v); return v

def status(bundle):
    v=verify_bundle(bundle)
    return {"contractVersion":STATUS_VERSION,"state":"SOURCE_READY_NO_LIVE_PROVIDER","bundleDigest":v["bundleDigest"],"finalProofDigest":v["finalProofDigest"],"provider_effects":0,"live_authorization":False,"nextPermittedAction":"INDEPENDENT_VERIFY_OR_STOP_NO_LIVE_PROVIDER","mediaR25":"UNACCEPTED_NOT_CONSUMED"}

def main(argv: Sequence[str]|None=None):
    p=argparse.ArgumentParser(prog="creator-proof-release-r36"); sub=p.add_subparsers(dest="cmd",required=True)
    q=sub.add_parser("readiness"); q.add_argument("--out")
    q=sub.add_parser("rehearsal"); q.add_argument("--out",required=True)
    q=sub.add_parser("verify"); q.add_argument("--bundle",required=True); q.add_argument("--out")
    q=sub.add_parser("status"); q.add_argument("--bundle",required=True); q.add_argument("--out")
    a=p.parse_args(argv)
    if a.cmd=="readiness": result=readiness()
    elif a.cmd=="rehearsal": result=run_chaos(a.out)
    else:
        b=json.loads(Path(a.bundle).read_text())
        result=verify_bundle(b) if a.cmd=="verify" else status(b)
    if getattr(a,"out",None) and a.cmd!="rehearsal": Path(a.out).write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print(json.dumps(result,sort_keys=True)); return 0

if __name__=="__main__": raise SystemExit(main())
