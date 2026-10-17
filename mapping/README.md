# 공간 매핑 (mapping)

CCTV 화면의 픽셀 좌표를 실제 노면 좌표로 바꾸고(Homography), 가상환경 정답으로 그 오차를 잽니다.

## 설치

```bash
python -m pip install -r mapping/requirements.txt
```

## 실행

**Unity 없이 먼저 해 보기.** Unity 예제 씬과 같은 배치를 Python으로 계산한 합성 데이터입니다. 이미지는 만들지 않습니다.

```bash
python mapping/scripts/make_synthetic_export.py out/synthetic --fake-detections
python mapping/scripts/evaluate_mapping.py out/synthetic --max-distance 80 --sweep --classes car,truck
```

**Unity로 저장한 데이터** ([simulation/TwinSightSim](../simulation/TwinSightSim/README.md)):

```bash
python mapping/scripts/evaluate_mapping.py simulation/TwinSightSim/TwinSightExport/<저장 폴더> --max-distance 80 --sweep
```

**YOLO 검출까지 포함** (차량 3D 에셋으로 저장한 데이터):

```bash
python mapping/scripts/run_yolo_on_frames.py <저장 폴더> --weights yolo11n.pt --classes car,truck,bus
python mapping/scripts/evaluate_mapping.py <저장 폴더> --max-distance 80 --classes car,truck,bus
```

결과는 `<저장 폴더>/mapping_eval/`에 `report.json`(요약), `object_errors.csv`(객체·프레임별 오차)로 저장됩니다.

| 옵션 | 뜻 |
| --- | --- |
| `--n-fit` | Homography에 쓸 기준점 수 (기본 6). 화면 전체에 고르게 퍼진 점을 고릅니다 |
| `--pixel-noise` | 사람이 화면에서 기준점을 찍을 때의 오차(px, 표준편차) |
| `--max-distance` | 카메라에서 이 거리(m) 안의 기준점·객체만 평가 |
| `--classes` | 평가할 클래스. YOLO 평가 때는 검출기가 아는 클래스만 넣어야 재현율이 맞습니다 |
| `--sweep` | 기준점 수(4~16) × 클릭 오차(0~4 px) 조합별 정확도표 |

## 실제 CCTV 캘리브레이션 (미터 단위)

CCTV 파이프라인 화면에서 `c`를 누르면 표시가 없는 원본 프레임이 `captures/<카메라ID>_<시각>.png`로 저장됩니다. 그 이미지로 캘리브레이션합니다. CCTV 파이프라인 폴더에서 실행하면 결과가 그 폴더의 `calibration/`에 저장되고, 다음 실행부터 자동으로 쓰입니다.

```bash
cd C:\Code\Computer_vison.ipynb
python C:\Users\82103\Desktop\Computer-vision\mapping\scripts\calibrate_homography.py --image captures\utic-1294_20261017_221500.png --latlon
```

1. 창에서 노면 위의 점을 찍습니다. 왼쪽 클릭으로 추가하고, 오른쪽 클릭이나 `u`로 지우고, `Enter`로 끝냅니다. 화면 구석의 돋보기로 정확한 픽셀을 고릅니다.
2. 콘솔에서 점마다 실제 좌표를 입력합니다. `--latlon`이면 지도(브이월드 항공사진, 카카오맵, 네이버지도)에서 읽은 `위도 경도`를, 없으면 직접 정한 좌표계의 `x z`(m)를 입력합니다.
3. 점마다 잔차와 **leave-one-out 오차**(그 점을 빼고 구한 Homography로 그 점을 맞혔을 때의 오차)가 표로 나옵니다. 다른 점보다 유난히 큰 점은 경고가 뜨니 다시 찍거나 좌표를 확인합니다.
4. `calibration/<카메라ID>.json`, 점 목록 `<카메라ID>.points.csv`, 위에서 본 그림 `<카메라ID>_birdseye.png`가 저장됩니다. 그림에서 차선이 평행하고 격자가 고르게 보이면 대체로 맞은 것입니다. CSV를 고친 뒤 `--points`로 다시 계산할 수 있습니다.

점은 **6개 이상**, 화면의 가까운 곳·먼 곳·좌우에 고르게, **같은 노면 위**에서만 찍습니다(가드레일·터널 입구처럼 높이가 다른 점은 쓰지 않음). 합성 데이터 결과로는 기준점 수보다 찍는 정확도가 오차를 더 크게 좌우합니다.

## 결과 읽는 법

객체 위치 오차를 세 가지로 나눠 봅니다. 위에서 아래로 갈수록 실제 파이프라인에 가깝습니다.

| 모드 | 변환하는 픽셀 | 남는 오차 |
| --- | --- | --- |
| `ground_pixel` | 정답 바닥점 | Homography 자체(평면 가정, 기준점) |
| `bbox_bottom` | 정답 박스의 아래 가운데 | + "박스 아래 = 객체 위치"라는 가정 |
| `detection` | YOLO 박스의 아래 가운데 | + 검출 오차 |

오차는 카메라에서 객체를 보는 방향으로 **종방향**(앞뒤), 그에 수직인 **횡방향**(좌우)으로도 나눕니다. 종방향 편향이 음수면 실제보다 카메라 쪽으로 추정한다는 뜻입니다.

`bbox_bottom`, `detection`에는 아래 편향 보정을 적용한 결과(`+view`, `+track`, `+road`)도 함께 나옵니다. 거리 구간별, 클래스별 표도 출력됩니다.

## 박스 아래 가운데 편향 보정

검출 박스의 아래 가장자리는 차체 중심이 아니라 **카메라에서 가장 가까운 바닥 모서리**입니다. 그래서 박스 아래 가운데를 변환하면 실제 위치보다 카메라 쪽(차체 길이의 절반 안팎)으로 나옵니다. `twinsight_mapping/correction.py`가 이를 기하학적으로 보정합니다.

1. 화면의 한 행은 노면에서 카메라 깊이 방향에 수직인 직선입니다. 차량 중심은 박스 아래 행보다 **바닥면이 깊이 방향으로 차지하는 반폭** `s = 길이/2·|cos φ| + 폭/2·|sin φ|`만큼 더 깊습니다(φ: 차량 진행 방향과 깊이 방향의 각).
2. 화면의 한 열은 노면에서 한 점 `O = H·[0, 1, 0]`을 지납니다. 차량 중심은 `O`에서 추정점으로 뻗은 직선 위에 있습니다.
3. 따라서 추정점을 `O`에서 멀어지는 방향으로, 깊이가 `s`만큼 늘 때까지 밉니다.

차량 진행 방향은 **추적 ID로 구한 이동 방향**을 먼저 쓰고, 없으면 **도로 방향**(캘리브레이션의 `road_heading_deg`), 그것도 없으면 깊이 방향과 같다고 가정합니다(`s = 길이/2`). 차량 크기는 클래스별 대표값(승용차 4.6×1.85 m, 화물차 7.0×2.5 m, 버스 11×2.5 m 등)을 쓰고, `--dims car=4.5x1.8`로 바꿀 수 있습니다. 화면 가장자리에 닿은 박스는 잘렸을 수 있어 진행 방향 계산에서 뺍니다.

**Unity 데이터 검증** (예제 씬 288프레임, 80 m 이내, 대표 크기 사용, 도로 방향 0°)

| 방식 | 평균 오차 | p95 | 종방향 편향 | 승용차 | 화물차 |
| --- | --- | --- | --- | --- | --- |
| 보정 없음 | 2.15 m | 4.15 m | -2.15 m | 2.37 m | 4.15 m |
| 보정 (시선 방향 가정) | 0.27 m | 0.67 m | -0.21 m | 0.11 m | 0.68 m |
| 보정 (추적 방향) | 0.25 m | 0.56 m | -0.13 m | 0.11 m | 0.57 m |
| 보정 (도로 방향) | 0.25 m | 0.55 m | -0.13 m | 0.11 m | 0.56 m |

- 화물차에 남는 0.5 m 남짓은 대표 길이(7 m)와 예제 화물차 길이(8 m)의 차이 때문입니다. 실제 크기(`--dims car=4.5x1.8,truck=8x2.5`)를 주면 승용차 0.09 m, 화물차 0.25 m까지 내려갑니다.
- 평균에는 보정 대상이 아닌 포트홀(0.36 m, 크기 정보 없음)이 섞여 있습니다.

**크기 변동과 검출 흔들림이 있을 때** (합성 데이터: 차량 길이·폭 ±10%, 검출 박스 ±2 px, 승용차·화물차, 80 m 이내)

| 방식 | 정답 박스 | 흔든 검출 박스 |
| --- | --- | --- |
| 보정 없음 | 2.97 m | 2.93 m |
| 보정 (도로 방향) | 0.34 m | 0.57 m |

검출 박스로는 멀수록 남는 오차가 커집니다(60~80 m에서 0.76 m). 먼 곳에서는 박스가 몇 픽셀만 흔들려도 위치가 크게 바뀌기 때문입니다.

실제 CCTV 파이프라인(`CCTV` 스크립트)은 미터 단위 캘리브레이션이 있으면 같은 보정을 적용해 `detections.jsonl`에 `mapped_xz_corrected`로 기록합니다. 화면 표시와 디지털 트윈용 좌표에도 보정한 값을 씁니다.

## 합성 데이터로 확인한 점

Unity 예제 씬과 같은 배치(높이 8 m, 15° 내려다봄, 세로 화각 45°, 1920×1080)의 합성 데이터에서 80 m 이내를 평가한 결과입니다. Unity 렌더링 결과가 아니므로 경향 확인용입니다.

1. **평평한 도로에서는 Homography 자체 오차가 0입니다.** 기준점을 정확히 찍으면 정답 바닥점 변환 오차가 0.000 m입니다.
2. **박스 아래 가운데를 객체 위치로 쓰면 평균 2.7 m 틀립니다(차량).** 오차는 거의 전부 종방향 -2.7 m입니다. 박스의 아래 가장자리는 차체 중심이 아니라 카메라 쪽 차체 끝이기 때문입니다(승용차 길이 4.5 m의 절반, 화물차 8 m의 절반 정도). 거리와 상관없이 일정해서 보정할 수 있습니다(위의 "박스 아래 가운데 편향 보정" 참고).
3. **기준점 수보다 클릭 오차가 더 큰 변수입니다.** 기준점을 4개에서 16개로 늘려도 오차는 조금만 줄어듭니다.

   | 기준점 수 | 0 px | 1 px | 2 px | 4 px |
   | --- | --- | --- | --- | --- |
   | 4 | 0.00 | 0.20 | 0.37 | 0.64 |
   | 8 | 0.00 | 0.18 | 0.36 | 0.68 |
   | 16 | 0.00 | 0.16 | 0.31 | 0.62 |

   (사용하지 않은 기준점의 평균 노면 오차, m. 조합마다 50회 반복)
4. **도로가 평면이 아니면 먼 구간부터 틀어집니다.** 40 m 지점부터 노면이 위로 휘는 도로(80 m에서 0.16 m 높음, `--sag 0.0001`)는 0~20 m 오차가 0.007 m인데 40~60 m에서는 0.22 m입니다. 언덕이나 곡선 구간이 있는 CCTV는 구간을 나눠 Homography를 따로 구하는 방안이 필요할 수 있습니다.

## 테스트

```bash
python -m unittest discover -s mapping/tests
```

## 파일

```
mapping/
  twinsight_mapping/
    dataset.py      내보내기 폴더 읽기 (docs/data_format.md)
    homography.py   Homography 계산, 픽셀 → 노면 변환, 기준점 고르기
    evaluate.py     오차 계산, 검출-정답 짝짓기, 거리 구간별 통계
    synthetic.py    Unity 없이 같은 형식의 합성 데이터 생성
    calibration.py  실제 CCTV 캘리브레이션: 위도·경도 → 미터, leave-one-out 오차, 위에서 본 그림
    correction.py   박스 아래 가운데의 카메라 쪽 편향 보정, 추적 ID별 진행 방향
  scripts/
    evaluate_mapping.py       평가 실행
    make_synthetic_export.py  합성 데이터 만들기
    run_yolo_on_frames.py     가상환경 프레임에 YOLO 실행 → detections.jsonl
    calibrate_homography.py   실제 CCTV 화면에서 점 찍기 → calibration/<카메라ID>.json
  tests/
    test_mapping.py
    test_calibration.py
    test_correction.py
```
