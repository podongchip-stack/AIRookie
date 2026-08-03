# feature/voice 음성 추출 → 자동 처리 파이프라인 아키텍처

## 📋 개요

현재는 **수동 모드**(개발/테스트용)이고, 최종적으로는 **자동 모드**(실제 응급이송 운영용)로 전환되어야 한다.

- **현재 상태**: 음성 파일을 직접 넣고 `python transcribe.py` 실행
- **최종 상태**: 통화가 끝나면 자동으로 파이프라인 실행 → feature/hub로 자동 전송

---

## 현재 상태: 수동 모드 (개발/테스트)

```
개발자
  ↓ (음성 파일 직접 추가)
data/origin_data/
  ↓ (수동 실행)
python transcribe.py data/origin_data/파일.wav --summarize
  ↓
STT (Whisper) → 필터링 (의료 관련) → 구조화 (LLM)
  ↓
data/summary_text/파일_call_summary.json
  ↓ (터미널 출력만, feature/hub로 보내지 않음)
개발자가 JSON 내용 확인
```

**특징**:

- 한 파일씩 수동 처리
- 파이프라인 성능 테스트용
- 에러 발생 시 즉시 피드백 가능

---

## 최종 상태: 자동 모드 (운영)

```
실제 응급이송 환경
  ↓
[1단계] 음성 추출 및 저장
  ↓ (구급차 PBX/통신 인터페이스가 음성 파일을 저장)
Voice File Storage
  ├─ 통화 시작 시각
  ├─ 통화 종료 시각
  └─ .wav 파일
  
  ↓ (File Watcher가 감지)
[2단계] 파일 감지 및 큐 등록
  ↓
Voice Processing Queue
  (watchdog / 간단한 파일 감시)
  
  ↓ (Worker 자동 처리)
[3단계] 자동 파이프라인 실행
  ├─ STT (Whisper)
  ├─ 실시간 음성 필터링 (의료 관련 문장 분류)
  ├─ SBAR 구조화 (LLM)
  └─ JSON 생성
  
  ↓
[4단계] feature/hub로 자동 전송
  ├─ WebSocket 또는 HTTP
  └─ 실시간 양방향 통신
  
  ↓
feature/hub (규칙 기반 병원 매칭)
  ↓
feature/dashboard (구급차/병원 대시보드)
```

**특징**:

- 파일이 도착하면 자동 처리
- 동시에 여러 통화 처리 가능
- 에러 자동 재시도
- 처리 상태 모니터링
- 전체 과정이 실시간 흐름

---



## 🏗️ 구현 전략: 3가지 Phase



### **Phase 1: 현재 상태 (프로토타입)** ✅

**상태**: transcribe.py 수동 실행

```bash
python transcribe.py data/origin_data/파일.wav --summarize
```

**용도**:

- 파이프라인 기능 검증
- 모델 성능 테스트
- 일회성 처리

---



### **Phase 2: 자동 감지 및 처리** (2-3주 예상)

**추가되는 것**: 파일 감시 + 큐 + 워커

#### 데이터 흐름

```
[File Watcher]
  data/origin_data/ 감시
  ↓
  새 파일 감지 → 이벤트 발생
  ↓
[Queue Manager]
  처리 대기 목록 관리
  ↓
[Voice Processing Worker]
  STT → 필터링 → 구조화
  ↓
[Result Handler]
  JSON 저장
  + 상태 로그 기록
```



#### 폴더 구조

```
AIRookie/
├── transcribe.py              (기존 - 변경 없음)
├── filtering.py               (기존)
├── summarizer.py              (기존)
├── schema.py                  (기존)
├── ollama_bootstrap.py        (기존)
├── add_noise.py               (기존)
│
├── voice_processing/          ← 새로 추가
│   ├── __init__.py
│   ├── file_watcher.py        # 파일 감시 + 이벤트
│   ├── processing_queue.py    # FIFO 큐 관리
│   ├── worker.py              # 워커 프로세스 (파이프라인 실행)
│   ├── config.py              # 설정값 (경로, threshold 등)
│   └── utils.py               # 공통 유틸리티
│
├── voice_daemon.py            ← 메인 진입점 (데몬 서버)
│                                 # 백그라운드에서 항상 실행
└── data/
    ├── origin_data/           (입력 - 음성 파일)
    ├── origin_noise_data/     (테스트용 - 노이즈 합성본)
    ├── origin_text/           (출력 - STT 결과)
    ├── summary_text/          (출력 - 최종 JSON)
    └── processing_status/     ← 새로 추가 (처리 로그)
        ├── pending/           # 대기 중인 작업
        ├── processing/        # 진행 중인 작업
        └── completed/         # 완료된 작업
```



#### 구현 예시

```python
# voice_daemon.py
import logging
from voice_processing.file_watcher import AudioFileWatcher
from voice_processing.processing_queue import VoiceProcessingQueue
from voice_processing.worker import VoiceProcessingWorker

def main():
    logger = setup_logging()
    queue = VoiceProcessingQueue()
    
    # 1. 파일 감시 시작 (백그라운드 스레드)
    watcher = AudioFileWatcher(
        watch_dir="data/origin_data",
        queue=queue,
        logger=logger
    )
    watcher.start()
    logger.info("파일 감시 시작...")
    
    # 2. 워커 시작 (메인 스레드에서 무한 루프)
    worker = VoiceProcessingWorker(
        queue=queue,
        logger=logger
    )
    worker.run()  # 영원히 대기하며 새 작업을 처리

if __name__ == "__main__":
    main()
```

**실행 방법**:

```bash
# 터미널에서 실행 (또는 systemd 데몬으로 등록)
python voice_daemon.py

# 또는 백그라운드로 실행
nohup python voice_daemon.py > logs/voice_daemon.log 2>&1 &
```

**동작**:

1. voice_daemon.py 실행 → data/origin_data/ 감시 시작
2. 누군가 파일을 data/origin_data/에 추가
3. 워처가 자동 감지 → 큐에 등록
4. 워커가 큐에서 꺼내 자동 처리
5. 결과 JSON을 data/summary_text/에 저장
6. 처리 완료 로그 기록

---



### **Phase 3: feature/hub 연동** (3-5주 예상)

**추가되는 것**: WebSocket/HTTP 클라이언트 + 에러 재시도

#### 데이터 흐름

```
[Voice Processing Worker]
  ↓ (JSON 생성 완료)
[Hub Client]
  ├─ feature/hub에 전송 시도
  ├─ 실패 시 재시도 (exponential backoff)
  └─ 최종 실패 시 데드레터 큐에 저장
  ↓
feature/hub API
  GET http://feature-hub:8000/api/call_summary
  POST /call_summary
  
  결과: {"status": "success", "matching_result": {...}}
  ↓
[Result Handler]
  ├─ 상태 업데이트
  ├─ 로그 기록
  └─ 성공/실패 캐시
```



#### 구현 예시

```python
# voice_processing/hub_client.py
import requests
from typing import Optional
import logging

class HubClient:
    def __init__(self, hub_url: str = "http://feature-hub:8000"):
        self.hub_url = hub_url
        self.logger = logging.getLogger(__name__)
    
    def send_call_summary(self, call_summary: dict, max_retries: int = 3) -> bool:
        """feature/hub로 전송 (재시도 로직 포함)"""
        for attempt in range(max_retries):
            try:
                response = requests.post(
                    f"{self.hub_url}/api/call_summary",
                    json=call_summary,
                    timeout=30,
                    headers={"Content-Type": "application/json"}
                )
                if response.status_code == 200:
                    self.logger.info(f"feature/hub 전송 성공")
                    return True
                else:
                    self.logger.warning(f"feature/hub 응답: {response.status_code}")
            except requests.RequestException as e:
                self.logger.error(f"feature/hub 전송 실패 (시도 {attempt+1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # 지수 백오프
        
        return False

# 사용 예시
hub = HubClient()
success = hub.send_call_summary(call_summary_json)
if not success:
    # 실패 시 데드레터 큐에 저장
    save_to_deadletter_queue(call_summary_json)
```

---



## 📊 시스템 확장도

```
실제 운영 환경 (Phase 3)

┌─────────────────────────────────────────────────────────┐
│                  구급차 현장                              │
│  ┌──────────────────────────────────────────────────┐   │
│  │  PBX/통신 장치 (음성 녹음)                         │   │
│  │  → /mnt/voice_storage/ 에 실시간 저장            │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
                           ↓ (네트워크)
┌─────────────────────────────────────────────────────────┐
│                voice_daemon.py 실행 중                  │
│  (feature/voice 서버 또는 클라우드)                     │
│                                                         │
│  ┌────────────────────────────────────────────────┐    │
│  │  [File Watcher] (watchdog)                     │    │
│  │  → /mnt/voice_storage/ 감시                     │    │
│  │  → 새 파일 감지 시 이벤트                        │    │
│  └────────────────────────────────────────────────┘    │
│                      ↓                                   │
│  ┌────────────────────────────────────────────────┐    │
│  │  [Processing Queue]                            │    │
│  │  ├─ 파일1_20260731_143000.wav                  │    │
│  │  ├─ 파일2_20260731_143015.wav                  │    │
│  │  └─ 파일3_20260731_143030.wav                  │    │
│  └────────────────────────────────────────────────┘    │
│                      ↓                                   │
│  ┌────────────────────────────────────────────────┐    │
│  │  [Voice Processing Worker] x N (병렬)          │    │
│  │  ├─ STT (Whisper)                              │    │
│  │  ├─ 실시간 음성 필터링                          │    │
│  │  ├─ SBAR 구조화 (LLM)                          │    │
│  │  └─ JSON 생성                                   │    │
│  └────────────────────────────────────────────────┘    │
│                      ↓                                   │
│  ┌────────────────────────────────────────────────┐    │
│  │  [Hub Client]                                  │    │
│  │  → feature/hub에 WebSocket 연결                │    │
│  │  → JSON 전송 + 재시도 로직                      │    │
│  └────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
                           ↓ (네트워크)
┌─────────────────────────────────────────────────────────┐
│  feature/hub (규칙 기반 병원 매칭)                       │
│  → 환자 정보 + 병원 정보 결합                           │
│  → 존 기반 병원 리스트 생성                             │
└─────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────┐
│  feature/dashboard (구급차/병원 대시보드)                 │
│  → 구급대원: 병원 선택 화면                              │
│  → 병원: 응급 환자 승인/불가 화면                       │
└─────────────────────────────────────────────────────────┘
```

---



## ⚙️ Phase 2 즉시 구현 가능한 부분



### Step 1: 의존성 추가 (30분)

```bash
pip install watchdog==4.0.0
```

requirements.txt에 추가:

```
watchdog==4.0.0  # 파일 시스템 감시용
```



### Step 2: 폴더 구조 생성 (10분)

```bash
mkdir -p voice_processing
mkdir -p data/processing_status/{pending,processing,completed}
touch voice_processing/__init__.py
```



### Step 3: 파일 감시 모듈 (1시간)

**voice_processing/file_watcher.py**:

```python
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from pathlib import Path
import logging

class AudioFileHandler(FileSystemEventHandler):
    def __init__(self, queue, logger):
        self.queue = queue
        self.logger = logger
    
    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith(('.wav', '.mp3', '.m4a')):
            file_path = Path(event.src_path)
            self.logger.info(f"새 음성 파일 감지: {file_path.name}")
            self.queue.put(str(file_path))

class AudioFileWatcher:
    def __init__(self, watch_dir: str, queue, logger):
        self.watch_dir = watch_dir
        self.queue = queue
        self.logger = logger
        self.observer = Observer()
    
    def start(self):
        handler = AudioFileHandler(self.queue, self.logger)
        self.observer.schedule(handler, path=self.watch_dir, recursive=False)
        self.observer.start()
    
    def stop(self):
        self.observer.stop()
        self.observer.join()
```



### Step 4: 큐 관리 모듈 (30분)

**voice_processing/processing_queue.py**:

```python
from queue import Queue, Empty
from dataclasses import dataclass
from datetime import datetime

@dataclass
class ProcessingTask:
    file_path: str
    created_at: datetime
    attempt_count: int = 0

class VoiceProcessingQueue:
    def __init__(self):
        self.queue = Queue()
        self.failed_tasks = []
    
    def put(self, file_path: str):
        task = ProcessingTask(file_path=file_path, created_at=datetime.now())
        self.queue.put(task)
    
    def get(self, timeout: int = 1) -> ProcessingTask | None:
        try:
            return self.queue.get(timeout=timeout)
        except Empty:
            return None
    
    def task_done(self):
        self.queue.task_done()
    
    def put_failed(self, task: ProcessingTask):
        self.failed_tasks.append(task)
```



### Step 5: 워커 모듈 (2시간)

**voice_processing/worker.py**:

```python
import sys
from pathlib import Path
from transcribe import transcribe
import logging

class VoiceProcessingWorker:
    def __init__(self, queue, logger):
        self.queue = queue
        self.logger = logger
    
    def process_task(self, task):
        try:
            file_path = Path(task.file_path)
            if not file_path.exists():
                self.logger.error(f"파일 없음: {file_path}")
                return False
            
            self.logger.info(f"처리 시작: {file_path.name}")
            
            # 기존 transcribe.py 함수 호출
            transcribe(
                audio_path=file_path,
                model_size="large-v3",
                language="ko",
                device="auto",
                compute_type="auto",
                do_summarize=True,
                llm_model="qwen3:14b"
            )
            
            self.logger.info(f"처리 완료: {file_path.name}")
            return True
        
        except Exception as e:
            self.logger.error(f"처리 실패: {e}")
            task.attempt_count += 1
            if task.attempt_count < 3:
                self.queue.put(str(task.file_path))  # 재시도
            return False
    
    def run(self):
        self.logger.info("워커 시작...")
        while True:
            task = self.queue.get(timeout=1)
            if task:
                self.process_task(task)
                self.queue.task_done()
```



### Step 6: 데몬 진입점 (30분)

**voice_daemon.py**:

```python
import logging
from voice_processing.file_watcher import AudioFileWatcher
from voice_processing.processing_queue import VoiceProcessingQueue
from voice_processing.worker import VoiceProcessingWorker

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('logs/voice_daemon.log'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

def main():
    logger = setup_logging()
    queue = VoiceProcessingQueue()
    
    # 파일 감시 시작 (백그라운드)
    watcher = AudioFileWatcher(
        watch_dir="data/origin_data",
        queue=queue,
        logger=logger
    )
    watcher.start()
    logger.info("음성 파일 감시 시작: data/origin_data/")
    
    try:
        # 워커 시작 (메인 스레드)
        worker = VoiceProcessingWorker(queue=queue, logger=logger)
        worker.run()
    except KeyboardInterrupt:
        logger.info("데몬 종료...")
        watcher.stop()

if __name__ == "__main__":
    main()
```

---



## 🚀 사용 방법 (Phase 2 완성 후)



### 개발 중

```bash
# 여전히 수동 모드 사용 가능
python transcribe.py data/origin_data/test.wav --summarize
```



### 운영 중

```bash
# 데몬 시작 (백그라운드에서 항상 실행)
nohup python voice_daemon.py > logs/voice_daemon.log 2>&1 &

# 로그 확인
tail -f logs/voice_daemon.log

# 새 음성 파일 추가하면 자동 처리됨
cp /path/to/emergency_call.wav data/origin_data/

# 처리 결과 확인
cat data/summary_text/emergency_call_call_summary.json | jq
```

---



## 📋 Phase 2 체크리스트

- [ ] watchdog 라이브러리 추가
- [ ] voice_processing/ 폴더 및 모듈 생성
- [ ] file_watcher.py 구현
- [ ] processing_queue.py 구현
- [ ] worker.py 구현
- [ ] voice_daemon.py 구현
- [ ] logs/ 폴더 생성
- [ ] 수동 테스트 (파일 추가 → 자동 처리 확인)
- [ ] systemd 서비스 등록 (선택사항)

---



## 📋 Phase 3 체크리스트 (feature/hub 팀과 협의 후)

- [ ] feature/hub API 스펙 정의
- [ ] hub_client.py 구현
- [ ] WebSocket/HTTP 연동
- [ ] 에러 재시도 로직
- [ ] 데드레터 큐 구현
- [ ] feature/hub와 통합 테스트
- [ ] 모니터링 대시보드 (선택사항)

---



## 🔗 관련 문서

- `CLAUDE.md` - 프로젝트 전체 아키텍처
- `README.md` - feature/voice 현재 구현 상세
- `.docs/ERD.pdf` - 데이터 모델

