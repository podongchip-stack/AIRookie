import { css } from "styled-system/css";
import { Panel } from "@/components/layout/Panel";
import { Tag } from "@/components/hospital/Tag";
import type { CallSummaryMessage, TranscriptTurn } from "@/types/dashboard";

function TurnItem({ turn }: { turn: TranscriptTurn }) {
  return (
    <div
      className={css({
        paddingY: "2",
        borderBottomWidth: "1px",
        borderStyle: "dashed",
        borderColor: "line",
        _last: { borderBottomWidth: 0 },
      })}
    >
      <div
        className={css({
          fontSize: "xs",
          fontWeight: "semibold",
          color: "navy",
          marginBottom: "0.5",
        })}
      >
        {turn.speaker}
        <span
          className={css({
            color: "ink",
            fontWeight: "normal",
            marginLeft: "1.5",
          })}
        >
          {turn.timestamp}
        </span>
      </div>
      <p
        className={css({
          fontSize: "sm",
          color: "ink",
        })}
      >
        {turn.text}
        {turn.excludedFromSummary && (
          <span
            className={css({
              fontSize: "2xs",
              color: "ink",
              backgroundColor: "surfaceSub",
              borderWidth: "1px",
              borderColor: "line",
              paddingX: "1.5",
              borderRadius: "full",
              marginLeft: "1.5",
            })}
          >
            요약 제외
          </span>
        )}
      </p>
    </div>
  );
}

export function RawTranscriptPanel({ data }: { data: CallSummaryMessage | null }) {
  if (!data) {
    return (
      <Panel title="첫 병원 통화 · 원본" badge={<Tag source="ai">Whisper STT</Tag>}>
        <p className={css({ color: "ink", fontSize: "sm" })}>수신 대기 중...</p>
      </Panel>
    );
  }

  const turns = data.transcript.turns;

  return (
    <Panel title="첫 병원 통화 · 원본" badge={<Tag source="ai">Whisper STT</Tag>}>
      {turns && turns.length > 0 ? (
        turns.map((turn) => <TurnItem key={`${turn.speaker}-${turn.timestamp}`} turn={turn} />)
      ) : (
        <p className={css({ fontSize: "sm", color: "ink" })}>{data.transcript.raw_text}</p>
      )}
    </Panel>
  );
}
