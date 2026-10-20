using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;

namespace TwinSight.Simulation
{
    /// <summary>
    /// 실제 CCTV 파이프라인(python CCTV --serve 8765)이 내주는 실시간 검출 결과로 차량을 노면 좌표에 움직이고,
    /// 최신 CCTV 영상을 화면 오른쪽 위에 띄운다.
    /// 노면 좌표 (x, z)는 twinOrigin 기준으로 놓는다. 미터 단위 캘리브레이션이 아니면(units = px) pixelUnitScale로 줄인다.
    /// </summary>
    public class CctvLiveClient : MonoBehaviour
    {
        [Serializable]
        public class ClassPrefab
        {
            public string className = "car";
            public GameObject prefab;
        }

#pragma warning disable 0649 // 아래 두 클래스의 필드는 JsonUtility가 채운다
        [Serializable]
        class LiveObject
        {
            public int id;
            public string class_name;
            public float x;
            public float z;
            public float confidence;
        }

        [Serializable]
        class LiveState
        {
            public string camera_id;
            public string camera_name;
            public string units;
            public float timestamp;
            public int frame;
            public List<LiveObject> objects = new List<LiveObject>();
            public int unplaced;
        }
#pragma warning restore 0649

        class Vehicle
        {
            public GameObject go;
            public Vector3 target;
            public float lastSeen;
        }

        [Header("CCTV 파이프라인 서버")]
        public string serverUrl = "http://127.0.0.1:8765";
        [Range(0.05f, 2f)] public float statePollSeconds = 0.1f;
        [Range(0.05f, 2f)] public float framePollSeconds = 0.2f;

        [Header("영상 표시 (화면 오른쪽 위)")]
        public bool showVideo = true;
        [Range(0.1f, 0.6f)] public float videoWidthRatio = 0.35f;

        [Header("디지털 트윈")]
        public Transform twinOrigin;
        [Tooltip("미터 단위 캘리브레이션(units = m)일 때 노면 좌표 1단위의 크기(m)")]
        public float metersPerUnit = 1f;
        [Tooltip("예전 픽셀 캘리브레이션(units = px)일 때 1픽셀을 몇 m로 볼지")]
        public float pixelUnitScale = 0.05f;
        [Tooltip("같은 클래스에 여러 프리팹이 있으면 추적 ID에 따라 골라 쓴다")]
        public List<ClassPrefab> prefabs = new List<ClassPrefab>();
        public GameObject fallbackPrefab;
        [Tooltip("이 시간(초) 동안 다시 보이지 않으면 차량을 없앤다")]
        public float staleSeconds = 1.5f;
        [Tooltip("목표 위치를 따라가는 빠르기. 검출 간격 사이를 부드럽게 잇는다")]
        public float followSpeed = 6f;
        public bool snapToRoad = true;

        [Header("카메라 따라가기")]
        [Tooltip("지정하면 차량들의 가운데를 비스듬히 내려다보도록 따라간다")]
        public Camera followCamera;
        public Vector3 cameraOffset = new Vector3(0f, 45f, -35f);

        [Header("상태 (읽기 전용)")]
        public string status = "연결 전";

        readonly Dictionary<int, Vehicle> vehicles = new Dictionary<int, Vehicle>();
        readonly List<int> stale = new List<int>();
        HttpClient http;
        CancellationTokenSource cts;
        Texture2D videoTexture;

        void OnEnable()
        {
            http = new HttpClient { Timeout = TimeSpan.FromSeconds(3) };
            cts = new CancellationTokenSource();
            _ = PollState(cts.Token);
            if (showVideo) _ = PollFrame(cts.Token);
        }

        void OnDisable()
        {
            cts?.Cancel();
            cts?.Dispose();
            cts = null;
            http?.Dispose();
            http = null;
            foreach (var v in vehicles.Values)
                if (v.go) Destroy(v.go);
            vehicles.Clear();
        }

        void OnDestroy()
        {
            if (videoTexture) Destroy(videoTexture);
        }

        async Task PollState(CancellationToken token)
        {
            while (!token.IsCancellationRequested)
            {
                try
                {
                    using (var response = await http.GetAsync(serverUrl + "/state", token))
                    {
                        string json = await response.Content.ReadAsStringAsync();
                        if (token.IsCancellationRequested || this == null) return;
                        Apply(JsonUtility.FromJson<LiveState>(json));
                    }
                }
                catch (OperationCanceledException) when (token.IsCancellationRequested)
                {
                    return;
                }
                catch (Exception e)
                {
                    status = $"서버 연결 실패 ({serverUrl}): {e.GetBaseException().Message}";
                }

                try { await Task.Delay(TimeSpan.FromSeconds(statePollSeconds), token); }
                catch (OperationCanceledException) { return; }
            }
        }

        async Task PollFrame(CancellationToken token)
        {
            while (!token.IsCancellationRequested)
            {
                try
                {
                    using (var response = await http.GetAsync(serverUrl + "/frame.jpg", token))
                    {
                        if (response.IsSuccessStatusCode)
                        {
                            byte[] bytes = await response.Content.ReadAsByteArrayAsync();
                            if (token.IsCancellationRequested || this == null) return;
                            if (videoTexture == null) videoTexture = new Texture2D(2, 2);
                            videoTexture.LoadImage(bytes);
                        }
                    }
                }
                catch (OperationCanceledException) when (token.IsCancellationRequested)
                {
                    return;
                }
                catch (Exception)
                {
                    // 연결 상태는 PollState가 status에 적는다
                }

                try { await Task.Delay(TimeSpan.FromSeconds(framePollSeconds), token); }
                catch (OperationCanceledException) { return; }
            }
        }

        void Apply(LiveState state)
        {
            if (state == null) return;
            float scale = state.units == "px" ? pixelUnitScale : metersPerUnit;
            float now = Time.time;
            foreach (var o in state.objects)
            {
                var local = new Vector3(o.x * scale, 0f, o.z * scale);
                var world = twinOrigin ? twinOrigin.TransformPoint(local) : local;
                if (snapToRoad && RoadSurface.TryGetSurfacePoint(world, out var ground)) world.y = ground.y;

                if (!vehicles.TryGetValue(o.id, out var v))
                {
                    v = new Vehicle { go = Spawn(o) };
                    v.go.transform.position = world;
                    vehicles[o.id] = v;
                }
                v.target = world;
                v.lastSeen = now;
            }

            status = $"{state.camera_name} | frame {state.frame} | 차량 {state.objects.Count}대" +
                     (state.unplaced > 0 ? $" (좌표 없음 {state.unplaced})" : "") + $" | 단위 {state.units}";
        }

        GameObject Spawn(LiveObject o)
        {
            var candidates = new List<GameObject>();
            foreach (var p in prefabs)
                if (p.prefab && p.className == o.class_name) candidates.Add(p.prefab);
            var prefab = candidates.Count > 0 ? candidates[Mathf.Abs(o.id) % candidates.Count] : fallbackPrefab;

            var go = prefab ? Instantiate(prefab) : GameObject.CreatePrimitive(PrimitiveType.Cube);
            go.name = $"live_{o.id}_{o.class_name}";
            foreach (var mover in go.GetComponentsInChildren<WaypointMover>()) Destroy(mover);
            return go;
        }

        void Update()
        {
            float now = Time.time;
            float t = 1f - Mathf.Exp(-followSpeed * Time.deltaTime);
            Vector3 sum = Vector3.zero;
            int count = 0;

            foreach (var pair in vehicles)
            {
                var v = pair.Value;
                if (!v.go || now - v.lastSeen > staleSeconds)
                {
                    stale.Add(pair.Key);
                    continue;
                }
                var tr = v.go.transform;
                var delta = v.target - tr.position;
                delta.y = 0f;
                if (delta.sqrMagnitude > 0.01f) tr.rotation = Quaternion.Slerp(tr.rotation, Quaternion.LookRotation(delta), t);
                tr.position = Vector3.Lerp(tr.position, v.target, t);
                sum += tr.position;
                count++;
            }

            foreach (int id in stale)
            {
                if (vehicles[id].go) Destroy(vehicles[id].go);
                vehicles.Remove(id);
            }
            stale.Clear();

            if (followCamera && count > 0)
            {
                var center = sum / count;
                var desired = center + cameraOffset;
                var ct = followCamera.transform;
                ct.position = Vector3.Lerp(ct.position, desired, 1f - Mathf.Exp(-1.5f * Time.deltaTime));
                ct.rotation = Quaternion.Slerp(ct.rotation, Quaternion.LookRotation(center - ct.position), 1f - Mathf.Exp(-1.5f * Time.deltaTime));
            }
        }

        void OnGUI()
        {
            if (Event.current.type != EventType.Repaint) return;
            GUI.Label(new Rect(10, 10, Screen.width * 0.6f, 24), status);
            if (!showVideo || videoTexture == null) return;
            float w = Screen.width * videoWidthRatio;
            float h = w * videoTexture.height / Mathf.Max(1, videoTexture.width);
            GUI.DrawTexture(new Rect(Screen.width - w - 10, 10, w, h), videoTexture, ScaleMode.ScaleToFit);
        }
    }
}
