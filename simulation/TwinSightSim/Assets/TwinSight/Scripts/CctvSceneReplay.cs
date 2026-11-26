using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using UnityEngine;
using UnityEngine.Networking;

namespace TwinSight.Simulation
{
    /// <summary>
    /// 실제 CCTV 영상 한 편을 같은 구도로 재현한다(mapping/scripts/cctv_scene_replay.py가 만든 replay.json).
    /// - 바닥: 영상 배경(차량 제거)을 위에서 본 그림으로 편 질감. 같은 자세의 카메라로 보면 원래 화면과 겹친다.
    /// - 배경막: 카메라를 마주 보는 먼 판에 같은 배경 화면을 붙여 건물·하늘까지 같은 구도로 보이게 한다.
    /// - 차량: 추적 궤적(미터, 카메라 발밑 원점)을 시간에 맞춰 보간해 움직인다. 시간은 웹 페이지의 실제 영상과 맞춘다.
    /// City Lab에서 멀리 떨어진 빈 곳(origin)에 만들어 도시 모델과 겹치지 않는다. 1단위 = 2.92 m(City Lab 차량 크기 기준).
    /// </summary>
    public class CctvSceneReplay : MonoBehaviour
    {
        [Serializable] class CameraInfo { public float height_m, pitch_deg, roll_deg, vertical_fov_deg; }
        [Serializable] class GroundInfo { public string image; public float[] right_m, fwd_m; }
        [Serializable] class BackdropInfo { public string image; public float distance_m; }
        [Serializable] class Vehicle { public int id; public string class_name; }
        [Serializable] class Hazard { public string type, label; public float right_m, fwd_m; }
        [Serializable] class Replay
        {
            public string source; public float duration_s; public int[] image_size;
            public CameraInfo camera; public GroundInfo ground; public BackdropInfo backdrop; public Hazard[] hazards;
        }

        public string folder = "RealCctv/yunggeon";
        public GameObject suvPrefab, miniPrefab;
        public float metersPerUnit = 2.92f;
        public Vector3 origin = new Vector3(0f, 0.507f, -400f);
        public bool loop = true;

        public Camera ReplayCamera { get; private set; }
        public float Time01 => replay == null ? 0 : time / Mathf.Max(0.01f, replay.duration_s);
        public float CurrentTime => time;
        public float Duration => replay?.duration_s ?? 0;
        public int ActiveVehicles { get; private set; }
        /// <summary>원본 영상의 가로/세로 비율(검출용 캡처와 웹 화면 비율을 같게 한다).</summary>
        public float ImageAspect => replay?.image_size != null && replay.image_size.Length == 2 ? (float)replay.image_size[0] / replay.image_size[1] : 16f / 9f;
        public string Error { get; private set; }
        public bool Ready { get; private set; }

        Replay replay;
        readonly List<(Vehicle info, float[,] s, GameObject go)> vehicles = new List<(Vehicle, float[,], GameObject)>();
        float time;
        Material unlitGround, unlitBackdrop;

        static bool OnWeb => Application.platform == RuntimePlatform.WebGLPlayer;
        string Url(string name) => (OnWeb ? Application.streamingAssetsPath : Path.Combine(Directory.GetParent(Application.dataPath).FullName))
                                   + "/" + folder + "/" + name;

        IEnumerator Start()
        {
            string json = null;
            using (var request = UnityWebRequest.Get(OnWeb ? Url("replay.json") : "file:///" + Url("replay.json")))
            {
                yield return request.SendWebRequest();
                if (request.result != UnityWebRequest.Result.Success) { Error = "replay.json: " + request.error; yield break; }
                json = request.downloadHandler.text;
            }
            try { replay = JsonUtility.FromJson<Replay>(json); ParseVehicles(json); }
            catch (Exception e) { Error = "replay.json 해석 실패: " + e.Message; yield break; }

            Texture2D ground = null, backdrop = null;
            yield return LoadTexture(replay.ground.image, t => ground = t);
            yield return LoadTexture(replay.backdrop.image, t => backdrop = t);
            if (ground == null || backdrop == null) { Error ??= "질감을 불러오지 못했습니다"; yield break; }

            BuildCamera();
            BuildGround(ground);
            BuildBackdrop(backdrop);
            BuildHazards();
            Ready = true;
        }

        IEnumerator LoadTexture(string name, Action<Texture2D> done)
        {
            using (var request = UnityWebRequestTexture.GetTexture(OnWeb ? Url(name) : "file:///" + Url(name)))
            {
                yield return request.SendWebRequest();
                if (request.result != UnityWebRequest.Result.Success) { Error = name + ": " + request.error; done(null); yield break; }
                var tex = DownloadHandlerTexture.GetContent(request);
                tex.wrapMode = TextureWrapMode.Clamp;
                done(tex);
            }
        }

        // JsonUtility는 이중 배열(float[][])을 못 읽어서 차량 궤적은 직접 해석한다
        void ParseVehicles(string json)
        {
            // "vehicles":[{"id":1,"class_name":"car","samples":[[t,right,fwd,heading],...]}, ...] 를 손으로 읽는다
            int start = json.IndexOf("\"vehicles\"", StringComparison.Ordinal);
            int i = json.IndexOf('[', start);
            int depth = 0, objStart = -1;
            for (int k = i; k < json.Length; k++)
            {
                char ch = json[k];
                if (ch == '{') { if (depth == 1) objStart = k; depth++; }
                else if (ch == '}') { depth--; if (depth == 1 && objStart >= 0) { AddVehicle(json.Substring(objStart, k - objStart + 1)); objStart = -1; } }
                else if (ch == '[') { if (depth == 0) depth = 1; else if (depth >= 2) depth++; }
                else if (ch == ']') { if (depth == 1) break; if (depth >= 2) depth--; }
            }
        }

        void AddVehicle(string obj)
        {
            var info = JsonUtility.FromJson<Vehicle>(obj);
            int a = obj.IndexOf("\"samples\"", StringComparison.Ordinal);
            a = obj.IndexOf('[', a) + 1;
            var rows = new List<float[]>();
            while (true)
            {
                int open = obj.IndexOf('[', a); if (open < 0) break;
                int close = obj.IndexOf(']', open); if (close < 0) break;
                var parts = obj.Substring(open + 1, close - open - 1).Split(',');
                if (parts.Length == 4)
                {
                    var row = new float[4];
                    for (int p = 0; p < 4; p++) row[p] = float.Parse(parts[p], System.Globalization.CultureInfo.InvariantCulture);
                    rows.Add(row);
                }
                a = close + 1;
                int next = obj.IndexOf(',', a), end = obj.IndexOf(']', a);
                if (end >= 0 && (next < 0 || end < next)) break;   // 샘플 목록 끝
            }
            if (rows.Count < 2) return;
            var s = new float[rows.Count, 4];
            for (int r = 0; r < rows.Count; r++) for (int c = 0; c < 4; c++) s[r, c] = rows[r][c];
            vehicles.Add((info, s, null));
        }

        Vector3 World(float right_m, float fwd_m, float up_m = 0f) =>
            origin + new Vector3(right_m / metersPerUnit, up_m / metersPerUnit, fwd_m / metersPerUnit);

        static Material Unlit(Texture2D tex)
        {
            var m = new Material(Shader.Find("Sprites/Default")) { mainTexture = tex };
            return m;
        }

        void BuildCamera()
        {
            var go = new GameObject("ReplayCCTV");
            go.transform.SetParent(transform, false);
            ReplayCamera = go.AddComponent<Camera>();
            ReplayCamera.transform.position = World(0, 0, replay.camera.height_m);
            ReplayCamera.transform.rotation = Quaternion.Euler(replay.camera.pitch_deg, 0f, replay.camera.roll_deg);
            ReplayCamera.fieldOfView = replay.camera.vertical_fov_deg;
            ReplayCamera.nearClipPlane = 0.05f; ReplayCamera.farClipPlane = 2000f;
            ReplayCamera.clearFlags = CameraClearFlags.SolidColor; ReplayCamera.backgroundColor = new Color(0.82f, 0.84f, 0.86f);
        }

        void BuildGround(Texture2D tex)
        {
            float r0 = replay.ground.right_m[0], r1 = replay.ground.right_m[1], f0 = replay.ground.fwd_m[0], f1 = replay.ground.fwd_m[1];
            var mesh = new Mesh
            {
                vertices = new[] { World(r0, f0, 0.01f), World(r1, f0, 0.01f), World(r1, f1, 0.01f), World(r0, f1, 0.01f) },
                uv = new[] { new Vector2(0, 0), new Vector2(1, 0), new Vector2(1, 1), new Vector2(0, 1) },
                triangles = new[] { 0, 2, 1, 0, 3, 2 }
            };
            mesh.RecalculateNormals();
            var go = new GameObject("ReplayGround");
            go.transform.SetParent(transform, false);
            go.AddComponent<MeshFilter>().sharedMesh = mesh;
            go.AddComponent<MeshRenderer>().sharedMaterial = unlitGround = Unlit(tex);
            // 차량이 바닥 위에 서도록 충돌체(물리 없이 높이 기준용)
            go.AddComponent<MeshCollider>().sharedMesh = mesh;
        }

        void BuildBackdrop(Texture2D tex)
        {
            // 카메라 광축에 수직인 먼 판: 원래 화면 전체를 같은 화각으로 덮는다. 가까운 바닥이 그 앞을 가린다.
            float d = replay.backdrop.distance_m / metersPerUnit;
            float hgt = 2f * d * Mathf.Tan(replay.camera.vertical_fov_deg * 0.5f * Mathf.Deg2Rad);
            float aspect = replay.image_size != null && replay.image_size.Length == 2 ? (float)replay.image_size[0] / replay.image_size[1] : 16f / 9f;
            float wid = hgt * aspect;
            var cam = ReplayCamera.transform;
            Vector3 c = cam.position + cam.forward * d, ux = cam.right * wid * 0.5f, uy = cam.up * hgt * 0.5f;
            var mesh = new Mesh
            {
                vertices = new[] { c - ux - uy, c + ux - uy, c + ux + uy, c - ux + uy },
                uv = new[] { new Vector2(0, 0), new Vector2(1, 0), new Vector2(1, 1), new Vector2(0, 1) },
                triangles = new[] { 0, 2, 1, 0, 3, 2 }
            };
            var go = new GameObject("ReplayBackdrop");
            go.transform.SetParent(transform, false);
            go.AddComponent<MeshFilter>().sharedMesh = mesh;
            go.AddComponent<MeshRenderer>().sharedMaterial = unlitBackdrop = Unlit(tex);
        }

        void BuildHazards()
        {
            if (replay.hazards == null) return;
            foreach (var h in replay.hazards)
            {
                // 노면 위 반투명 표시 고리(질감 속 물웅덩이를 가리키는 표식)
                var ring = new GameObject("ReplayHazard_" + h.type).AddComponent<LineRenderer>();
                ring.transform.SetParent(transform, false);
                ring.sharedMaterial = new Material(Shader.Find("Sprites/Default"));
                ring.startColor = ring.endColor = new Color(1f, 0.25f, 0.2f, 0.9f);
                ring.widthMultiplier = 0.035f; ring.loop = true; ring.positionCount = 32;
                for (int k = 0; k < 32; k++)
                {
                    float a = k / 32f * Mathf.PI * 2f;
                    ring.SetPosition(k, World(h.right_m + Mathf.Cos(a) * 1.6f, h.fwd_m + Mathf.Sin(a) * 1.6f, 0.05f));
                }
            }
        }

        GameObject Spawn(Vehicle v)
        {
            GameObject prefab = v.id % 2 == 0 ? suvPrefab : miniPrefab;
            Vector3 scale = Vector3.one;
            switch (v.class_name)
            {
                case "bus": prefab = suvPrefab; scale = new Vector3(1.15f, 1.6f, 2.4f); break;
                case "truck": prefab = suvPrefab; scale = new Vector3(1.05f, 1.25f, 1.6f); break;
                case "motorcycle": case "bicycle": case "person": prefab = miniPrefab; scale = new Vector3(0.4f, 0.9f, 0.45f); break;
            }
            if (prefab == null) return null;
            var go = Instantiate(prefab, transform);
            go.name = $"Replay_{v.class_name}_{v.id}";
            go.transform.localScale = Vector3.Scale(prefab.transform.localScale, scale);
            // 재생 차량은 경로를 그대로 따라가므로 물리·교통 스크립트를 끈다
            foreach (var body in go.GetComponentsInChildren<Rigidbody>()) body.isKinematic = true;
            foreach (var agent in go.GetComponentsInChildren<TrafficVehicleAgent>()) agent.enabled = false;
            foreach (var mover in go.GetComponentsInChildren<WaypointMover>()) mover.enabled = false;
            return go;
        }

        bool paused;
        float lastSync = -10f;

        /// <summary>웹 페이지의 실제 영상 재생 시각에 맞춘다. 멈춰 있으면 같은 시각에 세우고, 재생 중이면 차이가 클 때만 건너뛴다.</summary>
        public void Sync(float videoTime, bool playing)
        {
            if (replay == null) return;
            lastSync = Time.unscaledTime;
            paused = !playing;
            if (!playing || Mathf.Abs(videoTime - time) > 0.2f) time = Mathf.Repeat(videoTime, replay.duration_s);
        }

        void Update()
        {
            if (!Ready) return;
            // 페이지가 1초 넘게 시각을 안 보내면(탭이 뒤로 감 등) 스스로 재생을 이어 간다
            if (!paused || Time.unscaledTime - lastSync > 1f) time += Time.deltaTime;
            if (time > replay.duration_s) time = loop ? 0f : replay.duration_s;
            int active = 0;
            for (int i = 0; i < vehicles.Count; i++)
            {
                var (info, s, go) = vehicles[i];
                int n = s.GetLength(0);
                bool on = time >= s[0, 0] && time <= s[n - 1, 0];
                if (!on) { if (go != null) go.SetActive(false); continue; }
                if (go == null) { go = Spawn(info); vehicles[i] = (info, s, go); if (go == null) continue; }
                int k = 1;
                while (k < n - 1 && s[k, 0] < time) k++;
                float a = Mathf.InverseLerp(s[k - 1, 0], s[k, 0], time);
                float right = Mathf.Lerp(s[k - 1, 1], s[k, 1], a), fwd = Mathf.Lerp(s[k - 1, 2], s[k, 2], a);
                float heading = Mathf.LerpAngle(s[k - 1, 3], s[k, 3], a);
                go.SetActive(true);
                go.transform.SetPositionAndRotation(World(right, fwd), Quaternion.Euler(0f, heading, 0f));
                active++;
            }
            ActiveVehicles = active;
        }
    }
}
