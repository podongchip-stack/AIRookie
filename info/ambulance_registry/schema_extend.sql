-- 구급차 레지스트리 보강 컬럼 (2026-10-04) — Supabase 구급차 프로젝트 > SQL Editor에서 한 번 실행
-- 기존 컬럼(apid, name, wgs84_lat, wgs84_lon, voice_port, updated_at)은 그대로 둔다.
-- info → hub 전송(send_to_hub.py)은 기존 컬럼만 읽으므로 hub로 가는 형식은 바뀌지 않는다.
alter table ambulances add column if not exists sido          text;  -- 시도 (예: 서울)
alter table ambulances add column if not exists fire_station  text;  -- 소방서 (예: 강남소방서)
alter table ambulances add column if not exists center        text;  -- 119안전센터 (예: 역삼119안전센터)
alter table ambulances add column if not exists unit_no       int;   -- 그 센터의 몇 번째 구급차
alter table ambulances add column if not exists addr          text;  -- 센터 주소(소방청 공공데이터)
alter table ambulances add column if not exists phone         text;  -- 센터 전화번호
alter table ambulances add column if not exists coord_source  text;  -- 좌표를 얻은 방법: address(주소 검색) | keyword(이름 검색)
