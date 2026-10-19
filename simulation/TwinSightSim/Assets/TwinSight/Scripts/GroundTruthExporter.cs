using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace TwinSight.Simulation
{
    /// <summary>
    /// 가상 CCTV 카메라에 붙인다. 프레임 이미지, 프레임별 정답(ground_truth.jsonl), 카메라 정보,
    /// 노면 기준점을 docs/data_format.md 형식으로 저장한다.
    /// 에디터에서는 Game 뷰가 열려 있어야 프레임이 저장된다(WaitForEndOfFrame).
    /// </summary>
    [RequireComponent(typeof(Camera))]
    public class GroundTruthExporter : MonoBehaviour
    {
        [Header("카메라")]
        public string cameraId = "virtual-cam-01";
        public int imageWidth = 1920;
        public int imageHeight = 1080;

        [Header("저장")]
        [Tooltip("상대 경로면 Unity 프로젝트 폴더 기준")]
        public string outputRoot = "TwinSightExport";
        public float captureFps = 10f;
        [Tooltip("이 시간(초)이 지난 뒤부터 저장한다. 차량이 도로에 퍼질 때까지 기다리는 용도")]
        public float warmupSeconds = 15f;
        [Tooltip("0이면 Play를 멈출 때까지 저장")]
        public int maxFrames = 300;
        public bool saveImages = true;
        [Range(50, 100)] public int jpgQuality = 95;
        public bool stopPlayModeWhenDone = true;
        public bool manualCapture;

        [Header("정답")]
        public CalibrationGrid calibrationGrid;
        [Tooltip("가로나 세로가 이보다 작은 박스(px)는 내보내지 않는다")]
        public float minBoxSize = 2f;

        Camera cam;
        RenderTexture target;
        Texture2D readback;
        StreamWriter gtWriter;
        string runDir;
        int frame;
        bool done;
        TrafficSignalController signals;
        RoadScenarioDirector scenarios;
        [SerializeField, HideInInspector] bool recording;
        readonly List<Vector3> pointBuffer = new List<Vector3>();

        void Start()
        {
            cam = GetComponent<Camera>();
            signals = FindFirstObjectByType<TrafficSignalController>();
            scenarios = FindFirstObjectByType<RoadScenarioDirector>();
            target = new RenderTexture(imageWidth, imageHeight, 24, RenderTextureFormat.ARGB32);
            target.Create();
            readback = new Texture2D(imageWidth, imageHeight, TextureFormat.RGB24, false);

            // 저장 속도와 상관없이 프레임마다 시뮬레이션 시간이 1/fps씩 흐르게 한다
            Time.captureDeltaTime = 1f / captureFps;

            string root = Path.IsPathRooted(outputRoot)
                ? outputRoot
                : Path.Combine(Directory.GetParent(Application.dataPath).FullName, outputRoot);
            runDir = Path.Combine(root, $"{cameraId}_{DateTime.Now:yyyyMMdd_HHmmss}");
            Directory.CreateDirectory(Path.Combine(runDir, "frames"));

            // 카메라 정보와 기준점은 저장 해상도의 화면비 기준으로 계산한다
            cam.aspect = (float)imageWidth / imageHeight;
            WriteJson("camera.json", BuildCameraInfo());
            WriteJson("control_points.json", BuildControlPoints());
            if (scenarios != null) WriteJson("scenario_config.json", scenarios.Snapshot());
            cam.ResetAspect();
            gtWriter = new StreamWriter(Path.Combine(runDir, "ground_truth.jsonl"));
            Debug.Log($"TwinSight: 저장 위치 {runDir}");

            recording = true;
            if (!manualCapture) StartCoroutine(CaptureLoop());
        }

        public void CaptureOneForDataset()
        {
            if (!manualCapture || gtWriter == null || done) throw new InvalidOperationException("Manual exporter is not ready.");
            CaptureFrame(); frame++;
        }
        public void CompleteManualDataset() { if (manualCapture && !done) Finish(); }

        void Update()
        {
            // Play 중에 스크립트가 다시 컴파일되면 저장 코루틴과 파일이 사라져 이어서 저장할 수 없다
            if (!recording || done || gtWriter != null) return;
            done = true;
            Debug.LogError("TwinSight: Play 중에 스크립트가 다시 컴파일되어 저장이 중단됐습니다. " +
                           "Play를 다시 눌러 처음부터 저장하세요. (Preferences > General > Script Changes While Playing을 " +
                           "'Recompile After Finished Playing'으로 바꾸면 이런 일이 없습니다)");
#if UNITY_EDITOR
            UnityEditor.EditorApplication.isPlaying = false;
#endif
        }

        IEnumerator CaptureLoop()
        {
            var endOfFrame = new WaitForEndOfFrame();
            while (!done)
            {
                yield return endOfFrame;
                if (Time.time < warmupSeconds) continue;
                CaptureFrame();
                frame++;
                if (maxFrames > 0 && frame >= maxFrames) Finish();
            }
        }

        void CaptureFrame()
        {
            var record = new FrameRecord
            {
                camera_id = cameraId,
                frame = frame,
                timestamp = Time.time,
                width = imageWidth,
                height = imageHeight,
                signals = signals != null ? signals.Snapshot() : null,
                scenario = scenarios != null ? scenarios.Snapshot() : null,
            };

            // 저장 해상도의 화면비로 잠시 바꿔 텍스처에 한 번 더 렌더링한다. Game 뷰는 평소대로 그려진다.
            cam.aspect = (float)imageWidth / imageHeight;
            Matrix4x4 viewProjection = cam.projectionMatrix * cam.worldToCameraMatrix;
            if (saveImages)
            {
                record.image = $"frames/{frame:D6}.jpg";
                var previousTarget = cam.targetTexture;
                cam.targetTexture = target;
                cam.Render();
                cam.targetTexture = previousTarget;

                var previous = RenderTexture.active;
                RenderTexture.active = target;
                readback.ReadPixels(new Rect(0, 0, imageWidth, imageHeight), 0, 0, false);
                readback.Apply(false);
                RenderTexture.active = previous;
                File.WriteAllBytes(Path.Combine(runDir, record.image), readback.EncodeToJPG(jpgQuality));
            }
            cam.ResetAspect();

            foreach (var obj in TrackedObject.All)
            {
                var item = BuildObjectRecord(obj, viewProjection);
                if (item != null) record.objects.Add(item);
            }

            gtWriter.WriteLine(JsonUtility.ToJson(record));
            gtWriter.Flush();
        }

        ObjectRecord BuildObjectRecord(TrackedObject obj, Matrix4x4 viewProjection)
        {
            pointBuffer.Clear();
            obj.CollectWorldPoints(pointBuffer);

            float xMin = float.MaxValue, yMin = float.MaxValue;
            float xMax = float.MinValue, yMax = float.MinValue;
            int projected = 0;
            foreach (var p in pointBuffer)
            {
                if (!TryProject(viewProjection, p, out var px)) continue;
                projected++;
                xMin = Mathf.Min(xMin, px.x);
                yMin = Mathf.Min(yMin, px.y);
                xMax = Mathf.Max(xMax, px.x);
                yMax = Mathf.Max(yMax, px.y);
            }
            if (projected == 0) return null;
            if (xMax <= 0f || yMax <= 0f || xMin >= imageWidth || yMin >= imageHeight) return null;

            float x1 = Mathf.Clamp(xMin, 0f, imageWidth), y1 = Mathf.Clamp(yMin, 0f, imageHeight);
            float x2 = Mathf.Clamp(xMax, 0f, imageWidth), y2 = Mathf.Clamp(yMax, 0f, imageHeight);
            if (x2 - x1 < minBoxSize || y2 - y1 < minBoxSize) return null;

            var record = new ObjectRecord
            {
                track_id = obj.TrackId,
                class_name = obj.className,
                bbox_xyxy = new[] { x1, y1, x2, y2 },
                truncated = projected < pointBuffer.Count
                            || x1 != xMin || y1 != yMin || x2 != xMax || y2 != yMax,
                ground_point_world = new float[0],
                ground_point_pixel = new float[0],
            };

            if (obj.TryGetGroundPoint(out var ground))
            {
                record.ground_point_world = ToArray(ground);
                if (TryProject(viewProjection, ground, out var gp))
                {
                    record.ground_point_pixel = new[] { gp.x, gp.y };
                    record.ground_point_in_frame = InFrame(gp);
                }
            }
            return record;
        }

        /// <summary>월드 점 → 픽셀(왼쪽 위 원점). 카메라 뒤에 있으면 false.</summary>
        bool TryProject(Matrix4x4 viewProjection, Vector3 world, out Vector2 pixel)
        {
            Vector4 clip = viewProjection * new Vector4(world.x, world.y, world.z, 1f);
            pixel = default;
            if (clip.w <= 1e-5f) return false;
            pixel = new Vector2(
                (clip.x / clip.w * 0.5f + 0.5f) * imageWidth,
                (0.5f - clip.y / clip.w * 0.5f) * imageHeight);
            return true;
        }

        bool InFrame(Vector2 p) => p.x >= 0f && p.x < imageWidth && p.y >= 0f && p.y < imageHeight;

        CameraInfo BuildCameraInfo()
        {
            Matrix4x4 p = cam.projectionMatrix;
            Matrix4x4 v = cam.worldToCameraMatrix;

            // Unity 뷰 공간(y 위, -z 방향을 봄) → OpenCV 카메라 좌표(y 아래, z 앞)
            var worldToCameraCv = new float[12];
            for (int r = 0; r < 3; r++)
            {
                float sign = r == 0 ? 1f : -1f;
                for (int c = 0; c < 4; c++) worldToCameraCv[r * 4 + c] = sign * v[r, c];
            }

            return new CameraInfo
            {
                camera_id = cameraId,
                scene = SceneManager.GetActiveScene().name,
                unity_version = Application.unityVersion,
                image_width = imageWidth,
                image_height = imageHeight,
                vertical_fov_deg = cam.fieldOfView,
                capture_fps = captureFps,
                fx = p[0, 0] * imageWidth * 0.5f,
                fy = p[1, 1] * imageHeight * 0.5f,
                cx = (1f - p[0, 2]) * imageWidth * 0.5f,
                cy = (1f + p[1, 2]) * imageHeight * 0.5f,
                position = ToArray(transform.position),
                rotation_euler_deg = ToArray(transform.eulerAngles),
                forward = ToArray(transform.forward),
                world_to_camera_cv = worldToCameraCv,
            };
        }

        ControlPointFile BuildControlPoints()
        {
            var file = new ControlPointFile { camera_id = cameraId };
            if (calibrationGrid == null)
            {
                Debug.LogWarning("GroundTruthExporter: calibrationGrid가 비어 있어 기준점을 저장하지 않습니다.", this);
                return file;
            }

            Matrix4x4 viewProjection = cam.projectionMatrix * cam.worldToCameraMatrix;
            var points = calibrationGrid.Points;
            for (int i = 0; i < points.Count; i++)
            {
                bool ok = TryProject(viewProjection, points[i], out var px);
                file.points.Add(new ControlPoint
                {
                    id = i,
                    world = ToArray(points[i]),
                    pixel = ok ? new[] { px.x, px.y } : new float[0],
                    in_frame = ok && InFrame(px),
                });
            }
            return file;
        }

        void Finish()
        {
            done = true;
            recording = false;
            CloseWriter();
            Time.captureDeltaTime = 0f;
            Debug.Log($"TwinSight: {frame}프레임 저장 완료 → {runDir}");
#if UNITY_EDITOR
            if (stopPlayModeWhenDone) UnityEditor.EditorApplication.isPlaying = false;
#endif
        }

        void OnGUI()
        {
            if (Event.current.type != EventType.Repaint) return;
            string status = done ? "Done"
                : Time.time < warmupSeconds ? $"Warming up {Time.time:F0}/{warmupSeconds:F0}s"
                : $"Recording {frame}/{maxFrames}";
            GUI.Label(new Rect(10, 10, 400, 24), status);
        }

        void OnDestroy()
        {
            CloseWriter();
            Time.captureDeltaTime = 0f;
            if (cam != null) cam.ResetAspect();
            if (target != null)
            {
                target.Release();
                Destroy(target);
            }
            if (readback != null) Destroy(readback);
        }

        void CloseWriter()
        {
            if (gtWriter == null) return;
            gtWriter.Dispose();
            gtWriter = null;
        }

        void WriteJson(string fileName, object data) =>
            File.WriteAllText(Path.Combine(runDir, fileName), JsonUtility.ToJson(data, true));

        static float[] ToArray(Vector3 v) => new[] { v.x, v.y, v.z };
    }
}
