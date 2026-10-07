"""생존모델 벤치마크 — XGBoost AFT vs Cox PH · DeepSurv · DeepHit (같은 데이터·같은 분할·같은 지표).

    python -m reliability.benchmark_deep                 # hvec θ3, 시드 3종, Mac GPU(MPS)가 있으면 사용
    python -m reliability.benchmark_deep --seeds 42      # 빠른 확인

서빙 모델(aft_egen_theta3_ext0923)과 같은 라벨·피처(labeling.build_versions, FULL9)로 버전을 만들고,
서빙과 같은 시간 경계(2026-09-22 KST)로 train/test를 나눈다. train의 마지막 15%(탄생 시각 기준)는
모든 모델의 early stopping용 검증 구간이다(test는 학습·조기종료에 전혀 쓰지 않는다).

비교 대상
- XGB-AFT          서빙 설정(fit.PARAMS) — 구간검열 라벨을 그대로 받는다
- XGB-AFT(점 라벨)  사건을 "변화가 관측된 시각(hi)" 한 점으로 바꾼 라벨 — 신경망과 같은 조건
- XGB-AFT+재보정    위 1번에 서빙과 같은 잔차 재보정(μR, σR)을 검증 구간에서 적합해 적용
- INTERVAL          갱신 리듬 2피처만 쓴 XGB-AFT(필수 대조군)
- CoxPH(선형)       Cox 부분우도 + 선형 모델(Breslow 기준위험)
- DeepSurv         Katzman et al. 2018 — Cox 부분우도 + MLP
- DeepHit          Lee et al. 2018 — 이산시간 pmf + (우도 + 순위 손실), 단일 위험. 원 논문·pycox 기본(α=0.2)과
                   우도만(α=1) 둘 다 — 순위 손실이 캘리브레이션을 해치는 성질을 같이 보이려고
  (DeepSurv·DeepHit는 MPS에서 돌리려고 PyTorch로 직접 구현했다. 손실식은 pycox 구현과 같다.)

지표(전부 test에서): Harrell C · 시간의존 C(Antolini) · IBS(IPCW) · ECE@30분(구간검열로 판정 가능한 행만)
· D-calibration · 학습/추론 시간. 신경망은 결측을 못 받아 결측 표시+중앙값 대체·log1p·표준화를 한다
(트리는 원값·NaN 그대로). 서빙 모델 파일·실서버는 건드리지 않는다. 결과는 data/benchmark/.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost  # noqa: F401 — torch보다 먼저 불러야 한다(macOS에서 두 라이브러리의 OpenMP가 한 프로세스에서 부딪혀 segfault)
from scipy.stats import norm

from . import fit
from .calibrate import fit_residual
from .engine import _DEFAULT_SNAPSHOT_DIR
from .evaluate import cindex, dcal, ipcw_ibs
from .features import FEATURES
from .labeling import Version, build_versions
from .train_field import _median_gap_by_hpid

CUTOFF = "2026-09-22T00:00:00+09:00"
THETA = 3
VAL_FRAC = 0.15
TAU = 1800.0                                  # ECE 지평(30분) — calibrate.py와 같다
GRID = np.unique(np.concatenate([np.geomspace(60.0, 6 * 3600.0, 80), [TAU]]))  # 생존곡선 평가 격자(초)
IBS_GRID = GRID[(GRID >= 300.0) & (GRID <= 4 * 3600.0)]
OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "benchmark"


# ── 데이터 ───────────────────────────────────────────────────────────────────

def _labels(vs: list[Version]) -> dict[str, np.ndarray]:
    lo = np.array([v.lo for v in vs], dtype=float)
    hi = np.array([v.hi if v.event else np.inf for v in vs], dtype=float)
    ev = np.array([v.event for v in vs])
    t_obs = np.where(ev, hi, lo)              # 사건은 변화가 관측된 시각, 검열은 마지막 생존 확인 시각
    return {"lo": lo, "hi": hi, "event": ev, "t": np.maximum(t_obs, 1.0)}


def _frame(vs: list[Version]) -> pd.DataFrame:
    return pd.DataFrame([v.features for v in vs], columns=FEATURES, dtype=np.float32)


class NetPrep:
    """신경망·Cox 입력 — horizon_s(항상 결측) 제거, 결측 표시 3개, 중앙값 대체, log1p, 시각·요일 원형 인코딩, 표준화."""

    LOG = ["version_no", "t_since_claim_start", "prev_lifetime", "mean_interval_so_far", "delta_pred_s", "route_med_gap"]
    MISS = ["prev_lifetime", "mean_interval_so_far", "delta_pred_s"]

    def fit(self, X: pd.DataFrame) -> "NetPrep":
        self.median = X[self.LOG].median()
        Z = self._raw(X)
        self.mu, self.sd = Z.mean(0), Z.std(0) + 1e-6
        return self

    def _raw(self, X: pd.DataFrame) -> np.ndarray:
        cols = [np.log1p(np.clip(X[c].fillna(self.median[c]).to_numpy(np.float64), 0, None)) for c in self.LOG]
        cols += [X[c].isna().to_numpy(np.float64) for c in self.MISS]
        h = X["hour_utc"].to_numpy(np.float64) * 2 * math.pi / 24
        d = X["dow"].to_numpy(np.float64) * 2 * math.pi / 7
        cols += [np.sin(h), np.cos(h), np.sin(d), np.cos(d)]
        return np.stack(cols, 1)

    def transform(self, X: pd.DataFrame) -> np.ndarray:
        return ((self._raw(X) - self.mu) / self.sd).astype(np.float32)


# ── 지표 ─────────────────────────────────────────────────────────────────────

def _col(t: float) -> int:
    return int(np.argmin(np.abs(GRID - t)))


def metrics(S: np.ndarray, scalar: np.ndarray, surv_at, y: dict, rng_seed: int = 0) -> dict:
    """S: (N, len(GRID)) 생존곡선, scalar: 클수록 오래 산다는 한 값(Harrell C용),
    surv_at(rows, times): 그 행들의 정확한 S(times) — 격자 근사를 쓰면 20분 폴링에 몰린 사건 시각 직전 격자에서
    계단이 아직 안 떨어져 Cox·DeepHit 곡선이 전부 동점이 된다(스모크 테스트에서 확인)."""
    t, ev, lo, hi = y["t"], y["event"], y["lo"], y["hi"]
    w = np.ones(len(t))
    out = {"cHarrell": float(cindex(t, ev, scalar))}
    # 시간의존 C(Antolini): i(사건) < j 쌍에서 S_i(t_i) < S_j(t_i)이면 일치
    rng = np.random.default_rng(rng_seed)
    ev_idx = np.flatnonzero(ev)
    i = rng.choice(ev_idx, 400_000)
    j = rng.integers(0, len(t), 400_000)
    ok = t[i] < t[j]
    i, j = i[ok], j[ok]
    si, sj = surv_at(i, t[i]), surv_at(j, t[i])
    out["cTd"] = float(((si < sj).sum() + 0.5 * (si == sj).sum()) / len(i))
    out["ibs"] = ipcw_ibs(lambda tg: S[:, _col(tg)], t, ev, w, IBS_GRID)
    # ECE@30분 — 판정 가능한 행만(lo ≥ τ면 생존, 사건이고 hi ≤ τ면 깨짐)
    p = S[:, _col(TAU)]
    alive, dead = lo >= TAU, ev & (hi <= TAU)
    use = alive | dead
    p_u, o_u = p[use], alive[use].astype(float)
    ece = 0.0
    for b in np.array_split(np.argsort(p_u), 10):
        ece += len(b) / len(p_u) * abs(p_u[b].mean() - o_u[b].mean())
    out["ece30"] = float(ece)
    out["dcal"] = dcal(surv_at(np.arange(len(t)), t), ev, w)[0]
    return out


# ── XGBoost AFT ──────────────────────────────────────────────────────────────

def aft_curve(m: np.ndarray, mu: float = 0.0, sigma: float = 1.0) -> np.ndarray:
    return norm.sf((np.log(GRID)[None, :] - (np.log(np.maximum(m, 1e-12))[:, None] + mu)) / sigma).astype(np.float32)


def run_xgb(name, cols, Xtr, ytr, Xva, yva, Xte, yte, seed, point=False, recal_versions=None):
    up_tr = np.where(ytr["event"], ytr["t"] if point else ytr["hi"], np.inf)
    up_va = np.where(yva["event"], yva["t"] if point else yva["hi"], np.inf)
    lo_tr = np.where(ytr["event"] & point, ytr["t"], ytr["lo"])
    lo_va = np.where(yva["event"] & point, yva["t"], yva["lo"])
    t0 = time.time()
    bst = fit.train(Xtr[cols], lo_tr, up_tr, Xva[cols], lo_va, up_va, rounds=300, params={"seed": seed})
    train_sec = time.time() - t0
    t0 = time.time()
    m = fit.predict(bst, Xte[cols])
    mu, sigma = 0.0, 1.0
    if recal_versions is not None:
        mu, sigma = fit_residual(fit.predict(bst, Xva[cols]), recal_versions)
    S = aft_curve(m, mu, sigma)
    infer_sec = time.time() - t0
    surv_at = lambda rows, tt: norm.sf((np.log(np.maximum(tt, 1e-12)) - np.log(np.maximum(m[rows], 1e-12)) - mu) / sigma)
    res = metrics(S, m, surv_at, yte)
    res.update(trainSec=round(train_sec, 1), inferSec=round(infer_sec, 2), rounds=int(bst.best_iteration) + 1)
    if recal_versions is not None:
        res.update(muR=round(float(mu), 4), sigmaR=round(float(sigma), 4))
    return res


# ── 신경망(Cox · DeepSurv · DeepHit) ─────────────────────────────────────────

def _torch():
    import torch
    return torch


def mlp(d_in: int, d_out: int, hidden: tuple[int, ...]):
    torch = _torch()
    nn = torch.nn
    layers, d = [], d_in
    for h in hidden:
        layers += [nn.Linear(d, h), nn.ReLU(), nn.BatchNorm1d(h), nn.Dropout(0.1)]
        d = h
    layers.append(nn.Linear(d, d_out))
    return nn.Sequential(*layers)


def cox_loss(log_h, t, ev):
    """pycox cox_ph_loss와 같은 식(Breslow 근사): 시간 내림차순 정렬 뒤 누적 log-sum-exp."""
    torch = _torch()
    order = torch.argsort(t, descending=True)
    log_h, ev = log_h[order].view(-1), ev[order].float()
    gamma = log_h.max()
    log_cum = torch.log(torch.cumsum(torch.exp(log_h - gamma), 0)) + gamma
    return -((log_h - log_cum) * ev).sum() / ev.sum().clamp(min=1.0)


def deephit_loss(logits, idx, ev, alpha=0.2, sigma=0.1):
    """pycox DeepHitSingle과 같은 식: α·NLL(pmf) + (1−α)·순위 손실. logits는 K개 구간 + '마지막 구간 너머' 1개.
    구간 k는 (cuts[k−1], cuts[k]]. 사건이면 idx = 그 시각을 오른쪽 끝으로 포함하는 구간(−log pmf[idx]),
    검열이면 idx = 이미 지나온 마지막 경계(−log(1 − F(idx)) = 그 경계 너머 생존)."""
    torch = _torch()
    pmf = torch.softmax(logits, 1)
    K = logits.shape[1] - 1
    cdf = torch.cumsum(pmf[:, :K], 1)
    ar = torch.arange(len(idx), device=logits.device)
    p_ev = pmf[ar, idx].clamp(min=1e-7)
    surv_after = (1.0 - cdf[ar, idx]).clamp(min=1e-7)            # 검열: 그 구간 끝까지 살아 있음
    nll = -(ev * torch.log(p_ev) + (1 - ev) * torch.log(surv_after)).mean()
    F_at = cdf[:, idx].T                                          # F_at[i, j] = F_j(T_i)
    Fi = torch.diagonal(F_at)
    pair = (idx[:, None] < idx[None, :]) | ((idx[:, None] == idx[None, :]) & (ev[None, :] == 0))
    pair = pair & (ev[:, None] == 1)
    diff = Fi[:, None] - F_at
    rank = (pair * torch.exp(-diff / sigma)).sum() / pair.sum().clamp(min=1)
    return alpha * nll + (1 - alpha) * rank


def run_net(kind, Ztr, ytr, Zva, yva, Zte, yte, seed, device, epochs=40, patience=5, batch=1024, alpha=0.2):
    torch = _torch()
    torch.manual_seed(seed)
    np.random.seed(seed)
    if kind == "deephit":
        ev_t = ytr["t"][ytr["event"]]
        cuts = np.unique(np.concatenate([[0.0], np.quantile(ev_t, np.linspace(0, 1, 50))]))
        K = len(cuts)
        # 20분 폴링이라 사건 시각이 경계값과 정확히 겹친다 — 사건은 그 경계를 오른쪽 끝으로 갖는 구간,
        # 검열은 지나온 마지막 경계(스모크 테스트에서 한 칸 늦게 떨어지던 버그 수정)
        to_idx = lambda tt, e: np.where(
            e, np.clip(np.searchsorted(cuts, tt, side="left"), 0, K - 1),
            np.clip(np.searchsorted(cuts, tt, side="right") - 1, 0, K - 1))
        net = mlp(Ztr.shape[1], K + 1, (64, 64))
    else:
        net = mlp(Ztr.shape[1], 1, () if kind == "cox" else (64, 64))
    net = net.to(device)
    opt = torch.optim.Adam(net.parameters(), lr=1e-3)

    def tensors(Z, y):
        z = torch.tensor(Z, device=device)
        ev = torch.tensor(y["event"].astype(np.float32), device=device)
        if kind == "deephit":
            return z, torch.tensor(to_idx(y["t"], y["event"]), device=device, dtype=torch.long), ev
        return z, torch.tensor(y["t"].astype(np.float32), device=device), ev

    ztr, a_tr, e_tr = tensors(Ztr, ytr)
    zva, a_va, e_va = tensors(Zva, yva)
    loss_fn = (lambda out, a, e: deephit_loss(out, a, e, alpha=alpha)) if kind == "deephit" else (lambda out, a, e: cox_loss(out, a, e))

    def val_loss():
        net.eval()
        with torch.no_grad():
            if kind == "deephit":  # 순위 손실은 배치 단위라 검증도 같은 크기로 나눠 평균
                losses = [loss_fn(net(zva[s:s + batch]), a_va[s:s + batch], e_va[s:s + batch]).item()
                          for s in range(0, len(zva), batch)]
                return float(np.mean(losses))
            return loss_fn(net(zva), a_va, e_va).item()

    best, best_state, bad, t0, ep_run = math.inf, None, 0, time.time(), 0
    n = len(ztr)
    for ep in range(epochs):
        net.train()
        perm = torch.randperm(n, device=device)
        for s in range(0, n, batch):
            b = perm[s:s + batch]
            if len(b) < 2:
                continue
            opt.zero_grad()
            loss = loss_fn(net(ztr[b]), a_tr[b], e_tr[b])
            loss.backward()
            opt.step()
        vl = val_loss()
        ep_run = ep + 1
        if vl < best - 1e-5:
            best, bad = vl, 0
            best_state = {k: v.detach().clone() for k, v in net.state_dict().items()}
        else:
            bad += 1
            if bad >= patience:
                break
    net.load_state_dict(best_state)
    train_sec = time.time() - t0

    t0 = time.time()
    net.eval()
    with torch.no_grad():
        zte = torch.tensor(Zte, device=device)
        out_te = torch.cat([net(zte[s:s + 8192]) for s in range(0, len(zte), 8192)]).cpu().numpy()
        if kind != "deephit":
            out_tr = torch.cat([net(ztr[s:s + 8192]) for s in range(0, len(ztr), 8192)]).cpu().numpy()
    if kind == "deephit":
        pmf = np.exp(out_te - out_te.max(1, keepdims=True))
        pmf /= pmf.sum(1, keepdims=True)
        cdf = np.cumsum(pmf[:, :K], 1)
        # S(t) = 1 − F(오른쪽 끝이 t 이하인 구간까지) — 경계에서 떨어지는 계단(cuts[0]=0이라 k ≥ 0)
        k_grid = np.searchsorted(cuts, GRID, side="right") - 1
        S = (1.0 - cdf[:, k_grid]).astype(np.float32)
        scalar = np.trapezoid(S, GRID, axis=1)                      # 제한 평균 생존시간

        def surv_at(rows, tt):
            return 1.0 - cdf[rows, np.searchsorted(cuts, tt, side="right") - 1]
    else:
        # Breslow 기준누적위험 — train 전체로 추정
        r = np.exp(out_tr.reshape(-1).astype(np.float64))
        order = np.argsort(ytr["t"])
        t_s, e_s, r_s = ytr["t"][order], ytr["event"][order], r[order]
        risk_set = np.cumsum(r_s[::-1])[::-1]
        H_steps = np.cumsum(e_s / risk_set)
        H0 = np.concatenate([[0.0], H_steps])[np.searchsorted(t_s, GRID, side="right")]
        log_h = out_te.reshape(-1).astype(np.float64)
        S = np.exp(-H0[None, :] * np.exp(log_h)[:, None]).astype(np.float32)
        scalar = -log_h
        H_all = np.concatenate([[0.0], H_steps])

        def surv_at(rows, tt):
            return np.exp(-H_all[np.searchsorted(t_s, tt, side="right")] * np.exp(log_h[rows]))
    infer_sec = time.time() - t0
    res = metrics(S, scalar, surv_at, yte)
    res.update(trainSec=round(train_sec, 1), inferSec=round(infer_sec, 2), epochs=ep_run)
    return res


# ── 실행 ─────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--snapshots", type=Path, default=_DEFAULT_SNAPSHOT_DIR)
    ap.add_argument("--seeds", type=int, nargs="+", default=[42, 43, 44])
    ap.add_argument("--cpu", action="store_true", help="MPS가 있어도 CPU로")
    args = ap.parse_args()
    torch = _torch()
    device = torch.device("cpu" if args.cpu or not torch.backends.mps.is_available() else "mps")
    cutoff = datetime.fromisoformat(CUTOFF).astimezone(timezone.utc)
    print(f"[준비] 장치 {device} · θ={THETA} · cutoff {cutoff.isoformat()}", flush=True)

    t0 = time.time()
    versions = build_versions(args.snapshots, field="hvec", theta=THETA)
    train_all = sorted([v for v in versions if v.born < cutoff], key=lambda v: v.born)
    test = [v for v in versions if v.born >= cutoff]
    split = int(len(train_all) * (1 - VAL_FRAC))
    train, val = train_all[:split], train_all[split:]
    gap, national = _median_gap_by_hpid(train)               # 누수 방지: train 구간에서만
    for v in versions:
        v.features[8] = gap.get(v.hpid, national)
    data_span = (min(v.born for v in versions).isoformat(), max(v.born for v in versions).isoformat())
    print(f"[데이터] 버전 {len(versions):,} (train {len(train):,} / val {len(val):,} / test {len(test):,}) "
          f"· 사건 test {sum(v.event for v in test):,} · {time.time() - t0:.0f}초", flush=True)

    Xtr, Xva, Xte = _frame(train), _frame(val), _frame(test)
    ytr, yva, yte = _labels(train), _labels(val), _labels(test)
    prep = NetPrep().fit(Xtr)
    Ztr, Zva, Zte = prep.transform(Xtr), prep.transform(Xva), prep.transform(Xte)

    models = [
        ("XGB-AFT", lambda s: run_xgb("aft", FEATURES, Xtr, ytr, Xva, yva, Xte, yte, s)),
        ("XGB-AFT(점 라벨)", lambda s: run_xgb("aft_point", FEATURES, Xtr, ytr, Xva, yva, Xte, yte, s, point=True)),
        ("XGB-AFT+재보정", lambda s: run_xgb("aft_recal", FEATURES, Xtr, ytr, Xva, yva, Xte, yte, s, recal_versions=val)),
        ("INTERVAL", lambda s: run_xgb("interval", fit.INTERVAL_ONLY, Xtr, ytr, Xva, yva, Xte, yte, s)),
        ("CoxPH(선형)", lambda s: run_net("cox", Ztr, ytr, Zva, yva, Zte, yte, s, device)),
        ("DeepSurv", lambda s: run_net("deepsurv", Ztr, ytr, Zva, yva, Zte, yte, s, device)),
        ("DeepHit(α=0.2, 기본)", lambda s: run_net("deephit", Ztr, ytr, Zva, yva, Zte, yte, s, device, alpha=0.2)),
        ("DeepHit(α=1, 우도만)", lambda s: run_net("deephit", Ztr, ytr, Zva, yva, Zte, yte, s, device, alpha=1.0)),
    ]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_json = OUT_DIR / f"benchmark_hvec_theta{THETA}.json"
    results: dict = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "field": "hvec", "theta": THETA, "cutoff": cutoff.isoformat(), "valFrac": VAL_FRAC, "device": str(device),
        "dataSpan": data_span,
        "sizes": {"train": len(train), "val": len(val), "test": len(test),
                  "testEvents": int(sum(v.event for v in test))},
        "models": {},
    }
    for name, run in models:
        per_seed = {}
        for s in args.seeds:
            res = run(s)
            per_seed[str(s)] = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in res.items()}
            print(f"[{name}] seed {s}: C {res['cHarrell']:.4f} · Ctd {res['cTd']:.4f} · IBS {res['ibs']:.4f} "
                  f"· ECE30 {res['ece30']:.4f} · Dcal {res['dcal']:.5f} · 학습 {res['trainSec']}초", flush=True)
        keys = ["cHarrell", "cTd", "ibs", "ece30", "dcal", "trainSec", "inferSec"]
        summary = {k: {"mean": round(float(np.mean([r[k] for r in per_seed.values()])), 4),
                       "std": round(float(np.std([r[k] for r in per_seed.values()])), 4)} for k in keys}
        results["models"][name] = {"seeds": per_seed, "summary": summary}
        out_json.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")  # 모델마다 중간 저장

    lines = [
        f"# 생존모델 벤치마크 — hvec θ{THETA}", "",
        f"- 생성 {results['generatedAt']} · 장치 {device} · 데이터 {data_span[0][:10]} ~ {data_span[1][:10]}",
        f"- 분할: train {len(train):,} / val {len(val):,} (early stopping) / test {len(test):,} "
        f"(사건 {results['sizes']['testEvents']:,}) · 경계 {CUTOFF}",
        f"- 시드 {args.seeds} 평균 ± 표준편차. C·Ctd는 클수록, IBS·ECE·Dcal은 작을수록 좋다.", "",
        "| 모델 | Harrell C | 시간의존 C | IBS | ECE@30분 | D-cal | 학습(초) |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, r in results["models"].items():
        sm = r["summary"]
        lines.append(f"| {name} | {sm['cHarrell']['mean']:.4f} ± {sm['cHarrell']['std']:.4f} | "
                     f"{sm['cTd']['mean']:.4f} | {sm['ibs']['mean']:.4f} | {sm['ece30']['mean']:.4f} | "
                     f"{sm['dcal']['mean']:.5f} | {sm['trainSec']['mean']:.0f} |")
    (OUT_DIR / f"benchmark_hvec_theta{THETA}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines), flush=True)
    print(f"[완료] {out_json}", flush=True)


if __name__ == "__main__":
    main()
