#if UNITY_EDITOR
using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEngine;

namespace TwinSight.Simulation
{
    /// <summary>Play-mode-only fresh scenes, with explicit session splits and exported object labels.</summary>
    public class SyntheticTrainingCapture : MonoBehaviour
    {
        public bool Finished { get; private set; }
        public string Progress { get; private set; }
        public bool distantDetailPass;
        public int trainingSamples = 240;
        public int evaluationSamples = 48;
        public bool nightCapture;
        public int seedOffset;
        public string sessionPrefix;
        readonly List<GameObject> extras = new List<GameObject>();
        System.Random random;
        RoadScenarioDirector director;
        GameObject personTemplate;

        IEnumerator Start()
        {
            Application.runInBackground = true;
            director = FindFirstObjectByType<RoadScenarioDirector>();
            director.automaticEpisodes = false; director.cleanDatasetCapture = true;
            director.incidentXRange = distantDetailPass ? new Vector2(5f, 17f) : new Vector2(-10f, 15f);
            var spawners = FindObjectsByType<TrafficSpawner>(FindObjectsSortMode.None);
            foreach (var spawner in spawners) spawner.enabled = false;
            foreach (var vehicle in TrafficVehicleAgent.All.ToArray()) if (vehicle != null) Destroy(vehicle.gameObject);
            // The imported, parked car has no instance label. Hide it for the capture session.
            var city = GameObject.Find("SeoulCity");
            foreach (var r in city.GetComponentsInChildren<Renderer>())
                if (r.name == "Plane.002_Chrome_0") r.enabled = false;
            var walkers = FindObjectsByType<PedestrianCrossingAgent>(FindObjectsSortMode.None);
            personTemplate = walkers[0].gameObject;
            foreach (var walker in walkers) walker.gameObject.SetActive(false);
            var camera = GameObject.Find("VirtualCCTV").GetComponent<Camera>();
            var existing = camera.GetComponent<GroundTruthExporter>(); existing.enabled = false;
            var sun = GameObject.Find("Sun").GetComponent<Light>();
            var lighting = FindFirstObjectByType<DayNightEnvironment>();
            if (nightCapture && lighting == null) throw new InvalidOperationException("Install Day/Night Environment before capture.");
            if (lighting != null) lighting.showControls = false;
            foreach (var stage in new[] { ("train", 6201, trainingSamples), ("val", 7302, evaluationSamples), ("test", 8403, evaluationSamples) })
            {
                int seed = stage.Item2 + (distantDetailPass ? 1000 : 0) + seedOffset;
                random = new System.Random(seed); director.ResetSampling(seed);
                var exporter = camera.gameObject.AddComponent<GroundTruthExporter>();
                exporter.calibrationGrid = existing.calibrationGrid;
                exporter.manualCapture = true; exporter.imageWidth = distantDetailPass ? 1440 : 720; exporter.imageHeight = distantDetailPass ? 960 : 480;
                string prefix = string.IsNullOrEmpty(sessionPrefix) ? (distantDetailPass ? "geumchon-detail-" : "geumchon-v1-") : sessionPrefix;
                exporter.cameraId = prefix + stage.Item1 + "-" + seed;
                exporter.maxFrames = 0; exporter.captureFps = 5; exporter.warmupSeconds = 0;
                exporter.stopPlayModeWhenDone = false;
                var poses = new List<object>();
                yield return null;
                for (int i = 0; i < stage.Item3; i++)
                {
                    Progress = stage.Item1 + " " + i + "/" + stage.Item3;
                    foreach (var extra in extras) if (extra != null) { extra.SetActive(false); Destroy(extra); }
                    extras.Clear();
                    var scenario = (RoadScenario)(i % 5);
                    director.BeginEpisode(scenario);
                    // Keep the restored reference CCTV pose fixed, including validation/test.
                    if (nightCapture) lighting.Apply(SimulationTimeOfDay.Night, seed * 1000 + i);
                    else {
                    sun.intensity = distantDetailPass ? Range(1.1f, 1.3f) : Range(0.85f, 1.35f);
                    sun.transform.rotation = distantDetailPass ? Quaternion.Euler(Range(43f, 47f), Range(-38f, -32f), 0)
                        : Quaternion.Euler(Range(38f, 65f), Range(-55f, -15f), 0);
                    }
                    foreach (var obj in TrackedObject.All.ToArray())
                        if (obj != null && (obj.className == "pothole" || obj.className == "debris"))
                            obj.transform.localScale *= Range(0.8f, 1.3f);
                    // Keep the added vehicles clear of hazards and deliberate collision actors.
                    int cars = scenario == RoadScenario.Normal ? i / 5 % 4 : (i % 2);
                    for (int c = 0; c < cars; c++)
                    {
                        Vector3 pos = new Vector3(Range(-12f, 21f), 0.507f, 0.24f);
                        var prefab = (i + c) % 2 == 0 ? director.suvPrefab : director.miniPrefab;
                        extras.Add(Instantiate(prefab, pos, Quaternion.Euler(0, -90 + Range(-4, 4), 0)));
                    }
                    for (int p = 0; p < i % 3; p++)
                    {
                        var person = Instantiate(personTemplate);
                        person.GetComponent<PedestrianCrossingAgent>().enabled = false;
                        person.transform.position = new Vector3(Range(-10f, 19f), 0.507f, p == 0 ? 1.7f : -2.15f);
                        person.transform.rotation = Quaternion.Euler(0, Range(0, 360), 0);
                        person.transform.localScale = Vector3.one * Range(0.9f, 1.15f);
                        person.SetActive(true); extras.Add(person);
                    }
                    // Capture settled debris and actual collision aftermath, not the scheduled event.
                    if (scenario == RoadScenario.FallingDebris) yield return new WaitForSeconds(1.3f);
                    else if (scenario == RoadScenario.VehicleCollision || scenario == RoadScenario.StructureCollision)
                        yield return new WaitForSeconds(distantDetailPass && i % 3 == 0 ? 0.4f : 2.3f);
                    else yield return null;
                    yield return null;
                    exporter.CaptureOneForDataset();
                    poses.Add(new { frame = i, scenario = scenario.ToString(), position = camera.transform.position.ToString("F4"),
                        rotation = camera.transform.eulerAngles.ToString("F4"), fov = camera.fieldOfView, light = sun.intensity });
                }
                exporter.CompleteManualDataset(); Destroy(exporter);
                Directory.CreateDirectory("Logs");
                File.WriteAllText(Path.Combine("Logs", prefix + stage.Item1 + "-poses.json"), Newtonsoft.Json.JsonConvert.SerializeObject(poses));
                yield return null;
            }
            Progress = "complete"; Finished = true;
            // Capture is a disposable Play session. Stop Play before normal simulation or saving a scene.
        }
        float Range(float low, float high) => low + (float)random.NextDouble() * (high - low);
    }
}
#endif
