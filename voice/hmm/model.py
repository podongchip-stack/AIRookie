"""통화 텍스트 -> 필드별 점수(logits)를 내는 다중과제 모델. C:\\Dev\\HMM\\model_HMM\\model.py에서 가져왔다.

    인코더   H^(0..L) = Encoder(x)                        사전학습 한국어 인코더 (기본 KLUE RoBERTa-large)
    층 혼합  h_t = gamma * sum_j softmax(w)_j H^(j)_t     마지막 N층, 문장용·토큰용 두 그룹, layer dropout
    풀링     alpha_t = softmax_t(q_k . h_t / sqrt(d))     문장 헤드 k마다 query 하나 (패딩은 제외)
    문장 헤드 원인·부위·중증도·나이대·성별(단일 선택) + 처치(다중 선택), RoBERTa 분류 헤드
    증상 태거 토큰별 선형 한 겹 -> 5태그

모듈 구성과 이름이 곧 체크포인트(best.pt)의 state_dict 키라서, 추론에서 안 쓰는 dropout 층도 그대로 둔다.
"""

from __future__ import annotations

import torch
from torch import nn
from transformers import AutoConfig, AutoModel

from . import labels as L

DEFAULT_ENCODER = "klue/roberta-large"
DEFAULT_LAST_N_LAYERS = 4
DEFAULT_LAYER_DROPOUT = 0.1
DEFAULT_MAX_TOKENS = 2048

TREATMENT_HEAD = "treatment"
SYMPTOM_HEAD = "symptoms"

SENTENCE_HEADS: tuple[str, ...] = tuple(head.name for head in L.SINGLE_CHOICE_HEADS) + (TREATMENT_HEAD,)


def resize_position_embeddings(encoder, target_tokens: int) -> None:
    """RoBERTa 절대 포지션 임베딩을 target_tokens 기준으로 늘린다.

    포지션 0·1은 패딩용이라 실제 토큰은 인덱스 2부터 쓴다 -> 테이블 크기는 target_tokens + padding_idx + 1.
    새 자리는 사전학습된 실제 토큰 구간(512자리)을 반복해 초기화한다. 추론에서는 곧바로 best.pt 값으로 덮인다.
    """
    embeddings = encoder.embeddings
    old_embedding = embeddings.position_embeddings
    old_size, hidden = old_embedding.weight.shape
    padding_idx = old_embedding.padding_idx
    new_size = target_tokens + padding_idx + 1
    if new_size <= old_size:
        return

    old_weight = old_embedding.weight.data
    new_weight = old_weight.new_empty((new_size, hidden))
    new_weight[:old_size] = old_weight
    real_pattern = old_weight[padding_idx + 1 :]
    repeats = (new_size - old_size + real_pattern.shape[0] - 1) // real_pattern.shape[0]
    new_weight[old_size:] = real_pattern.repeat(repeats, 1)[: new_size - old_size]

    new_embedding = nn.Embedding(new_size, hidden, padding_idx=padding_idx)
    new_embedding.weight.data.copy_(new_weight)
    embeddings.position_embeddings = new_embedding
    embeddings.register_buffer("position_ids", torch.arange(new_size).unsqueeze(0), persistent=False)
    if hasattr(embeddings, "token_type_ids"):
        embeddings.register_buffer("token_type_ids", torch.zeros((1, new_size), dtype=torch.long), persistent=False)
    encoder.config.max_position_embeddings = new_size


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
        max_position_embeddings: int | None = DEFAULT_MAX_TOKENS,
    ) -> None:
        super().__init__()
        config = AutoConfig.from_pretrained(encoder_name)
        load_options = {"config": config}
        if config.model_type == "roberta":
            load_options["add_pooling_layer"] = False
        self.encoder = AutoModel.from_pretrained(encoder_name, **load_options)
        if max_position_embeddings is not None and config.model_type == "roberta":
            resize_position_embeddings(self.encoder, max_position_embeddings)
        hidden = self.encoder.config.hidden_size
        layer_count = min(last_n_layers, self.encoder.config.num_hidden_layers)

        self.sentence_mix = LayerMix(layer_count, layer_dropout)
        self.token_mix = LayerMix(layer_count, layer_dropout)
        self.pool = AttentionPool(hidden, len(SENTENCE_HEADS))

        inner = head_hidden_size or hidden
        output_sizes = {head.name: head.size for head in L.SINGLE_CHOICE_HEADS}
        output_sizes[TREATMENT_HEAD] = len(L.TREATMENTS)
        self.heads = nn.ModuleDict(
            {name: ClassificationHead(hidden, inner, output_sizes[name], dropout) for name in SENTENCE_HEADS}
        )
        self.symptom_tagger = nn.Sequential(nn.Dropout(dropout), nn.Linear(hidden, len(L.SYMPTOM_TAGS)))

    def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor) -> dict[str, torch.Tensor]:
        encoded = self.encoder(input_ids=input_ids, attention_mask=attention_mask, output_hidden_states=True)
        pooled = self.pool(self.sentence_mix(encoded.hidden_states), attention_mask)
        logits = {name: self.heads[name](pooled[:, index]) for index, name in enumerate(SENTENCE_HEADS)}
        logits[SYMPTOM_HEAD] = self.symptom_tagger(self.token_mix(encoded.hidden_states))
        return logits
