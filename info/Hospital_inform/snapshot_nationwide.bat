@echo off
REM 이 파일은 반드시 CRLF 줄바꿈으로 저장한다. LF만 있으면 cmd가 줄을 제대로 끊지
REM 못해 주석 조각이 명령으로 실행된다. 편집기 설정 확인 필요.
REM
REM E-Gen 전국 스냅샷 1회 수집. Windows 작업 스케줄러에 이 파일을 등록해서 쓴다.
REM
REM   작업 스케줄러 > 작업 만들기
REM     트리거 : 매일, 반복 간격 20분, 기간 무기한
REM     동작   : 프로그램 시작 -> 이 .bat 파일
REM
REM 서울 전용 snapshot.bat 과의 차이는 인자 두 개뿐이다.
REM   --stage1 을 비우면 전국이 1회 호출로 온다. 호출 횟수는 서울만 받을 때와 같다.
REM   --dir 로 저장 폴더를 나눠 서울 데이터와 섞이지 않게 한다.
REM
REM 전국이 서울을 포함하므로 분석할 때 hpid 접두어 A11 로 걸러 쓰면 된다.
REM 20분 주기 기준 하루 145회.

setlocal
set PYTHON=C:\Users\user\anaconda3\envs\dev\python.exe
set PYTHONIOENCODING=utf-8

cd /d "%~dp0"
REM 로그 리다이렉트가 폴더보다 먼저 평가되므로 여기서 미리 만들어 둔다
if not exist "info\data\snapshots_nationwide" mkdir "info\data\snapshots_nationwide"
"%PYTHON%" info\snapshot.py --stage1 "" --dir "info\data\snapshots_nationwide" >> info\data\snapshots_nationwide\poller.log 2>&1
endlocal
