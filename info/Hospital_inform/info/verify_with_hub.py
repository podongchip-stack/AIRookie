"""우리가 만든 병원 JSON을 feature/hub의 진짜 매칭 엔진에 넣어보는 검증 스크립트.

왜 필요한가
----------
`schema.py`의 검사기는 "우리가 이해한 형식"을 검사한다. 우리가 hub 코드를 잘못
읽었을 가능성은 그 검사로 잡히지 않는다. 실제 hub 엔진에 넣어보는 것만이 확실하다.

팀 저장소를 건드리지 않는다
--------------------------
hub 모듈을 복사해두면 상대가 코드를 고쳤을 때 조용히 낡은 사본을 검증하게 된다.
그래서 실행할 때마다 git에서 최신 `feature/hub`를 임시 폴더로 꺼내 쓰고, 끝나면
버린다. `C:\\Dev\\AIRookie` 작업 트리에는 파일 하나도 만들지 않는다.

실행
----
임베딩 모델(sentence-transformers)이 필요해 `dev` 환경으로는 안 된다.

    conda create -n rookie_info python=3.11 -y
    conda activate rookie_info
    pip install pydantic==2.13.4 sentence-transformers==5.6.1 numpy
    python info/verify_with_hub.py

첫 실행 때 임베딩 모델(약 500MB)을 내려받는다.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_HUB_REPO = Path(r"C:\Dev\AIRookie")
HUB_BRANCH = "feature/hub"
HUB_MODULES = ("schema.py", "geo.py", "scoring.py", "specialty_matcher.py", "decision_log.py", "hub_engine.py")

#: hub의 run_match.py에 박혀 있는 구급차 위치(진주시청 부근). 거리 계산 기준점.
AMBULANCE = {"lat": 35.1800, "lng": 128.1080}

#: 시나리오별 voice 요약. feature/voice의 출력 형태를 그대로 흉내낸 것.
SCENARIOS: dict[str, dict] = {
    "stroke": {
        "제목": "① 뇌졸중 의심 — 가까운 병원이 아니라 재관류 가능 병원이 뽑혀야 한다",
        "기대": "경상국립대학교병원(4.2km, 재관류 가능)이 진주고려병원(1.5km, 불가)보다 위",
        "voice": {
            # hub의 VoiceCallSummaryMessage가 transcript를 필수로 받기 시작해서
            # (rawTranscript/filteredTranscript를 dashboard까지 전달하기 위함),
            # 이 검증 스크립트도 최소 형태로 맞춰준다 — 매칭 로직과는 무관.
            "transcript": {
                "raw_text": "구급대원: 60대 남성, 급성 허혈성 뇌졸중 의심입니다.",
                "filtered_text": "60대 남성, 급성 허혈성 뇌졸중 의심. 우측 편마비, 언어 장애.",
            },
            "summary": {
                "patient": "60대 남성",
                "mechanism": "급성 허혈성 뇌졸중 의심",
                "symptoms": ["우측 편마비", "언어 장애"],
                "treatment": ["산소 공급"],
                "severity_tag": "high",
            },
            "source": "ai",
        },
    },
    "pediatric": {
        "제목": "② 소아 고열 경련 — 소아 병상이 있는 병원이 뽑혀야 한다",
        "기대": "hub가 bedsByType을 읽기 전까지는 성립하지 않는다 (진료과 매칭으로만 부분 재현)",
        "voice": {
            "transcript": {
                "raw_text": "구급대원: 4세 여아, 소아 열성 경련입니다.",
                "filtered_text": "4세 여아, 소아 열성 경련. 전신 강직, 고열.",
            },
            "summary": {
                "patient": "4세 여아",
                "mechanism": "소아 열성 경련",
                "symptoms": ["전신 강직", "고열"],
                "treatment": ["기도 확보"],
                "severity_tag": "high",
            },
            "source": "ai",
        },
    },
}


def extract_hub_modules(repo: Path, dest: Path) -> None:
    """git에서 feature/hub의 모듈을 꺼내 dest에 쓴다. 작업 트리는 건드리지 않는다.

    hub 브랜치가 코드를 hub/ 폴더로 옮긴 뒤로(develop 통합), git show 경로는
    hub/<name>이어야 하지만 로컬에는 원래 이름 그대로 풀어서 import가
    그대로 되게 한다.
    """
    for name in HUB_MODULES:
        result = subprocess.run(
            ["git", "-C", str(repo), "show", f"{HUB_BRANCH}:hub/{name}"],
            capture_output=True,
        )
        if result.returncode != 0:
            raise SystemExit(
                f"hub 모듈을 꺼내지 못했다: hub/{name}\n"
                f"  저장소: {repo}\n"
                f"  {result.stderr.decode('utf-8', 'replace').strip()}"
            )
        (dest / name).write_bytes(result.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(description="병원 JSON을 hub 매칭 엔진에 넣어 검증한다")
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="stroke")
    parser.add_argument("--hub-repo", type=Path, default=DEFAULT_HUB_REPO)
    parser.add_argument("--hospitals", type=Path, default=BASE_DIR / "data" / "output")
    parser.add_argument("--max-zone", type=int, default=1, help="hub의 run_match.py 기본값은 1")
    args = parser.parse_args()

    files = sorted(args.hospitals.glob("*.json"))
    if not files:
        print(f"병원 JSON이 없다: {args.hospitals}", file=sys.stderr)
        print("먼저 `python info/build_hospitals.py`를 실행할 것.", file=sys.stderr)
        return 1

    scenario = SCENARIOS[args.scenario]
    workdir = Path(tempfile.mkdtemp(prefix="hubcheck_"))
    try:
        extract_hub_modules(args.hub_repo, workdir)
        sys.path.insert(0, str(workdir))

        from hub_engine import HubEngine  # noqa: E402  (임시 폴더 준비 후에만 import 가능)
        from schema import GpsPoint, HospitalInfo, VoiceCallSummaryMessage  # noqa: E402

        try:
            engine = HubEngine()
        except ModuleNotFoundError as exc:
            print(
                f"\nhub 엔진에 필요한 패키지가 없다: {exc.name}\n"
                "이 검증은 임베딩 모델이 필요해 dev 환경으로는 안 된다. 아래를 실행할 것:\n\n"
                "    conda create -n rookie_info python=3.11 -y\n"
                "    conda activate rookie_info\n"
                "    pip install pydantic==2.13.4 sentence-transformers==5.6.1 numpy\n"
                "    python info/verify_with_hub.py\n\n"
                "첫 실행 때 임베딩 모델(약 500MB)을 내려받는다.",
                file=sys.stderr,
            )
            return 1
        print("=== 병원 정보 로드 (hub의 HospitalInfo로 파싱) ===")
        for path in files:
            info = HospitalInfo.model_validate_json(path.read_text(encoding="utf-8"))
            engine.update_hospital_info(info)
            depts = ", ".join(s.department for s in info.specialties) or "(없음)"
            print(f"  {info.hospitalId} {info.name} — 병상 {info.availableBedCount}, 진료과: {depts}")

        gps = GpsPoint(**AMBULANCE)
        print(f"\n=== {scenario['제목']} ===")
        print(f"  기대: {scenario['기대']}")
        print(f"  예상 병명: {scenario['voice']['summary']['mechanism']}")

        voice = VoiceCallSummaryMessage.model_validate(scenario["voice"])
        result = engine.process_voice_summary(voice, gps, max_zone=args.max_zone)

        print(f"\n  활성 존: {result.zoneActive} (zone 1 = 0~5km)")
        print(f"\n  {'순위':<4}{'병원명':<18}{'거리':>8}{'병상':>6}{'매칭 진료과':>14}{'유사도':>8}")
        print("  " + "-" * 62)
        for i, h in enumerate(result.hospitals, 1):
            dept = h.specialtyMatch.department or "(매칭 실패)"
            print(
                f"  {i:<4}{h.name:<18}{h.distanceKm:>7.2f}km{h.availableBedCount:>6}"
                f"{dept:>14}{h.specialtyMatch.score:>8.3f}"
            )

        # 판정: 1위가 기대한 병원인지
        top = result.hospitals[0]
        nearest = min(result.hospitals, key=lambda h: h.distanceKm)
        print()
        if top.hospitalId == nearest.hospitalId:
            print(f"  [주의] 1위 = 가장 가까운 병원({top.name}). "
                  "'가장 가까운 병원 ≠ 정답'이 증명되지 않는다.")
        else:
            print(f"  [성공] 1위 {top.name}({top.distanceKm}km)가 "
                  f"가장 가까운 {nearest.name}({nearest.distanceKm}km)를 제쳤다.")

        # 병상 0인 병원이 걸러지는지 (hub는 아직 병상을 필터에 안 쓴다)
        zero_bed = [h.name for h in result.hospitals if h.availableBedCount == 0]
        if zero_bed:
            print(f"  [확인 필요] 병상 0인데 후보에 남아 있음: {zero_bed}")
            print("             hub가 availableBedCount를 필터에 쓰지 않기 때문. "
                  "시나리오 ③은 hub 수정이 필요하다.")
        return 0
    finally:
        sys.path[:] = [p for p in sys.path if p != str(workdir)]
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
