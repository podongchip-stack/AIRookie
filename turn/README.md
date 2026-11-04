# 골든링크 TURN 서버

아이폰 구급대 앱 → Android 병원 앱(H-병원코드)의 음성 중계용 coturn이다.
통화 신호와 만료형 자격 증명 발급은 기존 hub가 담당한다. 음성은 hub/Cloudflare HTTP 터널을 거치지 않는다.
두 앱을 열어둔 상태에서 시험한다. 푸시 수신·잠금 화면 통화는 별도 작업이다.

## 이 장비에서 start-all과 함께 실행

1. macOS: `brew install coturn`, Ubuntu: `sudo apt install coturn`.
   Ubuntu의 기본 coturn 서비스가 같은 포트를 쓰면 먼저 중지한다.
2. `cp turn/.env.example turn/.env` 후 실제 `TURN_HOST`, `TURN_EXTERNAL_IP`를 입력한다.
3. `openssl rand -hex 32`로 만든 값을 `HUB_TURN_SECRET`에 넣고 `chmod 600 turn/.env` 한다.
4. 도메인은 공인 IP를 가리키는 **DNS only A 레코드**로 설정한다. Cloudflare 프록시/HTTP 터널은 사용하지 않는다.
5. 서버 방화벽과 NAT 공유기에서 TCP/UDP 3478, UDP 49160~49259를 이 장비로 연다.
   NAT는 릴레이 포트 번호를 바꾸면 안 된다. CGNAT 회선은 별도 공인 IP 서버가 필요하다.
6. `./start-all.sh --turn` 실행. 설정이 있으면 평소 `./start-all.sh`도 TURN을 자동 실행한다.

`TURN_EXTERNAL_IP=공인IP/로컬IP`는 NAT 환경, `TURN_EXTERNAL_IP=공인IP`는 공인 IP가 직접 붙은 서버다.
`TURN_BIN`으로 실행 파일 경로를 지정할 수 있다. `--no-turn`은 STUN만 쓰는 개발용이다.
Ctrl-C는 이 실행이 시작한 coturn도 종료한다. `turn.log`와 hub 로그는 기존 `LOG_DIR`에 기록한다.
설정 파일은 실행별 임시 파일(권한 600)이며 종료 때 삭제한다. 공유 비밀값은 앱에 보내지 않는다.

## TLS와 TCP 대안

기본 UDP와 TCP TURN을 모두 제공한다. TCP TURN도 단말↔TURN 구간이 TCP이고 릴레이 포트는 UDP다.
`TURN_CERT`, `TURN_PKEY`에 해당 TURN 도메인의 신뢰할 수 있는 인증서/개인키 경로를 지정하면
`turns:호스트:5349?transport=tcp`도 hub가 광고한다. 이때 TCP 5349도 열어야 한다.
모바일망이 UDP나 일반 TURN 포트를 차단하면, 사용 가능한 전용 IP에서 `TURN_TLS_PORT=443`을 고려한다
(443 충돌·낮은 포트 바인딩 권한은 서버 운영 설정으로 해결). 인증서 발급/갱신은 별도다.

## 별도 공인 서버에서 상시 실행

해당 서버에 coturn과 Python 3를 설치하고 이 폴더를 복사한다. 그 서버에서:

```bash
set -a
source turn/.env
set +a
umask 077
python3 turn/configure.py /tmp/goldenlink-turn.conf
bash turn/start-turn.sh /tmp/goldenlink-turn.conf
```

운영 환경에서는 프로세스 관리자로 실행하고 설정 파일을 보호한다. hub를 실행하는 장비의 `turn/.env`는:

```bash
TURN_MODE=external
HUB_TURN_URLS='turn:실제호스트:3478?transport=udp,turn:실제호스트:3478?transport=tcp'
HUB_TURN_SECRET=서버와동일한비밀값
HUB_TURN_TTL_SEC=3600
```

이 모드의 `start-all.sh`는 hub에 설정을 전달한다. 원격 TURN 서버의 생명주기는 관리하지 않는다.
TLS를 구성했으면 위 URL 목록에 `turns:실제호스트:5349?transport=tcp`를 추가한다.

## 완료 판정

`TURN 로컬 리스너 준비 완료`는 외부 연결 성공을 의미하지 않는다.

- 서로 다른 휴대폰에서 Wi-Fi를 끄고 각각 LTE/5G로 앱을 연결한다.
- iPhone 구급대가 발신, Android 병원 접근 코드로 접속한 수신자가 받기, 양방향 음성 및 양쪽 종료를 확인한다.
- 별도 relay 강제 시험에서 선택된 ICE 후보가 `relay`임을 기록한다. 직접 연결 성공만으로 TURN 검증을 대신하지 않는다.
- UDP 경로와 TCP/TLS 경로를 각각 시험한다. 현재 앱에는 relay 강제 옵션이 없으므로 해당 시험 설정/진단은 후속 작업이다.

설정/연동 단위 검증: `python3 -m unittest discover -s turn -p 'test_*.py'`.
공식 설정 근거: https://github.com/coturn/coturn/blob/master/examples/etc/turnserver.conf
