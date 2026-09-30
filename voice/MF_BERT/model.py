"""통화 텍스트 -> v2 필드별 점수(logits)를 내는 다중과제 모델. 이전에 쓰던 HMM v2와 출력층이 같다.
원본은 BERT_Multiclass Classification/BERT/mf_bert/model.py (학습 코드와 같은 파일이어야 체크포인트가 맞는다).

    조각 인코딩 H^(0..L)_c = Encoder(chunk_c)                 512토큰 조각마다 사전학습 한국어 인코더 (기본 KLUE RoBERTa-large)
    토큰 복원   H^(j) = concat_c H^(j)_c[keep_c]               겹친 토큰은 한 조각 것만 남겨 원문 토큰 줄로 이어 붙임 (chunking.py)
    층 혼합     h_t = gamma * sum_j softmax(w)_j H^(j)_t        마지막 N층, 문장용·토큰용 두 그룹, layer dropout
    풀링        alpha_t = softmax_t(q_k . h_t / sqrt(d))        문장 헤드 k마다 query 하나, 통화 전체 토큰 대상 (패딩은 제외)
    문장 헤드   단일 선택 8개(labels.SINGLE_CHOICE_HEADS) + 다중 선택 7개(labels.MULTI_LABEL_HEADS), RoBERTa 분류 헤드
    구간 태거   토큰별 선형 한 겹 -> 11태그 (VITALS·AGE·ONSET·DX·MED의 BIO)

HMM v2는 포지션 임베딩을 2048칸으로 늘려 긴 통화를 한 번에 넣지만, 여기서는 포지션을 늘리지 않고 조각으로 나눠
사전학습된 512칸만 쓴다. 조각이 하나뿐인 통화는 HMM v2와 계산이 같다.

새 층은 초기값에서 기존 함수와 같게 시작한다(w=0, gamma=1이면 마지막 N층 단순 평균, q=0이면 패딩 뺀 토큰 평균).
dropout은 새로 만든 층(헤드·태거)에, encoder_dropout은 인코더 내부 hidden dropout에 걸린다(None이면 사전학습 설정 그대로).
"""

from __future__ import annotations

import torch
from torch import nn
from transformers import AutoConfig, AutoModel

from . import labels as L

#: 구간 태거 출력의 로짓 키
SPAN_HEAD = "spans"

DEFAULT_ENCODER = "klue/roberta-large"
DEFAULT_LAST_N_LAYERS = 4
DEFAULT_LAYER_DROPOUT = 0.1

SENTENCE_HEADS: tuple[str, ...] = tuple(head.name for head in L.SINGLE_CHOICE_HEADS) + tuple(L.MULTI_LABEL_HEADS)


class LayerMix(nn.Module):
    """마지막 N층의 softmax 가중합에 스칼라 gamma를 곱한다. 학습 중엔 층을 확률 layer_dropout로 통째로 뺀다."""

    def __init__(self, layer_count: int, layer_dropout: float) -> None:
        super().__init__()
        if layer_count < 1:
            raise ValueError("last_n_layers must be >= 1")
        if not 0.0 <= layer_dropout < 1.0:
            raise ValueError("layer_dropout must be in [0, 1)")
        self.layer_count = layer_count
        self.layer_dropout = layer_dropout
        self.weights = nn.Parameter(torch.zeros(layer_count))
        self.gamma = nn.Parameter(torch.ones(()))

    def forward(self, hidden_states: tuple[torch.Tensor, ...]) -> torch.Tensor:
        selected = hidden_states[-self.layer_count :]
        weights = self.weights
        if self.training and self.layer_dropout > 0:
            dropped = torch.rand(self.layer_count, device=weights.device) < self.layer_dropout
            if not dropped.all():
                weights = weights.masked_fill(dropped, float("-inf"))
        weights = torch.softmax(weights, dim=0)
        return self.gamma * sum(weight * state for weight, state in zip(weights, selected))


class AttentionPool(nn.Module):
    """헤드별 query 하나로 토큰을 가중 평균한다. 초기값 q=0이면 패딩 뺀 평균과 같다."""

    def __init__(self, hidden_size: int, head_count: int) -> None:
        super().__init__()
        self.query = nn.Parameter(torch.zeros(head_count, hidden_size))
        self.scale = hidden_size ** -0.5

    def forward(self, token_vectors: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
        scores = torch.einsum("btd,kd->bkt", token_vectors, self.query.to(token_vectors.dtype)) * self.scale
        scores = scores.masked_fill(attention_mask.unsqueeze(1) == 0, float("-inf"))
        return torch.einsum("bkt,btd->bkd", torch.softmax(scores, dim=-1), token_vectors)


class ClassificationHead(nn.Module):
    """dropout -> dense -> tanh -> dropout -> out_proj (RoBERTa 분류 헤드)."""

    def __init__(self, hidden_size: int, inner_size: int, num_outputs: int, dropout: float) -> None:
        super().__init__()
        self.dropout = nn.Dropout(dropout)
        self.dense = nn.Linear(hidden_size, inner_size)
        self.out_proj = nn.Linear(inner_size, num_outputs)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = torch.tanh(self.dense(self.dropout(x)))
        return self.out_proj(self.dropout(x))


class CallExtractor(nn.Module):
    def __init__(
        self,
        encoder_name: str = DEFAULT_ENCODER,
        dropout: float = 0.1,
        last_n_layers: int = DEFAULT_LAST_N_LAYERS,
        layer_dropout: float = DEFAULT_LAYER_DROPOUT,
        head_hidden_size: int | None = None,
        encoder_dropout: float | None = None,
        pretrained: bool = True,
    ) -> None:
        """pretrained=False면 사전학습 가중치를 받지 않고 구조만 만든다(학습한 체크포인트를 덮어 불러올 때)."""
        super().__init__()
        config = AutoConfig.from_pretrained(encoder_name)
        if encoder_dropout is not None:
            if not 0.0 <= encoder_dropout < 1.0:
                raise ValueError("encoder_dropout must be in [0, 1)")
            config.hidden_dropout_prob = encoder_dropout
        load_options = {"add_pooling_layer": False} if config.model_type == "roberta" else {}
        if pretrained:
            self.encoder = AutoModel.from_pretrained(encoder_name, config=config, **load_options)
        else:
            self.encoder = AutoModel.from_config(config, **load_options)
        hidden = self.encoder.config.hidden_size
        self.layer_count = min(last_n_layers, self.encoder.config.num_hidden_layers)

        self.sentence_mix = LayerMix(self.layer_count, layer_dropout)
        self.token_mix = LayerMix(self.layer_count, layer_dropout)
        self.pool = AttentionPool(hidden, len(SENTENCE_HEADS))

        inner = head_hidden_size or hidden
        output_sizes = {head.name: head.size for head in L.SINGLE_CHOICE_HEADS}
        output_sizes.update({name: len(options) for name, options in L.MULTI_LABEL_HEADS.items()})
        self.heads = nn.ModuleDict(
            {name: ClassificationHead(hidden, inner, output_sizes[name], dropout) for name in SENTENCE_HEADS}
        )
        self.span_tagger = nn.Sequential(nn.Dropout(dropout), nn.Linear(hidden, len(L.SPAN_TAGS)))

    def encode_chunks(
        self,
        input_ids: torch.Tensor,
        attention_mask: torch.Tensor,
        chunk_mask: torch.Tensor,
        keep_mask: torch.Tensor,
        token_mask: torch.Tensor,
    ) -> tuple[torch.Tensor, ...]:
        """조각 (B, C, L) -> 마지막 N층의 복원된 토큰 줄 N개, 각각 (B, T, H). 빈 조각은 인코더에 넣지 않는다."""
        encoded = self.encoder(
            input_ids=input_ids[chunk_mask],
            attention_mask=attention_mask[chunk_mask],
            output_hidden_states=True,
        )
        layers = torch.stack(encoded.hidden_states[-self.layer_count :])  # (N, 조각 수, L, H)
        kept = layers[:, keep_mask[chunk_mask]]                          # (N, 남긴 토큰 수, H) — 통화·조각·위치 순서
        restored = kept.new_zeros(self.layer_count, *token_mask.shape, kept.size(-1))
        restored[:, token_mask] = kept
        return tuple(restored)

    def forward(
        self,
        input_ids: torch.Tensor,
        attention_mask: torch.Tensor,
        chunk_mask: torch.Tensor,
        keep_mask: torch.Tensor,
        token_mask: torch.Tensor,
    ) -> dict[str, torch.Tensor]:
        hidden_states = self.encode_chunks(input_ids, attention_mask, chunk_mask, keep_mask, token_mask)
        pooled = self.pool(self.sentence_mix(hidden_states), token_mask)
        logits = {name: self.heads[name](pooled[:, index]) for index, name in enumerate(SENTENCE_HEADS)}
        logits[SPAN_HEAD] = self.span_tagger(self.token_mix(hidden_states))  # (B, T, 태그 수)
        return logits
