# 학습·검증 자료 DB 등록

2026-10-22 팀원 카탈로그 구현 `origin/codex/local-db-validation@3bddc0d`를 재사용해 기존 Supabase PostgreSQL의 `twinsight` 스키마에 등록했다. 테이블·권한·RLS는 변경하지 않았으며 `DATABASE_AUTO_CREATE=false`를 유지했다.

## 저장 결과

| 항목 | 등록 수 |
| --- | ---: |
| 데이터셋 버전 | 9 |
| YOLO 정답 라벨 | 2,487 |
| 학습 / 검증 / 시험 라벨 | 1,543 / 472 / 472 |
| 정답 객체 박스 | 7,050 |
| 카탈로그 기록 | 240 |
| 파일 참조 | 12,822 |
| 로그 행 | 10,470 |
| 기록 간 연결 | 337 |

라벨 수는 데이터셋 버전별 합계다. 보강 데이터셋에서 같은 원본이 재사용되므로 서로 다른 원본 이미지 2,487장이라는 의미는 아니다. 카탈로그 240건은 시뮬레이션 1, 수집 165, 데이터셋 및 라벨 묶음 49, 모델 10, 학습 7, 실제 영상 추론 4, 평가 4건이다.

DB에는 **YOLO 라벨 원문과 정규화 박스, 데이터 분할, 설정·출처, 파일 경로·크기·SHA256, 학습 로그, 검출·평가 결과**가 들어 있다. 라벨 원문은 줄바꿈까지 보존하고 원본 해시와 대조했다. 초기 실험·중간 모델은 초안 상태와 출처를 함께 기록했다.

**이미지·영상·모델 가중치의 바이너리는 DB에 업로드하지 않았다.** 별도 파일 서버가 없어 원본은 `D:\Capston disign`에 보관한다. `catalog_files.path`는 이 폴더 기준 상대 경로이며 다른 PC에서 바로 열리는 URL이 아니다. 다른 PC에서 원본을 쓰려면 해당 파일 전달 또는 별도 Storage 업로드가 필요하다. 파일 저장 방식은 각 기록의 `details.storage`에도 명시했다.

합성 라벨은 자동 생성된 정답이며 사람의 전체 검수를 완료했다고 표시하지 않았다. 실제 CCTV는 정답 라벨이 없어 추론 결과와 평가 관찰만 등록했다. 실제 CCTV 사고 인식 정확도나 재현율이 검증됐다는 의미는 아니다. 사용하지 않은 공개 데이터와 이미지가 없는 수집 1건은 제외했다.

새 연결로 전체 수량과 라벨 해시를 확인했다. 같은 자료를 재등록해 신규 기록 0건으로 중복 방지도 확인했다. [등록 결과](validation/database-registration-20261022/registration-report.json), [새 연결 검증](validation/database-registration-20261022/fresh-connection-verification.json), [재등록 검증](validation/database-registration-20261022/retry-report.json), [기록 목록](validation/database-registration-20261022/registered-records.json)에 근거를 보관했다.

## 조회 예시

기존 앱 역할로 접속해 조회할 수 있다. 비밀번호는 문서·Git에 넣지 않는다.

```sql
SELECT kind, count(*)
FROM twinsight.catalog_records
GROUP BY kind ORDER BY kind;

SELECT record_id, title, data_origin, status,
       details->'split_counts' AS split_counts
FROM twinsight.catalog_records
WHERE kind = 'dataset' AND details->'split_counts' IS NOT NULL;

SELECT r.details->>'dataset' AS dataset,
       r.details->>'split' AS split,
       s->>'image' AS image_path,
       s->>'label' AS label_path,
       s->>'label_text' AS yolo_label,
       s->>'label_sha256' AS label_sha256
FROM twinsight.catalog_records r
CROSS JOIN LATERAL json_array_elements(r.details->'samples') AS s
WHERE r.details->>'type' = 'yolo_split_annotations';
```

## 다시 등록하기

구현은 [register_experiment_catalog.py](../backend/scripts/register_experiment_catalog.py)에 있다. 현재 PC에서는 팀원 API 검증 모델을 `D:\Capston disign\reviews\db-catalog-3bddc0d`에 보존한 스냅샷에서 읽는다. 다른 PC에서는 해당 브랜치 코드 위치를 지정한다. 현재 체크아웃의 이전 백엔드에는 이 카탈로그 모델이 없다.

DB 연결 정보는 Git에서 제외한 저장소 루트 `.env.database`에 보관했다. 기존 대시보드의 `.env`와 분리해 이전 백엔드가 원격 DB 스키마를 자동 생성하지 않게 했다. 필요한 설정 이름은 `DATABASE_URL`, `DATABASE_SCHEMA=twinsight`, `DATABASE_AUTO_CREATE=false`다.

저장소 루트 PowerShell에서 실행한다. 아래 `new-import`는 매번 새 폴더 이름으로 바꾼다. 준비된 스냅샷은 덮어쓰지 않는다.

```powershell
$env:TEMP = 'D:\Capston disign\tmp'
$env:TMP = $env:TEMP
$env:PIP_CACHE_DIR = 'D:\Capston disign\tools\pip-cache'
.\.venv\Scripts\python.exe -X utf8 -m pip install -r backend/requirements-catalog.txt
.\.venv\Scripts\python.exe -X utf8 backend/scripts/register_experiment_catalog.py prepare --team-code-root 'D:/Capston disign/reviews/db-catalog-3bddc0d' --team-code-ref 'origin/codex/local-db-validation@3bddc0d' --manifest runs/new-import/catalog-manifest.json
.\.venv\Scripts\python.exe -X utf8 backend/scripts/register_experiment_catalog.py upload --manifest runs/new-import/catalog-manifest.json --report runs/new-import/registration-report.json
```

업로드는 기존 네 카탈로그 테이블에 한 트랜잭션으로 추가한다. 기존 기록을 삭제하거나 바꾸지 않으며 내용 지문이 다른 동일 ID는 거부한다. 비밀 설정·서명된 CCTV 주소를 제외하고, 파일 해시·라벨·DB 재조회가 일치해야 커밋한다. 원본 수집 자료와 전체 등록 스냅샷은 로컬 `runs/database-registration-20261022`에 있다.
