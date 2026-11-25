using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;
using Object = UnityEngine.Object;

namespace TwinSight.Simulation.EditorTools
{
    /// <summary>
    /// 실제 CCTV 인식 결과(mapping/scripts/detections_to_twin.py가 만든 RealCctv/*.twin.json)를 City Lab에 놓고
    /// VirtualCCTV 시점으로 렌더링한다. 차량은 VirtualCCTV 위치 기준 X = 카메라 X + along / 1단위, Z = 중앙선 - lateral / 1단위.
    /// 렌더링 결과와 배치값은 Logs/twin_replay/<이름>/에 저장해 실제 CCTV 화면과 비교한다.
    /// </summary>
    public class CityLabTwinReplay : EditorWindow
    {
#pragma warning disable 0649
        [Serializable] class TwinObject
        {
            public int id; public string class_name; public float confidence;
            public float[] bbox_xyxy; public float[] pixel;
            public float along_m, lateral_m; public string direction; public bool truncated, in_road;
        }
        [Serializable] class TwinFrame { public int frame; public float timestamp; public string image; public TwinObject[] objects; }
        [Serializable] class TwinLane { public string color, kind; public float[] along_m, lateral_m; }
        [Serializable] class TwinFile { public string camera_id, virtual_camera_id; public int[] image_size; public TwinLane[] lanes; public TwinFrame[] frames; }
#pragma warning restore 0649

        [Serializable] class PlacedObject
        {
            public int id; public string class_name, prefab, direction; public float confidence;
            public float[] real_bbox_xyxy, real_pixel, unity_position; public float unity_yaw_deg; public float[] size_units;
        }
        [Serializable] class RenderedFrame { public int frame; public string real_image, rendered_image; public List<PlacedObject> objects = new List<PlacedObject>(); }
        [Serializable] class Manifest
        {
            public string twin_file, camera_id; public int[] image_size;
            public float[] camera_position, camera_rotation_xyzw; public float camera_vertical_fov_deg, meters_per_unit, ground_y, centre_z;
            public List<RenderedFrame> frames = new List<RenderedFrame>();
        }

        const string RootName = "TwinReplay (임시, 저장 안 됨)";
        static string RealCctvDir => Path.Combine(Directory.GetParent(Application.dataPath).FullName, "RealCctv");
        string[] found = Array.Empty<string>();
        string path;
        TwinFile twin;
        string message;
        int frameIndex;
        float metersPerUnit = 2.92f, groundY = 0.507f;
        bool onlyInRoad = true, skipTruncated = true, showLanes = true;
        GameObject suvPrefab, miniPrefab;

        [MenuItem("TwinSight/City Lab/Replay Real CCTV Detections...")]
        static void Open() => GetWindow<CityLabTwinReplay>("실제 인식 → City Lab").Show();

        void OnEnable()
        {
            found = Directory.Exists(RealCctvDir) ? Directory.GetFiles(RealCctvDir, "*.twin.json") : Array.Empty<string>();
            if (found.Length > 0) Load(found[0]);
            suvPrefab = AssetDatabase.LoadAssetAtPath<GameObject>(CityAssetTools.Generated + "/Vehicles/SUV/SUV.prefab");
            miniPrefab = AssetDatabase.LoadAssetAtPath<GameObject>(CityAssetTools.Generated + "/Vehicles/Mini/Mini.prefab");
        }

        void OnDisable() => Clear();

        void Load(string file)
        {
            path = file; twin = null; message = null;
            try { twin = JsonUtility.FromJson<TwinFile>(File.ReadAllText(file)); frameIndex = 0; }
            catch (Exception e) { message = "파일을 읽지 못했습니다: " + e.Message; }
        }

        void OnGUI()
        {
            EditorGUILayout.HelpBox("실제 CCTV 검출을 도로 기준 좌표로 바꾼 *.twin.json을 City Lab에 놓고 VirtualCCTV로 렌더링한다. " +
                "먼저 CityTrafficLab 씬을 열고 Place VirtualCCTV From Real CCTV로 같은 CCTV 자세를 배치한다(Play 중이 아닐 때).", MessageType.Info);
            if (found.Length == 0) { EditorGUILayout.HelpBox("RealCctv 폴더에 *.twin.json이 없습니다.", MessageType.Warning); return; }
            int current = Array.IndexOf(found, path);
            int picked = EditorGUILayout.Popup("재생 파일 (RealCctv)", Mathf.Max(0, current), found.Select(Path.GetFileName).ToArray());
            if (picked != current) Load(found[picked]);
            if (twin == null || twin.frames == null || twin.frames.Length == 0) { if (message != null) EditorGUILayout.HelpBox(message, MessageType.Error); return; }

            EditorGUILayout.LabelField("실제 카메라", $"{twin.camera_id}  ({twin.frames.Length}프레임, 차선 {twin.lanes?.Length ?? 0}개)");
            metersPerUnit = EditorGUILayout.FloatField("1단위 = m", metersPerUnit);
            groundY = EditorGUILayout.FloatField("노면 높이 y", groundY);
            onlyInRoad = EditorGUILayout.Toggle(new GUIContent("도로 영역 안 차량만", "road-context 도로 영역 밖(길가 주차 등)은 City Lab에 그 공간이 없어 뺀다"), onlyInRoad);
            skipTruncated = EditorGUILayout.Toggle(new GUIContent("화면 가장자리에 잘린 박스 빼기", "잘린 박스는 바닥 위치를 믿기 어렵다"), skipTruncated);
            showLanes = EditorGUILayout.Toggle("인식한 차선 그리기", showLanes);
            frameIndex = EditorGUILayout.IntSlider("프레임", frameIndex, 0, twin.frames.Length - 1);
            var f = twin.frames[frameIndex];
            EditorGUILayout.LabelField(" ", $"차량 {Selected(f).Count()}대 (전체 {f.objects?.Length ?? 0})");

            using (new EditorGUILayout.HorizontalScope())
            {
                if (GUILayout.Button("이 프레임 배치")) message = Place(f, out _);
                if (GUILayout.Button("이 프레임 렌더링")) message = Render(new[] { frameIndex });
                if (GUILayout.Button("지우기")) { Clear(); message = "지웠습니다."; }
            }
            if (GUILayout.Button("모든 프레임 렌더링 (Logs/twin_replay)", GUILayout.Height(26)))
                message = Render(Enumerable.Range(0, twin.frames.Length).ToArray());
            EditorGUILayout.Space();
            if (GUILayout.Button("▶ Play 재생용으로 씬에 넣기", GUILayout.Height(26))) message = InstallPlayer();
            if (!string.IsNullOrEmpty(message)) EditorGUILayout.HelpBox(message, MessageType.None);
        }

        IEnumerable<TwinObject> Selected(TwinFrame f) =>
            (f.objects ?? Array.Empty<TwinObject>()).Where(o => (!onlyInRoad || o.in_road) && (!skipTruncated || !o.truncated));

        static Camera FindCctv()
        {
            if (EditorApplication.isPlaying) return null;
            var go = GameObject.Find("VirtualCCTV");
            return go != null ? go.GetComponent<Camera>() : null;
        }

        static void Clear()
        {
            var root = GameObject.Find(RootName);
            if (root != null) Object.DestroyImmediate(root);
        }

        GameObject Root()
        {
            Clear();
            var root = new GameObject(RootName) { hideFlags = HideFlags.DontSave };
            return root;
        }

        (GameObject prefab, Vector3 scale, string name) PrefabFor(TwinObject o)
        {
            // City Lab 차량은 SUV(1.6단위 ≈ 4.7 m)·Mini(1.3단위)뿐이라 트럭·버스는 SUV를 늘려 쓴다
            switch (o.class_name)
            {
                case "bus": return (suvPrefab, new Vector3(1.15f, 1.6f, 2.4f), "SUV×bus");
                case "truck": return (suvPrefab, new Vector3(1.05f, 1.2f, 1.45f), "SUV×truck");
                case "motorcycle":
                case "bicycle": return (miniPrefab, new Vector3(0.45f, 0.9f, 0.55f), "Mini×bike");
                default: return o.id % 2 == 0 ? (suvPrefab, Vector3.one, "SUV") : (miniPrefab, Vector3.one, "Mini");
            }
        }

        string Place(TwinFrame f, out RenderedFrame record)
        {
            record = null;
            var cam = FindCctv();
            if (cam == null) return "VirtualCCTV가 없거나 Play 중입니다. CityTrafficLab 씬을 열고 Play를 멈추세요.";
            if (suvPrefab == null || miniPrefab == null) return "City Lab 차량 프리팹이 없습니다. Build City Traffic Lab을 먼저 실행하세요.";
            var root = Root();
            Vector3 forward = Vector3.right, right = Vector3.Cross(Vector3.up, forward).normalized;  // City Lab 도로 앞쪽 +X, 오른쪽 -Z
            var origin = new Vector3(cam.transform.position.x, groundY, CityLabBuilder.PaintedCentreZ);
            record = new RenderedFrame { frame = f.frame, real_image = f.image };
            foreach (var o in Selected(f))
            {
                var (prefab, scale, name) = PrefabFor(o);
                var go = (GameObject)Object.Instantiate(prefab, root.transform);
                go.hideFlags = HideFlags.DontSave;
                go.transform.position = origin + forward * (o.along_m / metersPerUnit) + right * (o.lateral_m / metersPerUnit);
                go.transform.rotation = Quaternion.LookRotation(o.direction == "toward" ? -forward : forward, Vector3.up);
                go.transform.localScale = Vector3.Scale(go.transform.localScale, scale);
                var bounds = new Bounds(go.transform.position, Vector3.zero);
                foreach (var r in go.GetComponentsInChildren<Renderer>()) bounds.Encapsulate(r.bounds);
                record.objects.Add(new PlacedObject
                {
                    id = o.id, class_name = o.class_name, prefab = name, direction = o.direction, confidence = o.confidence,
                    real_bbox_xyxy = o.bbox_xyxy, real_pixel = o.pixel,
                    unity_position = new[] { go.transform.position.x, go.transform.position.y, go.transform.position.z },
                    unity_yaw_deg = go.transform.eulerAngles.y,
                    size_units = new[] { bounds.size.x, bounds.size.y, bounds.size.z },
                });
            }
            if (showLanes && twin.lanes != null)
            {
                var material = new Material(Shader.Find("Sprites/Default")) { hideFlags = HideFlags.DontSave };
                foreach (var lane in twin.lanes)
                {
                    if (lane.kind == "barrier") continue;
                    var go = new GameObject("lane") { hideFlags = HideFlags.DontSave };
                    go.transform.SetParent(root.transform, false);
                    var lr = go.AddComponent<LineRenderer>();
                    lr.sharedMaterial = material; lr.useWorldSpace = true; lr.widthMultiplier = 0.05f; lr.positionCount = 2;
                    Color c = lane.color == "yellow" ? new Color(1f, 0.85f, 0.1f) : new Color(0.2f, 1f, 1f);
                    lr.startColor = lr.endColor = c;
                    for (int i = 0; i < 2; i++)
                        lr.SetPosition(i, origin + forward * (lane.along_m[i] / metersPerUnit) + right * (lane.lateral_m[i] / metersPerUnit) + Vector3.up * 0.01f);
                }
            }
            return $"프레임 {f.frame}: 차량 {record.objects.Count}대 배치";
        }

        /// <summary>Play를 누르면 이 재생 파일을 VirtualCCTV 시점으로 재생하도록 씬에 RealCctvTwinPlayer를 넣고 저장한다.</summary>
        string InstallPlayer()
        {
            var cam = FindCctv();
            if (cam == null) return "VirtualCCTV가 없거나 Play 중입니다. CityTrafficLab 씬을 열고 Play를 멈추세요.";
            if (suvPrefab == null || miniPrefab == null) return "City Lab 차량 프리팹이 없습니다. Build City Traffic Lab을 먼저 실행하세요.";
            Clear();   // 편집 모드 미리보기 물체가 Play에 섞이지 않게 치운다
            // Unity 물체는 ?? 로 null을 가릴 수 없어(편집기의 가짜 null) 직접 비교한다
            var go = GameObject.Find("RealCctvTwinPlayer");
            if (go == null) go = new GameObject("RealCctvTwinPlayer");
            var player = go.GetComponent<RealCctvTwinPlayer>();
            if (player == null) player = go.AddComponent<RealCctvTwinPlayer>();
            Undo.RecordObject(player, "Install RealCctvTwinPlayer");
            string project = Directory.GetParent(Application.dataPath).FullName;
            player.twinFile = path.StartsWith(project) ? path.Substring(project.Length + 1).Replace('\\', '/') : path;
            player.virtualCctv = cam; player.suvPrefab = suvPrefab; player.miniPrefab = miniPrefab;
            player.metersPerUnit = metersPerUnit; player.groundY = groundY; player.centreZ = CityLabBuilder.PaintedCentreZ;
            player.onlyInRoad = onlyInRoad; player.skipTruncated = skipTruncated; player.showLanes = showLanes;
            EditorUtility.SetDirty(player);
            var scene = go.scene;
            UnityEditor.SceneManagement.EditorSceneManager.MarkSceneDirty(scene);
            if (scene.path == CityLabBuilder.ScenePath) UnityEditor.SceneManagement.EditorSceneManager.SaveScene(scene);
            Selection.activeGameObject = go;
            Debug.Log($"TwinSight: Play 재생 준비 — {player.twinFile}. ▶ Play를 누르면 VirtualCCTV 시점으로 재생합니다.");
            return $"씬에 RealCctvTwinPlayer를 넣었습니다({player.twinFile}). ▶ Play를 누르면 재생합니다(←/→ 넘기기, P 자동 재생). " +
                   "City Lab 자체 교통은 재생 중 꺼집니다. 다시 원래대로 쓰려면 RealCctvTwinPlayer 물체를 끄거나 지우세요.";
        }

        string Render(int[] indices)
        {
            var cam = FindCctv();
            if (cam == null) return "VirtualCCTV가 없거나 Play 중입니다.";
            int w = twin.image_size != null && twin.image_size.Length == 2 ? twin.image_size[0] : 720;
            int h = twin.image_size != null && twin.image_size.Length == 2 ? twin.image_size[1] : 480;
            string name = Path.GetFileName(path).Replace(".twin.json", "");
            string dir = Path.Combine(Directory.GetParent(Application.dataPath).FullName, "Logs", "twin_replay", name);
            Directory.CreateDirectory(dir);
            var manifest = new Manifest
            {
                twin_file = path, camera_id = twin.camera_id, image_size = new[] { w, h },
                camera_position = new[] { cam.transform.position.x, cam.transform.position.y, cam.transform.position.z },
                camera_rotation_xyzw = new[] { cam.transform.rotation.x, cam.transform.rotation.y, cam.transform.rotation.z, cam.transform.rotation.w },
                camera_vertical_fov_deg = cam.fieldOfView, meters_per_unit = metersPerUnit, ground_y = groundY, centre_z = CityLabBuilder.PaintedCentreZ,
            };
            var rt = RenderTexture.GetTemporary(w, h, 24);
            var tex = new Texture2D(w, h, TextureFormat.RGB24, false);
            var previous = cam.targetTexture;
            try
            {
                for (int k = 0; k < indices.Length; k++)
                {
                    EditorUtility.DisplayProgressBar("실제 인식 → City Lab", $"프레임 {k + 1}/{indices.Length}", (float)k / indices.Length);
                    string placed = Place(twin.frames[indices[k]], out var record);
                    if (record == null) return placed;
                    cam.targetTexture = rt; cam.aspect = (float)w / h; cam.Render();
                    RenderTexture.active = rt; tex.ReadPixels(new Rect(0, 0, w, h), 0, 0); tex.Apply();
                    record.rendered_image = Path.Combine(dir, $"frame_{record.frame:D4}.png");
                    File.WriteAllBytes(record.rendered_image, tex.EncodeToPNG());
                    manifest.frames.Add(record);
                }
                File.WriteAllText(Path.Combine(dir, "manifest.json"), JsonUtility.ToJson(manifest, true));
            }
            finally
            {
                cam.targetTexture = previous; cam.ResetAspect(); RenderTexture.active = null;
                RenderTexture.ReleaseTemporary(rt); Object.DestroyImmediate(tex);
                EditorUtility.ClearProgressBar();
            }
            int total = manifest.frames.Sum(r => r.objects.Count);
            Debug.Log($"TwinSight: 실제 인식 재생 {manifest.frames.Count}프레임(차량 {total}대) 렌더링 → {dir}");
            return $"{manifest.frames.Count}프레임 렌더링, 차량 {total}대 → {dir}";
        }
    }
}
