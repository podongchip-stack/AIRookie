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
  soundOn: boolean;
  toggleSound: () => void;
  ack: (keys: string[]) => void;
  /** 처리 중으로 표시한 사건 — 이 화면 안에서만 유지된다(hub 공유 전, 담당자 구분 없음) */
  handling: ReadonlySet<string>;
  startHandling: (caseId: string, keys: string[]) => void;
  finishHandling: (caseId: string) => void;
  ackAll: () => void;
}

/**
 * 관제 알림. 1초마다 사건 요약에서 규칙(lib/control-alerts)을 평가해, 새로 생긴 긴급 알림만 소리를 낸다(시연 사건은 소리 없음).
 * 같은 상황은 한 번만 알리고(key), 확인하면 그 상황이 끝났다가 다시 생길 때까지 조용하다.
 */
export function useControlAlerts(incidents: Incident[], connected: boolean): ControlAlertsView {
  const [active, setActive] = useState<ControlAlert[]>([]);
  const [acked, setAcked] = useState<ReadonlySet<string>>(new Set());
  const [soundOn, setSoundOn] = useState(false);
  // 방금 접수된 사건(목록에서 NEW로 깜빡이는 것) — 알림 카드를 확인(닫기)해도 NEW_CASE_MS 동안은 목록 표시가 남는다.
  // 접속 직후 따라잡는 사건은 새 사건이 아니라 제외한다.
  const [handling, setHandling] = useState<ReadonlySet<string>>(new Set());
  const [freshIds, setFreshIds] = useState<ReadonlySet<string>>(new Set());
  const silentRef = useRef<Set<string>>(new Set());

  const inputRef = useRef({ incidents, connected, soundOn });
  useEffect(() => {
    inputRef.current = { incidents, connected, soundOn };
  }, [incidents, connected, soundOn]);

  const trackerRef = useRef(newTracker());
  const prevKeysRef = useRef<Set<string>>(new Set());
  const ackedRef = useRef<Set<string>>(new Set());
  const liveSinceRef = useRef<number | null>(null);
  const wasLiveRef = useRef(false);
  const baselineRef = useRef(false);
  const audioRef = useRef<AudioContext | null>(null);

  const syncAcked = useCallback((next: Set<string>) => {
    ackedRef.current = next;
    setAcked(next);
  }, []);

  useEffect(() => {
    const tick = () => {
      const now = Date.now();
      const { incidents: incs, connected: live, soundOn: sound } = inputRef.current;
      if (live) {
        wasLiveRef.current = true;
        liveSinceRef.current ??= now;
      } else {
        liveSinceRef.current = null;
        baselineRef.current = false;
      }
      const list = live ? deriveAlerts(incs, now, trackerRef.current) : [];
      if (!live && wasLiveRef.current) list.push(HUB_DOWN_ALERT);
      const keys = new Set(list.map((a) => a.key));

      if (!baselineRef.current && live && liveSinceRef.current != null && now - liveSinceRef.current >= BASELINE_MS) baselineRef.current = true;
      let nextAcked = ackedRef.current;
      if (!baselineRef.current && live) {
        // 따라잡는 중 — 지금 보이는 상황은 이미 본 것으로
        nextAcked = new Set([...nextAcked, ...keys]);
        keys.forEach((k) => silentRef.current.add(k));
      } else {
        const fresh = list.filter((a) => !prevKeysRef.current.has(a.key) && !nextAcked.has(a.key));
        // 긴급은 두 번, 그냥 새 사건은 한 번(시연 사건은 소리 없음)
        if (sound && fresh.some((a) => a.level === "urgent" && !a.fake)) beep(audioRef.current, 2);
        else if (sound && fresh.some((a) => a.level === "info" && !a.fake)) beep(audioRef.current, 1);
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

  const toggleSound = useCallback(() => {
    // 소리는 사용자가 한 번 눌러야 켤 수 있다(브라우저 정책) — 켤 때 오디오를 만들고 확인음을 한 번 낸다
    setSoundOn((on) => {
      if (!on) {
        audioRef.current ??= new AudioContext();
        beep(audioRef.current);
      }
      return !on;
    });
  }, []);
  const ack = useCallback((keys: string[]) => syncAcked(new Set([...ackedRef.current, ...keys])), [syncAcked]);
  const ackAll = useCallback(() => syncAcked(new Set([...ackedRef.current, ...prevKeysRef.current])), [syncAcked]);

  const startHandling = useCallback((caseId: string, keys: string[]) => {
    syncAcked(new Set([...ackedRef.current, ...keys]));
    setHandling((prev) => new Set(prev).add(caseId));
  }, [syncAcked]);
  const finishHandling = useCallback((caseId: string) => setHandling((prev) => new Set([...prev].filter((id) => id !== caseId))), []);

  return { handling, startHandling, finishHandling, alerts: active.filter((a) => !acked.has(a.key)), freshIds, soundOn, toggleSound, ack, ackAll };
}

function beep(ctx: AudioContext | null, times = 2) {
  if (!ctx) return;
  void ctx.resume();
  [0, 0.28].slice(0, times).forEach((offset) => {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.value = 880;
    gain.gain.setValueAtTime(0.0001, ctx.currentTime + offset);
    gain.gain.exponentialRampToValueAtTime(0.25, ctx.currentTime + offset + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + offset + 0.2);
    osc.connect(gain).connect(ctx.destination);
    osc.start(ctx.currentTime + offset);
    osc.stop(ctx.currentTime + offset + 0.22);
  });
}
