"""데모용 거절 로그 주입기 — 플라이휠 배선이 실제로 도는 것을 보여주기 위한 도구.

    python -m hospital_score.demo_rejections          # 로그 파일에 직접 기록
    python -m hospital_score.demo_rejections --post   # 수신 서버(5003) 경유 (실왕복)
    python -m hospital_score.rejection_report         # 결과 확인

거절 로그는 실서비스가 돌아야 쌓이는 데이터라, 시범운영 전에는 통계 근거로
쓸 수 없다. 이 스크립트의 목적은 통계가 아니라 **배선의 시연**이다 — "거절
사유 4축 + 결정 시점 스냅샷 + 무응답 구분이 수신구에 실제로 축적되고
집계된다"를 30초 안에 보여준다.

모든 건에 `demo: true` 마커가 들어가므로(수신구가 extra에 보존), 나중에 실
로그가 쌓이기 시작해도 `rejection_report --exclude-demo`로 완전히 분리된다 —
데모 데이터가 실 통계를 오염시키지 않는다는 원칙(무응답의 caseFinalized
구분과 같은 취지).

시나리오는 고정(난수 없음)이며 hub가 실제로 보내는 페이로드 형태(결정 시점
스냅샷 `*AtRequest`, 무응답 `reachedAtBroadcast`/`caseFinalized` 포함)를 그대로
따른다 — hub/app.py의 `_rejection_payload()`/`_log_no_responses()` 참고.
"""
from __future__ import annotations

import argparse
import json

from . import rejection as R

#: 시연 서사가 담긴 고정 시나리오. 세 사건(심근경색·중증화상·소아 경련)에
#: 걸쳐, 리포트의 각 섹션이 최소 한 번씩 등장하도록 구성했다:
#: - 정보 무효의 독립 관측: authority 높았는데 BEDS_FULL 거절 (G2 라벨 후보)
#: - 신고 오류 후보: 같은 병원의 구조적(NO_WARD) 거절 반복
#: - "가능(Y) 신고였는데 거절"
#: - 무응답 3분해: 도달했는데 무시 / 미도달 / 미결 종료 사건
DEMO_REJECTIONS: list[dict] = [
    # ── 사건 1: 심근경색 (case-demo-mi) ──────────────────────────────────
    {  # 시스템은 병상 유효 91%로 봤는데 만실 거절 — 정보 무효의 독립 관측
        "hospitalId": "A1100017", "caseId": "case-demo-mi",
        "timestamp": "2026-09-29T09:12:00+09:00", "reasonCode": "BEDS_FULL",
        "severity": "high", "diseaseGroup": "재관류중재술", "declaredAtRequest": "Y",
        "availableBedCountAtRequest": 5, "bedCountUnknownAtRequest": False,
        "bedAuthorityAtRequest": 0.91, "bedRArriveAtRequest": 0.86,
        "travelMinAtRequest": 9.4, "finalScoreAtRequest": 0.71, "demo": True,
    },
    {  # 당직 불일치 — 주기적 축
        "hospitalId": "A1100021", "caseId": "case-demo-mi",
        "timestamp": "2026-09-29T09:13:00+09:00", "reasonCode": "ON_CALL_MISMATCH",
        "severity": "high", "diseaseGroup": "재관류중재술", "declaredAtRequest": "Y",
        "bedAuthorityAtRequest": 0.74, "bedRArriveAtRequest": 0.66,
        "travelMinAtRequest": 14.0, "finalScoreAtRequest": 0.58, "demo": True,
    },
    {  # 확정 시점까지 무응답 — 요청은 도달했었음(무시 축)
        "hospitalId": "A1100050", "caseId": "case-demo-mi",
        "timestamp": "2026-09-29T09:20:00+09:00", "reasonCode": "NO_RESPONSE",
        "severity": "high", "diseaseGroup": "재관류중재술",
        "reachedAtBroadcast": True, "hospitalDashboardConnected": True,
        "caseFinalized": True, "finalizedTo": "A1100014", "demo": True,
    },
    {  # 확정 시점까지 무응답 — 대시보드 미접속(미도달, 보급 지표)
        "hospitalId": "A1100062", "caseId": "case-demo-mi",
        "timestamp": "2026-09-29T09:20:00+09:00", "reasonCode": "NO_RESPONSE",
        "severity": "high", "diseaseGroup": "재관류중재술",
        "reachedAtBroadcast": False, "hospitalDashboardConnected": False,
        "caseFinalized": True, "finalizedTo": "A1100014", "demo": True,
    },
    # ── 사건 2: 중증화상 (case-demo-burn) ────────────────────────────────
    {  # 화상 병동 없음 — 구조적. E-Gen 신고가 틀렸다는 증거 후보
        "hospitalId": "A1300002", "caseId": "case-demo-burn",
        "timestamp": "2026-09-29T14:02:00+09:00", "reasonCode": "NO_WARD",
        "severity": "high", "diseaseGroup": "중증화상", "declaredAtRequest": "Y",
        "bedAuthorityAtRequest": 0.83, "travelMinAtRequest": 11.2, "demo": True,
    },
    {  # 같은 병원, 다른 사건에서도 반복된 구조적 거절 (신고 오류 후보 상위로)
        "hospitalId": "A1300002", "caseId": "case-demo-burn2",
        "timestamp": "2026-09-29T18:40:00+09:00", "reasonCode": "NO_WARD",
        "severity": "medium", "diseaseGroup": "중증화상", "declaredAtRequest": "Y",
        "demo": True,
    },
    {  # 수술방 사용 중 — 순간적
        "hospitalId": "A1300011", "caseId": "case-demo-burn",
        "timestamp": "2026-09-29T14:05:00+09:00", "reasonCode": "OR_OCCUPIED",
        "severity": "high", "diseaseGroup": "중증화상",
        "bedAuthorityAtRequest": 0.62, "travelMinAtRequest": 18.5, "demo": True,
    },
    # ── 사건 3: 소아 경련 — 확정 없이 종료된 미결 사건 ───────────────────
    {  # 중증도 초과 — 환자 요인
        "hospitalId": "A1100031", "caseId": "case-demo-ped",
        "timestamp": "2026-09-29T21:30:00+09:00", "reasonCode": "SEVERITY_EXCEEDED",
        "severity": "high", "diseaseGroup": "장중첩/폐색", "demo": True,
    },
    {  # 미결 종료 사건의 무응답 — 요청 유효성 모호(caseFinalized=false)
        "hospitalId": "A1100044", "caseId": "case-demo-ped",
        "timestamp": "2026-09-29T23:30:00+09:00", "reasonCode": "NO_RESPONSE",
        "severity": "high", "diseaseGroup": "장중첩/폐색",
        "reachedAtBroadcast": True, "hospitalDashboardConnected": False,
        "caseFinalized": False, "demo": True,
    },
    {  # 이유 미기재 거절 — UNSPECIFIED 경로도 시연
        "hospitalId": "A1100059", "caseId": "case-demo-ped",
        "timestamp": "2026-09-29T21:33:00+09:00",
        "severity": "high", "diseaseGroup": "장중첩/폐색", "demo": True,
    },
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--post", action="store_true",
                        help="파일 직접 기록 대신 수신 서버(POST /hub/rejection)로 보낸다")
    parser.add_argument("--url", default="http://127.0.0.1:5003/hub/rejection")
    args = parser.parse_args()

    if args.post:
        import requests

        response = requests.post(args.url, json=DEMO_REJECTIONS, timeout=10)
        response.raise_for_status()
        print(f"수신 서버 경유로 {response.json().get('saved')}건 기록 — {args.url}")
    else:
        for payload in DEMO_REJECTIONS:
            R.append(R.normalize(payload))
        print(f"데모 거절 {len(DEMO_REJECTIONS)}건 기록 — {R.LOG_DIR}")
    print(json.dumps({"cases": 4, "hospitals": len({p['hospitalId'] for p in DEMO_REJECTIONS})},
                     ensure_ascii=False))
    print("확인: python -m hospital_score.rejection_report")
    print("실 로그와 분리: python -m hospital_score.rejection_report --exclude-demo")


if __name__ == "__main__":
    main()
