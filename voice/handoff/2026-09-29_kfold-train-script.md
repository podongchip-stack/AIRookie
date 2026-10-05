# 작업 인수인계

## 목표
`C:\Dev\HMM\data_v3\golden_v3.jsonl` 데이터셋으로 K-fold 교차검증 학습을 할 수 있는 스크립트를 만드는 것. fold마다 결과를 내고, 전체 fold 평균(±표준편차)도 함께 내야 한다. 사용자가 GPU가 달린 PC의 Anaconda Prompt에서 직접 실행할 것이므로, 코드만 준비하고 실행은 하지 않는다.

## 현재까지 완료한 것
- `C:\Dev\HMM\model_v2\train_kfold.py`를 새로 작성함. 기존 `model_v2\train.py`(단일 train/eval split 학습 스크립트)와 `data.py`/`labels.py`/`model.py`/`losses.py`/`metrics.py`(수정 없이 그대로 재사용)를 기반으로, K-fold 학습 로직만 추가한 스크립트다.
- `data_v3\필드_설명.md`를 읽고, `golden_v3.jsonl`의 `v2` 필드가 `model_v2`가 원래 쓰던 `data_v2/golden_v2.jsonl`과 완전히 같은 스키마임을 확인함 (문서에 "model_v2/check_data.py·train.py는 위 v2 필드를 문장 단위 분류·구간 태깅으로 바꿔 학습한다"고 명시돼 있음). 즉 `model_v3` 같은 별도 코드 없이 `model_v2`의 기존 파이프라인을 그대로 재사용할 수 있다.
- `train_kfold.py`의 동작:
  - `edge`(경계 사례)와 `call_type == "119 신고"`인 통화는 기존 `train.py`와 동일하게 전부 제외한다.
  - 나머지는 원래 `split`(train/eval) 필드를 무시하고 하나의 풀로 모아, 시드 고정 셔플 후 K등분한다 (`pool_examples()`, `make_folds()` 함수).
  - 각 fold마다 모델을 처음부터 새로 초기화해서 나머지 (K-1)개 fold로 학습하고, 자신의 fold로 검증한다 (`run_fold()` 함수). 결과는 `<output-dir>/fold00/ ~ fold0{K-1}/`에 `best.pt`, `best.json`, `history.jsonl`, `run_config.json`으로 저장 (`train.py`와 동일 포맷).
  - 전체 fold가 끝나면 `aggregate()`로 fold별 best score, 헤드별 정확도/macro-F1, 다중 선택 헤드 micro/macro-F1, span F1을 평균±표준편차로 묶어 `<output-dir>/summary.json`, `summary.txt`에 저장한다.
  - 학습 하이퍼파라미터 인자(`--encoder`, `--epochs`, `--batch-size`, `--learning-rate`, `--head-weight` 등)는 `train.py`와 동일하게 받는다. 새로 추가된 인자는 `--folds`(기본 5)와 `--limit-pool`(스모크 테스트용, 기본 0=전부).
  - 사용자 요청에 따라 `--output-dir` 기본값을 `D:\Local_AI_Model\HMM\model_v2\runs\kfold5`로 설정함 (C드라이브에 학습 산출물을 쌓지 않기 위해 — PC 전역 규칙: 코드는 `C:\Dev`, 대용량 산출물은 `D:\Local_AI_Model`).
- 검증 수준: `python -m py_compile train_kfold.py`로 문법 오류만 확인함(통과). **실제 실행(스모크 테스트)은 아직 한 번도 안 됐다** — 사용자가 스모크 테스트 tool 호출을 거부하고 본인이 Anaconda Prompt + GPU로 직접 돌리겠다고 함.

## 지금 진행 중인 것 / 다음 할 일
1. 사용자가 Anaconda Prompt에서 아래 명령으로 먼저 스모크 테스트를 돌려야 한다 (아직 안 함):
   ```bat
   conda activate ml
   cd C:\Dev\HMM\model_v2
   python train_kfold.py --folds 3 --epochs 1 --limit-pool 200 --device cuda
   ```
   여기서 런타임 에러(데이터 로딩, 텐서 shape, device 관련 등)가 날 수 있으니, 에러가 나면 그 트레이스백을 보고 고쳐야 한다.
2. 스모크 테스트가 통과하면 기본 설정(5-fold, fold당 10 에폭)으로 본 학습을 돌린다:
   ```bat
   python train_kfold.py --device cuda
   ```
3. 학습이 끝나면 `D:\Local_AI_Model\HMM\model_v2\runs\kfold5\summary.txt`로 결과를 확인한다.
4. **이 작업을 기존에 진행 중인 GitHub 브랜치에 커밋해야 하는데, `C:\Dev\HMM`는 현재 git 저장소가 아니다** (`git status` 실행 시 "fatal: not a git repository" — `.git` 폴더가 3단계 깊이까지 어디에도 없음을 확인함). 사용자가 말한 "이미 하고 있는 브랜치"가 실제로 어느 경로/저장소를 가리키는지 아직 파악 못 했다. 새 세션은 이 부분부터 사용자에게 확인해야 한다 (다른 위치에 별도 git 작업 디렉터리가 있는지, 아니면 이 폴더에 `git init`부터 해야 하는지).
5. 커밋 전에 `model_v2/runs/` 아래에 로컬 스모크 테스트 산출물이 남아있지 않은지 확인 — 원래 `train.py`도 `runs/` 하위에 결과를 남기는 구조라, 실수로 큰 체크포인트 파일이 커밋에 딸려가지 않게 주의해야 한다 (다만 이번 스크립트는 기본값을 D드라이브로 뺐으므로 C드라이브 쪽엔 안 쌓일 것으로 예상됨 — 스모크 테스트 결과로 재확인 필요).

## 관련 파일
- `model_v2/train_kfold.py` — 이번에 새로 만든 K-fold 학습 스크립트. 이번 작업의 핵심 산출물.
- `model_v2/train.py` — 원본 단일 split 학습 스크립트. `train_kfold.py`가 이 파일의 학습 루프·옵티마이저 설정·평가 로직을 거의 그대로 복사해서 fold 단위로 감싼 구조라, 두 파일을 비교하면 차이점(= K-fold 관련 로직)만 빠르게 파악 가능.
- `model_v2/data.py` — 데이터 로딩·검증·인코딩 (`load_examples`, `partition_valid`, `CallDataset`, `collate`). 수정 안 함. `EXCLUDED_CALL_TYPES`(119 신고 제외 목록)를 여기서 import해서 씀.
- `model_v2/labels.py`, `model_v2/model.py`, `model_v2/losses.py`, `model_v2/metrics.py` — 라벨 어휘, 모델 구조, 손실 함수, 평가 지표. 전부 수정 안 함.
- `data_v3/golden_v3.jsonl` — 이번에 학습 대상인 데이터셋 (9,677줄, `{id, split, text, meta, v2}` 구조).
- `data_v3/필드_설명.md` — `golden_v3.jsonl`의 `v2` 필드와 모델 헤드 매핑을 설명하는 문서. 이번 스키마 호환성 판단의 근거.

## 중요한 맥락 / 주의사항
- `data_v3`용 별도 모델 코드(`model_v3` 같은 것)는 존재하지 않는다. `model_v2`의 코드가 그대로 `data_v3` 스키마를 처리하도록 만들어져 있음(문서에 명시됨) — 새 세션이 이걸 모르고 "model_v3부터 만들어야 하나?"로 헤매지 않도록.
- 사용자의 전역 개발 규칙(`C:\Users\podon\.claude\CLAUDE.md`, `DevSetting.md`): 프로젝트 코드는 `C:\Dev\`, 학습/모델 산출물처럼 큰 파일은 OneDrive 안쪽인 `C:\Users\...\문서` 계열이나 프로젝트 루트에 쌓지 않고 `D:\Local_AI_Model\` 계열에 둔다. 이번에 `--output-dir` 기본값을 D드라이브로 잡은 이유가 이것.
- 학습은 conda `ml` 환경(`C:\Users\podon\anaconda3\envs\ml\python.exe`)에서 GPU(RTX 5080, bf16)로 돈다. 일반 PowerShell에서 `conda activate`가 안 되는 환경이라, 사용자는 Anaconda Prompt에서 직접 `conda activate ml` 후 실행한다.
- **미검증 상태임을 반드시 인지할 것**: `train_kfold.py`는 문법 검사만 통과했고, 실제로 한 번도 실행된 적이 없다. 데이터 로딩, 텐서 shape, GPU 메모리, fold 분할 경계값(`make_folds`가 `len(pool) < k`일 때 에러 내는 부분 등) 관련 버그가 있을 수 있다.
- git 저장소 위치가 불확실함(위 "다음 할 일" 4번 참고) — 이 폴더(`C:\Dev\HMM`) 자체는 git 저장소가 아니다. 사용자가 언급한 "이미 하고 있는 브랜치"의 실제 위치를 먼저 확인해야 커밋 작업을 진행할 수 있다.
- 사용자는 커밋 메시지에 Claude/AI를 공동 작성자로 표기하는 것을 금지함(전역 규칙). 이 프로젝트에서 git 커밋을 만들 때는 `Co-Authored-By: Claude ...` 같은 트레일러를 추가하면 안 된다.

## 검증 방법
1. 문법 검사(이미 통과): `C:\Users\podon\anaconda3\envs\ml\python.exe -m py_compile model_v2\train_kfold.py`
2. 스모크 테스트 (아직 실행 안 됨, 새 세션 또는 사용자가 실행):
   ```bat
   conda activate ml
   cd C:\Dev\HMM\model_v2
   python train_kfold.py --folds 3 --epochs 1 --limit-pool 200 --device cuda
   ```
   성공 기준: 에러 없이 fold별로 `train_loss=... val_loss=... score=...` 로그가 찍히고, `D:\Local_AI_Model\HMM\model_v2\runs\kfold5\fold00\best.pt`와 `fold01\best.pt`, `fold02\best.pt`가 생성되고, 마지막에 `summary.txt`가 출력됨.
3. 본 학습 후: `D:\Local_AI_Model\HMM\model_v2\runs\kfold5\summary.txt`를 열어 fold별 score와 평균±표준편차가 합리적인 범위(0~1)에 있는지, fold 간 편차가 비정상적으로 크지 않은지 확인.
