-- Supabase(Postgres) 테이블 생성 스크립트: 서울 권역 응급의료기관 정보
--
-- E-Gen(국립중앙의료원 전국 응급의료기관 정보 조회 서비스, data.go.kr/data/15000563)
-- 서비스키가 아직 승인되지 않아, 실제 API를 대체할 목적으로 만드는 테이블이다.
-- 컬럼명은 실제 E-Gen 오퍼레이션들의 필드명을 그대로 따랐다 (나중에 진짜 API로
-- 바꿀 때 매핑 코드를 거의 안 바꿔도 되게 하기 위함):
--   - 가용병상(getEmrrmRltmUsefulSckbdInfoInqire): hpid, dutyName, hvidate, hvec,
--     hvoc, hvcc, hvccc, hvicc, hvgc, hv1, hv2, hv3
--   - 목록정보(getEgytListInfoInqire): hpid, dutyName, wgs84Lat, wgs84Lon, dutyAddr
--   - 중증질환 수용가능(getSrsillDissAceptncPosblInfoInqire): hpid, dutyName, MKioskTy*
--
-- 실제 정보 vs 플레이스홀더 구분 (요청하신 대로 명확히 구분해뒀다):
--   [실제] hpid 형식, duty_name(병원명), duty_addr(주소), wgs84_lat/lon(좌표)
--          -> 서울 권역응급의료센터로 실제 지정된 병원 이름·주소를 썼다. 좌표는
--             근사치이므로 실사용 전 재검증 필요 (본문 답변 참고).
--   [플레이스홀더] hvec 등 병상 수, 장비 가용여부, 중증질환 수용가능 여부
--          -> 이 값들은 실시간으로 바뀌는 운영 데이터라 지금 이 순간의 정확한
--             값을 알 방법이 없다. 서비스키 승인 후 실제 값으로 갈아끼울 자리다.

create table if not exists hospitals (
    hpid            text primary key,           -- [실제 형식] E-Gen 기관코드 형식 (예: A0000028). 실제 코드는 API 승인 후 교체
    duty_name       text not null,               -- [실제] 병원명
    duty_addr       text,                        -- [실제] 주소
    wgs84_lat       double precision not null,   -- [실제, 근사치] 위도
    wgs84_lon       double precision not null,   -- [실제, 근사치] 경도

    -- 가용 병상 (전부 [플레이스홀더] — 실시간 값 없음)
    hvec            integer,                     -- 응급실 가용 병상
    hvoc            integer,                     -- 수술실 가용 병상
    hvcc            integer,                     -- 신경외과 중환자실 병상
    hvccc           integer,                     -- 흉부외과 중환자실 병상
    hvicc           integer,                     -- 일반 중환자실 병상
    hvgc            integer,                     -- 입원실 병상
    hv1             text,                        -- 응급실 당직의 직통전화
                                                  -- (Hospital_inform/README.md "팀 확인 요청" 참고:
                                                  --  hv1은 "전문의 보유 여부"가 아니라 전화번호 필드)
    hv2             integer,                     -- 내과 중환자실 병상
    hv3             integer,                     -- 외과 중환자실 병상
    hv11            integer,                     -- 소아 관련 병상 (mapper.py: [추정] 필드)
    hvidate         timestamptz,                 -- 마지막 갱신 시각

    -- 중증질환 수용가능 여부 [플레이스홀더] — MKioskTy 코드별 의미가 아직
    -- 실측 전 가정 단계라(README "실측 전 가정" 표 참고), 코드->값 구조 그대로 보관
    severe_illness  jsonb default '{}'::jsonb,

    -- 장비 가용여부 [플레이스홀더] (CT/MRI/혈관조영기/인공호흡기 등)
    equipment       jsonb default '{}'::jsonb,

    -- hub의 HospitalInfo.specialties에 대응하는 진료과 목록 [플레이스홀더]
    -- (E-Gen에는 이 형태의 필드가 없어 info 쪽에서 별도로 관리·매핑해야 함)
    specialties     jsonb default '[]'::jsonb,

    source          text not null default 'rule',
    updated_at      timestamptz not null default now()
);

comment on table hospitals is
    'E-Gen API 대체용 임시 테이블. 병원명/주소/좌표는 실제 서울 권역응급의료센터 '
    '기준, 병상·장비·중증질환 수용여부는 실시간 API 연동 전까지의 플레이스홀더.';

-- 실제 지정된 서울 권역응급의료센터 7곳
-- (출처: 나무위키 "권역응급의료센터" 항목, 각 병원 공식 홈페이지 — 2026-08 기준)
-- 위경도는 대략적인 근사치이며, 실사용 전 정확한 좌표로 재검증이 필요하다.

-- severe_illness의 키(MKioskTy1/2/3)는 mapper.py의 MKIOSK_TO_CAPABILITY와
-- 정확히 맞춰야 한다: MKioskTy1=재관류(심근경색), MKioskTy2=재관류(뇌경색),
-- MKioskTy3=뇌출혈 수술. 값은 E-Gen 실제 규약(clean_flag() 참고)대로 "Y"/"N"
-- 문자열이며, 아래 배정은 전부 [플레이스홀더]다.

insert into hospitals
    (hpid, duty_name, duty_addr, wgs84_lat, wgs84_lon, hvec, hvoc, hvcc, hvccc, hvicc, hvgc,
     hv1, hv2, hv3, hv11, hvidate, severe_illness, equipment, specialties, source)
values
    ('S0000001', '서울대학교병원', '서울특별시 종로구 대학로 101 (연건동)',
     37.5799, 127.0033,
     5, 2, 1, 1, 3, 10, '02-2072-2802', 2, 2, 2, now(),
     '{"MKioskTy1": "Y", "MKioskTy2": "Y", "MKioskTy3": "Y"}'::jsonb,
     '{"ct": true, "mri": true, "angio": true, "ventilator": true}'::jsonb,
     '[{"department": "신경외과", "doctorCount": 4, "recentProcedureTags": []},
       {"department": "흉부외과", "doctorCount": 3, "recentProcedureTags": []}]'::jsonb,
     'rule'),

    ('S0000002', '고려대학교안암병원', '서울특별시 성북구 고려대로 73 (안암동)',
     37.5863, 127.0257,
     4, 2, 1, 1, 2, 8, '02-920-5911', 1, 1, 1, now(),
     '{"MKioskTy1": "Y", "MKioskTy2": "N", "MKioskTy3": "Y"}'::jsonb,
     '{"ct": true, "mri": true, "angio": true, "ventilator": true}'::jsonb,
     '[{"department": "외상외과", "doctorCount": 2, "recentProcedureTags": []},
       {"department": "신경외과", "doctorCount": 3, "recentProcedureTags": []}]'::jsonb,
     'rule'),

    ('S0000003', '서울의료원', '서울특별시 중랑구 신내로 156 (신내동)',
     37.6075, 127.0926,
     6, 1, 1, 0, 2, 12, '02-2276-7000', 1, 1, 1, now(),
     '{"MKioskTy1": "N", "MKioskTy2": "N", "MKioskTy3": "N"}'::jsonb,
     '{"ct": true, "mri": false, "angio": false, "ventilator": true}'::jsonb,
     '[{"department": "응급의학과", "doctorCount": 5, "recentProcedureTags": []}]'::jsonb,
     'rule'),

    ('S0000004', '고려대학교구로병원', '서울특별시 구로구 구로동로 148 (구로동)',
     37.4925, 126.8843,
     3, 1, 1, 1, 2, 9, '02-2626-1100', 1, 1, 1, now(),
     '{"MKioskTy1": "Y", "MKioskTy2": "Y", "MKioskTy3": "N"}'::jsonb,
     '{"ct": true, "mri": true, "angio": true, "ventilator": true}'::jsonb,
     '[{"department": "흉부외과", "doctorCount": 2, "recentProcedureTags": []},
       {"department": "정형외과", "doctorCount": 3, "recentProcedureTags": []}]'::jsonb,
     'rule'),

    ('S0000005', '이화여자대학교목동병원', '서울특별시 양천구 안양천로 1071 (목동)',
     37.5362, 126.8756,
     2, 1, 0, 0, 1, 6, '02-2650-5114', 0, 1, 3, now(),
     '{"MKioskTy1": "N", "MKioskTy2": "N", "MKioskTy3": "N"}'::jsonb,
     '{"ct": true, "mri": true, "angio": false, "ventilator": true}'::jsonb,
     '[{"department": "산부인과", "doctorCount": 4, "recentProcedureTags": []}]'::jsonb,
     'rule'),

    ('S0000006', '한양대학교병원', '서울특별시 성동구 왕십리로 222-1 (사근동)',
     37.5573, 127.0431,
     4, 2, 1, 1, 2, 8, '02-2290-8000', 1, 1, 1, now(),
     '{"MKioskTy1": "Y", "MKioskTy2": "N", "MKioskTy3": "N"}'::jsonb,
     '{"ct": true, "mri": true, "angio": true, "ventilator": true}'::jsonb,
     '[{"department": "외상외과", "doctorCount": 2, "recentProcedureTags": []}]'::jsonb,
     'rule'),

    ('S0000007', '강동경희대학교병원', '서울특별시 강동구 동남로 892 (상일동)',
     37.5535, 127.1638,
     3, 1, 1, 0, 1, 7, '02-440-6000', 1, 0, 1, now(),
     '{"MKioskTy1": "N", "MKioskTy2": "Y", "MKioskTy3": "Y"}'::jsonb,
     '{"ct": true, "mri": true, "angio": false, "ventilator": true}'::jsonb,
     '[{"department": "신경외과", "doctorCount": 2, "recentProcedureTags": []}]'::jsonb,
     'rule')

on conflict (hpid) do nothing;
