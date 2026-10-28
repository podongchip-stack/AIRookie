"use client";

import { useEffect, useMemo, useState } from "react";
import type { CaseHistoryItem } from "@/types/dashboard";
import {
  ARCHIVE_MOCK, computeStats, fetchCaseArchive, filterCases, ymd,
  type CaseArchiveQuery, type CaseArchiveResponse, type CaseArchiveStats,
} from "@/lib/case-archive";

export interface CaseArchiveView {
  cases: CaseHistoryItem[];
  total: number;
  stats: CaseArchiveStats;
  loading: boolean;
  error: string | null;
}

/**
 * 지난 사건 목록·통계. 오늘 하루만 보면 hub가 이미 보내는 case_history(today)를 그대로 쓰고(조회 없이 지금 hub와 호환),
 * 이전 날짜가 들어가면 hub 사건 이력 조회(없으면 오류 문구, mock 모드면 가짜 데이터)를 부른다. 검색어는 입력이 멈춘 뒤 조회한다.
 */
export function useCaseArchive(query: CaseArchiveQuery, today: CaseHistoryItem[]): CaseArchiveView {
  const [q, setQ] = useState(query.q);
  useEffect(() => {
    const t = setTimeout(() => setQ(query.q), 300);
    return () => clearTimeout(t);
  }, [query.q]);

  const { from, to, result } = query;
  const todayOnly = !ARCHIVE_MOCK && from === to && from === ymd(new Date());
  // 응답에 어떤 조건으로 받은 것인지(key)를 같이 두면, 조건이 바뀐 직후엔 key가 달라 "불러오는 중"이 파생된다
  const key = `${from}|${to}|${q}|${result}`;
  const [done, setDone] = useState<{ key: string; data: CaseArchiveResponse | null; error: string | null } | null>(null);

  useEffect(() => {
    if (todayOnly) return;
    const ctrl = new AbortController();
    fetchCaseArchive({ from, to, q, result }, ctrl.signal)
      .then((data) => setDone({ key, data, error: null }))
      .catch((e: unknown) => {
        if (ctrl.signal.aborted) return;
        setDone({ key, data: null, error: e instanceof Error ? e.message : "사건 이력 조회 실패" });
      });
    return () => ctrl.abort();
  }, [todayOnly, key, from, to, q, result]);
  const loading = done?.key !== key;
  const fetched = done?.key === key ? done.data : null;
  const error = done?.key === key ? done.error : null;

  const local = useMemo(() => {
    const cases = filterCases(today, { from, to, q, result });
    return { cases, total: cases.length, stats: computeStats(cases) };
  }, [today, from, to, q, result]);

  if (todayOnly) return { ...local, loading: false, error: null };
  const empty = { cases: [], total: 0, stats: computeStats([]) };
  return { ...(fetched ?? empty), loading, error };
}
