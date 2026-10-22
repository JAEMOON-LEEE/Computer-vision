using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using Object = UnityEngine.Object;

namespace TwinSight.Simulation.EditorTools
{
    public static class CityLabBuilder
    {
        public const string ScenePath = CityAssetTools.Generated + "/CityTrafficLab.unity";
        // Match the purchased city's painted lane scale, rather than assuming real-world vehicle dimensions.
        public const float SuvLength = 1.6f;
        public const float MiniLength = 1.3f;
        public const float VehicleWidth = 0.7f;
        // Calibrated from a 7-unit high, 720px orthographic road view of this source asset.
        public const float PaintedCentreZ = -0.41f;
        public const float InnerLaneOffset = 0.65f;
        static readonly List<Collider> roadColliders = new List<Collider>();

        [MenuItem("TwinSight/City Lab/Build City Traffic Lab")]
        public static void BuildFromMenu()
        {
            if (!EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;
            Build();
        }

        public static string Build()
        {
            if (EditorApplication.isPlaying) throw new InvalidOperationException("Stop Play mode before building City Lab.");
            if (EditorSceneManager.GetActiveScene().isDirty)
                throw new InvalidOperationException("Save the current scene first, then use TwinSight > City Lab > Build City Traffic Lab.");
            CityAssetTools.ImportSources();
            var suv = VehicleRigBuilder.Build(CityAssetTools.Imported + "/Vehicles/SUV/suv.fbx", "SUV", SuvLength, VehicleWidth);
            var mini = VehicleRigBuilder.Build(CityAssetTools.Imported + "/Vehicles/Mini/mini_coo0er.fbx", "Mini", MiniLength, VehicleWidth);
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            var source = AssetDatabase.LoadAssetAtPath<GameObject>(CityAssetTools.Imported + "/City/south_korea_FBX.fbx");
            var city = (GameObject)PrefabUtility.InstantiatePrefab(source);
            city.name = "SeoulCity";
            var meshFilters = city.GetComponentsInChildren<MeshFilter>(true);
            var cityBounds = city.GetComponentsInChildren<Renderer>().Select(r => r.bounds).Aggregate((a, b) => { a.Encapsulate(b); return a; });
            city.transform.position -= new Vector3(cityBounds.center.x, cityBounds.min.y, cityBounds.center.z);
            CityMaterialBuilder.Apply(city);

            roadColliders.Clear();
            var collisionRoot = new GameObject("RoadSurfaces");
            var roadBounds = new Bounds(); bool hasRoad = false; int number = 0;
            foreach (var filter in meshFilters)
            {
                var renderer = filter.GetComponent<MeshRenderer>();
                if (renderer == null) continue;
                var mesh = filter.sharedMesh;
                var indices = new List<int>();
                for (int s = 0; s < mesh.subMeshCount; s++)
                {
                    var shared = renderer.sharedMaterials[s];
                    string material = (shared.name + " " + (shared.mainTexture == null ? "" : shared.mainTexture.name)).ToLowerInvariant();
                    if (material.Contains("road") && !material.Contains("sidewalk") && !material.Contains("marking")) indices.AddRange(mesh.GetTriangles(s));
                }
                if (indices.Count == 0) continue;
                if (filter.transform.localToWorldMatrix.determinant < 0)
                    for (int t = 0; t < indices.Count; t += 3)
                    { int swap = indices[t + 1]; indices[t + 1] = indices[t + 2]; indices[t + 2] = swap; }
                var original = mesh.vertices;
                var vertices = original.Select(v => filter.transform.TransformPoint(v)).ToArray();
                foreach (int index in indices)
                {
                    if (!hasRoad) { roadBounds = new Bounds(vertices[index], Vector3.zero); hasRoad = true; }
                    else roadBounds.Encapsulate(vertices[index]);
                }
                var collisionMesh = new Mesh { name = "RoadCollision" + number, indexFormat = IndexFormat.UInt32 };
                collisionMesh.vertices = vertices; collisionMesh.triangles = indices.ToArray(); collisionMesh.RecalculateBounds();
                string meshPath = CityAssetTools.Generated + "/RoadCollision" + number + ".asset";
                var previous = AssetDatabase.LoadAssetAtPath<Mesh>(meshPath);
                if (previous == null) AssetDatabase.CreateAsset(collisionMesh, meshPath);
                else { EditorUtility.CopySerialized(collisionMesh, previous); Object.DestroyImmediate(collisionMesh); collisionMesh = previous; }
                var go = new GameObject("RoadSurface_" + number++);
                go.transform.SetParent(collisionRoot.transform, false);
                go.AddComponent<MeshCollider>().sharedMesh = collisionMesh;
                go.AddComponent<RoadSurface>(); roadColliders.Add(go.GetComponent<Collider>());
            }
            if (!hasRoad) throw new InvalidOperationException("No road material found. Inspect the source city's material names.");
            Physics.SyncTransforms();
            var corridor = FindCorridor(roadBounds);
            Vector3 forward = corridor.Item2, right = Vector3.Cross(Vector3.up, forward);
            Vector3 start = corridor.Item1, end = corridor.Item3;
            if (forward != Vector3.right) throw new InvalidOperationException("Painted-lane calibration needs updating for the changed city asset.");
            start.z = end.z = PaintedCentreZ;
            var traffic = new GameObject("Traffic").transform;
            BuildLane("Outbound", start + right * InnerLaneOffset, end + right * InnerLaneOffset, suv, mini, traffic, 21);
            BuildLane("Inbound", end - right * InnerLaneOffset, start - right * InnerLaneOffset, suv, mini, traffic, 22);

            var sun = new GameObject("Sun", typeof(Light)).GetComponent<Light>();
            sun.type = LightType.Directional; sun.intensity = 1.2f; sun.shadows = LightShadows.Soft;
            sun.transform.rotation = Quaternion.Euler(45, -35, 0);
            RenderSettings.ambientMode = AmbientMode.Trilight;
            RenderSettings.ambientSkyColor = new Color(0.65f, 0.72f, 0.82f);
            RenderSettings.ambientEquatorColor = new Color(0.55f, 0.57f, 0.6f);
            RenderSettings.ambientGroundColor = new Color(0.35f, 0.37f, 0.4f);
            RenderSettings.fog = false;

            var cctv = MakeCamera("VirtualCCTV", start + forward * 5f + right * 3.6f + Vector3.up * 8f,
                Vector3.Lerp(start, end, 0.55f));
            cctv.tag = "MainCamera"; cctv.gameObject.AddComponent<AudioListener>();
            var overview = MakeCamera("OverviewCamera", (start + end) / 2f - forward * 20f + Vector3.up * 65f,
                (start + end) / 2f);
            overview.enabled = false;
            var grid = new GameObject("CalibrationGrid").AddComponent<CalibrationGrid>();
            grid.transform.SetPositionAndRotation(start, Quaternion.LookRotation(forward));
            grid.xRange = new Vector2(-3f, 3f); grid.zRange = new Vector2(2f, Vector3.Distance(start, end) - 2f);
            grid.spacing = 3f;
            var exporter = cctv.gameObject.AddComponent<GroundTruthExporter>();
            exporter.enabled = false; exporter.cameraId = "city-lab-cctv-01"; exporter.calibrationGrid = grid;
            exporter.imageWidth = 1280; exporter.imageHeight = 720; exporter.maxFrames = 100;
            exporter.warmupSeconds = 0f; exporter.stopPlayModeWhenDone = false;
            var settings = new GameObject("ExperimentSettings").AddComponent<CityLabExperiment>();
            settings.cctv = cctv; settings.overview = overview; settings.sun = sun; settings.exporter = exporter;
            EditorSceneManager.SaveScene(scene, ScenePath);
            TrafficExperimentBuilder.Install();
            AssetDatabase.SaveAssets();
            Selection.activeGameObject = settings.gameObject;
            if (SceneView.lastActiveSceneView != null) SceneView.lastActiveSceneView.LookAt((start + end) / 2f, Quaternion.Euler(55, 0, 0), 70f);
            File.WriteAllText("Logs/city-lab-build.json", Newtonsoft.Json.JsonConvert.SerializeObject(new
            {
                scene = ScenePath, roadSurfaces = roadColliders.Count, roadBounds = roadBounds.ToString(),
                start = start.ToString("F3"), end = end.ToString("F3"), lengthMetres = Vector3.Distance(start, end),
                vehicles = new[] { suv.name, mini.name }
            }, Newtonsoft.Json.Formatting.Indented));
            return ScenePath;
        }

        [MenuItem("TwinSight/City Lab/Rebuild Vehicle Prefabs")]
        public static void RebuildVehicles()
        {
            if (EditorApplication.isPlaying) throw new InvalidOperationException("Stop Play mode before rebuilding vehicles.");
            VehicleRigBuilder.Build(CityAssetTools.Imported + "/Vehicles/SUV/suv.fbx", "SUV", SuvLength, VehicleWidth);
            VehicleRigBuilder.Build(CityAssetTools.Imported + "/Vehicles/Mini/mini_coo0er.fbx", "Mini", MiniLength, VehicleWidth);
            AssetDatabase.SaveAssets();
        }

        public static void AlignPaintedLanes()
        {
            if (EditorApplication.isPlaying) throw new InvalidOperationException("Stop Play mode before aligning lanes.");
            foreach (string lane in new[] { "Outbound", "Inbound" })
            {
                var path = GameObject.Find("Traffic/" + lane + "/Path");
                if (path == null) throw new InvalidOperationException("Open CityTrafficLab before aligning lanes.");
                float z = PaintedCentreZ + (lane == "Outbound" ? -InnerLaneOffset : InnerLaneOffset);
                foreach (Transform point in path.transform)
                { var position = point.position; position.z = z; point.position = position; }
            }
            var grid = Object.FindFirstObjectByType<CalibrationGrid>();
            var gridPosition = grid.transform.position; gridPosition.z = PaintedCentreZ; grid.transform.position = gridPosition;
            var camera = GameObject.Find("VirtualCCTV").GetComponent<Camera>();
            CityLabCameraProfile.Apply(camera);
            EditorSceneManager.MarkSceneDirty(UnityEngine.SceneManagement.SceneManager.GetActiveScene());
            EditorSceneManager.SaveScene(UnityEngine.SceneManagement.SceneManager.GetActiveScene(), ScenePath);
        }

        static Camera MakeCamera(string name, Vector3 position, Vector3 target)
        {
            var cam = new GameObject(name, typeof(Camera)).GetComponent<Camera>();
            cam.transform.position = position; cam.transform.LookAt(target);
            cam.fieldOfView = 55; cam.nearClipPlane = 0.1f; cam.farClipPlane = 1500;
            cam.clearFlags = CameraClearFlags.SolidColor; cam.backgroundColor = new Color(0.6f, 0.72f, 0.82f);
            return cam;
        }

        static void BuildLane(string name, Vector3 from, Vector3 to, GameObject suv, GameObject mini, Transform parent, int seed)
        {
            var go = new GameObject(name); go.transform.SetParent(parent, false);
            var path = new GameObject("Path").transform; path.SetParent(go.transform, false);
            for (int i = 0; i < 2; i++)
            {
                var node = new GameObject(i == 0 ? "Start" : "End").transform; node.SetParent(path, false);
                Vector3 p = i == 0 ? from : to;
                if (!OnRoad(p, out var hit)) throw new InvalidOperationException("Lane endpoint is outside the road.");
                node.position = hit;
            }
            var spawner = go.AddComponent<TrafficSpawner>(); spawner.path = path; spawner.seed = seed;
            spawner.minGap = 9f; spawner.maxAlive = 10; spawner.intervalSeconds = new Vector2(2f, 3f);
            spawner.speedRange = new Vector2(5f, 7f);
            spawner.prefabs = new[]
            {
                new TrafficSpawner.Entry { prefab = suv, className = "car", weight = 1f },
                new TrafficSpawner.Entry { prefab = mini, className = "car", weight = 1f }
            };
        }

        static Tuple<Vector3, Vector3, Vector3> FindCorridor(Bounds bounds)
        {
            float bestLength = 0f; Vector3 bestFrom = default, bestTo = default, bestDirection = default;
            foreach (var forward in new[] { Vector3.forward, Vector3.right })
            {
                var right = Vector3.Cross(Vector3.up, forward);
                bool zAxis = forward == Vector3.forward;
                float acrossMin = zAxis ? bounds.min.x : bounds.min.z, acrossMax = zAxis ? bounds.max.x : bounds.max.z;
                float alongMin = zAxis ? bounds.min.z : bounds.min.x, alongMax = zAxis ? bounds.max.z : bounds.max.x;
                float scanStep = Mathf.Max(0.25f, (acrossMax - acrossMin) / 500f);
                float sampleStep = Mathf.Max(1f, (alongMax - alongMin) / 500f);
                for (float across = acrossMin + 2.5f; across < acrossMax - 2.5f; across += scanStep)
                {
                    float runStart = alongMin;
                    for (float along = alongMin; along <= alongMax; along += sampleStep)
                    {
                        Vector3 p = zAxis ? new Vector3(across, 0, along) : new Vector3(along, 0, across);
                        bool valid = OnRoad(p, out _) && OnRoad(p + right * 2.5f, out _) && OnRoad(p - right * 2.5f, out _);
                        if (!valid) { runStart = along + sampleStep; continue; }
                        float length = along - runStart;
                        if (length <= bestLength) continue;
                        bestLength = length; bestDirection = forward;
                        bestFrom = zAxis ? new Vector3(across, 0, runStart + 3f) : new Vector3(runStart + 3f, 0, across);
                        bestTo = p - forward * 3f;
                    }
                }
            }
            if (bestLength < 25f) throw new InvalidOperationException("No continuous two-lane road corridor >=25m found. Check city units and road materials before creating traffic.");
            OnRoad(bestFrom, out bestFrom); OnRoad(bestTo, out bestTo);
            return Tuple.Create(bestFrom, bestDirection, bestTo);
        }

        static bool OnRoad(Vector3 p, out Vector3 result)
        {
            var ray = new Ray(new Vector3(p.x, 2000, p.z), Vector3.down);
            float distance = float.MaxValue; result = default;
            foreach (var collider in roadColliders)
            {
                if (collider.Raycast(ray, out var hit, 4000) && hit.distance < distance)
                { distance = hit.distance; result = hit.point; }
            }
            return distance < float.MaxValue;
        }
    }
}
