#if UNITY_EDITOR
using System.Collections;
using System.IO;
using UnityEngine;

namespace TwinSight.Simulation
{
    /// <summary>Fresh night stills, independent queue clips, and held-out warning clips.</summary>
    public class NightExperimentCapture : MonoBehaviour
    {
        public bool Finished { get; private set; }
        public string Progress { get; private set; }

        IEnumerator Start()
        {
            var data = new GameObject("NightStills").AddComponent<SyntheticTrainingCapture>();
            data.distantDetailPass = true; data.trainingSamples = 160; data.evaluationSamples = 40;
            data.nightCapture = true; data.seedOffset = 22000; data.sessionPrefix = "night-v1-";
            while (!data.Finished) { Progress = "stills: " + data.Progress; yield return null; }
            Destroy(data.gameObject); yield return null;
            var queues = new GameObject("NightQueues").AddComponent<StopZoneCapture>();
            queues.nightCapture = true; queues.seedOffset = 22000; queues.sessionPrefix = "nightqueue-v1-";
            while (!queues.Finished) { Progress = "queues: " + queues.Progress; yield return null; }
            Destroy(queues.gameObject); yield return null;
            var checks = new GameObject("NightWarnings").AddComponent<SyntheticWarningCapture>();
            checks.nightCapture = true; checks.sessionPrefix = "night-v1-clip-";
            while (!checks.Finished) { Progress = "warnings: " + checks.Progress; yield return null; }
            Destroy(checks.gameObject);
            Progress = "complete"; Finished = true;
            Directory.CreateDirectory("Logs"); File.WriteAllText("Logs/night-v1-capture-complete.txt", "complete");
        }
    }
}
#endif
