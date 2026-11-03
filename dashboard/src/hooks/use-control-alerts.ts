"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Incident } from "@/lib/control-map";
import { HUB_DOWN_ALERT, deriveAlerts, newTracker, type ControlAlert } from "@/lib/control-alerts";

// 연결된 뒤 이 시간 동안은 이미 진행 중이던 사건을 따라잡는 시간이라 알리지 않고 '이미 본 것'으로 친다
const BASELINE_MS = 3_000;

export interface ControlAlertsView {
  /** 확인하지 않은 알림 — 긴급 → 주의 → 시스템 순 */
  alerts: ControlAlert[];
  freshIds: ReadonlySet<string>;
  ack: (keys: string[]) => void;
  /** 처리 중으로 표시한 사건 — 이 화면 안에서만 유지된다(hub 공유 전, 담당자 구분 없음) */
  handling: ReadonlySet<string>;
  startHandling: (caseId: string, keys: string[]) => void;
  finishHandling: (caseId: string) => void;
  ackAll: () => void;
}

/**
 * 관제 알림. 1초마다 사건 요약에서 규칙(lib/control-alerts)을 평가한다. 알림음은 2026-11-01에 없앴다(화면 카드와 탭 제목 깜빡임만).
 * 같은 상황은 한 번만 알리고(key), 확인하면 그 상황이 끝났다가 다시 생길 때까지 조용하다.
 */
export function useControlAlerts(incidents: Incident[], connected: boolean, assignOpened: Record<string, string> = {}): ControlAlertsView {
  const [active, setActive] = useState<ControlAlert[]>([]);
  const [acked, setAcked] = useState<ReadonlySet<string>>(new Set());
  // 방금 접수된 사건(목록에서 NEW로 깜빡이는 것) — 알림 카드를 확인(닫기)해도 NEW_CASE_MS 동안은 목록 표시가 남는다.
  // 접속 직후 따라잡는 사건은 새 사건이 아니라 제외한다.
  const [handling, setHandling] = useState<ReadonlySet<string>>(new Set());
  const [freshIds, setFreshIds] = useState<ReadonlySet<string>>(new Set());
  const silentRef = useRef<Set<string>>(new Set());

  const inputRef = useRef({ incidents, connected, assignOpened });
  useEffect(() => {
    inputRef.current = { incidents, connected, assignOpened };
  }, [incidents, connected, assignOpened]);

  const trackerRef = useRef(newTracker());
  const prevKeysRef = useRef<Set<string>>(new Set());
  const ackedRef = useRef<Set<string>>(new Set());
  const liveSinceRef = useRef<number | null>(null);
  const wasLiveRef = useRef(false);
  const baselineRef = useRef(false);

  const syncAcked = useCallback((next: Set<string>) => {
    ackedRef.current = next;
    setAcked(next);
  }, []);

  useEffect(() => {
    const tick = () => {
      const now = Date.now();
      const { incidents: incs, connected: live, assignOpened: opened } = inputRef.current;
      if (live) {
        wasLiveRef.current = true;
        liveSinceRef.current ??= now;
      } else {
        liveSinceRef.current = null;
        baselineRef.current = false;
      }
      const list = live ? deriveAlerts(incs, now, trackerRef.current, opened) : [];
      if (!live && wasLiveRef.current) list.push(HUB_DOWN_ALERT);
      const keys = new Set(list.map((a) => a.key));

      if (!baselineRef.current && live && liveSinceRef.current != null && now - liveSinceRef.current >= BASELINE_MS) baselineRef.current = true;
      let nextAcked = ackedRef.current;
      if (!baselineRef.current && live) {
        // 따라잡는 중 — 지금 보이는 상황은 이미 본 것으로
        nextAcked = new Set([...nextAcked, ...keys]);
        keys.forEach((k) => silentRef.current.add(k));
      }
      // 끝난 상황은 확인 기록에서 지운다 — 같은 상황이 다시 생기면 새로 알린다
      const pruned = new Set([...nextAcked].filter((k) => keys.has(k)));
      if (pruned.size !== ackedRef.current.size || [...pruned].some((k) => !ackedRef.current.has(k))) syncAcked(pruned);
      prevKeysRef.current = keys;
      silentRef.current = new Set([...silentRef.current].filter((k) => keys.has(k)));
      const fresh = list.filter((a) => a.key.endsWith(":new") && a.caseId && !silentRef.current.has(a.key)).map((a) => a.caseId as string);
      setFreshIds((prev) => (prev.size === fresh.length && fresh.every((id) => prev.has(id)) ? prev : new Set(fresh)));
      setActive(list);
      // 끝난 사건의 처리 표시는 지운다
      const liveIds = new Set(incs.map((i) => i.caseId));
      setHandling((prev) => (prev.size && [...prev].some((id) => !liveIds.has(id)) ? new Set([...prev].filter((id) => liveIds.has(id))) : prev));
    };
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, [syncAcked]);

  const ack = useCallback((keys: string[]) => syncAcked(new Set([...ackedRef.current, ...keys])), [syncAcked]);
  const ackAll = useCallback(() => syncAcked(new Set([...ackedRef.current, ...prevKeysRef.current])), [syncAcked]);

  const startHandling = useCallback((caseId: string, keys: string[]) => {
    syncAcked(new Set([...ackedRef.current, ...keys]));
    setHandling((prev) => new Set(prev).add(caseId));
  }, [syncAcked]);
  const finishHandling = useCallback((caseId: string) => setHandling((prev) => new Set([...prev].filter((id) => id !== caseId))), []);

  return { handling, startHandling, finishHandling, alerts: active.filter((a) => !acked.has(a.key)), freshIds, ack, ackAll };
}
