"""MF_BERT를 Core ML 두 모델로 나누는 래퍼 + 아이폰과 같은 순서로 도는 Python 기준 구현.

    MFBertEncoder : input_ids (1, L)            -> hidden (N, L, 1024)       512토큰 조각 하나, L <= 512
    (이어 붙이기)  : 조각마다 keep 행만 골라 순서대로 이어 붙임 (Swift MFBertRunner, 여기선 run_split)
    MFBertHeads   : hidden (N, T, 1024)         -> 헤드별 로짓 + spans (1, T, 11)

조각을 하나씩(패딩 없이) 넣으므로 attention_mask는 전부 1이고, 통화 1건이라 token_mask도 전부 1이다 — 그래서 두
모델 모두 마스크 입력을 받지 않는다(int 마스크 변환 문제를 아예 없앰). 원본(collate)은 여러 조각을 패딩해 한 번에
넣는데, 패딩 칸은 어텐션에서 가려지므로 실제 토큰 값은 같다(부동소수 오차 수준 — check_mf_bert.py가 잰다).

    python dashboard/iphone/convert/mf_bert_split.py     # 자체 검사: 무작위 가중치로 분할 = 원본 forward (가중치 불필요)
"""

from __future__ import annotations

import sys
from pathlib import Path

import torch
from torch import nn

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "voice"))

from MF_BERT.chunking import chunk_text, collate  # noqa: E402
from MF_BERT.model import SPAN_HEAD, CallExtractor  # noqa: E402


class Encoder(nn.Module):
    def __init__(self, model: CallExtractor) -> None:
        super().__init__()
        self.encoder = model.encoder
        self.n = model.layer_count

    def forward(self, input_ids: torch.Tensor) -> torch.Tensor:
        out = self.encoder(input_ids=input_ids, attention_mask=torch.ones_like(input_ids), output_hidden_states=True)
        return torch.stack(out.hidden_states[-self.n:])[:, 0]  # (N, L, H)


class Heads(nn.Module):
    """출력 순서 = head_names(). Core ML 출력 이름도 이 이름들이다."""

    def __init__(self, model: CallExtractor) -> None:
        super().__init__()
        self.m = model

    def head_names(self) -> list[str]:
        return list(self.m.pooled_heads) + list(self.m.label_attention_heads) + [SPAN_HEAD]

    def forward(self, hidden: torch.Tensor) -> tuple[torch.Tensor, ...]:
        m = self.m
        hs = tuple(hidden[i:i + 1] for i in range(m.layer_count))  # 각 (1, T, H)
        mask = torch.ones(1, hidden.shape[1], dtype=torch.long, device=hidden.device)
        tv = m.sentence_mix(hs)
        pooled = m.pool(tv, mask)
        outs = [m.heads[n](pooled[:, i]) for i, n in enumerate(m.pooled_heads)]
        outs += [m.heads[n](tv, mask) for n in m.label_attention_heads]
        outs.append(m.span_tagger(m.token_mix(hs)))
        return tuple(outs)


@torch.no_grad()
def run_split(model: CallExtractor, tokenizer, text: str, encoder=None, heads=None) -> dict[str, torch.Tensor]:
    """아이폰과 같은 순서: 조각마다 인코더 -> keep 행 이어 붙이기 -> 헤드. encoder/heads에 Core ML 래퍼를 넣을 수 있다."""
    encoder = encoder or Encoder(model).eval()
    heads = heads or Heads(model).eval()
    item = chunk_text(text, tokenizer)
    rows = []
    for chunk, keep in zip(item["chunks"], item["keep"]):
        h = encoder(torch.tensor([chunk]))  # (N, L, H)
        rows.append(h[:, keep])
    hidden = torch.cat(rows, dim=1)
    names = Heads(model).head_names()
    return dict(zip(names, heads(hidden)))


@torch.no_grad()
def run_original(model: CallExtractor, tokenizer, text: str) -> dict[str, torch.Tensor]:
    item = chunk_text(text, tokenizer)
    return model(**collate([item], tokenizer.pad_token_id))


def _selftest() -> None:
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained("klue/roberta-large")
    torch.manual_seed(0)
    for label_attention in (False, True):
        model = CallExtractor("klue/roberta-large", label_attention=label_attention, pretrained=False).eval()
        model.encoder.set_attn_implementation("eager")
        with torch.no_grad():  # 초기값(q=0, w=0)이면 갈래가 안 갈려 검사가 약하다 — 새 층을 흔든다
            for name, p in model.named_parameters():
                if not name.startswith("encoder."):
                    p.add_(torch.randn_like(p) * 0.05)
        for text in ["", "혈압 150에 90 맥박 110", "\n".join(["62세 남성 흉통 30분 전부터, 산소포화도 96%"] * 60)]:
            a, b = run_original(model, tok, text), run_split(model, tok, text)
            worst = max((a[k].float() - b[k].float()).abs().max().item() for k in a)
            print(f"label_attention={label_attention} 토큰 {len(chunk_text(text, tok)['offsets'])}개: 최대 차 {worst:.2e}")
            assert worst < 1e-3, worst
    print("통과: 분할 실행 = 원본 forward")


if __name__ == "__main__":
    _selftest()
