#if UNITY_EDITOR
using System.Collections;
using System.Linq;
using UnityEngine;

namespace TwinSight.Simulation
{
    /// <summary>Temporary capture probe for varied synthetic stills, not attached to saved scenes.</summary>
    public class ScenarioDatasetCapture : MonoBehaviour
    {
        public int samples = 96;
        public int datasetSeed = 110;
        public string split = "train";
        public bool Finished { get; private set; }

        IEnumerator Start()
        {
            var director = FindFirstObjectByType<RoadScenarioDirector>();
            director.automaticEpisodes = false; director.ResetSampling(datasetSeed);
            director.cleanDatasetCapture = true;
            var spawners = FindObjectsByType<TrafficSpawner>(FindObjectsSortMode.None);
            foreach (var spawner in spawners) spawner.enabled = false;
            foreach (var vehicle in TrafficVehicleAgent.All.ToArray()) if (vehicle != null) Destroy(vehicle.gameObject);
            var camera = GameObject.Find("VirtualCCTV").GetComponent<Camera>();
            var existing = camera.GetComponent<GroundTruthExporter>();
            var exporter = camera.gameObject.AddComponent<GroundTruthExporter>();
            exporter.calibrationGrid = existing.calibrationGrid;
            exporter.manualCapture = true; exporter.imageWidth = 640; exporter.imageHeight = 360;
            exporter.cameraId = "scenario-" + split + "-" + datasetSeed;
            exporter.maxFrames = 0; exporter.captureFps = 5; exporter.warmupSeconds = 0;
            exporter.stopPlayModeWhenDone = false; exporter.enabled = true;
            var random = new System.Random(datasetSeed);
            Vector3 originalPosition = camera.transform.position; Quaternion originalRotation = camera.transform.rotation;
            yield return new WaitForEndOfFrame();
            for (int i = 0; i < samples; i++)
            {
                RoadScenario scenario = (i % 4) switch
                { 0 => RoadScenario.Normal, 1 => RoadScenario.Pothole, 2 => RoadScenario.FallingDebris, _ => RoadScenario.StructureCollision };
                director.BeginEpisode(scenario);
                camera.transform.position = new Vector3(8f, 11f, -3f) + new Vector3((float)random.NextDouble() - 0.5f,
                    (float)random.NextDouble() - 0.5f, (float)random.NextDouble() * 0.6f - 0.3f);
                camera.transform.LookAt(new Vector3(11.7f + (float)random.NextDouble(), 0.507f, -0.41f));
                // Let falling concrete settle through actual simulation before taking its training image.
                if (scenario == RoadScenario.FallingDebris) yield return new WaitForSeconds(0.9f);
                else yield return null;
                yield return new WaitForEndOfFrame();
                exporter.CaptureOneForDataset();
            }
            exporter.CompleteManualDataset();
            Destroy(exporter);
            camera.transform.SetPositionAndRotation(originalPosition, originalRotation);
            director.automaticEpisodes = true; director.cleanDatasetCapture = false;
            foreach (var spawner in spawners) spawner.enabled = true;
            Finished = true;
        }
    }
}
#endif
