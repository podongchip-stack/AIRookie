# feature/voice-live: 스트리밍 음성 처리 설계

## 📋 핵심 원칙

1. **모든 컴포넌트를 추상화** - 입력, STT, 필터링, LLM, 출력 모두 교체 가능
2. **텍스트는 스트리밍, JSON은 주기적 생성** - 실시간 텍스트 ≠ 실시간 JSON
3. **계층 분리** - 입력, 처리, 출력이 완전히 독립적
4. **On-Premise 지향** - 외부 API 최소화

---

## 아키텍처 (완전 추상화)

```
┌─────────────────────────────────────────────────────────────┐
│                    입력 계층 (Pluggable)                     │
├─────────────────────────────────────────────────────────────┤
│  AudioInput (ABC)                                           │
│  ├─ MicrophoneInput (현재)                                  │
│  ├─ TelephonyInput (미래: SIP/VoIP)                         │
│  └─ WebRTCInput (미래: 웹앱)                                │
└─────────────┬───────────────────────────────────────────────┘
              │ get_chunk() → bytes
              ↓
┌─────────────────────────────────────────────────────────────┐
│                   처리 계층 (Pluggable)                      │
├─────────────────────────────────────────────────────────────┤
│  STTStreamer (ABC)                                          │
│  ├─ WhisperStreamer (현재)                                  │
│  └─ Qwen3ASRStreamer (선택지)                               │
│                                                              │
│  MedicalFilter (ABC)                                        │
│  ├─ SentenceTransformersFilter (현재)                       │
│  └─ CustomBERTFilter (선택지)                               │
│                                                              │
│  Structurer (ABC)                                           │
│  ├─ QwenStructurer (현재: Ollama qwen3:14b)                 │
│  └─ OtherLLMStructurer (선택지)                             │
└─────────────┬───────────────────────────────────────────────┘
              │ 텍스트 누적 → JSON 생성 (주기적)
              ↓
┌─────────────────────────────────────────────────────────────┐
│                   출력 계층 (Pluggable)                      │
├─────────────────────────────────────────────────────────────┤
│  OutputHandler (ABC)                                        │
│  ├─ DashboardWebSocketHandler (현재)                        │
│  ├─ FileStorageHandler (로깅)                               │
│  └─ DatabaseHandler (미래: 병원 시스템)                     │
└─────────────────────────────────────────────────────────────┘
```

---



## 실시간 처리 흐름 (정확한 정의)



### Phase 1: 텍스트 스트리밍 (실시간)

**통화 중:**

```
시간  입력       STT         필터링          의료 문장 누적
────  ──────────  ──────────  ────────────   ──────────────
0.0s  [통화시작]
0.2s  청크1       "구"        -              (의료 아님)
0.4s  청크2       "급"        -              (의료 아님)
0.6s  청크3       "대"        -              (의료 아님)
0.8s  청크4       "원입니다."  [문장완성]
                              [필터링]       ✗ 의료 관련 아님
                              → 버림
1.0s  청크5       "환자"      -              -
1.2s  청크6       "는"        -              -
1.5s  청크7       "50대..."    [문장완성]
                              [필터링]       ✅ 의료 관련
                              → 추가        "환자는 50대 남성"
1.7s  청크8       "교통사고"   -              -
1.9s  청크9       "흉부충격"   [문장완성]
                              [필터링]       ✅ 의료 관련
                              → 추가        "교통사고 흉부충격"
```



### Phase 2: JSON 생성 (주기적 - 3초마다)

**3초 시점:**

```
누적된 의료 문장:
  "환자는 50대 남성입니다. 교통사고 흉부 충격입니다."
  
  ↓
  
[LLM 호출 - 한 번에]
입력: 위 누적 텍스트 전체
출력:
{
  "patient": "50대 남성",
  "mechanism": "교통사고 · 흉부 충격",
  "symptoms": [],
  "treatment": [],
  "severity_tag": "medium",
  "required_department": "흉부외과"
}

  ↓
  
[대시보드 업데이트]
```

**6초 시점 (계속 스트리밍 중):**

```
새로운 의료 문장 추가:
  "환자는 50대 남성입니다. 교통사고 흉부 충격입니다.
   의식 저하 관찰되고 있습니다."
  
  ↓
  
[LLM 호출 - 전체 누적 텍스트]
출력 (갱신):
{
  "patient": "50대 남성",
  "mechanism": "교통사고 · 흉부 충격",
  "symptoms": ["의식 저하"],  ← 새로 추가됨
  "treatment": [],
  "severity_tag": "high",     ← 업그레이드
  "required_department": "신경외과"  ← 변경
}

  ↓
  
[대시보드 업데이트]
```

**통화 종료 후:**

```
최종 JSON 생성 (모든 누적 텍스트 기반)
→ feature/hub로 전송
```

---



## 코드 설계 (완전 추상화)



### Layer 1: 입력 (AudioInput)

```python
# abstractions/audio_input.py
from abc import ABC, abstractmethod

class AudioInput(ABC):
    @abstractmethod
    def start(self):
        """음성 수신 시작"""
        pass
    
    @abstractmethod
    def get_chunk(self) -> bytes | None:
        """청크 반환
        
        Returns:
            bytes: 음성 데이터 (160ms ~ 320ms)
            None: 스트림 종료
        """
        pass
    
    @abstractmethod
    def stop(self):
        """음성 수신 종료"""
        pass
    
    @abstractmethod
    def get_sample_rate(self) -> int:
        return 16000
```



### Layer 2: STT (STTStreamer)

```python
# abstractions/stt_streamer.py
from abc import ABC, abstractmethod

class STTStreamer(ABC):
    """음성 청크를 텍스트로 변환 (스트리밍)"""
    
    @abstractmethod
    def add_chunk(self, audio_chunk: bytes) -> str:
        """청크 추가, 누적 텍스트 반환"""
        pass
    
    @abstractmethod
    def get_full_text(self) -> str:
        """지금까지의 전체 텍스트"""
        pass
    
    @abstractmethod
    def finalize(self) -> str:
        """스트림 종료, 최종 텍스트"""
        pass
```



### Layer 3: 필터링 (MedicalFilter)

```python
# abstractions/medical_filter.py
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class FilterResult:
    is_medical: bool
    confidence: float

class MedicalFilter(ABC):
    @abstractmethod
    def classify(self, sentence: str) -> FilterResult:
        """문장의 의료 관련도 판정"""
        pass
```



### Layer 4: 구조화 (Structurer)

```python
# abstractions/structurer.py
from abc import ABC, abstractmethod

class Structurer(ABC):
    """의료 텍스트를 SBAR JSON으로 구조화"""
    
    @abstractmethod
    def structure(self, medical_text: str) -> dict:
        """텍스트를 JSON으로 구조화
        
        Returns:
            dict: {patient, mechanism, symptoms, treatment, 
                   severity_tag, required_department}
        """
        pass
```



### Layer 5: 출력 (OutputHandler)

```python
# abstractions/output_handler.py
from abc import ABC, abstractmethod

class OutputHandler(ABC):
    @abstractmethod
    def handle(self, summary: dict, timestamp: float):
        """JSON 결과를 외부로 전송/저장"""
        pass
```



### 통합: LiveProcessor

```python
# processors/live_processor.py
import time
from abstractions import (
    AudioInput, STTStreamer, MedicalFilter, 
    Structurer, OutputHandler
)

class LiveProcessor:
    """모든 계층을 연결하는 오케스트레이터"""
    
    def __init__(self, 
                 audio_input: AudioInput,
                 stt: STTStreamer,
                 filter: MedicalFilter,
                 structurer: Structurer,
                 output_handlers: list[OutputHandler],
                 json_update_interval: int = 3):
        self.audio_input = audio_input
        self.stt = stt
        self.filter = filter
        self.structurer = structurer
        self.output_handlers = output_handlers
        self.update_interval = json_update_interval
        
        self.last_json_update = time.time()
        self.medical_sentences = []
    
    def process(self):
        """실시간 처리 루프"""
        self.audio_input.start()
        
        try:
            while True:
                # Phase 1: 음성 청크 수신
                chunk = self.audio_input.get_chunk()
                if chunk is None:
                    break
                
                # Phase 1: STT (텍스트 스트리밍)
                full_text = self.stt.add_chunk(chunk)
                
                # 문장 분리
                sentences = self._extract_new_sentences(full_text)
                
                for sentence in sentences:
                    # 필터링
                    result = self.filter.classify(sentence)
                    if result.is_medical:
                        self.medical_sentences.append(sentence)
                
                # Phase 2: 주기적 JSON 생성 (3초마다)
                now = time.time()
                if now - self.last_json_update >= self.update_interval:
                    self._generate_and_output_json()
                    self.last_json_update = now
        
        finally:
            self.audio_input.stop()
            # 최종 JSON 생성
            self._generate_and_output_json()
    
    def _extract_new_sentences(self, full_text: str) -> list[str]:
        """새로운 문장 추출"""
        sentences = full_text.split('.')
        return [s.strip() for s in sentences if s.strip()]
    
    def _generate_and_output_json(self):
        """JSON 생성 및 출력"""
        if not self.medical_sentences:
            return
        
        medical_text = '. '.join(self.medical_sentences)
        
        # LLM 구조화
        summary = self.structurer.structure(medical_text)
        
        # 모든 output_handler에 전송
        timestamp = time.time()
        for handler in self.output_handlers:
            handler.handle(summary, timestamp)
```



### 사용 방식

```python
# main.py

# 현재: 마이크 + Whisper + SentenceTransformers + Qwen3
from implementations.microphone_input import MicrophoneInput
from implementations.whisper_streamer import WhisperStreamer
from implementations.sentence_transformers_filter import SentenceTransformersFilter
from implementations.qwen_structurer import QwenStructurer
from implementations.dashboard_handler import DashboardWebSocketHandler

audio = MicrophoneInput()
stt = WhisperStreamer()
filter = SentenceTransformersFilter(threshold=0.4)
structurer = QwenStructurer()
handlers = [DashboardWebSocketHandler(url="ws://localhost:8000/audio")]

processor = LiveProcessor(
    audio, stt, filter, structurer, handlers, 
    json_update_interval=3
)
processor.process()

# 미래: 다른 모델로 교체 (코드 구조 완전히 동일!)
# 옵션 1: STT 모델 교체
stt = Qwen3ASRStreamer()  # 구현만 다름

# 옵션 2: 필터링 교체
filter = CustomBERTFilter(model_path="./models/medical_bert")

# 옵션 3: LLM 교체
structurer = LlamaMedicalStructurer()

# 옵션 4: 입력 소스 교체
audio = TelephonyInput(sip_server="asterisk.local", extension="101")

# 옵션 5: 출력 대상 추가
handlers = [
    DashboardWebSocketHandler(...),
    FileStorageHandler(output_dir="./data/"),
    DatabaseHandler(db_url="mysql://hospital/goldenlink")
]

processor = LiveProcessor(audio, stt, filter, structurer, handlers)
processor.process()  # 완전히 동일한 흐름!
```

---



## 파일 구조

```
feature/voice-live/
├── abstractions/
│   ├── __init__.py
│   ├── audio_input.py
│   ├── stt_streamer.py
│   ├── medical_filter.py
│   ├── structurer.py
│   └── output_handler.py
│
├── implementations/
│   ├── microphone_input.py
│   ├── telephony_input.py          (미구현)
│   ├── whisper_streamer.py
│   ├── sentence_transformers_filter.py
│   ├── qwen_structurer.py
│   └── dashboard_handler.py
│
├── processors/
│   └── live_processor.py
│
├── live_main.py
└── data/
    └── live_calls/
```

---



## 핵심 개선 사항


| 항목             | 기존 설계   | 개선된 설계    |
| -------------- | ------- | --------- |
| **STT 추상화**    | ❌       | ✅         |
| **필터링 추상화**    | ❌       | ✅         |
| **LLM 추상화**    | ❌       | ✅         |
| **출력 추상화**     | ❌       | ✅         |
| **JSON 생성 방식** | 부분 JSON | ✅ 주기적 갱신  |
| **교체 범위**      | 입력만     | **모든 계층** |


---



## 요약

- **텍스트:** 청크 단위 실시간 스트리밍
- **JSON:** 3초마다 주기적 생성 (완성된 누적 텍스트 기반)
- **LLM 입력:** 변하지 않음 (안정적)
- **모든 계층:** 추상화되어 교체 가능

