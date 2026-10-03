"""[demo 브랜치 전용] 시연 대본 입구 — 음성 인식(STT)은 건너뛰고 대본 텍스트로 실제 MF_BERT 구조화만 돌린다.

자동 시연(demo/)의 시나리오 진행기가 통화 대본을 보내면, 실제 통화와 똑같이 발화를 줄바꿈으로 이어 MF_BERT에
넣고, hub로 보낼 CallSummaryMessage를 만들어 **돌려준다**(hub로 직접 보내지 않는다 — 진행기가 시연용 hub로 넘긴다.
그래서 이 voice가 실서버 hub에 붙어 있어도 시연 사건이 실서버로 새지 않는다). 파일 저장도 하지 않는다.

    POST /demo/structure {"caseId": "...", "lines": [{"start": 0.0, "end": 3.2, "text": "..."}], "durationSec": 48}
    → 200 {"message": <CallSummaryMessage>, "extractSec": 0.83}

⚠ develop에 병합하지 않는다(demo 브랜치 규칙).
"""
from __future__ import annotations

from flask import Flask, jsonify, request

from asr import Segment
from transcribe import build_call_summary_message


def register(app: Flask, get_extractor) -> None:
    @app.post("/demo/structure")
    def demo_structure():
        body = request.get_json(silent=True) or {}
        extractor = get_extractor()
        if extractor is None:
            return jsonify({"error": "모델을 아직 올리는 중입니다"}), 503
        lines = body.get("lines") or []
        segments = [
            Segment(start=float(x.get("start", 0)), end=float(x.get("end", 0)), text=str(x.get("text", "")).strip())
            for x in lines
            if str(x.get("text", "")).strip()
        ]
        if not segments:
            return jsonify({"error": "lines가 비어 있습니다"}), 400
        full_text = "\n".join(s.text for s in segments)
        summary, elapsed = extractor.extract(full_text)
        duration = float(body.get("durationSec") or segments[-1].end)
        message = build_call_summary_message(segments, duration, "demo", summary, body.get("caseId"))
        print(f"[시연 대본] caseId={body.get('caseId')} {len(segments)}문장 → 구조화 {elapsed:.2f}초")
        return jsonify({"message": message.to_payload(), "extractSec": round(elapsed, 2)}), 200
