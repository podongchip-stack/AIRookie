"""Swift 포팅(GoldenLinkCore)이 Python 원본과 같은 결과를 내는지 대조할 정답 파일을 만든다. 모델 가중치는 필요 없다
(MF_BERT 토크나이저 몇 MB만 받는다). 로짓은 무작위로 만들어 decode()의 모든 갈래를 지나게 한다.

    conda activate rookie_voice      # voice 환경(torch·transformers)
    python dashboard/iphone/convert/make_fixtures.py
    cd dashboard/iphone/GoldenLinkCore && swift test
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import numpy as np
import torch
from huggingface_hub import snapshot_download
from transformers import AutoTokenizer

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "voice"))

from MF_BERT import labels as L  # noqa: E402
from MF_BERT.chunking import chunk_text  # noqa: E402
from MF_BERT.decode import decode  # noqa: E402
from MF_BERT.parse import NUMBER_RE, parse_age, parse_onset, parse_vitals  # noqa: E402
from live_transcriber import find_utterance_end, frame_rms  # noqa: E402
from weights import MF_BERT_REPO_ID, MF_BERT_REVISION  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "GoldenLinkCore/Tests/GoldenLinkCoreTests/Fixtures"

TEXTS = [
    "환자 62세 남성이고 30분 전부터 흉통 호소합니다. 혈압 150에 90, 맥박 110, 산소포화도 96%입니다.",
    "네 응급실입니다\n구급대원입니다. 교통사고 환자 50대 남성, 의식 저하, 호흡 곤란 있습니다.",
    "혈압은 백오십에 구십이고 맥박 백십 호흡 이십 체온 삼십육점팔도요",
    "생후 8개월 여아 열이 39도 8부, 경련 5분 정도 했고요 BST 120",
    "85년생 여성분 어제 저녁부터 복통, 오후 3시 15분에 구토 두 번",
    "혈압 측정 안 되고 맥박 안 잡혀요. CPR 시행 중, AED Shock 1회",
    "산소 15리터에 94% 유지 중이고 호흡수 28회, 혈당 하이(HI)",
    "할머니 80대 후반, 낙상 후 고관절 통증, 좌측 다리 단축 외회전",
    "2시간 반 전부터 두통, 우측 팔다리 마비, 뇌졸중 의심",
    "사흘 전부터 기침 가래, 체온 38.5도, SpO2 91",
    "아스피린 복용 중이시고 와파린도 드세요. 고혈압 당뇨 있으시고요.",
    "ＡＢＣ　전각 문자와 한자 頭痛 그리고 이모지 없이 끝",
    "",
]

VITALS = [
    "혈압 150에 90, 맥박 110, 산소포화도 96%", "혈압은 백오십에 구십이고 맥박 백십", "BP 120/80 HR 88 RR 20",
    "맥박이 100 호흡 20", "체온 삼십육점팔", "39도 8부", "36.8도로 정상", "혈압 측정 안 되고 맥박 안 잡혀요",
    "산소 15리터에 94%", "호흡곤란 있고 맥박 구십 칠", "혈당 백십 육", "산소포화도 구십삼이고", "혈압 80에 50 맥박 140 체온 열",
    "새츄레이션 88프로", "BST 측정불가", "호흡음 감소 호흡수 30", "혈압 바이 90", "혈압 130 바이 85", "맥박 촉지 안 됨",
    "펄스 60 혈압 백이십에 팔십 산소 98", "체온 40.2", "열 38도 5부", "혈압 90/60 산소 2리터 비관 투여 중 포화도 95",
]
AGES = ["62세 남성", "50대", "80대 후반", "생후 8개월", "생후 3일", "85년생", "2010년생", "05년생", "10세 미만", "신생아",
        "여성분이세요 서른다섯 살", "육십오세", "스물셋", "두 살 아기", "100세", "90대", "애기", "7개월", "열 살"]
ONSETS = ["30분 전부터", "2시간 반 전", "1시간 20분 전", "어제 저녁", "방금", "사흘 전", "일주일 전", "반나절", "그제",
          "오후 3시 15분", "10분 후", "하루 종일", "3일", "두 시간 전", "한 달 전", "삼십 분 전"]


def tokenizer_cases(tok) -> list[dict]:
    out = []
    for text in TEXTS:
        enc = tok(text, add_special_tokens=False, return_offsets_mapping=True)
        out.append({"text": text, "ids": enc["input_ids"], "offsets": [list(p) for p in enc["offset_mapping"]]})
    return out


def chunk_cases(tok) -> list[dict]:
    long_text = "\n".join(TEXTS * 8)
    cases = []
    for text, size, stride in [(TEXTS[0], 512, 128), (long_text, 512, 128), (long_text, 64, 16), (long_text, 40, 0)]:
        c = chunk_text(text, tok, size, stride)
        cases.append({"text": text, "chunk_tokens": size, "stride": stride, "chunks": c["chunks"], "keep": c["keep"],
                      "offsets": [list(p) for p in c["offsets"]]})
    return cases


def random_tags(n: int, rng: random.Random) -> list[int]:
    tags = [0] * n
    i = 1
    while i < n - 1:
        if rng.random() < 0.25:
            t = rng.randrange(len(L.SPAN_TYPES))
            length = rng.randint(1, 6)
            for j in range(i, min(i + length, n - 1)):
                tags[j] = 1 + 2 * t + (0 if j == i else 1)
            if rng.random() < 0.2:  # 짝 없는 I-
                tags[i] = 2 + 2 * t
            i += length
        i += 1
    return tags


def decode_cases(tok) -> list[dict]:
    rng = random.Random(7)
    torch.manual_seed(7)
    sizes = {h.name: h.size for h in L.SINGLE_CHOICE_HEADS}
    sizes.update({k: len(v) for k, v in L.MULTI_LABEL_HEADS.items()})
    cases = []
    for k in range(60):
        text = TEXTS[k % (len(TEXTS) - 1)]
        c = chunk_text(text, tok)
        offsets = c["offsets"]
        heads = {}
        for name, size in sizes.items():
            v = torch.randn(1, size) * 2
            if name in L.MULTI_LABEL_HEADS:
                v = v - 2.5  # 양성이 몇 개만 나오게
            if k % 5 == 0 and name in ("cc_major", "primary_incident", "sex", "avpu", "disease"):
                v[0, -1] = 10  # 미언급 갈래
            heads[name] = v
        tags = random_tags(len(offsets), rng)
        spans = torch.full((1, len(offsets), len(L.SPAN_TAGS)), -5.0)
        spans[0, torch.arange(len(offsets)), torch.tensor(tags)] = 5.0
        logits = {**heads, "spans": spans}
        expected = decode(text, logits, offsets)
        # 원본의 incidents 순서는 set 순회 순서라 실행마다 다를 수 있다 — 주 사고 다음을 보기 순서로 맞춘다(Decode.swift와 같게)
        expected["incidents"].sort(key=lambda d: (not d["primary"], L.INCIDENT_TYPES.index(d["type"])))
        cases.append({"text": text, "heads": {n: v[0].tolist() for n, v in heads.items()}, "tags": tags,
                      "offsets": [list(p) for p in offsets], "expected": expected})
    return cases


def segment_cases() -> dict:
    rng = np.random.default_rng(3)
    finds = []
    for _ in range(300):
        n = int(rng.integers(0, 160))
        rms = (rng.random(n) * 0.02).astype(np.float32)
        # 말하는 구간 몇 개 끼워 넣기
        for _ in range(int(rng.integers(0, 3))):
            a = int(rng.integers(0, max(1, n)))
            rms[a:a + int(rng.integers(1, 40))] = 0.05
        hold = int(rng.integers(1, 8))
        finds.append({"rms": rms.tolist(), "threshold": 0.01, "hold": hold,
                      "expected": find_utterance_end(rms, 0.01, hold)})
    # 오디오 -> 프레임 RMS (float32 계산 차이 확인)
    audio = (rng.standard_normal(16000 * 3) * 0.05).astype(np.float32)
    return {"find": finds, "frame_audio": audio[:16000].tolist(), "frame_rms": frame_rms(audio[:16000]).tolist()}


def main() -> None:
    tok = AutoTokenizer.from_pretrained(
        Path(snapshot_download(MF_BERT_REPO_ID, revision=MF_BERT_REVISION, allow_patterns=["tokenizer/*"])) / "tokenizer")
    OUT.mkdir(parents=True, exist_ok=True)
    data = {
        "tokenizer": tokenizer_cases(tok),
        "chunks": chunk_cases(tok),
        "number_re": NUMBER_RE,
        "vitals": [{"text": t, "expected": parse_vitals(t)} for t in VITALS],
        "ages": [{"text": t, "expected": parse_age(t)} for t in AGES],
        "onsets": [{"text": t, "expected": parse_onset(t)} for t in ONSETS],
        "decode": decode_cases(tok),
        "segment": segment_cases(),
    }
    (OUT / "fixtures.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"저장: {OUT / 'fixtures.json'}")


if __name__ == "__main__":
    main()
