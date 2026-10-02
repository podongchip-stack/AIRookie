"use client";

import { FrameModalButton } from "@/components/ui/FrameModalButton";

// lidar3d(feature/lidar3d)의 3D 현장 뷰어 주소. 뷰어는 별도 서버(lidar3d FastAPI,
// 포트 8000)가 띄우는 독립 웹페이지라 dashboard는 주소만 알고 iframe으로 띄운다 —
// dashboard가 hub와만 통신한다는 원칙은 "데이터"에 대한 것이고, 이건 사람이 보는
// 별도 화면을 그대로 여는 것이라 hub를 거치지 않는다(3D 파일은 세션당 100MB대라
// 애초에 hub 경유가 불가능하다 — lidar3d 설계 문서 "전송 구조" 절).
//
// 값 예: https://lidar.rookie-goldenlink.xyz/viewer/?token=<LIDAR_TOKEN>
// 뷰어의 데이터 요청은 토큰이 필요해서 주소에 ?token=을 붙여 둔다. NEXT_PUBLIC_*은
// 빌드 결과에 그대로 박히므로 대시보드를 열 수 있는 사람은 이 토큰도 볼 수 있다 —
// 공개 운영 전에는 도메인 앞에 로그인(Cloudflare Access 등)을 두는 것을 전제로 한다.
// 미설정이면 버튼 자체를 숨긴다(3D가 없어도 매칭·승인은 정상 동작해야 하므로).
const VIEWER_URL = process.env.NEXT_PUBLIC_LIDAR_VIEWER_URL;

export function Viewer3DButton() {
  if (!VIEWER_URL) return null;
  return <FrameModalButton label="3D 현장 뷰어" badge="LiDAR 촬영 · 사람 인식은 AI" url={VIEWER_URL} />;
}
