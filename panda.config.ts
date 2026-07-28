import { defineConfig, defineRecipe } from "@pandacss/dev";

// 배지류는 variant 값이 런타임 prop으로 들어오므로, 동적 토큰 문자열 대신
// recipe로 정의해 모든 조합의 CSS가 빌드 타임에 정적으로 생성되도록 한다.
const badgeBase = {
  display: "inline-flex",
  alignItems: "center",
  borderRadius: "full",
  paddingX: "2.5",
  paddingY: "0.5",
  fontSize: "xs",
  fontWeight: "medium",
} as const;

const sourceBadgeRecipe = defineRecipe({
  className: "sourceBadge",
  base: badgeBase,
  variants: {
    source: {
      ai: { color: "source.ai", backgroundColor: "source.ai.subtle" },
      rule: { color: "source.rule", backgroundColor: "source.rule.subtle" },
    },
  },
});

const severityBadgeRecipe = defineRecipe({
  className: "severityBadge",
  base: { ...badgeBase, fontWeight: "bold" },
  variants: {
    severity: {
      high: { color: "severity.high", backgroundColor: "severity.high.subtle" },
      medium: {
        color: "severity.medium",
        backgroundColor: "severity.medium.subtle",
      },
      low: { color: "severity.low", backgroundColor: "severity.low.subtle" },
    },
  },
});

const hospitalStatusBadgeRecipe = defineRecipe({
  className: "hospitalStatusBadge",
  base: badgeBase,
  variants: {
    status: {
      pending: {
        color: "hospitalStatus.pending",
        backgroundColor: "hospitalStatus.pending.subtle",
      },
      approved: {
        color: "hospitalStatus.approved",
        backgroundColor: "hospitalStatus.approved.subtle",
      },
      rejected: {
        color: "hospitalStatus.rejected",
        backgroundColor: "hospitalStatus.rejected.subtle",
      },
      confirmed: {
        color: "hospitalStatus.confirmed",
        backgroundColor: "hospitalStatus.confirmed.subtle",
      },
    },
  },
});

export default defineConfig({
  // Whether to use css reset
  preflight: true,

  // Where to look for your css declarations
  include: ["./src/**/*.{js,jsx,ts,tsx}", "./pages/**/*.{js,jsx,ts,tsx}"],

  // Files to exclude
  exclude: [],

  // Useful for theme customization
  theme: {
    extend: {
      recipes: {
        sourceBadge: sourceBadgeRecipe,
        severityBadge: severityBadgeRecipe,
        hospitalStatusBadge: hospitalStatusBadgeRecipe,
      },
      semanticTokens: {
        colors: {
          // 브랜드 (골든링크 강조색 — 이송 승인 등 핵심 액션)
          brand: {
            DEFAULT: { value: "{colors.amber.500}" },
            emphasis: { value: "{colors.amber.600}" },
          },
          // 정보 출처 구분: AI 처리 vs 규칙 기반 (CLAUDE.md 필수 요구사항)
          source: {
            ai: { value: "{colors.violet.600}" },
            "ai.subtle": { value: "{colors.violet.100}" },
            rule: { value: "{colors.blue.600}" },
            "rule.subtle": { value: "{colors.blue.100}" },
          },
          // 중증도 (severity_tag: high | medium | low)
          severity: {
            high: { value: "{colors.red.600}" },
            "high.subtle": { value: "{colors.red.100}" },
            medium: { value: "{colors.orange.600}" },
            "medium.subtle": { value: "{colors.orange.100}" },
            low: { value: "{colors.green.600}" },
            "low.subtle": { value: "{colors.green.100}" },
          },
          // 병원 응답 상태 (pending | approved | rejected | confirmed)
          hospitalStatus: {
            pending: { value: "{colors.gray.500}" },
            "pending.subtle": { value: "{colors.gray.100}" },
            approved: { value: "{colors.blue.600}" },
            "approved.subtle": { value: "{colors.blue.100}" },
            rejected: { value: "{colors.red.600}" },
            "rejected.subtle": { value: "{colors.red.100}" },
            confirmed: { value: "{colors.green.600}" },
            "confirmed.subtle": { value: "{colors.green.100}" },
          },
        },
      },
    },
  },

  // 배지 recipe는 variant 값이 런타임 prop(변수)으로 들어오기 때문에
  // 정적 분석만으로는 사용되는 조합을 추론하지 못한다. 모든 variant CSS를 강제 생성한다.
  staticCss: {
    recipes: {
      sourceBadge: ["*"],
      severityBadge: ["*"],
      hospitalStatusBadge: ["*"],
    },
  },

  // The output directory for your css system
  outdir: "styled-system",
});
