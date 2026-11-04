"""실제 양방향 통화(WebRTC) 세션 상태 기계 (2026-11-04, 개발계획서 §5·§10).

구급대원 앱(발신)과 병원 앱(수신)이 WebRTC로 음성을 직접 주고받을 때, hub는 **누가 누구에게 거는지·연결 협상 중계·
상태·종료**만 관리한다(음성은 hub를 거치지 않는다). 이 모듈은 소켓 입출력을 모르는 순수 로직이다 — 각 메서드는
`Outcome`(성공 여부 + 누구에게 어떤 메시지를 보낼지)을 돌려주고, app.py가 소켓으로 옮긴다.

식별자: caseId(환자 사건) / callId(통화 시도 하나, 재전화 시 새로 만든다) / requestId(작업 중복 방지 — 이 모듈은 쓰지 않는다)
        / sessionRevision(상태가 바뀔 때마다 +1, 오래된 상태 반영 방지) / negotiationRevision(연결 협상 세대, 지난 ICE 후보 무시)

상태: ringing → connecting → active → ended.  (inviting은 초대 직후 곧바로 ringing이라 따로 두지 않는다.)
  - 병원이 받으면(call_accept) connecting — 받았다는 사실과 음성 연결 완료를 구분한다.
  - 양쪽이 media_ready를 보고해야 active(통화 시간 시작). 상대가 조용하다고 시작을 미루지 않는다(실제 음성 크기는 조건 아님).
종료 사유: rejected · busy · unavailable(수신 가능한 병원 기기 없음) · no_answer · connection_failed · caller_cancelled ·
          local_hangup · remote_hangup · network_timeout · refused(hub 규칙으로 거부, detail에 이유)

시간 상수는 개발계획서 §10.3의 초기 제안값이며 실기기 측정 전이다: 수신 대기 30초, 연결 협상 15초, 신호 재접속 유예 10초.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

RINGING_SEC = float(os.environ.get("HUB_CALL_RINGING_SEC", "30"))
CONNECTING_SEC = float(os.environ.get("HUB_CALL_CONNECTING_SEC", "15"))
GRACE_SEC = float(os.environ.get("HUB_CALL_GRACE_SEC", "10"))
#: 끝난 통화를 기억해 두는 시간 — 종료된 callId의 늦은 answer·ICE·종료 신호를 무시하고 새 통화에 섞이지 않게 한다
HISTORY_SEC = 3600.0
MAX_ID_LEN = 100
MAX_SDP_LEN = 64 * 1024
MAX_ICE_LEN = 4 * 1024

LIVE_STATES = ("ringing", "connecting", "active")


def _iso(ts: float | None) -> str | None:
    return None if ts is None else datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def ice_servers_for(call_id: str, now: float | None = None, env=None) -> list[dict]:
    """WebRTC ICE 서버 목록. 기본은 공개 STUN. HUB_TURN_URLS + HUB_TURN_SECRET이 있으면 coturn REST 방식(use-auth-secret)의
    만료형 자격 증명(username = 만료시각:callId, credential = base64(HMAC-SHA1(secret, username)))을 함께 준다.
    비밀값은 로그·응답에 싣지 않는다 — 계산된 자격 증명만 나간다."""
    env = os.environ if env is None else env
    stun = [u.strip() for u in env.get("HUB_STUN_URLS", "stun:stun.l.google.com:19302").split(",") if u.strip()]
    servers: list[dict] = [{"urls": stun}] if stun else []
    turn_urls = [u.strip() for u in env.get("HUB_TURN_URLS", "").split(",") if u.strip()]
    secret = env.get("HUB_TURN_SECRET", "")
    if turn_urls and secret:
        expiry = int(now if now is not None else time.time()) + int(env.get("HUB_TURN_TTL_SEC", "3600"))
        username = f"{expiry}:{call_id}"
        credential = base64.b64encode(hmac.new(secret.encode(), username.encode(), hashlib.sha1).digest()).decode()
        servers.append({"urls": turn_urls, "username": username, "credential": credential})
    return servers


@dataclass
class CallSession:
    call_id: str
    case_id: str
    apid: str
    hospital_id: str
    caller_name: str | None = None
    hospital_name: str | None = None
    state: str = "ringing"
    revision: int = 0
    negotiation: int = 0
    caller_ws: object = None
    callee_ws: object = None
    caller_ready: bool = False
    callee_ready: bool = False
    created_at: float = 0.0
    state_at: float = 0.0
    started_at: float | None = None
    ended_at: float | None = None
    end_reason: str | None = None
    ended_by: str | None = None          # "caller" | "callee" | None(시간 초과·hub 규칙)
    detail: str | None = None
    device_ids: dict = field(default_factory=dict)       # 진단용 — 인증이 아니다
    disconnected: dict = field(default_factory=dict)     # "caller"/"callee" -> 신호 연결이 끊긴 시각

    @property
    def live(self) -> bool:
        return self.state in LIVE_STATES


@dataclass
class Outcome:
    ok: bool
    reason: str | None = None
    #: (받는 쪽, 메시지). 받는 쪽: "caller" | "callee" | "self" | "hospital:<hpid>"(그 병원의 통화 가능 기기 전부) | "hospital_others:<hpid>"(받은 기기 빼고)
    sends: list = field(default_factory=list)
    session: CallSession | None = None
    changed: bool = False   # 상태가 바뀌었다(통화 시작·종료 등) — app이 통화 상태·로그를 남긴다


class CallSessionManager:
    def __init__(self, clock: Callable[[], float] = time.time, ice_provider: Callable[[str], list] | None = None,
                 ringing_sec: float = RINGING_SEC, connecting_sec: float = CONNECTING_SEC, grace_sec: float = GRACE_SEC):
        self._clock = clock
        self._ice = ice_provider or (lambda call_id: ice_servers_for(call_id, now=clock()))
        self._ringing, self._connecting, self._grace = ringing_sec, connecting_sec, grace_sec
        self._sessions: dict[str, CallSession] = {}
        self._lock = threading.RLock()

    # ── 조회 ─────────────────────────────────────────────────────────────────
    def get(self, call_id: str) -> CallSession | None:
        with self._lock:
            return self._sessions.get(call_id)

    def live_for_case(self, case_id: str) -> CallSession | None:
        with self._lock:
            return next((s for s in self._sessions.values() if s.live and s.case_id == case_id), None)

    def live_for_hospital(self, hospital_id: str) -> CallSession | None:
        with self._lock:
            return next((s for s in self._sessions.values() if s.live and s.hospital_id == hospital_id), None)

    def live_for_identity(self, role: str, actor: str) -> CallSession | None:
        with self._lock:
            for s in self._sessions.values():
                if s.live and ((role == "ambulance" and s.apid == actor) or (role == "hospital" and s.hospital_id == actor)):
                    return s
        return None

    # ── 메시지 모양 ──────────────────────────────────────────────────────────
    def _view(self, s: CallSession, reason: str | None = None, with_ice: bool = False) -> dict:
        msg = {"type": "call_state", "callId": s.call_id, "caseId": s.case_id, "apid": s.apid, "hospitalId": s.hospital_id,
               "hospitalName": s.hospital_name, "ambulanceName": s.caller_name, "state": s.state,
               "sessionRevision": s.revision, "reason": reason if reason is not None else s.end_reason, "detail": s.detail,
               "startedAt": _iso(s.started_at), "endedAt": _iso(s.ended_at),
               "mediaReady": {"caller": s.caller_ready, "callee": s.callee_ready}}
        if with_ice:
            msg["iceServers"] = self._ice(s.call_id)
        return msg

    def _incoming(self, s: CallSession) -> dict:
        return {"type": "call_incoming", "callId": s.call_id, "caseId": s.case_id, "apid": s.apid, "ambulanceName": s.caller_name,
                "hospitalId": s.hospital_id, "hospitalName": s.hospital_name, "sessionRevision": s.revision,
                "ringingSec": self._ringing, "iceServers": self._ice(s.call_id)}

    # ── 내부 도우미 ──────────────────────────────────────────────────────────
    def _prune(self, now: float) -> None:
        for call_id in [k for k, s in self._sessions.items() if not s.live and s.ended_at is not None and now - s.ended_at > HISTORY_SEC]:
            del self._sessions[call_id]

    def _set_state(self, s: CallSession, state: str, now: float) -> None:
        s.state, s.state_at = state, now
        s.revision += 1

    def _party(self, s: CallSession, role: str, actor: str) -> str | None:
        if role == "ambulance" and actor == s.apid:
            return "caller"
        if role == "hospital" and actor == s.hospital_id:
            return "callee"
        return None

    @staticmethod
    def _bound(s: CallSession, party: str, ws) -> bool:
        """협상·준비 메시지는 그 쪽 자리에 묶인 소켓에서만 받는다 — 같은 접근 코드의 다른 소켓(웹 대시보드 등)이 끼어들지 못하게.
        자리가 비어 있으면(끊긴 뒤 sync 전) 받지 않는다."""
        bound = s.caller_ws if party == "caller" else s.callee_ws
        return bound is not None and bound is ws

    def _callee_target(self, s: CallSession) -> str:
        return "callee" if s.callee_ws is not None else f"hospital:{s.hospital_id}"

    @staticmethod
    def _reason_for(s: CallSession, party: str) -> str | None:
        """끝난 통화의 사유를 그 쪽 입장에서 — 먼저 끊은 쪽엔 local_hangup, 상대에겐 remote_hangup. 그 밖의 사유는 같다."""
        if s.end_reason == "hangup":
            return "local_hangup" if s.ended_by == party else "remote_hangup"
        return s.end_reason

    def _end(self, s: CallSession, reason: str, now: float, ended_by: str | None = None, detail: str | None = None) -> Outcome:
        """통화를 끝내고 양쪽에 알린다. reason "hangup"은 저장만 그대로 두고 보낼 때 쪽별 사유(local/remote)로 바꾼다."""
        s.ended_at, s.end_reason, s.ended_by, s.detail = now, reason, ended_by, detail
        self._set_state(s, "ended", now)
        s.caller_ready = s.callee_ready = False
        sends = [("caller", self._view(s, reason=self._reason_for(s, "caller"))),
                 (self._callee_target(s), self._view(s, reason=self._reason_for(s, "callee")))]
        return Outcome(True, sends=sends, session=s, changed=True)

    # ── 발신 ─────────────────────────────────────────────────────────────────
    def invite(self, *, call_id: str, case_id: str, apid: str, hospital_id: str, caller_ws, hospital_online: bool,
               caller_name: str | None = None, hospital_name: str | None = None, device_id: str | None = None) -> Outcome:
        if not isinstance(call_id, str) or not call_id or len(call_id) > MAX_ID_LEN:
            return Outcome(False, "invalid_call_id")
        now = self._clock()
        with self._lock:
            self._prune(now)
            existing = self._sessions.get(call_id)
            if existing is not None:
                if existing.live and (existing.case_id, existing.apid, existing.hospital_id) == (case_id, apid, hospital_id):
                    existing.caller_ws = caller_ws  # 같은 초대 재전송(네트워크 재시도) — 새 통화를 만들지 않는다
                    return Outcome(True, sends=[("caller", self._view(existing, with_ice=True))], session=existing)
                return Outcome(False, "duplicate_call_id")
            if self.live_for_case(case_id) is not None:
                return Outcome(False, "case_busy")
            hospital_busy = self.live_for_hospital(hospital_id) is not None  # 새 세션을 넣기 전에 본다(자기 자신을 세지 않게)
            s = CallSession(call_id, case_id, apid, hospital_id, caller_name, hospital_name, created_at=now, state_at=now,
                            caller_ws=caller_ws)
            if device_id:
                s.device_ids["caller"] = device_id[:100]
            self._sessions[call_id] = s
            if hospital_busy:
                out = self._end(s, "busy", now)
                out.sends = [("caller", {"type": "call_busy", "callId": call_id, "hospitalId": hospital_id}), out.sends[0]]
                return out
            if not hospital_online:
                out = self._end(s, "unavailable", now)
                out.sends = out.sends[:1]  # 병원엔 울린 적이 없으니 종료도 알리지 않는다
                return out
            self._set_state(s, "ringing", now)
            return Outcome(True, sends=[("caller", self._view(s, with_ice=True)), (f"hospital:{hospital_id}", self._incoming(s))],
                           session=s, changed=False)

    # ── 수신 응답 ────────────────────────────────────────────────────────────
    def accept(self, call_id: str, role: str, actor: str, ws, device_id: str | None = None) -> Outcome:
        now = self._clock()
        with self._lock:
            s = self._sessions.get(call_id)
            if s is None or self._party(s, role, actor) != "callee":
                return Outcome(False, "unknown_call" if s is None else "forbidden")
            if s.state != "ringing":
                return Outcome(False, "not_ringing")  # 이미 취소·종료됐거나 다른 기기가 받았다 — 늦은 받기는 무시한다
            s.callee_ws = ws
            if device_id:
                s.device_ids["callee"] = device_id[:100]
            self._set_state(s, "connecting", now)
            # 같은 병원의 다른 기기는 수신 화면을 닫는다(먼저 받은 기기만 통화한다)
            elsewhere = {**self._view(s, reason="answered_elsewhere"), "state": "ended"}
            return Outcome(True, sends=[("caller", self._view(s, with_ice=True)), ("callee", self._view(s, with_ice=True)),
                                        (f"hospital_others:{s.hospital_id}", elsewhere)], session=s)

    def reject(self, call_id: str, role: str, actor: str, ws) -> Outcome:
        now = self._clock()
        with self._lock:
            s = self._sessions.get(call_id)
            if s is None or self._party(s, role, actor) != "callee":
                return Outcome(False, "unknown_call" if s is None else "forbidden")
            if s.state != "ringing":
                return Outcome(False, "not_ringing")
            return self._end(s, "rejected", now, ended_by="callee")

    def hangup(self, call_id: str, role: str, actor: str, ws) -> Outcome:
        """통화 종료 — 양쪽 어느 쪽이든. 수신 대기 중 병원의 거부는 reject, 발신자의 취소는 hangup(caller_cancelled)이다.
        이미 끝난 통화에 대한 중복·늦은 종료 신호는 아무것도 하지 않는다(멱등)."""
        now = self._clock()
        with self._lock:
            s = self._sessions.get(call_id)
            if s is None:
                return Outcome(False, "unknown_call")
            party = self._party(s, role, actor)
            if party is None:
                return Outcome(False, "forbidden")
            if not s.live:
                return Outcome(True, "already_ended", session=s)
            if s.state == "ringing":
                if party == "callee":
                    return Outcome(False, "use_reject")
                return self._end(s, "caller_cancelled", now, ended_by="caller")
            out = self._end(s, "hangup", now, ended_by=party)
            return out

    # ── 연결 협상 중계 ───────────────────────────────────────────────────────
    def offer(self, call_id: str, role: str, actor: str, ws, sdp, negotiation_revision: int = 1) -> Outcome:
        with self._lock:
            s = self._sessions.get(call_id)
            if s is None or not isinstance(sdp, str) or not sdp or len(sdp) > MAX_SDP_LEN:
                return Outcome(False, "invalid")
            if self._party(s, role, actor) != "caller" or not self._bound(s, "caller", ws):
                return Outcome(False, "forbidden")
            if s.state not in ("connecting", "active") or s.callee_ws is None:
                return Outcome(False, "not_connecting")
            if not isinstance(negotiation_revision, int) or negotiation_revision < max(s.negotiation, 1):
                return Outcome(False, "stale")
            s.negotiation = negotiation_revision
            return Outcome(True, sends=[("callee", {"type": "rtc_offer", "callId": call_id, "negotiationRevision": s.negotiation,
                                                    "sessionRevision": s.revision, "sdp": sdp})], session=s)

    def answer(self, call_id: str, role: str, actor: str, ws, sdp, negotiation_revision: int = 1) -> Outcome:
        with self._lock:
            s = self._sessions.get(call_id)
            if s is None or not isinstance(sdp, str) or not sdp or len(sdp) > MAX_SDP_LEN:
                return Outcome(False, "invalid")
            if self._party(s, role, actor) != "callee" or not self._bound(s, "callee", ws):
                return Outcome(False, "forbidden")
            if s.state not in ("connecting", "active") or s.caller_ws is None:
                return Outcome(False, "not_connecting")
            if negotiation_revision != s.negotiation:
                return Outcome(False, "stale")
            return Outcome(True, sends=[("caller", {"type": "rtc_answer", "callId": call_id, "negotiationRevision": s.negotiation,
                                                    "sessionRevision": s.revision, "sdp": sdp})], session=s)

    def ice(self, call_id: str, role: str, actor: str, ws, candidate, negotiation_revision: int = 1) -> Outcome:
        """ICE 후보 중계. 끝났거나 지난 협상 세대의 후보는 조용히 버린다."""
        with self._lock:
            s = self._sessions.get(call_id)
            if s is None or not isinstance(candidate, dict) or len(str(candidate)) > MAX_ICE_LEN:
                return Outcome(False, "invalid")
            party = self._party(s, role, actor)
            if party is None or not self._bound(s, party, ws):
                return Outcome(False, "forbidden")
            if s.state not in ("connecting", "active") or negotiation_revision != s.negotiation:
                return Outcome(False, "stale")
            target = "callee" if party == "caller" else "caller"
            if (s.callee_ws if target == "callee" else s.caller_ws) is None:
                return Outcome(False, "peer_offline")
            return Outcome(True, sends=[(target, {"type": "rtc_ice", "callId": call_id, "negotiationRevision": s.negotiation,
                                                  "candidate": candidate})], session=s)

    def media_ready(self, call_id: str, role: str, actor: str, ws) -> Outcome:
        """한 쪽의 WebRTC 연결·오디오 경로 준비 완료. 양쪽이 보고하면 통화 중(active)으로 바뀌고 통화 시간이 시작된다."""
        now = self._clock()
        with self._lock:
            s = self._sessions.get(call_id)
            if s is None:
                return Outcome(False, "unknown_call")
            party = self._party(s, role, actor)
            if party is None or not self._bound(s, party, ws):
                return Outcome(False, "forbidden")
            if s.state == "active":
                return Outcome(True, "already_active", session=s)
            if s.state != "connecting":
                return Outcome(False, "not_connecting")
            if party == "caller":
                s.caller_ready = True
            else:
                s.callee_ready = True
            if not (s.caller_ready and s.callee_ready):
                return Outcome(True, session=s)
            s.started_at = now
            self._set_state(s, "active", now)
            return Outcome(True, sends=[("caller", self._view(s)), ("callee", self._view(s))], session=s, changed=True)

    def end_for_case(self, case_id: str, reason: str = "case_closed") -> Outcome | None:
        """사건이 닫히면(시연 초기화·방치 정리 등) 그 사건의 살아 있는 통화도 끝낸다. 없으면 None."""
        now = self._clock()
        with self._lock:
            s = self.live_for_case(case_id)
            return None if s is None else self._end(s, reason, now)

    # ── 재접속 · 시간 · 끊김 ─────────────────────────────────────────────────
    def sync(self, role: str, actor: str, ws, call_id: str | None = None) -> Outcome:
        """앱이 (재)접속해 현재 통화를 묻는다. 살아 있는 통화면 이 소켓을 그 쪽 자리에 다시 묶고 상태를 돌려준다.
        끝났거나 모르는 callId면 종료 상태를 돌려줘 앱이 화면을 정리하게 한다. 접속(identify)만으로는 다시 묶지 않는다 —
        같은 병원 코드로 열린 웹 대시보드가 통화 자리를 가로채지 못하게."""
        with self._lock:
            s = self._sessions.get(call_id) if call_id else self.live_for_identity(role, actor)
            if s is None:
                if call_id:
                    return Outcome(True, sends=[("self", {"type": "call_state", "callId": call_id, "state": "ended", "reason": "unknown"})])
                return Outcome(True)
            party = self._party(s, role, actor)
            if party is None:
                return Outcome(False, "forbidden")
            if not s.live:
                return Outcome(True, sends=[("self", self._view(s, reason=self._reason_for(s, party)))], session=s)
            if party == "caller":
                s.caller_ws = ws
            elif s.state != "ringing":
                s.callee_ws = ws
            s.disconnected.pop(party, None)
            sends = [("self", self._view(s, with_ice=True))]
            if party == "callee" and s.state == "ringing":
                sends.append(("self", self._incoming(s)))
            return Outcome(True, sends=sends, session=s)

    def socket_closed(self, ws) -> None:
        """신호 연결이 끊겼다. 곧바로 통화를 끝내지 않는다 — 음성(WebRTC)은 살아 있을 수 있다. 유예 시간(tick) 안에
        call_state_sync로 돌아오면 이어진다."""
        now = self._clock()
        with self._lock:
            for s in self._sessions.values():
                if not s.live:
                    continue
                if s.caller_ws is ws:
                    s.caller_ws, s.disconnected["caller"] = None, now
                if s.callee_ws is ws:
                    s.callee_ws, s.disconnected["callee"] = None, now

    def tick(self) -> list[Outcome]:
        """주기 점검(1초): 수신 대기·연결 협상 시간 초과, 신호 재접속 유예 초과를 종료한다. 끝낸 통화마다 Outcome을 돌려준다."""
        now = self._clock()
        done: list[Outcome] = []
        with self._lock:
            self._prune(now)
            for s in list(self._sessions.values()):
                if not s.live:
                    continue
                if s.state == "ringing" and now - s.state_at > self._ringing:
                    done.append(self._end(s, "no_answer", now))
                elif s.state == "connecting" and now - s.state_at > self._connecting:
                    done.append(self._end(s, "connection_failed", now))
                elif any(now - t > self._grace for t in s.disconnected.values()):
                    done.append(self._end(s, "network_timeout", now))
        return done
