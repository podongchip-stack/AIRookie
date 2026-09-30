# simulation3 — Qwen3-ASR → HMM 실험용 시뮬레이터

장비 마이크로 말하면 **말이 끊길 때마다** 그 발화를 인식하고, 지금까지의 통화로 6필드를 다시 뽑아
보여주는 데스크톱 화면(tkinter)이다. 통화를 끝내면 남은 발화까지 인식한 최종 결과와 hub로 갈 JSON을
보여준다. **실운영 경로가 아니다** — 시연과 무음 기준 튜닝, 모델 결과 확인용이다.

## 실행

```bat
conda activate AIRookieProject
cd C:\Dev\Project\AIRookie\voice
python simulation3\gui.py
```

추가 설치는 없다(tkinter는 파이썬 표준 라이브러리). voice의 `requirements.txt`를 그대로 쓰고,
가중치도 voice와 같이 첫 실행 때 Hugging Face Hub에서 자동으로 받는다(voice README "빠른 시작").

1. 창이 뜨면 모델을 올린다(약 15초). "준비 완료"가 뜨면 **통화 시작**
2. 말하면 발화가 끊길 때마다 표가 갱신된다
3. **통화 종료**를 누르면 남은 발화를 인식해 최종 결과를 보여준다(1초 안팎)

## 화면

| 영역 | 내용 |
| --- | --- |
| 무음 기준 RMS / 발화 끊김 판정 초 | `VOICE_SILENCE_RMS` / `VOICE_UTTERANCE_HOLD_SEC`와 같은 값. **통화 시작 시점 값이 적용**된다 |
| 현재 마이크 음량 | 최근 0.5초 RMS와, 지금 기준으로 말소리/무음 중 어느 쪽으로 판정되는지 |
| summary 6필드 | hub로 가는 값 + 각 필드가 AI 판정인지 규칙 조립인지 |
| 모델 판정 중간값 | 조립 전 값 — 원인·원인 유형·부위·대표 증상·나이대·성별·중증도·처치 |
| 발화별 인식 | 발화마다 시작·끝 시각(초)과 인식 텍스트 |
| 증상 구간 | 모델이 태깅한 증상 구간 원문, 있음/없음, 표준명(사전에 없으면 원문이 그대로 나감) |
| hub 전송 JSON 미리보기 | 스키마 검증을 통과한 `CallSummaryMessage` 그대로. **전송·저장은 하지 않는다** |

## 무음 기준 맞추기

말하지 않을 때 음량 표시가 "무음으로 봄", 말할 때 "말소리로 봄"이 되도록 **무음 기준 RMS**를
맞춘다. 발화가 너무 잘게 끊기면 **발화 끊김 판정 초**를 늘린다. 맞춘 값은 `app.py`를 띄울 때
환경변수로 그대로 옮기면 된다 — 마이크 입력(`MicRecorder`)부터 같은 코드라 결과가 같다.

```bat
set VOICE_SILENCE_RMS=0.02
set VOICE_UTTERANCE_HOLD_SEC=0.6
python app.py
```

## 실운영 코드와의 관계

사본이 없다. 녹음(`mic_recorder.MicRecorder`)·발화 단위 인식(`live_transcriber.LiveTranscriber`)·
ASR(`asr.py`)·구조화(`hmm/`)·JSON 조립(`transcribe.build_call_summary_message`)을 전부 voice/에서
import한다. 화면과 스레드만 이 파일(`gui.py`)이 담당한다.

| | `app.py` (실운영) | `simulation3/gui.py` |
| --- | --- | --- |
| 통화 시작·종료 | hub가 중계한 HTTP 신호 | 버튼 |
| 통화 중 6필드 갱신 | 안 함 (종료 후 1회) | 발화가 늘 때마다 |
| hub 전송·파일 저장 | 함 | 안 함 (JSON 미리보기만) |
| caseId | hub가 내려준 값 | `case-simulation` 고정 |
