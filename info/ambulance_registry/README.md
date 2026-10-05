# 구급차 레지스트리 — 소방청 공공데이터로 서울 119 구급차 등록 (2026-10-04)

시연용 구급차 3대(역삼·성산·회현, `A0000001~3`)를 **서울 119안전센터의 실제 운영 구급차 162대**로 교체하는 작업이다.
위치(센터 좌표)와 대수는 실제 공공데이터, 출동·이동은 기존처럼 시뮬레이션이다.

| 순서 | 할 일 | 명령 |
|---|---|---|
| 1 | 두 CSV(`dashboard/NationalFireAgency*.csv`) → 1대 = 1행, 좌표 변환(카카오 주소 → 키워드 검색) | `python info/ambulance_registry/build_seoul.py` |
| 2 | Supabase 구급차 프로젝트 SQL 편집기에서 보강 컬럼 추가(한 번) | `schema_extend.sql` 내용 실행 |
| 3 | `.env`에 URL·service_role 키 입력 후 확인 → 적용(기존 행은 지우고 새 162대로 교체) | `python info/ambulance_registry/upload.py` → `--apply` |

- 결과: `result/seoul_ambulances.csv`(162대, `SEL0001~SEL0162`), `result/unregistered_centers.csv`(좌표를 못 구한 센터 — 상위 센터 좌표로 대신하지 않음)
- 2026-10-04 실행: 서울 센터 119곳 모두 좌표 확보(주소 검색 117 · 키워드 검색 2: 상암·장위), 미등록 0곳
- 지역대(작은 거점)는 보류. 서울 데이터엔 지역대가 없다
- `voice_port`는 중앙 voice(6000) 하나라 모두 6000. info → hub 형식(`AmbulanceInfo`)은 그대로다
- 테이블을 통째로 바꿔도 hub에 옛 구급차가 남지 않는다 — `send_to_hub.py`가 구급차를 묶어 보낸 뒤 전체 apid 목록(`POST /info/ambulances/roster`)을 알리고, hub가 목록에 없는 구급차를 지운다(진행 중 사건·출동 중이면 보류)
