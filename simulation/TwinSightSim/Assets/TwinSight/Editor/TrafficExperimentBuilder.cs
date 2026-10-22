using System;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using Object = UnityEngine.Object;

namespace TwinSight.Simulation.EditorTools
{
    public static class TrafficExperimentBuilder
    {
        [MenuItem("TwinSight/City Lab/Install Day Night Controls")]
        public static void InstallDayNightControls()
        {
            var environment = Object.FindFirstObjectByType<DayNightEnvironment>();
            if (environment == null) environment = new GameObject("DayNightEnvironment").AddComponent<DayNightEnvironment>();
            environment.Apply(SimulationTimeOfDay.Day, 22001);
            if (!EditorApplication.isPlaying)
            {
                EditorSceneManager.MarkSceneDirty(UnityEngine.SceneManagement.SceneManager.GetActiveScene());
                EditorSceneManager.SaveScene(UnityEngine.SceneManagement.SceneManager.GetActiveScene());
            }
        }

        [MenuItem("TwinSight/City Lab/Capture Night Training Dataset (Play Mode)")]
        public static void CaptureNightDataset()
        {
            if (!EditorApplication.isPlaying) throw new InvalidOperationException("Enter Play mode before capturing.");
            var capture = new GameObject("NightTrainingCapture").AddComponent<SyntheticTrainingCapture>();
            capture.distantDetailPass = true; capture.trainingSamples = 160; capture.evaluationSamples = 40;
            capture.nightCapture = true; capture.seedOffset = 22000; capture.sessionPrefix = "night-v1-";
        }
        [MenuItem("TwinSight/City Lab/Capture Stop Zone Training and Checks (Play Mode)")]
        public static void CaptureStopZoneDataset()
        {
            if (!EditorApplication.isPlaying) throw new InvalidOperationException("Enter Play mode before capturing.");
            new GameObject("StopZoneCapture").AddComponent<StopZoneCapture>();
        }
        [MenuItem("TwinSight/City Lab/Capture Reference CCTV Detail Dataset (Play Mode)")]
        public static void CaptureDetailDataset()
        {
            if (!EditorApplication.isPlaying) throw new InvalidOperationException("Enter Play mode before capturing.");
            var capture = new GameObject("SyntheticTrainingCapture").AddComponent<SyntheticTrainingCapture>();
            capture.distantDetailPass = true; capture.trainingSamples = 120; capture.evaluationSamples = 32;
        }
        [MenuItem("TwinSight/City Lab/Capture Reference CCTV Detail Warning Clips (Play Mode)")]
        public static void CaptureDetailWarningClips()
        {
            if (!EditorApplication.isPlaying) throw new InvalidOperationException("Enter Play mode before capturing.");
            new GameObject("SyntheticWarningCapture").AddComponent<SyntheticWarningCapture>().highResolution = true;
        }
        [MenuItem("TwinSight/City Lab/Capture Varied Training Dataset (Play Mode)")]
        public static void CaptureVariedDataset()
        {
            if (!EditorApplication.isPlaying) throw new InvalidOperationException("Enter Play mode before capturing.");
            new GameObject("SyntheticTrainingCapture").AddComponent<SyntheticTrainingCapture>();
        }
        [MenuItem("TwinSight/City Lab/Capture Warning Check Clips (Play Mode)")]
        public static void CaptureWarningClips()
        {
            if (!EditorApplication.isPlaying) throw new InvalidOperationException("Enter Play mode before capturing.");
            new GameObject("SyntheticWarningCapture").AddComponent<SyntheticWarningCapture>();
        }
        [MenuItem("TwinSight/City Lab/Capture Prototype Incident Dataset (Play Mode)")]
        public static void CaptureDataset()
        {
            if (!EditorApplication.isPlaying) throw new InvalidOperationException("Enter Play mode before capturing.");
            new GameObject("ScenarioCaptureBatch").AddComponent<ScenarioCaptureBatch>();
        }

        [MenuItem("TwinSight/City Lab/Install Signals and Incident Scenarios")]
        public static void InstallFromMenu()
        {
            if (!EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;
            Install();
        }

        public static string Install()
        {
            if (EditorApplication.isPlaying) throw new InvalidOperationException("Stop Play mode before installing scenarios.");
            if (UnityEngine.SceneManagement.SceneManager.GetActiveScene().path != CityLabBuilder.ScenePath)
                throw new InvalidOperationException("Open CityTrafficLab first.");
            foreach (var probe in Object.FindObjectsByType<ScenarioDatasetCapture>(FindObjectsInactive.Include, FindObjectsSortMode.None)) Object.DestroyImmediate(probe.gameObject);
            foreach (var probe in Object.FindObjectsByType<ScenarioCaptureBatch>(FindObjectsInactive.Include, FindObjectsSortMode.None)) Object.DestroyImmediate(probe.gameObject);
            foreach (var probe in Object.FindObjectsByType<ScenarioRuntimeValidation>(FindObjectsInactive.Include, FindObjectsSortMode.None)) Object.DestroyImmediate(probe.gameObject);
            foreach (var probe in Object.FindObjectsByType<SyntheticTrainingCapture>(FindObjectsInactive.Include, FindObjectsSortMode.None)) Object.DestroyImmediate(probe.gameObject);
            foreach (var probe in Object.FindObjectsByType<SyntheticWarningCapture>(FindObjectsInactive.Include, FindObjectsSortMode.None)) Object.DestroyImmediate(probe.gameObject);
            foreach (var probe in Object.FindObjectsByType<StopZoneCapture>(FindObjectsInactive.Include, FindObjectsSortMode.None)) Object.DestroyImmediate(probe.gameObject);
            var previous = GameObject.Find("TrainingScenarios");
            if (previous != null) Object.DestroyImmediate(previous);
            var root = new GameObject("TrainingScenarios");
            var signals = root.AddComponent<TrafficSignalController>();
            var concrete = Material("IncidentConcrete", new Color(0.48f, 0.46f, 0.42f));
            var damage = Material("PotholeInterior", new Color(0.035f, 0.025f, 0.02f));
            var rim = Material("PotholeRim", new Color(0.19f, 0.15f, 0.10f));
            var city = GameObject.Find("SeoulCity");
            CitySignalAssetBinder.RestoreRoadAtlas(city);
            CitySignalAssetBinder.Bind(city, signals, root.transform);
            signals.RefreshLamps();
            MakePedestrian("Pedestrian_A", 8.05f, signals, root.transform, new Color(0.16f, 0.33f, 0.7f), false);
            MakePedestrian("Pedestrian_B", 8.55f, signals, root.transform, new Color(0.7f, 0.16f, 0.12f), true);

            foreach (var spawner in Object.FindObjectsByType<TrafficSpawner>(FindObjectsSortMode.None))
            {
                spawner.signals = signals; spawner.minGap = 3.0f; spawner.maxAlive = 5;
                spawner.speedRange = new Vector2(1.7f, 2.2f); spawner.intervalSeconds = new Vector2(5.5f, 8.5f);
                EditorUtility.SetDirty(spawner);
            }
            var director = root.AddComponent<RoadScenarioDirector>(); director.signals = signals;
            director.suvPrefab = AssetDatabase.LoadAssetAtPath<GameObject>(CityAssetTools.Generated + "/Vehicles/SUV/SUV.prefab");
            director.miniPrefab = AssetDatabase.LoadAssetAtPath<GameObject>(CityAssetTools.Generated + "/Vehicles/Mini/Mini.prefab");
            director.concreteMaterial = concrete; director.roadDamageMaterial = damage; director.rimMaterial = rim;
            var cctv = GameObject.Find("VirtualCCTV").GetComponent<Camera>();
            CityLabCameraProfile.Apply(cctv);
            var exporter = cctv.GetComponent<GroundTruthExporter>(); exporter.enabled = false;
            exporter.maxFrames = 150;
            exporter.captureFps = 10; exporter.stopPlayModeWhenDone = false;
            InstallDayNightControls();
            EditorSceneManager.MarkSceneDirty(UnityEngine.SceneManagement.SceneManager.GetActiveScene());
            EditorSceneManager.SaveScene(UnityEngine.SceneManagement.SceneManager.GetActiveScene(), CityLabBuilder.ScenePath);
            AssetDatabase.SaveAssets(); Selection.activeGameObject = root;
            return "Signals, pedestrians and probabilistic incident scenarios installed";
        }

        static void MakePedestrian(string name, float x, TrafficSignalController signals, Transform parent, Color shirt, bool reverse)
        {
            var root = new GameObject(name); root.transform.SetParent(parent, false);
            var skin = Material("PedestrianSkin", new Color(0.67f, 0.46f, 0.32f));
            var clothes = Material(name + "Clothes", shirt); var pants = Material("PedestrianPants", new Color(0.07f, 0.08f, 0.12f));
            Part("Head", root.transform, PrimitiveType.Sphere, new Vector3(0, 0.58f, 0), Vector3.one * 0.13f, skin);
            Part("Body", root.transform, PrimitiveType.Capsule, new Vector3(0, 0.39f, 0), new Vector3(0.18f, 0.13f, 0.11f), clothes);
            Part("LeftArm", root.transform, PrimitiveType.Capsule, new Vector3(-0.11f, 0.38f, 0), new Vector3(0.05f, 0.12f, 0.05f), skin);
            Part("RightArm", root.transform, PrimitiveType.Capsule, new Vector3(0.11f, 0.38f, 0), new Vector3(0.05f, 0.12f, 0.05f), skin);
            var left = Part("LeftLeg", root.transform, PrimitiveType.Capsule, new Vector3(-0.055f, 0.15f, 0), new Vector3(0.07f, 0.15f, 0.07f), pants);
            var right = Part("RightLeg", root.transform, PrimitiveType.Capsule, new Vector3(0.055f, 0.15f, 0), new Vector3(0.07f, 0.15f, 0.07f), pants);
            var walker = root.AddComponent<PedestrianCrossingAgent>(); walker.signals = signals;
            walker.from = new Vector3(x, 0.507f, reverse ? 2.35f : -3.1f);
            walker.to = new Vector3(x, 0.507f, reverse ? -3.1f : 2.35f);
            walker.leftLeg = left.transform; walker.rightLeg = right.transform; walker.waitSeconds = reverse ? 1.4f : 0.4f;
            root.transform.position = walker.from;
            root.AddComponent<TrackedObject>().className = "person";
        }

        static GameObject Part(string name, Transform parent, PrimitiveType type, Vector3 position, Vector3 scale, Material material)
        {
            var go = GameObject.CreatePrimitive(type); go.name = name; go.transform.SetParent(parent, false);
            go.transform.localPosition = position; go.transform.localScale = scale;
            Object.DestroyImmediate(go.GetComponent<Collider>()); go.GetComponent<Renderer>().sharedMaterial = material;
            return go;
        }
        static Material Material(string name, Color color)
        {
            string folder = CityAssetTools.Generated + "/Materials";
            var material = AssetDatabase.LoadAssetAtPath<Material>(folder + "/" + name + ".mat");
            if (material == null)
            { material = new Material(Shader.Find("Standard")); AssetDatabase.CreateAsset(material, folder + "/" + name + ".mat"); }
            material.color = color; material.SetFloat("_Glossiness", 0.1f); EditorUtility.SetDirty(material); return material;
        }
    }
}
