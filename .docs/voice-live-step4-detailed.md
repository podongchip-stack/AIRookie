# Step 4 상세 가이드: 필터링 통합

## 📚 개념: "의료 관련도를 실시간으로 판정"

Step 3은 **모든 발화를 그냥 출력**한다. "네 알겠습니다" 같은 잡담도 포함.

Step 4는 **각 발화가 의료 관련인지 판정해서, 관련 발화만 표시**한다.

```
Step 3 출력:
  [00:00:00.320] 환자는 의식이 없습니다
  [00:00:02.140] 네 알겠습니다
  [00:00:04.500] 호흡이 얕습니다

Step 4 출력:
  [00:00:00.320] 환자는 의식이 없습니다
    [0.850] 유지  환자는 의식이 없습니다
  
  [00:00:02.140] 네 알겠습니다
    [0.120] 제외  네 알겠습니다
  
  [00:00:04.500] 호흡이 얕습니다
    [0.790] 유지  호흡이 얕습니다
```

---

## 🧠 필터링 원리: "문장 임베딩과 코사인 유사도"

### 1. 문장 임베딩(Embedding)

```
입력 문장: "환자는 의식이 없습니다"
    ↓
문장 전체를 768차원의 벡터로 변환 (sentence-transformers 모델)
    ↓
[0.123, -0.456, 0.789, ..., 0.234]  (768개의 숫자)
```

**직관적으로:**
- 의미가 비슷한 문장 → 벡터도 가까움
- 의미가 다른 문장 → 벡터도 멈

### 2. 코사인 유사도(Cosine Similarity)

두 벡터가 얼마나 같은 방향을 가리키는지 측정.

```
의료 앵커 문장들의 중심 벡터:
  "환자는 의식이 저하되어 있습니다"
  "호흡 곤란을 호소하고 있습니다"
  "혈압과 맥박을 측정했습니다"
  ... (총 12개)
  
  ↓ (평균 벡터)
  
  의료 중심 벡터 C = [0.111, -0.222, 0.333, ..., 0.444]

입력 문장: "환자는 의식이 없습니다"
  ↓ (임베딩)
  벡터 A = [0.120, -0.234, 0.345, ..., 0.456]
  
  ↓ (코사인 유사도 계산)
  
  similarity(A, C) = cos(angle between A and C)
                   = (A · C) / (||A|| × ||C||)
                   = 0.850  (0~1 범위, 1에 가까울수록 유사)
  
  threshold = 0.4 이므로
  0.850 > 0.4 → 의료 관련 ✅
```

### 3. 실시간 분류

```python
from filtering import MedicalRelevanceFilter

# 모델은 한 번만 로드 (비용 큼)
relevance_filter = MedicalRelevanceFilter(threshold=0.4)

# 매번 새 턴 추가 시 전체 재분류
turn_texts = [
    "환자는 의식이 없습니다",
    "네 알겠습니다",
    "호흡이 얕습니다"
]

classified = relevance_filter.classify_turns(turn_texts)
# [ClassifiedTurn(text="...", is_relevant=True, score=0.850),
#  ClassifiedTurn(text="...", is_relevant=False, score=0.120),
#  ClassifiedTurn(text="...", is_relevant=True, score=0.790)]

# 출력
for c in classified:
    print(f"[{c.score:.3f}] {'유지' if c.is_relevant else '제외'}  {c.text}")
```

---

## 🎯 Step 4: live_transcribe.py 수정

Step 3 코드에서 **필터링 부분만 추가**.

### 추가할 import

```python
from filtering import MedicalRelevanceFilter
```

### 루프 전 (모델 로드)

```python
# Step 3의 기존 코드 다음에 추가
recorder = MicRecorder()
recorder.start()

# ← 여기 추가
relevance_filter = MedicalRelevanceFilter()  # 한 번만 생성
# threshold=0.4 기본값 사용
```

### 루프 내 (매 사이클마다)

```python
# Step 3에서 "새 세그먼트 추출" 부분 수정

# 새 세그먼트 추출 (수정 전)
# for seg in segments:
#     if seg.end <= printed_until:
#         continue
#     print(f"[{format_timestamp(seg.start)}] {seg.text}")

# 새 세그먼트 추출 (수정 후)
new_segments = []
for seg in segments:
    if seg.end <= printed_until:
        continue
    
    ts = format_timestamp(seg.start)
    text = seg.text.strip()
    
    # 세그먼트를 리스트에 추가
    print(f"[{ts}] {text}")
    all_turn_texts.append(text)
    all_turn_offsets.append(seg.start)
    new_segments.append(seg)
    printed_until = seg.end

# ← 여기 추가: 필터링
if all_turn_texts:  # 턴이 있으면
    classified = relevance_filter.classify_turns(all_turn_texts)
    
    # 이번 사이클에만 새로 추가된 턴의 필터링 결과만 출력
    # (이전 턴은 이미 출력했으므로 skip)
    num_printed_before = len(all_turn_texts) - len(new_segments)
    
    for i, c in enumerate(classified[num_printed_before:], start=num_printed_before):
        print(f"  [{c.score:.3f}] {'유지' if c.is_relevant else '제외'}  {c.text}")
```

---

## ✅ Step 4 실행 및 검증

### 실행
```bash
python live_transcribe.py --session live_test2 --model base --stt-interval 5
```

### 예상 터미널 출력

의료 관련 + 잡담 섞어서 발화:

```
모델 로딩 중... (base, device=auto, compute_type=auto)
모델 로딩 완료 (10.23초)

🎤 라이브 재변환 시작 (주기: 5초)
말하세요... Ctrl+C로 중지

[1차] 재변환 중... 누적 5.2초
[00:00:00.320] 환자는 의식이 없습니다
  [0.850] 유지  환자는 의식이 없습니다
[00:00:02.140] 네 알겠습니다
  [0.120] 제외  네 알겠습니다
[00:00:04.500] 호흡이 얕습니다
  [0.790] 유지  호흡이 얕습니다
(재변환: 2.34초, 누적 텍스트: data/live_text/live_test2.txt)

[2차] 재변환 중... 누적 10.5초
[00:00:06.200] 맥박도 빨라요
  [0.820] 유지  맥박도 빨라요
(재변환: 2.45초, 누적 텍스트: data/live_text/live_test2.txt)

🛑 녹음 중지 (Ctrl+C)
```

---

## 🧪 검증 단계

### 1️⃣ 필터링 결과 확인

```bash
# 0.85, 0.12, 0.79, 0.82 같은 점수가 나왔는지 확인
# "유지" "제외" 판정이 맞는지 귀로 듣고 확인
```

### 2️⃣ 필터링 임계값 조정

**score가 모두 낮으면 threshold 낮추기:**

```python
# filtering.py 호출 시
relevance_filter = MedicalRelevanceFilter(threshold=0.3)  # 0.4 → 0.3
```

**score가 모두 높으면 threshold 높이기:**

```python
relevance_filter = MedicalRelevanceFilter(threshold=0.5)  # 0.4 → 0.5
```

### 3️⃣ 필터링된 텍스트만 모으기 (선택)

```python
# 루프 내에서 "유지"된 문장만 별도 저장
filtered_texts = [c.text for c in classified if c.is_relevant]
filtered_text = " ".join(filtered_texts)
print(f"필터링됨: {filtered_text}")
```

---

## ⚠️ Step 4의 주의사항

| 상황 | 해결책 |
|---|---|
| **모든 발화가 "제외"** | threshold 낮추기 (0.4 → 0.3 또는 0.2) |
| **모든 발화가 "유지"** | threshold 높이기 (0.4 → 0.5 또는 0.6) |
| **필터링이 너무 느림** | 임베딩 모델 로드 확인, GPU 사용 여부 확인 |
| **점수가 이상함** | `filtering.py`의 앵커 문장 확인 |

---

## 📚 filtering.py 이해하기

```python
class MedicalRelevanceFilter:
    """발화의 의료 관련도를 판정하는 클래스"""
    
    def __init__(self, model_name: str = "paraphrase-multilingual-MiniLM-L12-v2",
                 threshold: float = 0.4,
                 anchor_sentences: list[str] | None = None):
        # 문장 임베딩 모델 로드 (처음 1회만, 비용 큼 ~ 1초)
        self.model = SentenceTransformer(model_name)
        
        # 의료 앵커 문장들의 중심 벡터 계산 (처음 1회만)
        self._centroid = anchor_embeddings.mean(axis=0)
        
        self.threshold = threshold
    
    def classify_turns(self, turn_texts: list[str]) -> list[ClassifiedTurn]:
        # 입력 문장들을 벡터화
        embeddings = self.model.encode(turn_texts, normalize_embeddings=True)
        
        # 각 문장의 코사인 유사도 계산
        scores = util.cos_sim(embeddings, self._centroid).numpy().flatten()
        
        # threshold와 비교해서 판정
        return [
            ClassifiedTurn(
                text=text,
                is_relevant=bool(score >= self.threshold),
                score=float(score)
            )
            for text, score in zip(turn_texts, scores)
        ]
```

**핵심:**
- `__init__`에서 모델 로드 (비용 큼, 1회만)
- `classify_turns()`에서 분류 (빠름, 매번 가능)

---

## 🎓 Step 4 핵심 포인트

1. **필터링은 "문장 임베딩" 기반** (deep learning, 의미 이해)
2. **모델은 루프 진입 전 1회만 로드** (비용 절약)
3. **분류는 매번 가능** (threshold와 비교만)
4. **threshold로 민감도 조절** (0.3 = 너무 통과, 0.6 = 너무 엄격)
5. **점수는 0~1 범위** (높을수록 의료 관련도 높음)

