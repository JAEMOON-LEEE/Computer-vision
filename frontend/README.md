# TwinSight 관제 화면

Vite + React + TypeScript 대시보드입니다. 이전 정적 화면은 [frontend-proto](../frontend-proto/README.md)에 그대로 두었습니다.

박스는 오버레이 확인용 목업이며 실제 영상 속 물체와 위치가 맞지 않습니다. 이력 표는 `GET /detections`, 차트는 `GET /detections/stats`로 저장된 검출을 조회합니다.

## 실행

백엔드 주소는 저장소 루트 `.env`의 `VITE_API_BASE`입니다. 없으면 `http://localhost:8000`을 씁니다. 예시는 [frontend/.env.example](.env.example)에 있습니다.

지도 타일은 `.env`에 `VITE_CARTO_KEY`가 있으면 CARTO 밝은 지도(light_all), 없으면 OpenStreetMap 기본 지도를 씁니다. 키 없이도 지도는 뜹니다. CARTO 키는 https://www.carto.com/basemaps/apikey/ 에서 이메일로 무료 발급받고, 키는 커밋하지 않습니다.

저장소 루트에서 `dev.bat`을 더블클릭하면 백엔드, 이 화면, 목업 재생이 함께 뜹니다. 목업 없이 띄우려면 `dev.bat nomock`입니다.

직접 띄울 때는 저장소 루트에서 백엔드를 실행하고, `frontend`에서 `npm install` 후 `npm run dev`를 실행합니다. 주소는 http://localhost:5173 입니다. `127.0.0.1`로 열면 CORS에 막힙니다.

## 화면

- 관제: 지도의 카메라 마커와 선택 카메라 패널로 고릅니다. 패널의 영상 하나만 HLS를 요청하고, 검출 박스는 캔버스에 유지하다가 500ms 동안 새 검출이 없으면 지웁니다. 미확인 경고는 오른쪽 서랍과 위험 이벤트 표에서 확인·기각합니다.
- 분석: 위험도 히트맵, 반복 구간, 시간대·유형 통계입니다. 캘리브레이션이 없으면 예시 좌표를 씁니다.
- 이력: 카메라·클래스·기간으로 `GET /detections`를 거르고, 클래스별·KST 1시간별 개수는 `GET /detections/stats`로 그립니다. 시각은 KST입니다.

저장소 루트 `.env`의 `VITE_DEMO_TWIN=1`이면 위치·반복 구간처럼 아직 없는 값을 예시로 채웁니다. `0`이거나 없으면 그 자리는 "데이터 없음"입니다.
- 오른쪽 아래 지연 패널은 검출 시각부터 캔버스에 그린 시점까지를 모읍니다. `timestamp_kind`가 `unix_seconds`가 아니면 메시지 수신 시각을 기준으로 합니다. CSV 버튼은 브라우저 콘솔에 찍습니다.

## 발표 시연 화면 (/demo)

http://localhost:5173/demo 에서 Unity City Lab이 브라우저 안에서 돌아갑니다. 백엔드·인터넷·ITS 키 없이 동작합니다.

- **City Lab 사고 시나리오:** 오른쪽 주의표지판을 누르면 Unity에 포트홀·낙하물·시설물 파손(시선유도봉·가드레일)·맨홀 이상이 생깁니다. 표지판 아래 변형 버튼으로 포트홀 크기, 낙하물 모양, 가드레일 휨·떨어짐, 맨홀 뚜껑 열림·들뜸·주변 침하를 고릅니다. 시설물 파손과 맨홀은 검출 모델이 아직 학습하지 않은 시연용 장면입니다(`DemoRoadHazards.cs`). 카메라(사고 지점·회전·가상 CCTV·전체)와 주간·야간을 바꿀 수 있습니다.
- **Unity 시나리오 기록**은 Unity가 남기는 정답 기록(생성·접촉 시점)이며 검출 모델의 경고가 아닙니다. 그 아래 "모델 검증 결과"는 합성 영상으로 확인한 주간·야간 결과입니다.
- **금촌 CCTV 디지털 트윈:** 실제 금촌신사거리 CCTV 검출 차량을 같은 자세의 가상 CCTV 앞에 다시 놓은 장면입니다. 주황 = Unity에 놓은 차량, 초록 = 실제 YOLO 박스, 오른쪽 위 = 같은 프레임의 실제 화면.

WebGL 빌드(약 220 MB)는 용량이 커서 Git에 없습니다. 각자 만들거나 팀 드라이브에서 `frontend/public/unity/`로 복사합니다. Unity 에디터를 끄고 저장소 루트에서:

```powershell
& "C:\Program Files\Unity\Hub\Editor\6000.6.6f1\Editor\Unity.exe" -batchmode -projectPath simulation/TwinSightSim -buildTarget WebGL -rebuildCityLab -executeMethod TwinSight.Simulation.EditorTools.WebDemoBuild.BuildFromCommandLine -logFile webgl-build.log
```

`-rebuildCityLab`은 City Lab 씬을 최신 코드로 다시 만듭니다(씬이 이미 최신이면 빼도 됩니다). 에디터에서는 **TwinSight → Web → Build WebGL Demo**입니다. 첫 빌드는 WebGL용 에셋 가져오기 때문에 10분 이상 걸립니다. Unity WebGL 모듈(Unity Hub → 설치 → 모듈 추가 → WebGL Build Support)이 필요합니다.

빌드를 새로 만든 뒤에는 `npm run dev`를 다시 시작해야 새 파일이 서빙됩니다(Vite는 이 폴더를 감시하지 않습니다).

사고 버튼을 누르면 Unity 화면 왼쪽 아래에 같은 종류의 실제 CCTV 영상이 함께 재생됩니다(위쪽 "실제 CCTV 영상" 버튼으로 끄고 켭니다). 영상은 팀 공유 드라이브 "CCTV영상" 폴더의 파일을 `frontend/public/demo-videos/`에 아래 이름으로 넣습니다(Git 제외). 파일이 없으면 패널이 나타나지 않습니다.

| 파일 | 드라이브 원본 |
| --- | --- |
| `pothole.mp4` | 포트홀.mp4 |
| `debris.mp4` | 낙하물.mp4 |
| `delineator.mp4` | 시선 윧봉 손상.mp4 |
| `guardrail.mp4` | 가드레일 손상.mp4 |
| `manhole.mp4` | 맨홀 뚜껑 손상.mp4 |

이 영상은 비교용 참고 자료이며 검출 결과가 아닙니다. 맨홀 영상은 KBS 뉴스 화면이니 발표 자료에 출처를 적습니다.
