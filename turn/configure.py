"""환경으로 coturn 설정 생성. 비밀값은 stdout/명령행에 노출하지 않는다."""
import ipaddress
import os
from pathlib import Path
import re
import sys


def configuration(env):
    def value(key, default=""):
        v = env.get(key, default)
        if any(c in v for c in "\r\n\x00"):
            raise ValueError(f"{key}: 줄바꿈을 포함할 수 없습니다")
        return v

    def port(key, default):
        n = int(value(key, str(default)))
        if not 1024 <= n <= 65535:
            raise ValueError(f"{key}: 1024~65535 포트가 필요합니다")
        return n

    host = value("TURN_HOST")
    if not re.fullmatch(r"[A-Za-z0-9.-]+", host) or host.endswith("example.com"):
        raise ValueError("TURN_HOST에 실제 공인 IPv4 또는 도메인을 지정하세요")
    secret = value("HUB_TURN_SECRET")
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,}", secret):
        raise ValueError("HUB_TURN_SECRET: openssl rand -hex 32 로 생성한 비밀값을 지정하세요")
    external = value("TURN_EXTERNAL_IP")
    for address in external.split("/"):
        ipaddress.IPv4Address(address)
    if len(external.split("/")) > 2:
        raise ValueError("TURN_EXTERNAL_IP 형식은 공인IP[/사설IP]입니다")
    listen = port("TURN_PORT", 3478)
    low, high = port("TURN_MIN_PORT", 49160), port("TURN_MAX_PORT", 49259)
    if low > high or low <= listen <= high:
        raise ValueError("TURN 릴레이 포트 범위를 확인하세요")
    lines = [
        f"listening-port={listen}", "listening-ip=0.0.0.0",
        f"external-ip={external}", f"min-port={low}", f"max-port={high}",
        f"realm={host}", "fingerprint", "use-auth-secret", f"static-auth-secret={secret}",
        "no-cli", "no-multicast-peers", "no-tcp-relay", "no-rfc5780",
        # 양쪽이 UDP/TCP/TLS 후보를 병렬 수집하고 재협상할 여유를 둔다(통화 ID당).
        "user-quota=16", "total-quota=100", "stale-nonce=600",
        "log-file=stdout", "simple-log",
    ]
    # TURN을 통한 로컬 서비스 접근 차단. WebRTC의 UDP relay는 유지한다.
    for network in ("0.0.0.0-0.255.255.255", "10.0.0.0-10.255.255.255",
                    "100.64.0.0-100.127.255.255", "127.0.0.0-127.255.255.255",
                    "169.254.0.0-169.254.255.255", "172.16.0.0-172.31.255.255",
                    "192.168.0.0-192.168.255.255", "::1", "fc00::-fdff:ffff:ffff:ffff:ffff:ffff:ffff:ffff",
                    "fe80::-febf:ffff:ffff:ffff:ffff:ffff:ffff:ffff"):
        lines.append(f"denied-peer-ip={network}")
    urls = [f"turn:{host}:{listen}?transport=udp", f"turn:{host}:{listen}?transport=tcp"]
    cert, key = value("TURN_CERT"), value("TURN_PKEY")
    if cert or key:
        if not cert or not key or not Path(cert).is_file() or not Path(key).is_file():
            raise ValueError("TURN_CERT와 TURN_PKEY는 읽을 수 있는 인증서/키 파일이어야 합니다")
        tls = port("TURN_TLS_PORT", 5349)
        if tls == listen or low <= tls <= high:
            raise ValueError("TLS 포트는 다른 TURN 포트와 겹칠 수 없습니다")
        lines += [f"tls-listening-port={tls}", f"cert={cert}", f"pkey={key}", "no-dtls", "no-tlsv1", "no-tlsv1_1"]
        urls.append(f"turns:{host}:{tls}?transport=tcp")
    else:
        lines += ["no-tls", "no-dtls"]
    return "\n".join(lines) + "\n", ",".join(urls)


if __name__ == "__main__":
    try:
        config, urls = configuration(os.environ)
        path = Path(sys.argv[1])
        # 기존 파일도 쓰기 전에 600으로 제한한다.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(config)
        print(urls)
    except (ValueError, OSError) as exc:
        sys.exit(f"TURN 설정 오류: {exc}")
