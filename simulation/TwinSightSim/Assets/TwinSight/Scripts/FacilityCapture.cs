#if UNITY_EDITOR
using System;
using System.Collections;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using UnityEngine;

namespace TwinSight.Simulation
{
    // One complete episode per session; never split the frames of a session.
    public class FacilityCapture : MonoBehaviour
    {
        public string outputRoot = "TwinSightExport/facility-v1";
        public int seedBase = 410000;
        public int repetitions = 1;
        public int framesPerClip = 96;
        public int captureFps = 8;
        public string onlyCase = "";
        public string onlyCases = "";
        public bool dayOnly;
        public bool varyBackground;
        public bool varyCamera;
        public bool exportDelineatorBoxes;
        public bool exportOtherFacilityBoxes;
        public bool noVehicles;
        public bool closerPositions;
        public bool centerlineFacilities;
        public bool nearestPositions;
        // When requested, capture a normal baseline and the selected target with the same seed.
        // Both sessions must remain in the same data split.
        public bool capturePairedReference;
        public string casePrefixes = "";
        public bool Finished { get; private set; }
        public string Progress { get; private set; }

        IEnumerator Start()
        {
            if (repetitions < 1 || repetitions > 100 || framesPerClip < 1 || captureFps < 1)
                throw new InvalidOperationException("Invalid facility capture settings.");
            string root = Path.GetFullPath(outputRoot);
            var workspace = Path.GetFullPath(@"D:\Capston disign").TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
            if (!root.StartsWith(workspace, StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Project captures must be stored under D:\\Capston disign.");
            if (!string.IsNullOrEmpty(onlyCase) && !Enum.GetNames(typeof(FacilityCase)).Contains(onlyCase))
                throw new InvalidOperationException("Unknown facility case: " + onlyCase);
            var requestedCases = onlyCases.Split(',').Select(value => value.Trim()).Where(value => value.Length > 0).ToArray();
            if (requestedCases.Any(value => !Enum.GetNames(typeof(FacilityCase)).Contains(value)))
                throw new InvalidOperationException("Unknown case in onlyCases.");
            if (Directory.Exists(root) && Directory.EnumerateFileSystemEntries(root).Any())
                throw new InvalidOperationException("Choose an empty output directory; never overwrite a capture.");
            Directory.CreateDirectory(root);
            Application.runInBackground = true;
            var director = FindFirstObjectByType<RoadScenarioDirector>();
            var lighting = FindFirstObjectByType<DayNightEnvironment>();
            var camera = GameObject.Find("VirtualCCTV").GetComponent<Camera>();
            var cameraPosition = camera.transform.position;
            var original = camera.GetComponent<GroundTruthExporter>();
            if (director == null || lighting == null || original == null) throw new InvalidOperationException("CityLab capture components are required.");
            director.automaticEpisodes = false;
            director.exportDelineatorBoxes = exportDelineatorBoxes;
            director.exportOtherFacilityBoxes = exportOtherFacilityBoxes;
            director.useCloserFacilityPositions = closerPositions;
            director.useCenterlineFacilities = centerlineFacilities;
            director.useNearestFacilityPositions = nearestPositions;
            original.enabled = false;
            lighting.showControls = false;
            foreach (var spawner in FindObjectsByType<TrafficSpawner>(FindObjectsSortMode.None)) spawner.enabled = false;
            foreach (var vehicle in TrafficVehicleAgent.All.ToArray()) if (vehicle != null) Destroy(vehicle.gameObject);
            if (noVehicles)
            {
                if (requestedCases.Any(value => value.EndsWith("PassingVehicle", StringComparison.Ordinal)))
                    throw new InvalidOperationException("A passing-vehicle case cannot also be vehicle-free.");
                var city = GameObject.Find("SeoulCity");
                if (city != null) foreach (var renderer in city.GetComponentsInChildren<Renderer>())
                    if (renderer.name == "Plane.002_Chrome_0") renderer.enabled = false;
            }
            var cases = (FacilityCase[])Enum.GetValues(typeof(FacilityCase));
            for (int split = 0; split < 3; split++)
            for (int dayNight = 0; dayNight < (dayOnly ? 1 : 2); dayNight++)
            for (int repeat = 0; repeat < repetitions; repeat++)
            foreach (var scenario in cases)
            {
                if (!string.IsNullOrEmpty(onlyCase) && scenario.ToString() != onlyCase) continue;
                if (requestedCases.Length > 0 && !requestedCases.Contains(scenario.ToString())) continue;
                if (!string.IsNullOrWhiteSpace(casePrefixes) && !casePrefixes.Split(',').Any(prefix => scenario.ToString().StartsWith(prefix.Trim(), StringComparison.Ordinal))) continue;
                if (capturePairedReference && !scenario.ToString().StartsWith("Guardrail", StringComparison.Ordinal) && !scenario.ToString().StartsWith("Manhole", StringComparison.Ordinal))
                    throw new InvalidOperationException("Paired reference capture supports guardrails and manholes only.");
                for (int pairStage = 0; pairStage < (capturePairedReference ? 2 : 1); pairStage++)
                {
                // Fixed disjoint ranges for split, lighting, repetition and case.
                int seed = checked(seedBase + split * 1000000 + dayNight * 200000 + repeat * 100 + (int)scenario);
                string splitName = split == 0 ? "train" : split == 1 ? "val" : "test";
                director.ResetSampling(seed);
                if (varyCamera) camera.transform.position = cameraPosition + new Vector3((split - 1) * .7f, 0, (split - 1) * .25f);
                lighting.Apply((SimulationTimeOfDay)dayNight, seed);
                var actualScenario = capturePairedReference && pairStage == 0 ?
                    (scenario.ToString().StartsWith("Manhole", StringComparison.Ordinal) ? FacilityCase.ManholeNormal : FacilityCase.GuardrailNormal) : scenario;
                director.BeginFacilityEpisode(actualScenario);
                var background = new List<GameObject>();
                if (varyBackground && !noVehicles)
                {
                    var variation = new System.Random(seed);
                    // Independent background configurations; not collision actors.
                    int number = 1 + variation.Next(3);
                    for (int i = 0; i < number; i++)
                    {
                        float x = -10f + i * 5f + (float)variation.NextDouble() * 2f;
                        float lane = variation.Next(2) == 0 ? -.95f : .24f;
                        var prefab = variation.Next(2) == 0 ? director.suvPrefab : director.miniPrefab;
                        var vehicle = Instantiate(prefab, new Vector3(x, .507f, lane), Quaternion.Euler(0, 90, 0));
                        vehicle.name = "FacilityBackgroundVehicle"; background.Add(vehicle);
                    }
                    if (dayNight == 0 && lighting.sun != null)
                        lighting.sun.intensity = .85f + (float)variation.NextDouble() * .5f;
                }
                var exporter = camera.gameObject.AddComponent<GroundTruthExporter>();
                exporter.outputRoot = root; exporter.calibrationGrid = original.calibrationGrid;
                exporter.manualCapture = true; exporter.imageWidth = 1440; exporter.imageHeight = 960;
                exporter.captureFps = captureFps; exporter.maxFrames = 0; exporter.warmupSeconds = 0;
                exporter.stopPlayModeWhenDone = false;
                string pairRole = capturePairedReference ? (pairStage == 0 ? "-reference" : "-target") : "";
                exporter.cameraId = $"facility-{splitName}-{(SimulationTimeOfDay)dayNight}-{scenario}{pairRole}-s{seed}";
                yield return null;
                for (int frame = 0; frame < framesPerClip; frame++)
                {
                    Progress = $"{splitName} {(SimulationTimeOfDay)dayNight} {scenario}{pairRole} {frame + 1}/{framesPerClip}";
                    yield return null;
                    if (noVehicles && TrackedObject.All.Any(item => item != null &&
                        (item.className == "car" || item.className == "truck" || item.className == "bus" || item.className == "motorcycle")))
                        throw new InvalidOperationException("Vehicle-free capture contains tracked vehicles.");
                    exporter.CaptureOneForDataset();
                }
                exporter.CompleteManualDataset();
                Destroy(exporter);
                foreach (var item in background) if (item != null) Destroy(item);
                yield return null;
                }
            }
            if (director.signals != null) { director.signals.suppressedVehicleLampIndex = -1; director.signals.RefreshLamps(); }
            director.exportDelineatorBoxes = false;
            director.exportOtherFacilityBoxes = false;
            director.useCloserFacilityPositions = false;
            director.useCenterlineFacilities = false;
            director.useNearestFacilityPositions = false;
            camera.transform.position = cameraPosition;
            Time.captureDeltaTime = 0;
            Progress = "complete"; Finished = true;
            File.WriteAllText(Path.Combine(root, "capture-complete.txt"), DateTime.Now.ToString("O"));
        }
    }
}
#endif
