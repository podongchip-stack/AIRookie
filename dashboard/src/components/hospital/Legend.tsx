import { css } from "styled-system/css";

const itemStyle = css({ display: "inline-flex", alignItems: "center", gap: "1.5" });
const dotAiStyle = css({ width: "2.5", height: "2.5", borderRadius: "sm", backgroundColor: "navy" });
const dotRuleStyle = css({ width: "2.5", height: "2.5", borderRadius: "sm", backgroundColor: "lineStrong" });
const dotHumanStyle = css({ width: "2.5", height: "2.5", borderRadius: "sm", backgroundColor: "brand" });

export function Legend() {
  return (
    <div
      className={css({
        display: "flex",
        alignItems: "center",
        gap: "3.5",
        flexWrap: "wrap",
        fontSize: "xs",
        color: "ink",
        paddingX: "1",
        paddingBottom: "3",
      })}
    >
      <span className={itemStyle}>
        <span className={dotAiStyle} />
        AI 처리
      </span>
      <span className={itemStyle}>
        <span className={dotRuleStyle} />
        규칙 기반 · 센서 · API
      </span>
      <span className={itemStyle}>
        <span className={dotHumanStyle} />
        의료진 판단 영역
      </span>
    </div>
  );
}
