"""예상 병명(expectedDiagnosis) ↔ 병원 진료과(department) 임베딩 유사도 매칭.

feature/voice의 "실시간 음성 필터링"과 동일한 모델(paraphrase-multilingual-MiniLM-L12-v2)을
재사용한다. 생성형 LLM이 아니라 사전학습된 문장 임베딩 모델이라, 매번 같은 입력에는
같은 점수가 나오는 결정적(deterministic) 동작을 한다.
"""
from __future__ import annotations

MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"


class SpecialtyMatcher:
    def __init__(self, model_name: str = MODEL_NAME) -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)
        # 텍스트(진료과명 또는 예상 병명) -> 임베딩 캐시. 병원 목록(진료과)은
        # 매 요청마다 거의 안 바뀌는데 process_voice_summary()가 호출될 때마다
        # 같은 문자열을 다시 인코딩하면 낭비라서, 한 번 인코딩한 텍스트는
        # SpecialtyMatcher 인스턴스가 살아있는 동안 재사용한다.
        self._embedding_cache: dict[str, object] = {}

    def _encode_cached(self, texts: list[str]) -> list[object]:
        """캐시에 없는 텍스트만 배치로 인코딩하고, 있는 건 캐시에서 그대로 꺼낸다."""
        missing = [t for t in texts if t not in self._embedding_cache]
        if missing:
            embeddings = self._model.encode(missing, convert_to_tensor=True)
            for text, embedding in zip(missing, embeddings):
                self._embedding_cache[text] = embedding
        return [self._embedding_cache[t] for t in texts]

    def match_many(
        self, expected_diagnosis: str, department_lists: list[list[str]]
    ) -> list[tuple[str | None, float]]:
        """여러 병원의 진료과 목록을 한 번에 배치 임베딩해서 매칭한다.

        department_lists[i]는 i번째 병원이 가진 진료과명 리스트. 병원마다 따로
        model.encode()를 부르면 병원 수만큼 임베딩 호출이 발생해 느려지므로,
        전체 진료과명을 중복 제거해 한 번에 배치 인코딩한 뒤 결과를 재사용한다
        (게다가 캐시에 이미 있는 진료과명은 이번 배치 인코딩에서도 제외된다).

        진료과 목록이 비어 있는 병원은 (None, 0.0)을 반환한다 — 매칭 실패로 병원을
        후보에서 제외하지 않고, 호출부(scoring.py)가 거리 점수만으로 순위를 매기게
        한다 ("뺑뺑이 방지"가 목적이라 잘못 걸러내는 게 더 위험함).
        """
        import torch
        from sentence_transformers import util

        all_departments = sorted({d for depts in department_lists for d in depts})
        if not all_departments:
            return [(None, 0.0) for _ in department_lists]

        query_emb = self._encode_cached([expected_diagnosis])[0]
        dept_embs = torch.stack(self._encode_cached(all_departments))
        sims = util.cos_sim(query_emb, dept_embs)[0]
        # 코사인 유사도는 이론상 -1~1이지만 실측상 0~1 근방이므로 0~1로만 클리핑한다
        score_by_dept = {
            dept: max(0.0, min(1.0, float(sims[i]))) for i, dept in enumerate(all_departments)
        }

        results: list[tuple[str | None, float]] = []
        for depts in department_lists:
            if not depts:
                results.append((None, 0.0))
                continue
            best_dept = max(depts, key=lambda d: score_by_dept[d])
            results.append((best_dept, score_by_dept[best_dept]))
        return results
