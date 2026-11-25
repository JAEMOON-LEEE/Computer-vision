using System;
using System.Runtime.InteropServices;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace TwinSight.Simulation
{
    /// <summary>
    /// 웹 대시보드(/demo)와 WebGL 빌드 사이의 연결. WebGL 실행 파일에서만 스스로 생긴다(에디터 Play에는 영향 없음).
    /// 페이지 → Unity: unityInstance.SendMessage("TwinSightBridge", 메서드, 문자열).
    /// Unity → 페이지: window의 "twinsight-unity" CustomEvent (상태 0.25초마다, 시나리오 정답 이벤트는 생길 때마다).
    /// 여기서 보내는 이벤트는 Unity 시뮬레이션의 정답 기록이며 검출 모델의 경고가 아니다.
    /// </summary>
    public class WebDemoBridge : MonoBehaviour
    {
#if UNITY_WEBGL && !UNITY_EDITOR
        [DllImport("__Internal")] static extern void TwinSightEmit(string json);
#else
        static void TwinSightEmit(string json) { }
#endif

        // 씬을 다시 불러와도 유지되는 요청 상태
        static string mode = "sim";            // sim: City Lab 교통·사고 시나리오, twin: 금촌 실제 인식 재생
        static string cameraName = "incident";  // incident · orbit · cctv · overview
        static bool night;
        static bool autoEpisodes;
        static float speed = 1f;
        static string pendingScenario;

        static readonly Vector3 IncidentCentre = new Vector3(12.2f, 0.5f, -0.9f);   // RoadScenarioDirector가 사고를 만드는 구간

        RoadScenarioDirector director;
        CityLabExperiment experiment;
        TrafficSignalController signals;
        DayNightEnvironment environment;
        RealCctvTwinPlayer twin;
        DemoRoadHazards hazards;
        Camera incidentCam, orbitCam;
        float orbitAngle = 210f, nextStatus, nextCount;
        int vehicleCount, lastEpisode = -1, lastEventCount;
        Color dayAmbientSky, dayAmbientEquator, dayAmbientGround;
        float daySun = 1.2f;
        readonly System.Collections.Generic.Dictionary<Camera, (CameraClearFlags flags, Color colour)> dayClear =
            new System.Collections.Generic.Dictionary<Camera, (CameraClearFlags, Color)>();

        [Serializable] class Status
        {
            public string type = "status";
            public string mode, camera, scenario, variant, signal_phase, vehicle_light, pedestrian_light;
            public bool night, auto_episodes;
            public int episode, vehicles, twin_frame, twin_frames, twin_vehicles;
            public float signal_remaining, speed, time;
        }

        [Serializable] class EventMessage
        {
            public string type = "event";
            public string scenario, variant, event_type, evidence;
            public float relative_speed, impulse;
            public int episode;
            public float time;
        }

        [Serializable] class Simple { public string type, mode; }

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Install()
        {
            if (Application.platform != RuntimePlatform.WebGLPlayer) return;
#if UNITY_WEBGL && !UNITY_EDITOR
            WebGLInput.captureAllKeyboardInput = false;   // 대시보드 입력창·단축키가 계속 동작하게
#endif
            Application.runInBackground = true;
            var go = new GameObject("TwinSightBridge");
            DontDestroyOnLoad(go);
            var bridge = go.AddComponent<WebDemoBridge>();
            SceneManager.sceneLoaded += (scene, _) => bridge.Configure();
            bridge.Configure();
            Emit(new Simple { type = "ready", mode = mode });
        }

        static void Emit(object message) => TwinSightEmit(JsonUtility.ToJson(message));

        void Configure()
        {
            director = FindAnyObjectByType<RoadScenarioDirector>(FindObjectsInactive.Include);
            experiment = FindAnyObjectByType<CityLabExperiment>(FindObjectsInactive.Include);
            signals = FindAnyObjectByType<TrafficSignalController>(FindObjectsInactive.Include);
            twin = FindAnyObjectByType<RealCctvTwinPlayer>(FindObjectsInactive.Include);
            environment = FindAnyObjectByType<DayNightEnvironment>(FindObjectsInactive.Include);
            if (environment != null) environment.showControls = false;   // 조명 버튼은 대시보드에 있다
            // DayNightEnvironment.Start가 자기 timeOfDay로 다시 적용하므로 요청 상태를 먼저 넣어 둔다
            if (environment != null) environment.timeOfDay = night ? SimulationTimeOfDay.Night : SimulationTimeOfDay.Day;
            lastEpisode = -1; lastEventCount = 0; dayClear.Clear();

            if (mode == "twin")
            {
                if (twin == null)
                {
                    twin = new GameObject("RealCctvTwinPlayer").AddComponent<RealCctvTwinPlayer>();
                    if (director != null) { twin.suvPrefab = director.suvPrefab; twin.miniPrefab = director.miniPrefab; }
                }
                twin.showGuiText = false;          // 브라우저에는 한글 글꼴이 없어 글자는 대시보드가 그린다
                twin.secondsPerFrame = 1.5f;
                if (experiment != null) experiment.SelectCamera(false);
            }
            else
            {
                // 씬에 저장된 트윈 재생기가 Awake에서 끈 교통·시나리오를 다시 켠다(Start 전이라 아직 아무것도 놓지 않았다)
                if (twin != null) { Destroy(twin); twin = null; }
                foreach (var s in FindObjectsByType<TrafficSpawner>(FindObjectsInactive.Include)) s.enabled = true;
                if (director != null) { director.enabled = true; director.automaticEpisodes = autoEpisodes; }
                hazards = new GameObject("DemoRoadHazards").AddComponent<DemoRoadHazards>();
                hazards.director = director;
                CreateDemoCameras();
            }

            if (experiment != null && experiment.sun != null)
            {
                daySun = experiment.sunIntensity > 0.3f ? experiment.sunIntensity : 1.2f;
                dayAmbientSky = RenderSettings.ambientSkyColor;
                dayAmbientEquator = RenderSettings.ambientEquatorColor;
                dayAmbientGround = RenderSettings.ambientGroundColor;
            }
            ApplyNight();
            ApplySpeed();
            ApplyCamera();

            if (mode == "sim" && !string.IsNullOrEmpty(pendingScenario))
            {
                var scenario = pendingScenario; pendingScenario = null;
                SetVariant(scenario);
            }
        }

        void CreateDemoCameras()
        {
            var template = experiment != null ? experiment.cctv : Camera.main;
            incidentCam = MakeCamera("DemoIncidentCamera", template, 46f);
            incidentCam.transform.position = new Vector3(8.6f, 2.6f, 1.6f);   // 사고 구간을 화면 가운데에 크게
            incidentCam.transform.LookAt(IncidentCentre);
            orbitCam = MakeCamera("DemoOrbitCamera", template, 50f);
        }

        static Camera MakeCamera(string name, Camera template, float fov)
        {
            var cam = new GameObject(name).AddComponent<Camera>();
            if (template != null)
            {
                cam.clearFlags = template.clearFlags; cam.backgroundColor = template.backgroundColor;
                cam.nearClipPlane = template.nearClipPlane; cam.farClipPlane = Mathf.Max(template.farClipPlane, 400f);
            }
            cam.fieldOfView = fov; cam.enabled = false;
            return cam;
        }

        void ApplyCamera()
        {
            if (mode == "twin") return;   // 트윈 재생은 VirtualCCTV 시점 고정
            if (experiment != null)
            {
                if (experiment.cctv != null) experiment.cctv.enabled = cameraName == "cctv";
                if (experiment.overview != null) experiment.overview.enabled = cameraName == "overview";
            }
            if (incidentCam != null) incidentCam.enabled = cameraName == "incident";
            if (orbitCam != null) orbitCam.enabled = cameraName == "orbit";
        }

        void ApplyNight()
        {
            if (environment != null)
            {
                // 팀의 주간·야간 조명(가로등 포함)을 그대로 쓴다. 시연용 카메라는 VirtualCCTV의 배경을 따른다.
                environment.Apply(night ? SimulationTimeOfDay.Night : SimulationTimeOfDay.Day, environment.lightingSeed);
                var source = experiment != null && experiment.cctv != null ? experiment.cctv : null;
                if (source != null)
                    foreach (var cam in new[] { incidentCam, orbitCam, experiment.overview })
                        if (cam != null) { cam.clearFlags = source.clearFlags; cam.backgroundColor = source.backgroundColor; }
                return;
            }
            if (experiment != null) experiment.sunIntensity = night ? 0.06f : daySun;
            float k = night ? 0.16f : 1f;
            RenderSettings.ambientSkyColor = dayAmbientSky * k;
            RenderSettings.ambientEquatorColor = dayAmbientEquator * k;
            RenderSettings.ambientGroundColor = dayAmbientGround * k;
            var nightSky = new Color(0.02f, 0.03f, 0.06f);
            foreach (var cam in FindObjectsByType<Camera>(FindObjectsInactive.Include, FindObjectsSortMode.None))
            {
                if (!dayClear.ContainsKey(cam)) dayClear[cam] = (cam.clearFlags, cam.backgroundColor);
                if (night) { cam.clearFlags = CameraClearFlags.SolidColor; cam.backgroundColor = nightSky; }
                else { cam.clearFlags = dayClear[cam].flags; cam.backgroundColor = dayClear[cam].colour; }
            }
        }

        void ApplySpeed() { if (experiment != null) experiment.simulationSpeed = speed; }

        // ---- 페이지에서 부르는 메서드 (SendMessage는 문자열 인자를 쓴다) ----

        public void SetScenario(string name)
        {
            if (mode != "sim") { pendingScenario = name; SetMode("sim"); return; }
            if (name == "RoadsideDamage") { SetVariant("Roadside:Delineators"); return; }
            if (name == "Manhole") { SetVariant("Manhole:Open"); return; }
            if (!Enum.TryParse(name, true, out RoadScenario scenario)) return;
            if (director == null) return;
            director.automaticEpisodes = autoEpisodes;
            director.BeginEpisode(scenario);
        }

        public void SetAuto(string on)
        {
            autoEpisodes = on == "1" || on == "true";
            if (director != null) director.automaticEpisodes = autoEpisodes;
        }

        /// <summary>"종류:변형" 예) Pothole:Wide, Debris:FlatSlab, Collision:HeadOn, StopZone:RearEnd, Signal:OutboundRed</summary>
        public void SetVariant(string value)
        {
            if (mode != "sim") { pendingScenario = value; SetMode("sim"); return; }
            if (director == null || string.IsNullOrEmpty(value)) return;
            var parts = value.Split(':');
            if (parts.Length != 2) { SetScenario(value); return; }
            director.automaticEpisodes = autoEpisodes;
            string name = parts[1];
            switch (parts[0])
            {
                case "Pothole": if (Enum.TryParse(name, out PotholeVariant p)) director.BeginPotholeEpisode(p); break;
                case "Debris": if (Enum.TryParse(name, out DebrisVariant d)) director.BeginDebrisEpisode(d); break;
                case "Collision": if (Enum.TryParse(name, out VehicleCollisionScenario c)) director.BeginVehicleCollisionEpisode(c); break;
                case "StopZone": if (Enum.TryParse(name, out StopZoneScenario z)) director.BeginStopZoneEpisode(z, false, 0f, 2.4f, 0.25f); break;
                case "Signal": if (Enum.TryParse(name, out SignalViolationVariant v)) director.BeginSignalViolationEpisode(v); break;
                case "Roadside": if (hazards != null && Enum.TryParse(name, out RoadsideDamageVariant r)) hazards.Spawn(r); break;
                case "Manhole": if (hazards != null && Enum.TryParse(name, out ManholeVariant m)) hazards.Spawn(m); break;
            }
        }

        public void SetCamera(string name)
        {
            cameraName = name;
            if (mode == "twin") { SetMode("sim"); return; }
            ApplyCamera();
        }

        public void SetNight(string on) { night = on == "1" || on == "true"; ApplyNight(); }

        public void SetSpeed(string value)
        {
            if (float.TryParse(value, System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var v))
            { speed = Mathf.Clamp(v, 0.25f, 3f); ApplySpeed(); }
        }

        public void SetMode(string value)
        {
            value = value == "twin" ? "twin" : "sim";
            if (value == mode) return;
            mode = value;
            SceneManager.LoadScene(SceneManager.GetActiveScene().buildIndex);
        }

        public void TwinStep(string delta) { if (twin != null && int.TryParse(delta, out var d)) twin.StepBy(d); }

        public void TwinAutoPlay(string on) { if (twin != null) twin.autoPlay = on == "1" || on == "true"; }

        string Scenario() => hazards != null && hazards.Current != "" ? hazards.Current : director != null ? director.Current.ToString() : "";

        string Variant() => hazards != null && hazards.Current != "" ? hazards.Variant : director == null ? "" : !string.IsNullOrEmpty(director.CollisionVariant) ? director.CollisionVariant : director.ScenarioVariant;

        void Update()
        {
            if (orbitCam != null && orbitCam.enabled)
            {
                orbitAngle += Time.unscaledDeltaTime * 10f;
                float rad = orbitAngle * Mathf.Deg2Rad;
                orbitCam.transform.position = IncidentCentre + new Vector3(Mathf.Cos(rad) * 6.5f, 3.6f, Mathf.Sin(rad) * 6.5f);
                orbitCam.transform.LookAt(IncidentCentre);
            }

            if (director != null && mode == "sim")
            {
                if (director.Episode != lastEpisode) { lastEpisode = director.Episode; lastEventCount = 0; }
                for (; lastEventCount < director.Events.Count; lastEventCount++)
                {
                    var e = director.Events[lastEventCount];
                    Emit(new EventMessage { scenario = Scenario(), variant = Variant(), event_type = e.event_type,
                        evidence = e.evidence, episode = director.Episode, time = e.timestamp,
                        relative_speed = e.relative_speed_units_per_second, impulse = e.impulse });
                }
            }

            if (Time.unscaledTime >= nextCount)
            {
                nextCount = Time.unscaledTime + 0.5f;
                vehicleCount = FindObjectsByType<TrafficVehicleAgent>(FindObjectsSortMode.None).Length;
            }
            if (Time.unscaledTime < nextStatus) return;
            nextStatus = Time.unscaledTime + 0.25f;
            var status = new Status
            {
                mode = mode, camera = mode == "twin" ? "cctv" : cameraName, night = night, auto_episodes = autoEpisodes,
                speed = speed, time = Time.time, vehicles = vehicleCount,
                scenario = mode == "sim" ? Scenario() : "",
                variant = mode == "sim" ? Variant() : "",
                episode = director != null ? director.Episode : 0,
            };
            if (signals != null && signals.isActiveAndEnabled)
            {
                var s = signals.Snapshot();
                status.signal_phase = s.phase; status.vehicle_light = s.vehicle; status.pedestrian_light = s.pedestrian;
                status.signal_remaining = s.remaining_seconds;
            }
            if (twin != null)
            {
                status.twin_frame = twin.FrameIndex; status.twin_frames = twin.FrameCount; status.twin_vehicles = twin.ShownCount;
            }
            Emit(status);
        }
    }
}
