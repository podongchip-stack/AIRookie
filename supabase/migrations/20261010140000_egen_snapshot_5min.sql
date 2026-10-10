-- E-Gen 스냅샷 수집 주기 20분 → 5분 (2026-10-10)
--
-- 왜: 1분 간격 탐침(2026-10-07·10-10)으로 E-Gen 공개 API가 전국 값을 정확히 5분 묶음으로 내보내고,
-- 응급실 병상(hvec)은 그 묶음마다 전국 약 29%(416곳 중 ~120곳)가 환자 1명 단위(±1 83%)로 바뀌는 것을
-- 확인했다. 20분 폴링은 그 사이 변화의 절반 이상을 놓치고(20분당 변화 52% = 5분 변화가 누적된 값),
-- 신뢰도 모델의 라벨(값 변화 시각)·유령 판정·재채점 해상도가 전부 20분 바닥에 묶였다.
-- 비용: 수집 호출 하루 약 290회 → 약 860회. info 5분 재조회(약 1,150회)와 합쳐도 일일 한도 80,000회의 3% 안.
--
-- raw/<날짜>/<HHMMSS>_<op>_p<page>.xml.gz 레이아웃과 snapshot_cloud.py의 (ts, operation) 병합은
-- 주기와 무관하므로 소비 코드 변경 없음.

select cron.unschedule('egen-snapshot-20min');

select cron.schedule(
  'egen-snapshot-5min',
  '*/5 * * * *',
  $$
  select net.http_post(
    url := 'https://znmkosobxtqfgabrjjzg.supabase.co/functions/v1/egen-snapshot',
    headers := '{"Content-Type": "application/json"}'::jsonb,
    body := '{}'::jsonb,
    timeout_milliseconds := 50000
  );
  $$
);
