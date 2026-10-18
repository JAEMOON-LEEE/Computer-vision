#if UNITY_EDITOR
using System.Collections;
using UnityEngine;

namespace TwinSight.Simulation
{
    public class ScenarioCaptureBatch : MonoBehaviour
    {
        public bool Finished { get; private set; }
        public string Progress { get; private set; }
        IEnumerator Start()
        {
            foreach (var stage in new[] { ("safe-train", 733, 64), ("safe-val", 844, 16), ("safe-test", 955, 16) })
            {
                Progress = stage.Item1;
                var capture = new GameObject(stage.Item1 + "Capture").AddComponent<ScenarioDatasetCapture>();
                capture.split = stage.Item1; capture.datasetSeed = stage.Item2; capture.samples = stage.Item3;
                while (!capture.Finished) yield return null;
            }
            Progress = "complete"; Finished = true;
        }
    }
}
#endif
