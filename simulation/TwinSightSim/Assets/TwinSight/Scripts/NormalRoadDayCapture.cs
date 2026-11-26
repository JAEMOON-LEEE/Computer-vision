#if UNITY_EDITOR
using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Newtonsoft.Json;
using UnityEngine;

namespace TwinSight.Simulation
{
    /// <summary>One seeded, daytime, normal road scene per capture session.</summary>
    public class NormalRoadDayCapture : MonoBehaviour
    {
        public string outputRoot = "TwinSightExport/normal-road-day-20261117";
        public int seedBase = 83000000;
        public int trainCount = 90, valCount = 45, testCount = 45;
        public bool Finished { get; private set; }
        public string Progress { get; private set; }
        readonly List<GameObject> extras = new List<GameObject>();

        IEnumerator Start()
        {
            if (trainCount < 0 || valCount < 0 || testCount < 0 || trainCount > 1000 || valCount > 1000 || testCount > 1000)
                throw new InvalidOperationException("Invalid split sizes.");
            var root = Path.GetFullPath(outputRoot);
            var workspace = Path.GetFullPath(@"D:\Capston disign").TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
            if (!root.StartsWith(workspace, StringComparison.OrdinalIgnoreCase)) throw new InvalidOperationException("Capture must remain in the project workspace.");
            if (Directory.Exists(root) && Directory.EnumerateFileSystemEntries(root).Any()) throw new InvalidOperationException("Choose an empty output directory.");
            Directory.CreateDirectory(root);
            Application.runInBackground = true;
            var director = FindFirstObjectByType<RoadScenarioDirector>();
            var lighting = FindFirstObjectByType<DayNightEnvironment>();
            var cameraObject = GameObject.Find("VirtualCCTV");
            if (director == null || lighting == null || cameraObject == null) throw new InvalidOperationException("Existing CityLab capture components are required.");
            var camera = cameraObject.GetComponent<Camera>();
            var existing = camera.GetComponent<GroundTruthExporter>();
            if (existing == null) throw new InvalidOperationException("Existing CCTV exporter is required.");
            var initialPosition = camera.transform.position;
            var initialRotation = camera.transform.rotation;
            var initialFov = camera.fieldOfView;
            director.automaticEpisodes = false; director.cleanDatasetCapture = true;
            existing.enabled = false; lighting.showControls = false;
            foreach (var spawner in FindObjectsByType<TrafficSpawner>(FindObjectsSortMode.None)) spawner.enabled = false;
            foreach (var vehicle in TrafficVehicleAgent.All.ToArray()) if (vehicle != null) Destroy(vehicle.gameObject);
            foreach (var walker in FindObjectsByType<PedestrianCrossingAgent>(FindObjectsSortMode.None)) walker.gameObject.SetActive(false);
            yield return null;
            foreach (var stage in new[] { ("train", 0, trainCount), ("val", 1, valCount), ("test", 2, testCount) })
            for (int i = 0; i < stage.Item3; i++)
            {
                foreach (var item in extras) if (item != null) { item.SetActive(false); Destroy(item); }
                extras.Clear();
                int seed = checked(seedBase + stage.Item2 * 1000000 + i);
                var rng = new System.Random(seed);
                float Range(float low, float high) => low + (float)rng.NextDouble() * (high - low);
                director.ResetSampling(seed); director.BeginEpisode(RoadScenario.Normal);
                lighting.Apply(SimulationTimeOfDay.Day, seed);
                float intensity = Range(.85f, 1.35f), sunPitch = Range(38f, 65f), sunYaw = Range(-55f, -15f);
                lighting.sun.intensity = intensity; lighting.sun.transform.rotation = Quaternion.Euler(sunPitch, sunYaw, 0);
                var offset = new Vector3(Range(-1.5f, 1.5f), Range(-.5f, .5f), Range(-1.0f, 1.0f));
                float pitch = Range(-4f, 4f), yaw = Range(-5f, 5f), fovDelta = Range(-3f, 3f);
                camera.transform.SetPositionAndRotation(initialPosition + offset, initialRotation * Quaternion.Euler(pitch, yaw, 0));
                camera.fieldOfView = initialFov + fovDelta;
                bool pedestrianPhase = rng.Next(2) == 0;
                if (director.signals != null)
                {
                    director.signals.SetPhaseForExperiment(pedestrianPhase ? SignalPhase.PedestrianGreen : SignalPhase.VehicleGreen);
                    director.signals.enabled = false;
                }
                int count = rng.Next(5);
                var cars = new List<object>();
                for (int j = 0; j < count; j++)
                {
                    bool suv = rng.Next(2) == 0;
                    var prefab = suv ? director.suvPrefab : director.miniPrefab;
                    if (prefab == null) throw new InvalidOperationException("Existing vehicle prefab is missing.");
                    float x = -10f + j * 7f + Range(-.7f, .7f), z = rng.Next(2) == 0 ? -1.06f : .24f;
                    float heading = (z < 0 ? 90f : -90f) + Range(-3f, 3f);
                    var car = Instantiate(prefab, new Vector3(x, .507f, z), Quaternion.Euler(0, heading, 0));
                    car.name = "NormalRoadBackgroundVehicle"; extras.Add(car);
                    foreach (var rb in car.GetComponentsInChildren<Rigidbody>()) { rb.linearVelocity = Vector3.zero; rb.isKinematic = true; }
                    foreach (var agent in car.GetComponentsInChildren<TrafficVehicleAgent>()) agent.enabled = false;
                    foreach (var mover in car.GetComponentsInChildren<WaypointMover>()) mover.enabled = false;
                    cars.Add(new { type = suv ? "suv" : "mini", x, z, heading });
                }
                if (TrackedObject.All.Any(o => o != null && (o.className == "pothole" || o.className == "debris")))
                    throw new InvalidOperationException("Normal capture contains tracked road hazards.");
                var exporter = cameraObject.AddComponent<GroundTruthExporter>();
                exporter.outputRoot = root; exporter.calibrationGrid = existing.calibrationGrid;
                exporter.manualCapture = true; exporter.imageWidth = 720; exporter.imageHeight = 480;
                exporter.captureFps = 5; exporter.warmupSeconds = 0; exporter.stopPlayModeWhenDone = false;
                exporter.cameraId = $"normal-road-{stage.Item1}-s{seed}";
                yield return null;
                Progress = $"{stage.Item1} {i+1}/{stage.Item3}";
                exporter.CaptureOneForDataset();
                var variation = new { split=stage.Item1, seed, scenario="Normal", state="normal", time_of_day="Day",
                    camera_position=new[]{camera.transform.position.x,camera.transform.position.y,camera.transform.position.z},
                    camera_euler=new[]{camera.transform.eulerAngles.x,camera.transform.eulerAngles.y,camera.transform.eulerAngles.z},
                    camera_fov=camera.fieldOfView, sun_intensity=intensity, sun_pitch=sunPitch, sun_yaw=sunYaw,
                    signal_phase=pedestrianPhase?"PedestrianGreen":"VehicleGreen", vehicle_count=count, vehicles=cars };
                File.WriteAllText(Path.Combine(exporter.RunDirectory, "variation.json"),JsonConvert.SerializeObject(variation,Formatting.Indented));
                exporter.CompleteManualDataset(); Destroy(exporter);
                yield return null;
            }
            foreach (var item in extras) if (item != null) { item.SetActive(false); Destroy(item); }
            camera.transform.SetPositionAndRotation(initialPosition,initialRotation); camera.fieldOfView=initialFov;
            Time.captureDeltaTime = 0; Progress="complete"; Finished=true;
            File.WriteAllText(Path.Combine(root,"capture-complete.txt"),DateTime.Now.ToString("O"));
        }
    }
}
#endif
