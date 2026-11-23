#if UNITY_EDITOR
using System.Collections;
using System.Linq;
using UnityEngine;

namespace TwinSight.Simulation
{
    /// <summary>Fixed-camera clips for inference and temporal warning checks, separate from still-image training.</summary>
    public class SyntheticWarningCapture : MonoBehaviour
    {
        public bool Finished { get; private set; }
        public string Progress { get; private set; }
        public int framesPerCase = 90;
        public bool highResolution = true;
        public bool nightCapture;
        public string sessionPrefix;
        IEnumerator Start()
        {
            Application.runInBackground = true;
            var director = FindFirstObjectByType<RoadScenarioDirector>();
            director.automaticEpisodes = false; director.cleanDatasetCapture = true; director.ResetSampling(5404);
            foreach (var s in FindObjectsByType<TrafficSpawner>(FindObjectsSortMode.None)) s.enabled = false;
            foreach (var v in TrafficVehicleAgent.All.ToArray()) if (v != null) Destroy(v.gameObject);
            var camera = GameObject.Find("VirtualCCTV").GetComponent<Camera>();
            var existing = camera.GetComponent<GroundTruthExporter>(); existing.enabled = false;
            var lighting=FindFirstObjectByType<DayNightEnvironment>();
            if(lighting!=null) lighting.showControls=false;
            if(nightCapture) lighting.Apply(SimulationTimeOfDay.Night,96502);
            foreach (var scenario in new[] { RoadScenario.Normal, RoadScenario.Pothole, RoadScenario.FallingDebris, RoadScenario.VehicleCollision, RoadScenario.StructureCollision })
            {
                director.BeginEpisode(scenario);
                if (scenario == RoadScenario.Normal)
                {
                    director.signals.SetPhaseForExperiment(SignalPhase.PedestrianGreen);
                    director.signals.enabled = false;
                    MakeQueueVehicle(director.suvPrefab, 5f, director);
                    MakeQueueVehicle(director.miniPrefab, 1.5f, director);
                }
                var exporter = camera.gameObject.AddComponent<GroundTruthExporter>();
                exporter.calibrationGrid = existing.calibrationGrid; exporter.manualCapture = true;
                exporter.imageWidth = highResolution ? 1440 : 720; exporter.imageHeight = highResolution ? 960 : 480; exporter.captureFps = 5;
                exporter.cameraId = (string.IsNullOrEmpty(sessionPrefix) ? (highResolution ? "geumchon-detail-clip-" : "geumchon-v1-clip-") : sessionPrefix) + scenario;
                exporter.maxFrames = 0; exporter.warmupSeconds = 0; exporter.stopPlayModeWhenDone = false;
                yield return null;
                for (int frame = 0; frame < framesPerCase; frame++)
                {
                    Progress = scenario + " " + frame + "/" + framesPerCase;
                    yield return null; exporter.CaptureOneForDataset();
                }
                exporter.CompleteManualDataset(); Destroy(exporter); yield return null;
                foreach (var v in TrafficVehicleAgent.All.ToArray())
                    if (v != null && v.gameObject.name.StartsWith("QueueCheck_")) Destroy(v.gameObject);
            }
            Progress = "complete"; Finished = true;
        }
        static void MakeQueueVehicle(GameObject prefab, float x, RoadScenarioDirector director)
        {
            var car = Instantiate(prefab, new Vector3(x, 0.507f, -1.06f), Quaternion.Euler(0,90,0));
            car.name = "QueueCheck_" + prefab.name;
            var agent = car.AddComponent<TrafficVehicleAgent>(); agent.signals = director.signals;
            if (car.GetComponent<TrackedObject>().TryGetWorldBounds(out var b)) agent.halfLength = b.size.x * 0.5f;
            var mover = car.AddComponent<WaypointMover>(); mover.speed = 2f;
            var path = FindObjectsByType<TrafficSpawner>(FindObjectsSortMode.None).First(s => s.name == "Outbound").path;
            mover.waypoints = Enumerable.Range(0,path.childCount).Select(i=>path.GetChild(i)).ToArray();
            mover.destroyAtEnd = false;
        }
    }
}
#endif
