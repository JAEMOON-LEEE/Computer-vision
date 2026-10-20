using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

namespace TwinSight.Simulation
{
    /// <summary>
    /// Play 중에 실제 CCTV 인식 결과(mapping/scripts/detections_to_twin.py가 만든 *.twin.json)를 City Lab에 재생한다.
    /// 차량은 VirtualCCTV 기준 X = 카메라 X + along / 1단위, Z = 중앙선 - lateral / 1단위에 놓고,
    /// 화면 오른쪽 위에 같은 프레임의 실제 CCTV 화면을 보여 준다. ←/→ 프레임 넘기기, P 자동 재생 켜기·끄기.
    /// </summary>
    public class RealCctvTwinPlayer : MonoBehaviour
    {
#pragma warning disable 0649
        [Serializable] class TwinObject
        {
            public int id; public string class_name; public float confidence; public float[] bbox_xyxy;
            public float along_m, lateral_m; public string direction; public bool truncated, in_road;
        }
        [Serializable] class TwinFrame { public int frame; public string image; public TwinObject[] objects; }
        [Serializable] class TwinLane { public string color, kind; public float[] along_m, lateral_m; }
        [Serializable] class TwinFile { public string camera_id; public int[] image_size; public TwinLane[] lanes; public TwinFrame[] frames; }
#pragma warning restore 0649

        [Tooltip("프로젝트 폴더 기준 경로 또는 절대 경로")] public string twinFile = "RealCctv/geumchon.twin.json";
        public Camera virtualCctv;
        public GameObject suvPrefab, miniPrefab;
        [Tooltip("실제 1차로 폭 3.5 m ÷ City Lab 차로 폭 1.2단위")] public float metersPerUnit = 2.92f;
        public float groundY = 0.507f, centreZ = -0.41f;
        [Range(0.2f, 10f)] public float secondsPerFrame = 2f;
        public bool autoPlay = true, loop = true;
        [Tooltip("도로 영역 밖(길가 주차) 차량은 City Lab에 그 공간이 없어 뺀다")] public bool onlyInRoad = true;
        [Tooltip("화면 가장자리에 잘린 박스는 바닥 위치를 믿기 어렵다")] public bool skipTruncated = true;
        public bool showLanes = true, showRealFrame = true;
        [Tooltip("가상 화면: 놓인 차량 박스(주황). 실제 CCTV 화면: YOLO 검출 박스(초록 = 도로 안, 회색 = 뺀 것)")] public bool showBoxes = true;
        [Tooltip("가상 화면에 같은 차량의 실제 YOLO 박스(초록)도 겹쳐 그린다. 두 박스가 겹치면 좌표 변환이 맞은 것")] public bool showRealBoxesOnTwin = true;
        [Tooltip("City Lab 자체 교통·사고 시나리오를 꺼서 실제 인식 결과만 보이게 한다")] public bool disableSimulatedTraffic = true;
        [Range(0.2f, 0.6f)] public float realFrameWidthRatio = 0.33f;

        TwinFile twin;
        string error;
        int index;
        float timer;
        readonly List<GameObject> pool = new List<GameObject>();
        readonly Dictionary<int, Texture2D> images = new Dictionary<int, Texture2D>();
        readonly List<(TwinObject obj, GameObject go)> placed = new List<(TwinObject, GameObject)>();
        int shown;
        static Texture2D white;

        void Awake()
        {
            var preview = GameObject.Find("TwinReplay (임시, 저장 안 됨)");   // 편집 모드 미리보기 물체가 남아 있으면 치운다
            if (preview != null) Destroy(preview);
            if (!disableSimulatedTraffic) return;
            foreach (var s in FindObjectsByType<TrafficSpawner>(FindObjectsInactive.Include)) s.enabled = false;
            foreach (var d in FindObjectsByType<RoadScenarioDirector>(FindObjectsInactive.Include)) d.enabled = false;
        }

        void Start()
        {
            if (virtualCctv == null) { var go = GameObject.Find("VirtualCCTV"); if (go != null) virtualCctv = go.GetComponent<Camera>(); }
            var experiment = FindAnyObjectByType<CityLabExperiment>();
            if (experiment != null) experiment.SelectCamera(false);   // Game 뷰를 VirtualCCTV 시점으로
            string path = Path.IsPathRooted(twinFile) ? twinFile : Path.Combine(Directory.GetParent(Application.dataPath).FullName, twinFile);
            try { twin = JsonUtility.FromJson<TwinFile>(File.ReadAllText(path)); }
            catch (Exception e) { error = "재생 파일을 읽지 못했습니다: " + e.Message; return; }
            if (twin.frames == null || twin.frames.Length == 0) { error = "재생 파일에 프레임이 없습니다."; return; }
            if (virtualCctv == null) { error = "VirtualCCTV가 없습니다."; return; }
            if (showLanes) DrawLanes();
            Show(0);
        }

        Vector3 Origin => new Vector3(virtualCctv.transform.position.x, groundY, centreZ);
        static readonly Vector3 Forward = Vector3.right;                                   // City Lab 도로 앞쪽 +X
        static Vector3 Right => Vector3.Cross(Vector3.up, Forward).normalized;             // 오른쪽 -Z

        Vector3 ToUnity(float along, float lateral) => Origin + Forward * (along / metersPerUnit) + Right * (lateral / metersPerUnit);

        void DrawLanes()
        {
            if (twin.lanes == null) return;
            var material = new Material(Shader.Find("Sprites/Default"));
            foreach (var lane in twin.lanes)
            {
                if (lane.kind == "barrier" || lane.along_m == null || lane.along_m.Length < 2) continue;
                var lr = new GameObject("RealLane").AddComponent<LineRenderer>();
                lr.transform.SetParent(transform, false);
                lr.sharedMaterial = material; lr.widthMultiplier = 0.05f; lr.positionCount = 2;
                lr.startColor = lr.endColor = lane.color == "yellow" ? new Color(1f, 0.85f, 0.1f) : new Color(0.2f, 1f, 1f);
                for (int i = 0; i < 2; i++) lr.SetPosition(i, ToUnity(lane.along_m[i], lane.lateral_m[i]) + Vector3.up * 0.01f);
            }
        }

        GameObject Vehicle(int slot, GameObject prefab)
        {
            while (pool.Count <= slot) pool.Add(null);
            if (pool[slot] != null && pool[slot].name != prefab.name) { Destroy(pool[slot]); pool[slot] = null; }
            if (pool[slot] == null) { pool[slot] = Instantiate(prefab, transform); pool[slot].name = prefab.name; }
            pool[slot].SetActive(true);
            return pool[slot];
        }

        void Show(int i)
        {
            index = i; timer = 0f; shown = 0;
            placed.Clear();
            foreach (var go in pool) if (go != null) go.SetActive(false);
            var frame = twin.frames[i];
            foreach (var o in frame.objects ?? Array.Empty<TwinObject>())
            {
                if ((onlyInRoad && !o.in_road) || (skipTruncated && o.truncated)) continue;
                GameObject prefab = suvPrefab; Vector3 scale = Vector3.one;
                switch (o.class_name)
                {
                    case "bus": scale = new Vector3(1.15f, 1.6f, 2.4f); break;
                    case "truck": scale = new Vector3(1.05f, 1.2f, 1.45f); break;
                    case "motorcycle": case "bicycle": prefab = miniPrefab; scale = new Vector3(0.45f, 0.9f, 0.55f); break;
                    default: prefab = o.id % 2 == 0 ? suvPrefab : miniPrefab; break;
                }
                if (prefab == null) continue;
                var go = Vehicle(shown++, prefab);
                go.transform.SetPositionAndRotation(ToUnity(o.along_m, o.lateral_m),
                    Quaternion.LookRotation(o.direction == "toward" ? -Forward : Forward, Vector3.up));
                go.transform.localScale = Vector3.Scale(prefab.transform.localScale, scale);
                placed.Add((o, go));
            }
        }

        static void DrawRect(Rect r, Color color, float thickness = 2f)
        {
            if (white == null) { white = new Texture2D(1, 1); white.SetPixel(0, 0, Color.white); white.Apply(); }
            var old = GUI.color;
            GUI.color = color;
            GUI.DrawTexture(new Rect(r.x, r.y, r.width, thickness), white);
            GUI.DrawTexture(new Rect(r.x, r.yMax - thickness, r.width, thickness), white);
            GUI.DrawTexture(new Rect(r.x, r.y, thickness, r.height), white);
            GUI.DrawTexture(new Rect(r.xMax - thickness, r.y, thickness, r.height), white);
            GUI.color = old;
        }

        static void Label(Rect r, string text, Color color)
        {
            var style = new GUIStyle(GUI.skin.label) { fontSize = 11, normal = { textColor = color } };
            GUI.Label(new Rect(r.x, r.y - 15, 140, 16), text, style);
        }

        /// <summary>놓인 차량의 화면 박스(렌더러 경계 상자 8꼭짓점을 VirtualCCTV로 투영, GUI 좌표).</summary>
        Rect? ScreenBox(GameObject go)
        {
            var renderers = go.GetComponentsInChildren<Renderer>();
            if (renderers.Length == 0) return null;
            var b = renderers[0].bounds;
            foreach (var r in renderers) b.Encapsulate(r.bounds);
            float x0 = float.MaxValue, y0 = float.MaxValue, x1 = float.MinValue, y1 = float.MinValue;
            for (int k = 0; k < 8; k++)
            {
                var c = new Vector3((k & 1) == 0 ? b.min.x : b.max.x, (k & 2) == 0 ? b.min.y : b.max.y, (k & 4) == 0 ? b.min.z : b.max.z);
                var s = virtualCctv.WorldToScreenPoint(c);
                if (s.z <= 0) return null;
                x0 = Mathf.Min(x0, s.x); x1 = Mathf.Max(x1, s.x);
                y0 = Mathf.Min(y0, Screen.height - s.y); y1 = Mathf.Max(y1, Screen.height - s.y);
            }
            return Rect.MinMaxRect(x0, y0, x1, y1);
        }

        /// <summary>실제 CCTV 픽셀 박스 → Game 화면 좌표. 세로 화각이 고정이라 세로 기준으로 맞추고 가로는 가운데 정렬.</summary>
        Rect RealToScreen(float[] box)
        {
            float w = twin.image_size[0], h = twin.image_size[1], s = Screen.height / h;
            float ox = Screen.width / 2f - w / 2f * s;
            return Rect.MinMaxRect(ox + box[0] * s, box[1] * s, ox + box[2] * s, box[3] * s);
        }

        void DrawBoxes()
        {
            var orange = new Color(1f, 0.55f, 0.1f);
            var green = new Color(0.2f, 1f, 0.3f);
            bool sized = twin.image_size != null && twin.image_size.Length == 2;
            foreach (var (o, go) in placed)
            {
                if (showRealBoxesOnTwin && sized && o.bbox_xyxy != null && o.bbox_xyxy.Length == 4)
                    DrawRect(RealToScreen(o.bbox_xyxy), green, 1f);
                var r = ScreenBox(go);
                if (r == null) continue;
                DrawRect(r.Value, orange, 2f);
                Label(r.Value, $"{o.class_name} {o.confidence:0.00}", orange);
            }
        }

        void DrawRealBoxes(Rect inset)
        {
            if (twin.image_size == null || twin.image_size.Length != 2) return;
            float sx = inset.width / twin.image_size[0], sy = inset.height / twin.image_size[1];
            foreach (var o in twin.frames[index].objects ?? Array.Empty<TwinObject>())
            {
                if (o.bbox_xyxy == null || o.bbox_xyxy.Length != 4) continue;
                bool used = (!onlyInRoad || o.in_road) && (!skipTruncated || !o.truncated);
                var r = Rect.MinMaxRect(inset.x + o.bbox_xyxy[0] * sx, inset.y + o.bbox_xyxy[1] * sy,
                                        inset.x + o.bbox_xyxy[2] * sx, inset.y + o.bbox_xyxy[3] * sy);
                DrawRect(r, used ? new Color(0.2f, 1f, 0.3f) : new Color(0.7f, 0.7f, 0.7f), 1f);
            }
        }

        void Update()
        {
            if (twin == null || error != null) return;
            if (Input.GetKeyDown(KeyCode.P)) autoPlay = !autoPlay;
            if (Input.GetKeyDown(KeyCode.RightArrow)) Step(1);
            if (Input.GetKeyDown(KeyCode.LeftArrow)) Step(-1);
            if (!autoPlay) return;
            timer += Time.unscaledDeltaTime;   // City Lab 일시정지(Space, timeScale 0)와 상관없이 넘긴다
            if (timer >= secondsPerFrame) Step(1);
        }

        void Step(int delta)
        {
            int next = index + delta;
            if (next >= twin.frames.Length) next = loop ? 0 : twin.frames.Length - 1;
            if (next < 0) next = loop ? twin.frames.Length - 1 : 0;
            Show(next);
        }

        Texture2D RealImage(int i)
        {
            if (images.TryGetValue(i, out var tex)) return tex;
            tex = null;
            string file = twin.frames[i].image;
            if (!string.IsNullOrEmpty(file) && !Path.IsPathRooted(file))   // 프로젝트 폴더 기준 상대 경로(RealCctv/...)
                file = Path.Combine(Directory.GetParent(Application.dataPath).FullName, file);
            if (!string.IsNullOrEmpty(file) && File.Exists(file))
            {
                tex = new Texture2D(2, 2);
                if (!tex.LoadImage(File.ReadAllBytes(file))) tex = null;
            }
            images[i] = tex;
            return tex;
        }

        void OnGUI()
        {
            var style = new GUIStyle(GUI.skin.box) { alignment = TextAnchor.UpperLeft, fontSize = 13, richText = true };
            if (error != null) { GUI.Box(new Rect(10, 10, 520, 26), error, style); return; }
            if (twin == null) return;
            if (showBoxes) DrawBoxes();
            var frame = twin.frames[index];
            string info = $"실제 인식 재생 {twin.camera_id}  프레임 {index + 1}/{twin.frames.Length} (원본 {frame.frame})  차량 {shown}대" +
                          $"   ←/→ 넘기기, P 자동 재생 {(autoPlay ? "켬" : "끔")}";
            GUI.Box(new Rect(10, 10, 640, 26), info, style);
            if (twin.image_size != null && twin.image_size.Length == 2)
            {
                float want = (float)twin.image_size[0] / twin.image_size[1], have = (float)Screen.width / Screen.height;
                if (Mathf.Abs(want - have) / want > 0.05f)
                    GUI.Box(new Rect(10, 40, 640, 26), $"Game 뷰 비율을 {twin.image_size[0]}x{twin.image_size[1]}로 맞추면 실제 CCTV와 같은 범위가 보입니다", style);
            }
            if (!showRealFrame) return;
            var tex = RealImage(index);
            if (tex == null) return;
            float w = Screen.width * realFrameWidthRatio, h = w * tex.height / tex.width;
            var rect = new Rect(Screen.width - w - 10, 10, w, h);
            GUI.DrawTexture(rect, tex, ScaleMode.ScaleToFit);
            if (showBoxes) DrawRealBoxes(rect);
            GUI.Box(new Rect(rect.x, rect.yMax, w, 22), "실제 CCTV (같은 프레임, 초록 = YOLO 검출)", style);
        }
    }
}
