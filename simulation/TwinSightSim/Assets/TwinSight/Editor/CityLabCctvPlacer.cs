using System;
using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace TwinSight.Simulation.EditorTools
{
    /// <summary>
    /// 실제 CCTV의 도로 기준 자세(mapping/scripts/road_relative_pose.py가 만든 *.road_pose.json)로
    /// City Lab의 VirtualCCTV를 배치한다. 실제 도로 중앙선 ↔ City Lab 주황 중앙선, 실제 도로 앞쪽 ↔ City Lab +X.
    /// </summary>
    public class CityLabCctvPlacer : EditorWindow
    {
        [Serializable]
        class RoadPose
        {
#pragma warning disable 0649
            public string camera_id, virtual_camera_id;
            public float road_bearing_deg, along_m, lateral_m, height_m, yaw_to_road_deg, pitch_deg, roll_deg;
            public float vertical_fov_deg, horizontal_fov_deg, ref_ahead_m;
            public int[] image_size;
            public bool has_ref;
#pragma warning restore 0649
        }

        const string PathKey = "TwinSight.CctvPlacer.PosePath";
        const string PreviewPath = "Logs/virtual_cctv_preview.png";
        // 프로젝트 폴더의 RealCctv/*.road_pose.json을 자동으로 목록에 보여 준다
        static string RealCctvDir => Path.Combine(Directory.GetParent(Application.dataPath).FullName, "RealCctv");

        string posePath;
        string[] found = Array.Empty<string>();
        RoadPose pose;
        string loadError, lastResult;
        Vector2 scroll;

        [Tooltip("실제 1차로 폭 3.5 m ÷ City Lab 차로 폭 1.2단위. SUV(4.7 m/1.6) 비율과도 같다")]
        float metersPerUnit = 2.92f;
        float groundY = 0.507f;
        bool keepRealDistance = true;
        float minX = -17f, maxX = 26f, fixedX = -15f;
        bool matchResolution = true;

        [MenuItem("TwinSight/City Lab/Place VirtualCCTV From Real CCTV...")]
        static void Open() => GetWindow<CityLabCctvPlacer>("실제 CCTV → City Lab").Show();

        void OnEnable()
        {
            posePath = EditorPrefs.GetString(PathKey, "");
            FindFiles();
            if ((string.IsNullOrEmpty(posePath) || !File.Exists(posePath)) && found.Length > 0) Select(found[0]);
            Load();
        }

        void FindFiles() =>
            found = Directory.Exists(RealCctvDir) ? Directory.GetFiles(RealCctvDir, "*.road_pose.json") : Array.Empty<string>();

        void Select(string path)
        {
            posePath = path;
            EditorPrefs.SetString(PathKey, posePath);
            Load();
        }

        void Load()
        {
            pose = null; loadError = null;
            if (string.IsNullOrEmpty(posePath)) return;
            try { pose = JsonUtility.FromJson<RoadPose>(File.ReadAllText(posePath)); }
            catch (Exception e) { loadError = e.Message; }
        }

        void OnGUI()
        {
            scroll = EditorGUILayout.BeginScrollView(scroll);
            EditorGUILayout.HelpBox("mapping/scripts/road_relative_pose.py가 만든 <카메라ID>.road_pose.json을 고르면, " +
                "실제 CCTV의 높이·각도·화각과 도로 중앙선 기준 위치를 City Lab VirtualCCTV에 옮긴다. " +
                "Build City Traffic Lab이나 Install Signals를 다시 실행하면 카메라가 원래 자리로 돌아가므로 이 메뉴를 다시 실행한다.",
                MessageType.Info);

            using (new EditorGUILayout.HorizontalScope())
            {
                string[] names = Array.ConvertAll(found, Path.GetFileName);
                int current = Array.IndexOf(found, posePath);
                if (found.Length > 0)
                {
                    int picked = EditorGUILayout.Popup("자세 파일 (RealCctv)", current, names);
                    if (picked != current && picked >= 0) Select(found[picked]);
                }
                else EditorGUILayout.LabelField("자세 파일", "RealCctv 폴더에 *.road_pose.json이 없습니다");
                if (GUILayout.Button("새로고침", GUILayout.Width(70))) FindFiles();
                if (GUILayout.Button("다른 파일", GUILayout.Width(70)))
                {
                    string dir = string.IsNullOrEmpty(posePath) ? RealCctvDir : Path.GetDirectoryName(posePath);
                    string other = EditorUtility.OpenFilePanel("road_pose.json 고르기", dir, "json");
                    if (!string.IsNullOrEmpty(other)) Select(other);
                }
            }
            if (!string.IsNullOrEmpty(posePath) && Array.IndexOf(found, posePath) < 0)
                EditorGUILayout.LabelField(" ", posePath, EditorStyles.miniLabel);
            if (loadError != null) EditorGUILayout.HelpBox("파일을 읽지 못했습니다: " + loadError, MessageType.Error);
            if (pose != null)
            {
                EditorGUILayout.LabelField("실제 카메라", pose.camera_id);
                EditorGUILayout.LabelField("  위치", $"중앙선 {(pose.lateral_m >= 0 ? "오른쪽" : "왼쪽")} {Mathf.Abs(pose.lateral_m):F2} m, 노면에서 {pose.height_m:F2} m");
                EditorGUILayout.LabelField("  방향", $"도로 대비 {pose.yaw_to_road_deg:+0.0;-0.0}°, 숙임 {pose.pitch_deg:F1}°, 기울기 {pose.roll_deg:F1}°");
                EditorGUILayout.LabelField("  화각·해상도", $"세로 {pose.vertical_fov_deg:F1}°, {Size(pose).x}×{Size(pose).y}");
                if (pose.has_ref) EditorGUILayout.LabelField("  기준 지점까지", $"{pose.ref_ahead_m:F1} m 앞");
            }

            EditorGUILayout.Space();
            EditorGUILayout.LabelField("City Lab 배치", EditorStyles.boldLabel);
            metersPerUnit = EditorGUILayout.FloatField(new GUIContent("1단위 = m", "실제 1차로 폭 3.5 m ÷ City Lab 차로 폭 1.2단위"), metersPerUnit);
            groundY = EditorGUILayout.FloatField(new GUIContent("노면 높이 y"), groundY);
            keepRealDistance = EditorGUILayout.Toggle(new GUIContent("정지선까지 실제 거리 유지",
                "카메라에서 기준 지점(사거리)까지의 실제 거리만큼 City Lab 정지선 앞에 둔다. 도로가 짧으면 시작 쪽 끝에 맞춘다"), keepRealDistance);
            if (keepRealDistance)
            {
                minX = EditorGUILayout.FloatField(new GUIContent("가장 뒤쪽 X", "직선 도로 시작(약 -17.8)보다 조금 안쪽"), minX);
                maxX = EditorGUILayout.FloatField("가장 앞쪽 X", maxX);
            }
            else fixedX = EditorGUILayout.FloatField(new GUIContent("카메라 X"), fixedX);
            matchResolution = EditorGUILayout.Toggle(new GUIContent("저장 해상도를 실제 CCTV와 같게",
                "가로·세로 비율이 같아야 같은 세로 화각에서 가로 화각도 맞는다"), matchResolution);

            EditorGUILayout.Space();
            using (new EditorGUI.DisabledScope(pose == null))
            {
                if (GUILayout.Button("VirtualCCTV 배치", GUILayout.Height(28))) lastResult = Place();
                if (GUILayout.Button("미리보기 이미지 저장 (" + PreviewPath + ")")) lastResult = SavePreview();
            }
            if (!string.IsNullOrEmpty(lastResult)) EditorGUILayout.HelpBox(lastResult, MessageType.None);
            EditorGUILayout.EndScrollView();
        }

        static Vector2Int Size(RoadPose p) =>
            p.image_size != null && p.image_size.Length == 2 ? new Vector2Int(p.image_size[0], p.image_size[1]) : new Vector2Int(1280, 720);

        static Camera FindCctv(out string error)
        {
            error = null;
            if (EditorApplication.isPlaying) { error = "Play를 멈춘 뒤 실행하세요."; return null; }
            var go = GameObject.Find("VirtualCCTV");
            if (go == null || go.GetComponent<Camera>() == null) { error = "VirtualCCTV가 없습니다. CityTrafficLab 씬을 먼저 여세요."; return null; }
            return go.GetComponent<Camera>();
        }

        string Place()
        {
            var cam = FindCctv(out string error);
            if (cam == null) return error;
            if (metersPerUnit <= 0f) return "1단위 = m 값은 0보다 커야 합니다.";

            // City Lab 도로: 앞쪽 +X, 중앙선 z = PaintedCentreZ. Unity는 왼손 좌표계라 +X를 볼 때 오른쪽이 -Z다
            Vector3 forward = Vector3.right, right = Vector3.Cross(Vector3.up, forward).normalized;
            var signals = UnityEngine.Object.FindAnyObjectByType<TrafficSignalController>();
            float stopX = signals != null ? signals.outboundStopX : 6.8f;
            string alongNote;
            float x;
            if (keepRealDistance && pose.has_ref)
            {
                float wanted = stopX - pose.ref_ahead_m / metersPerUnit;
                x = Mathf.Clamp(wanted, minX, maxX);
                alongNote = Mathf.Approximately(x, wanted)
                    ? $"정지선(X={stopX:F2})까지 실제 거리 {pose.ref_ahead_m:F0} m 유지"
                    : $"정지선까지 실제 거리 {pose.ref_ahead_m:F0} m({pose.ref_ahead_m / metersPerUnit:F0}단위)는 City Lab 도로보다 길어 X={x:F1}에 맞춤";
            }
            else { x = fixedX; alongNote = $"카메라 X={x:F1}"; }

            Vector3 position = new Vector3(x, groundY + pose.height_m / metersPerUnit, CityLabBuilder.PaintedCentreZ)
                               + right * (pose.lateral_m / metersPerUnit);
            float roadYaw = Mathf.Atan2(forward.x, forward.z) * Mathf.Rad2Deg;
            var rotation = Quaternion.Euler(pose.pitch_deg, roadYaw + pose.yaw_to_road_deg, pose.roll_deg);

            Undo.RecordObject(cam.transform, "Place VirtualCCTV");
            Undo.RecordObject(cam, "Place VirtualCCTV");
            cam.transform.SetPositionAndRotation(position, rotation);
            cam.fieldOfView = pose.vertical_fov_deg;
            var size = Size(pose);
            var exporter = cam.GetComponent<GroundTruthExporter>();
            if (exporter != null)
            {
                Undo.RecordObject(exporter, "Place VirtualCCTV");
                if (matchResolution) { exporter.imageWidth = size.x; exporter.imageHeight = size.y; }
                if (!string.IsNullOrEmpty(pose.virtual_camera_id)) exporter.cameraId = pose.virtual_camera_id;
                EditorUtility.SetDirty(exporter);
            }
            EditorUtility.SetDirty(cam);
            var scene = cam.gameObject.scene;
            EditorSceneManager.MarkSceneDirty(scene);
            if (scene.path == CityLabBuilder.ScenePath) EditorSceneManager.SaveScene(scene);
            Selection.activeGameObject = cam.gameObject;

            string summary = $"VirtualCCTV 배치: 위치 ({position.x:F2}, {position.y:F2}, {position.z:F2}), " +
                             $"회전 ({rotation.eulerAngles.x:F1}, {rotation.eulerAngles.y:F1}, {rotation.eulerAngles.z:F1}), " +
                             $"세로 화각 {cam.fieldOfView:F1}°, 저장 {(exporter != null ? exporter.imageWidth + "×" + exporter.imageHeight : "-")}, " +
                             $"1단위 {metersPerUnit:F2} m. {alongNote}.";
            Debug.Log("TwinSight: " + summary + " 원본: " + pose.camera_id);
            return summary;
        }

        string SavePreview()
        {
            var cam = FindCctv(out string error);
            if (cam == null) return error;
            var size = Size(pose);
            var rt = RenderTexture.GetTemporary(size.x, size.y, 24);
            var previous = cam.targetTexture;
            var tex = new Texture2D(size.x, size.y, TextureFormat.RGB24, false);
            try
            {
                cam.targetTexture = rt;
                cam.aspect = (float)size.x / size.y;
                cam.Render();
                RenderTexture.active = rt;
                tex.ReadPixels(new Rect(0, 0, size.x, size.y), 0, 0);
                tex.Apply();
                string full = Path.GetFullPath(Path.Combine(Directory.GetParent(Application.dataPath).FullName, PreviewPath));
                Directory.CreateDirectory(Path.GetDirectoryName(full));
                File.WriteAllBytes(full, tex.EncodeToPNG());
                Debug.Log("TwinSight: VirtualCCTV 미리보기 저장 → " + full);
                return "미리보기 저장: " + full;
            }
            finally
            {
                cam.targetTexture = previous;
                cam.ResetAspect();
                RenderTexture.active = null;
                RenderTexture.ReleaseTemporary(rt);
                DestroyImmediate(tex);
            }
        }
    }
}
