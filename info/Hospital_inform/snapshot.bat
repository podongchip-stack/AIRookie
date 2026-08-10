@echo off
REM E-Gen 스냅샷 1회 수집. Windows 작업 스케줄러에 이 파일을 등록해서 쓴다.
REM
REM   작업 스케줄러 > 작업 만들기
REM     트리거 : 매일, 반복 간격 10분, 기간 무기한
REM     동작   : 프로그램 시작 -> 이 .bat 파일
REM
REM 스케줄러 대신 콘솔에 띄워두고 싶으면 아래를 직접 실행한다.
REM   python info\snapshot.py --interval 600

setlocal
set PYTHON=C:\Users\user\anaconda3\envs\dev\python.exe
set PYTHONIOENCODING=utf-8

cd /d "%~dp0"
REM 로그 리다이렉트가 폴더보다 먼저 평가되므로 여기서 미리 만들어 둔다
if not exist "info\data\snapshots" mkdir "info\data\snapshots"
"%PYTHON%" info\snapshot.py >> info\data\snapshots\poller.log 2>&1
endlocal
