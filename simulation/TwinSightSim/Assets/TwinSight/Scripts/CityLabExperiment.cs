using UnityEngine;

namespace TwinSight.Simulation
{
    /// <summary>Keyboard controls for the synthetic-data scene. This is kinematic traffic, not a driving-physics model.</summary>
    public class CityLabExperiment : MonoBehaviour
    {
        public Camera cctv;
        public Camera overview;
        public GroundTruthExporter exporter;
        public Light sun;
        [Range(0.1f, 4f)] public float simulationSpeed = 1f;
        [Range(0f, 2f)] public float sunIntensity = 1.2f;
        bool paused;

        void Update()
        {
            if (Input.GetKeyDown(KeyCode.F1)) SelectCamera(false);
            if (Input.GetKeyDown(KeyCode.F2)) SelectCamera(true);
            if (Input.GetKeyDown(KeyCode.Space)) paused = !paused;
            if (Input.GetKeyDown(KeyCode.E) && exporter != null && !exporter.enabled) exporter.enabled = true;
            Time.timeScale = paused ? 0f : simulationSpeed;
            if (sun != null) sun.intensity = sunIntensity;
        }

        public void SelectCamera(bool useOverview)
        {
            if (cctv != null) cctv.enabled = !useOverview;
            if (overview != null) overview.enabled = useOverview;
        }

        void OnDestroy() => Time.timeScale = 1f;
    }
}
