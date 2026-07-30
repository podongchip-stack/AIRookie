# feature/hub 개발 환경 가이드

## 가상환경 설정

```bash
conda create -n hub python=3.11
conda activate hub
```

## 의존성 설치

```bash
pip install -r requirements.txt
```

## 실행 방법

```bash
python run_match.py
```

`data/test/`에 있는 병원 정보·voice 요약 샘플로 1단계(존 기반 후보 생성)와
2단계(voice 정보 반영 재처리)를 순서대로 실행하고, 최종 결과를
`data/test/output_hub_match_result.json`에 저장한다. 자세한 모듈 구성은
README.md의 "폴더 구조" 참고.

`sentence-transformers`가 처음 실행될 때 `paraphrase-multilingual-MiniLM-L12-v2`
모델을 Hugging Face에서 자동 다운로드한다 (약 470MB, 최초 1회. feature/voice와
동일 모델이라 이미 받아둔 캐시가 있으면 재사용됨).

## 참고

- 브랜치 전체 협업 규칙(브랜치 구조, PR 절차)은 저장소 공통 안내를 따른다.
