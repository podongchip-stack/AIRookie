# 보호자 사이트 배포

공개 웹사이트는 **정적 파일 + HTTPS 주소**다. 우리가 만든 `index.html` 하나가
그대로 그 사이트이고, 남은 건 어디에 올리느냐뿐이다.

다만 우리만의 제약이 하나 있다 — **정적 호스팅은 파이썬 루프를 못 돌린다.**
E-Gen을 5분마다 읽고 신뢰도 모델을 돌리는 건 어딘가에서 상시로 돌아야 한다.
그래서 "파일을 놓는 곳"과 "값을 만드는 곳"을 나눈다.

```
  Cloudflare Pages / Vercel        index.html      무료 · HTTPS · CDN
            │ fetch(DATA_URL)
            ▼
  Supabase Storage (공개 읽기)      data.json       5분마다 덮어씀
            ▲ 업로드
  serve_data.py (어딘가 상시)       E-Gen 폴링 + infosurv
```

Supabase는 스냅샷 수집에 **이미 쓰고 있어서** 추가 비용이 없다. 버킷
`egen-snapshots`가 공개 읽기이고 `Access-Control-Allow-Origin: *`이라
어느 도메인에서 열어도 그대로 받아진다(실측 확인).

---

## 1. 값을 만드는 쪽 — 상시 프로세스

```bash
conda activate dev
cd poc
python serve_data.py --interval 300 --upload
```

- 콜드 스타트에 스냅샷을 한 번 재생한다(실측 27초). 그 뒤로는 5분마다 E-Gen 2콜
- `data.json`을 로컬에 쓰고 Supabase Storage `peds/data.json`에 덮어쓴다
- 하루 약 600콜 — 일일 한도 80,000의 0.8%
- 한 주기가 실패해도 멈추지 않는다

⚠ 처음 한 번은 스냅샷이 있어야 한다:
`cd ../info/Hospital_inform/info && python snapshot_cloud.py --sync`

**어디서 돌리나** — 늘 켜져 있는 곳이면 된다. 지금은 개발 장비. 실제로는 작은
인스턴스(Fly.io·Render·VM) 하나면 충분하다. 메모리는 엔진 적재분이 가장 크다.

## 2. 파일을 놓는 쪽 — 정적 호스팅

```bash
# 공개 URL을 가리키도록 빌드
PEDS_DATA_URL="https://<프로젝트>.supabase.co/storage/v1/object/public/egen-snapshots/peds/data.json" \
  python build_peds_finder.py

cp out/peds_finder.html <배포폴더>/index.html
```

`PEDS_DATA_URL`을 주지 않으면 같은 폴더의 `data.json`을 본다(로컬 확인용).
HTML에 값이 통째로 박혀 있어서 **네트워크가 막혀도 화면은 뜬다** — 그때는 빌드
시점 값이고, 화면 상단에 그 시각이 적힌다.

호스팅은 아무 데나 — Cloudflare Pages·Vercel·Netlify·GitHub Pages 전부 무료에
HTTPS가 기본이다. 폴더 하나 올리면 끝이다.

## 3. 주소

도메인은 **당장은 없어도 된다.** 호스팅이 주는 기본 주소(`*.pages.dev`,
`*.vercel.app`)로 충분하고, 사람들에게 뿌리기 시작할 때 사면 된다(연 1~2만 원대).

⚠ **HTTPS가 아니면 "내 주변" 기능이 통째로 죽는다** — 브라우저 위치 권한은
secure context에서만 열린다. 위 호스팅은 전부 기본 HTTPS라 신경 쓸 일은 없지만,
직접 서버를 세운다면 반드시 인증서를 붙일 것.

---

## 갱신이 멈추면 어떻게 되나

화면은 계속 뜨고, **마지막으로 받은 시각이 상단에 그대로 적힌다.** 신뢰도는
시간이 갈수록 떨어지는 값이라 모델이 알아서 낮은 확률을 내놓는다 — 조용히 틀린
값을 보여주지는 않는다. 다만 혼잡도·공지는 옛것이 되므로 오래 멈추면 안 된다.

열어 둔 탭도 **5분마다 스스로 다시 가져온다.** 새벽에 띄워 놓고 한참 보는
화면이라 숫자가 굳어 있으면 안 된다.

## 올리면 안 되는 것

`poc/data/*.json`과 `out/*`은 공개 데이터라 올려도 되지만, `.env`(E-Gen·심평원
서비스키, Supabase 서비스 키)는 **절대 배포 폴더에 들어가면 안 된다.** 업로드는
상시 프로세스 쪽에서만 하고, 브라우저는 공개 읽기 URL만 본다.
