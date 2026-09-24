import { defineConfig, defineKeyframes, defineRecipe } from "@pandacss/dev";

// 병원 대시보드 시안(HTML 목업) 팔레트를 그대로 raw 토큰으로 옮긴다.
const brandColors = {
  bg: { value: "#F4F7FA" },
  surface: { value: "#FFFFFF" },
  surfaceSub: { value: "#F8FAFC" },
  line: { value: "#E2E8EF" },
  lineStrong: { value: "#CBD5E1" },
  ink: { value: "#16222E" },
  ink2: { value: "#55697C" },
  ink3: { value: "#66778A" },
  navy: { value: "#1E5FA8" },
  navySoft: { value: "#EAF2FB" },
  mint: { value: "#0E9F6E" },
  mintSoft: { value: "#E6F6F0" },
  coral: { value: "#D93F35" },
  coralSoft: { value: "#FDECEA" },
  amberBrand: { value: "#B87514" },
  amberSoft: { value: "#FCF3E3" },
} as const;

const keyframes = defineKeyframes({
  beat: {
    "0%, 100%": { opacity: 1, transform: "scale(1)" },
    "50%": { opacity: 0.35, transform: "scale(.8)" },
  },
  sweep: {
    from: { strokeDashoffset: 620 },
    to: { strokeDashoffset: 0 },
  },
  nudge: {
    "0%, 100%": { transform: "translateX(0)" },
    "50%": { transform: "translateX(7px)" },
  },
});

// 배지류는 variant 값이 런타임 prop으로 들어오므로, 동적 토큰 문자열 대신
// recipe로 정의해 모든 조합의 CSS가 빌드 타임에 정적으로 생성되도록 한다.
const badgeBase = {
  display: "inline-flex",
  alignItems: "center",
  borderRadius: "full",
  paddingX: "2",
  paddingY: "1",
  fontSize: "xs",
  fontWeight: "medium",
} as const;

const sourceBadgeRecipe = defineRecipe({
  className: "sourceBadge",
  base: {
    ...badgeBase,
    gap: "1.5",
    _before: {
      content: '""',
      width: "1.5",
      height: "1.5",
      borderRadius: "sm",
      backgroundColor: "currentcolor",
    },
  },
  variants: {
    source: {
      ai: { color: "source.ai", backgroundColor: "source.ai.subtle" },
      rule: {
        color: "source.rule",
        backgroundColor: "source.rule.subtle",
        borderWidth: "1px",
        borderColor: "line",
      },
    },
  },
});

const severityBadgeRecipe = defineRecipe({
  className: "severityBadge",
  base: { ...badgeBase, fontSize: "sm", fontWeight: "bold" },
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
      keyframes,
      tokens: {
        colors: brandColors,
        radii: {
          chip: { value: "6px" },
          field: { value: "10px" },
          panel: { value: "14px" },
        },
      },
      recipes: {
        sourceBadge: sourceBadgeRecipe,
        severityBadge: severityBadgeRecipe,
        hospitalStatusBadge: hospitalStatusBadgeRecipe,
      },
      semanticTokens: {
        colors: {
          // 브랜드 (골든링크 강조색 — 이송 승인, 의료진 판단 영역 등 핵심 액션)
          brand: {
            DEFAULT: { value: "{colors.amberBrand}" },
            emphasis: { value: "#9C6110" },
          },
          // 정보 출처 구분: AI 처리 vs 규칙 기반 (CLAUDE.md 필수 요구사항)
          source: {
            ai: { value: "{colors.navy}" },
            "ai.subtle": { value: "{colors.navySoft}" },
            rule: { value: "{colors.ink2}" },
            "rule.subtle": { value: "{colors.surfaceSub}" },
          },
          // 중증도 (severity_tag: high | medium | low)
          severity: {
            high: { value: "{colors.coral}" },
            "high.subtle": { value: "{colors.coralSoft}" },
            medium: { value: "{colors.amberBrand}" },
            "medium.subtle": { value: "{colors.amberSoft}" },
            low: { value: "{colors.mint}" },
            "low.subtle": { value: "{colors.mintSoft}" },
          },
          // 병원 응답 상태 (pending | approved | rejected | confirmed)
          hospitalStatus: {
            pending: { value: "{colors.ink3}" },
            "pending.subtle": { value: "{colors.surfaceSub}" },
            approved: { value: "{colors.navy}" },
            "approved.subtle": { value: "{colors.navySoft}" },
            rejected: { value: "{colors.coral}" },
            "rejected.subtle": { value: "{colors.coralSoft}" },
            confirmed: { value: "{colors.mint}" },
            "confirmed.subtle": { value: "{colors.mintSoft}" },
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
