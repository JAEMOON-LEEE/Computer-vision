using System;
using UnityEngine;
using UnityEngine.Rendering;

namespace TwinSight.Simulation
{
    public enum SimulationTimeOfDay { Day, Night }

    [Serializable]
    public class EnvironmentSnapshot
    {
        public string time_of_day;
        public int lighting_seed;
        public float ambient_level;
        public float sun_intensity;
        public float street_light_intensity;
    }

    /// <summary>Lighting only: preserves the purchased road, signal meshes and CCTV calibration.</summary>
    public class DayNightEnvironment : MonoBehaviour
    {
        public SimulationTimeOfDay timeOfDay = SimulationTimeOfDay.Day;
        public bool showControls = true;
        public int lightingSeed = 22001;
        public Light sun;
        public Camera cctv;
        Light[] streetLights;
        float ambientLevel, streetIntensity;

        void Start() { Apply(timeOfDay, lightingSeed); }

        public void SetDay() { Apply(SimulationTimeOfDay.Day, lightingSeed); }
        public void SetNight() { Apply(SimulationTimeOfDay.Night, lightingSeed); }

        public void Apply(SimulationTimeOfDay mode, int seed)
        {
            timeOfDay = mode; lightingSeed = seed;
            if (sun == null) sun = GameObject.Find("Sun").GetComponent<Light>();
            if (cctv == null) cctv = GameObject.Find("VirtualCCTV").GetComponent<Camera>();
            EnsureLights();
            var random = new System.Random(seed);
            bool night = mode == SimulationTimeOfDay.Night;
            ambientLevel = night ? 0.07f + (float)random.NextDouble() * 0.13f : 1f;
            streetIntensity = night ? 1.1f + (float)random.NextDouble() * 1.9f : 0f;
            sun.intensity = night ? 0.035f + (float)random.NextDouble() * 0.065f : 1.2f;
            var experiment = FindFirstObjectByType<CityLabExperiment>();
            if (experiment != null) experiment.sunIntensity = sun.intensity;
            sun.color = night ? new Color(0.56f, 0.65f, 1f) : Color.white;
            sun.transform.rotation = night ? Quaternion.Euler(24f, -35f, 0f) : Quaternion.Euler(45f, -35f, 0f);
            RenderSettings.ambientMode = AmbientMode.Trilight;
            RenderSettings.ambientSkyColor = new Color(0.65f, 0.72f, 0.82f) * ambientLevel;
            RenderSettings.ambientEquatorColor = new Color(0.55f, 0.57f, 0.6f) * ambientLevel;
            RenderSettings.ambientGroundColor = new Color(0.35f, 0.37f, 0.4f) * ambientLevel;
            RenderSettings.reflectionIntensity = night ? 0.08f : 1f;
            cctv.backgroundColor = night ? new Color(0.012f, 0.019f, 0.04f) : new Color(0.6f, 0.72f, 0.82f);
            foreach (var light in streetLights)
            {
                light.enabled = night;
                light.intensity = streetIntensity * (0.65f + (float)random.NextDouble() * 0.7f);
                light.color = Color.Lerp(new Color(1f, 0.64f, 0.32f), new Color(0.65f, 0.78f, 1f), (float)random.NextDouble());
            }
        }

        void EnsureLights()
        {
            if (streetLights != null) return;
            var root = transform.Find("NightStreetLighting");
            if (root == null)
            {
                root = new GameObject("NightStreetLighting").transform;
                root.SetParent(transform, false);
                // Light sources along the existing sidewalks; no replacement road/signal geometry.
                for (int i = 0; i < 8; i++)
                {
                    var lamp = new GameObject("StreetLight_" + i).AddComponent<Light>();
                    lamp.transform.SetParent(root, false);
                    lamp.transform.position = new Vector3(-13f + i / 2 * 10f, 3.8f, i % 2 == 0 ? -2.7f : 2f);
                    lamp.type = LightType.Point; lamp.range = 9f;
                    lamp.shadows = LightShadows.None; lamp.renderMode = LightRenderMode.ForcePixel;
                }
            }
            streetLights = root.GetComponentsInChildren<Light>(true);
        }

        public EnvironmentSnapshot Snapshot() => new EnvironmentSnapshot {
            time_of_day = timeOfDay.ToString(), lighting_seed = lightingSeed,
            ambient_level = ambientLevel, sun_intensity = sun != null ? sun.intensity : 0,
            street_light_intensity = streetIntensity
        };

        void OnGUI()
        {
            if (!showControls) return;
            GUILayout.BeginArea(new Rect(10, 40, 230, 94), GUI.skin.box);
            GUILayout.Label("CCTV lighting: " + timeOfDay);
            GUILayout.BeginHorizontal();
            if (GUILayout.Button("Day / 낮")) SetDay();
            if (GUILayout.Button("Night / 밤")) SetNight();
            GUILayout.EndHorizontal();
            GUILayout.EndArea();
        }
    }
}
