-- E-Gen 클라우드 수집기 설정 (2026-10-04, 프로젝트 goldenlink-egen)
-- 버킷 + 공개 목록 정책 + 20분 cron. 함수는 --no-verify-jwt로 배포돼 호출에 키가 필요 없다.

insert into storage.buckets (id, name, public)
values ('egen-snapshots', 'egen-snapshots', true)
on conflict (id) do nothing;

-- 공개 버킷이어도 목록 조회(list)는 RLS를 타므로 anon에 SELECT만 연다.
do $$ begin
  create policy "egen-snapshots 공개 목록"
  on storage.objects for select
  to anon, authenticated
  using (bucket_id = 'egen-snapshots');
exception when duplicate_object then null; end $$;

create extension if not exists pg_cron;
create extension if not exists pg_net;

select cron.schedule(
  'egen-snapshot-20min',
  '*/20 * * * *',
  $$
  select net.http_post(
    url := 'https://znmkosobxtqfgabrjjzg.supabase.co/functions/v1/egen-snapshot',
    headers := '{"Content-Type": "application/json"}'::jsonb,
    body := '{}'::jsonb,
    timeout_milliseconds := 50000
  );
  $$
);
