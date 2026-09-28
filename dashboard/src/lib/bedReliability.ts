// 병상 정보 신뢰도(bedReliability)의 실시간 감쇠 계산.
//
// hub는 매칭·재계산 시점의 authority/rArrive 스칼라와 함께 생존곡선의 파라미터
// (predictedSurvivalSec·bornAt·sigma)도 보내준다(2026-09-28, hub/schema.py
// BedReliabilityMatch). 파라미터가 있으면 dashboard가 다음 브로드캐스트를
// 기다리지 않고 초 단위로 확률을 직접 감쇠시켜 그릴 수 있다:
//
//   S(age) = 1 − Φ((ln age − ln m) / σ)   (log-normal AFT 생존곡선)
//
// 수식은 hub/bed_reliability.py(그리고 info의 infosurv 벤더링 사본)와 동일해야
// 한다 — Φ의 보생존은 erfc로 계산한다: norm.sf(x) = erfc(x/√2)/2.
// 파라미터가 없으면(구버전 hub) hub가 보낸 스칼라를 그대로 쓴다(감쇠 없이 정지).

import type { BedReliabilityMatch } from "@/types/dashboard";

// JS에는 erfc가 없어 Abramowitz & Stegun 7.1.26 근사(오차 < 1.5e-7)를 쓴다.
// 표시 단위가 1%p라 이 정밀도면 충분하고, hub의 정확값과 갈라질 일이 없다.
function erfc(x: number): number {
  const z = Math.abs(x);
  const t = 1 / (1 + 0.5 * z);
  const r =
    t *
    Math.exp(
      -z * z -
        1.26551223 +
        t *
          (1.00002368 +
            t *
              (0.37409196 +
                t *
                  (0.09678418 +
                    t *
                      (-0.18628806 +
                        t *
                          (0.27886807 +
                            t *
                              (-1.13520398 +
                                t *
                                  (1.48851587 +
                                    t * (-0.82215223 + t * 0.17087277)))))))),
    );
  return x >= 0 ? r : 2 - r;
}

function survival(predTSec: number, ageSec: number, sigma: number): number {
  if (ageSec <= 0) return 1;
  const z =
    (Math.log(Math.max(ageSec, 1e-9)) - Math.log(Math.max(predTSec, 1e-9))) /
    (Math.max(sigma, 1e-9) * Math.SQRT2);
  return Math.min(Math.max(0.5 * erfc(z), 0), 1);
}

export interface LiveBedReliability {
  // 지금(nowMs) 기준으로 감쇠시킨 확률. 파라미터가 없으면 hub 스칼라 그대로.
  authority: number;
  rArrive: number;
  // true면 초 단위로 흘러가는 값(파라미터 수신), false면 매칭 시점 정지값.
  live: boolean;
}

export function liveBedReliability(
  br: BedReliabilityMatch,
  nowMs: number,
): LiveBedReliability {
  if (br.predictedSurvivalSec == null || !br.bornAt) {
    return { authority: br.authority, rArrive: br.rArrive, live: false };
  }
  const bornMs = Date.parse(br.bornAt);
  if (Number.isNaN(bornMs)) {
    return { authority: br.authority, rArrive: br.rArrive, live: false };
  }
  const sigma = br.sigma ?? 1.0;
  const ageSec = Math.max((nowMs - bornMs) / 1000, 0);
  return {
    authority: survival(br.predictedSurvivalSec, ageSec, sigma),
    rArrive: survival(br.predictedSurvivalSec, ageSec + br.horizonSec, sigma),
    live: true,
  };
}

// 중증질환 신고 나이 표기: "3.2시간 전" / 1시간 미만은 "N분 전",
// ageIsMin(좌측검열)이면 "최소 " 접두 — 실제 신고는 더 오래됐을 수 있다는 뜻.
export function formatDeclarationAge(ageSec: number, ageIsMin: boolean): string {
  const prefix = ageIsMin ? "최소 " : "";
  if (ageSec < 3600) return `${prefix}${Math.max(Math.round(ageSec / 60), 1)}분 전`;
  return `${prefix}${(ageSec / 3600).toFixed(ageSec < 36000 ? 1 : 0)}시간 전`;
}
