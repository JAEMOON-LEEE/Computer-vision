#if UNITY_EDITOR
using System;
using System.Collections;
using System.IO;
using System.Linq;
using UnityEngine;

namespace TwinSight.Simulation
{
    // Disposable Play-mode capture: one independently seeded scene per session.
    public class NoVehicleRoadCapture : MonoBehaviour
    {
        public string outputRoot = "TwinSightExport/unified-yolo-no-vehicle-road-20261118";
        public int seedBase = 161000000;
        public int repetitions = 8;
        public bool closerPositions;
        public bool Finished { get; private set; }
        public string Progress { get; private set; }

        IEnumerator Start()
        {
            if (repetitions < 1 || repetitions > 100) throw new InvalidOperationException("Invalid repetitions.");
            string root = Path.GetFullPath(outputRoot);
            string workspace = Path.GetFullPath(@"D:\Capston disign").TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
            if (!root.StartsWith(workspace, StringComparison.OrdinalIgnoreCase)) throw new InvalidOperationException("Capture must stay in workspace.");
            if (Directory.Exists(root) && Directory.EnumerateFileSystemEntries(root).Any()) throw new InvalidOperationException("Output must be empty.");
            Directory.CreateDirectory(root); Application.runInBackground = true;
            var director = FindFirstObjectByType<RoadScenarioDirector>();
            var lighting = FindFirstObjectByType<DayNightEnvironment>();
            var camera = GameObject.Find("VirtualCCTV").GetComponent<Camera>();
            var original = camera.GetComponent<GroundTruthExporter>();
            if (director == null || lighting == null || original == null) throw new InvalidOperationException("Missing CityLab capture components.");
            director.automaticEpisodes = false; director.cleanDatasetCapture = false;
            var originalIncidentRange = director.incidentXRange;
            if (closerPositions) director.incidentXRange = new Vector2(-1f, 5f);
            original.enabled = false; lighting.showControls = false;
            foreach (var spawner in FindObjectsByType<TrafficSpawner>(FindObjectsSortMode.None)) spawner.enabled = false;
            foreach (var vehicle in TrafficVehicleAgent.All.ToArray()) if (vehicle != null) Destroy(vehicle.gameObject);
            var city = GameObject.Find("SeoulCity");
            if (city != null) foreach (var renderer in city.GetComponentsInChildren<Renderer>())
                if (renderer.name == "Plane.002_Chrome_0") renderer.enabled = false;
            var cameraPosition = camera.transform.position;
            yield return null;
            for (int split=0; split<3; split++)
            for (int repeat=0; repeat<repetitions; repeat++)
            for (int variant=0; variant<9; variant++)
            {
                int seed=checked(seedBase + split*1000000 + repeat*100 + variant);
                string splitName=split==0?"train":split==1?"val":"test";
                director.ResetSampling(seed); lighting.Apply(SimulationTimeOfDay.Day,seed);
                camera.transform.position=cameraPosition + new Vector3((split-1)*.7f,0,(split-1)*.25f);
                if (variant==0) director.BeginEpisode(RoadScenario.Normal);
                else if (variant<=4) director.BeginPotholeEpisode((PotholeVariant)(variant-1));
                else director.BeginDebrisEpisode((DebrisVariant)(variant-5));
                var exporter=camera.gameObject.AddComponent<GroundTruthExporter>();
                exporter.outputRoot=root; exporter.calibrationGrid=original.calibrationGrid;
                exporter.manualCapture=true; exporter.imageWidth=1440; exporter.imageHeight=960;
                exporter.captureFps=8; exporter.maxFrames=0; exporter.warmupSeconds=0; exporter.stopPlayModeWhenDone=false;
                exporter.cameraId=$"novehicle-{splitName}-v{variant}-s{seed}";
                if (variant>=5) yield return new WaitForSeconds(1.3f); else yield return null;
                yield return null;
                if (TrackedObject.All.Any(item => item != null && (item.className == "car" || item.className == "truck" || item.className == "bus" || item.className == "motorcycle")))
                    throw new InvalidOperationException("Vehicle-free capture contains tracked vehicles.");
                Progress=$"{splitName} {repeat+1}/{repetitions} variant {variant}";
                exporter.CaptureOneForDataset(); exporter.CompleteManualDataset(); Destroy(exporter);
                yield return null;
            }
            camera.transform.position=cameraPosition; Time.captureDeltaTime=0; Progress="complete"; Finished=true;
            director.incidentXRange = originalIncidentRange;
            File.WriteAllText(Path.Combine(root,"capture-complete.txt"),DateTime.Now.ToString("O"));
        }
    }
}
#endif
