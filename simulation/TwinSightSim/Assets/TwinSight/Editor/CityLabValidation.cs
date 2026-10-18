using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;
using Object = UnityEngine.Object;

namespace TwinSight.Simulation.EditorTools
{
    public static class CityLabValidation
    {
        [MenuItem("TwinSight/City Lab/Validate Vehicle Rigs")]
        public static void ValidateFromMenu() => Debug.Log(Validate());

        public static string Validate()
        {
            var results = new[]
            {
                CheckVehicle("SUV", CityAssetTools.Imported + "/Vehicles/SUV/suv.fbx"),
                CheckVehicle("Mini", CityAssetTools.Imported + "/Vehicles/Mini/mini_coo0er.fbx")
            };
            string report = Newtonsoft.Json.JsonConvert.SerializeObject(new { passed = true, vehicles = results }, Newtonsoft.Json.Formatting.Indented);
            File.WriteAllText("Logs/city-lab-validation.json", report);
            return report;
        }

        static object CheckVehicle(string name, string sourcePath)
        {
            var source = AssetDatabase.LoadAssetAtPath<GameObject>(sourcePath);
            var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(CityAssetTools.Generated + "/Vehicles/" + name + "/" + name + ".prefab");
            if (source == null || prefab == null) throw new InvalidOperationException("Build City Lab first.");
            long CountTriangles(GameObject go) => go.GetComponentsInChildren<MeshFilter>().Sum(f => (long)f.sharedMesh.triangles.Length / 3);
            long sourceTriangles = CountTriangles(source), rigTriangles = CountTriangles(prefab);
            if (sourceTriangles != rigTriangles) throw new Exception(name + ": splitting lost or duplicated triangles.");
            var instance = Object.Instantiate(prefab);
            try
            {
                var rig = instance.GetComponent<VehicleWheelAnimator>();
                var renderers = instance.GetComponentsInChildren<Renderer>();
                Bounds bounds = renderers[0].bounds;
                foreach (var renderer in renderers) bounds.Encapsulate(renderer.bounds);
                if (bounds.size.x > 0.72f) throw new Exception(name + ": too wide for the city asset's painted lanes.");
                if (rig.wheels.Length != 4 || rig.wheels.Any(w => w.radius <= 0 || w.rollingPivot == null || w.steeringPivot == null))
                    throw new Exception(name + ": invalid wheel pivots/radii.");
                rig.SendMessage("OnEnable");
                float distance = 0.5f * Mathf.PI * rig.wheels[0].radius;
                instance.transform.position += Vector3.forward * distance;
                rig.Animate(0.1f);
                float angle = Quaternion.Angle(Quaternion.identity, rig.wheels[0].rollingPivot.localRotation);
                if (Mathf.Abs(angle - 90f) > 0.1f) throw new Exception(name + ": wheel circumference does not match distance.");
                var stopped = rig.wheels[0].rollingPivot.localRotation;
                rig.Animate(0.1f);
                if (Quaternion.Angle(stopped, rig.wheels[0].rollingPivot.localRotation) > 0.001f)
                    throw new Exception(name + ": stationary wheel rotates.");
                instance.transform.position -= Vector3.forward * distance;
                rig.Animate(0.1f);
                float reverseError = Quaternion.Angle(Quaternion.identity, rig.wheels[0].rollingPivot.localRotation);
                if (reverseError > 0.1f) throw new Exception(name + ": reversing does not reverse the wheels.");
                instance.transform.position += Vector3.forward * 100f;
                rig.Animate(0.1f);
                if (Quaternion.Angle(Quaternion.identity, rig.wheels[0].rollingPivot.localRotation) > 0.1f)
                    throw new Exception(name + ": teleport rotates wheels.");
                return new { name, sourceTriangles, rigTriangles, width = bounds.size.x, length = bounds.size.z,
                    wheels = 4, quarterTurnDegrees = angle, reverseError };
            }
            finally { Object.DestroyImmediate(instance); }
        }

        public static string RenderPreview(string cameraName, string outputPath)
        {
            var camera = GameObject.Find(cameraName).GetComponent<Camera>();
            var texture = new RenderTexture(1280, 720, 24);
            var pixels = new Texture2D(1280, 720, TextureFormat.RGB24, false);
            var previousTarget = camera.targetTexture; var previousActive = RenderTexture.active;
            try
            {
                camera.targetTexture = texture; camera.Render(); RenderTexture.active = texture;
                pixels.ReadPixels(new Rect(0, 0, 1280, 720), 0, 0); pixels.Apply();
                File.WriteAllBytes(outputPath, pixels.EncodeToPNG());
                return outputPath;
            }
            finally
            {
                camera.targetTexture = previousTarget; RenderTexture.active = previousActive;
                texture.Release(); Object.DestroyImmediate(texture); Object.DestroyImmediate(pixels);
            }
        }

        public static string RenderLaneFitProof()
        {
            var objects = new System.Collections.Generic.List<GameObject>();
            try
            {
                float[] laneZ = { CityLabBuilder.PaintedCentreZ - CityLabBuilder.InnerLaneOffset,
                    CityLabBuilder.PaintedCentreZ + CityLabBuilder.InnerLaneOffset };
                float minMargin = float.MaxValue;
                for (int i = 0; i < 2; i++)
                {
                    string name = i == 0 ? "SUV" : "Mini";
                    var source = AssetDatabase.LoadAssetAtPath<GameObject>(CityAssetTools.Generated + "/Vehicles/" + name + "/" + name + ".prefab");
                    var car = Object.Instantiate(source); objects.Add(car);
                    var p = new Vector3(i == 0 ? 12.5f : 15f, 0, laneZ[i]);
                    if (RoadSurface.TryGetSurfacePoint(p, out var hit)) p.y = hit.y;
                    car.transform.SetPositionAndRotation(p, Quaternion.Euler(0, i == 0 ? 90 : -90, 0));
                    var renderers = car.GetComponentsInChildren<Renderer>(); Bounds b = renderers[0].bounds;
                    foreach (var r in renderers) b.Encapsulate(r.bounds);
                    // Conservative inner edges of the painted yellow band and dashed white lines.
                    float low = i == 0 ? -1.69f : -0.33f, high = i == 0 ? -0.49f : 0.83f;
                    float margin = Mathf.Min(b.min.z - low, high - b.max.z);
                    minMargin = Mathf.Min(minMargin, margin);
                    if (margin < 0.18f) throw new InvalidOperationException(name + " overlaps the measured painted lane boundary.");
                }
                var cameraObject = new GameObject("LaneFitProof"); objects.Add(cameraObject);
                var camera = cameraObject.AddComponent<Camera>(); camera.enabled = false; camera.orthographic = true;
                camera.orthographicSize = 3.5f; camera.nearClipPlane = 0.1f; camera.farClipPlane = 100;
                camera.transform.SetPositionAndRotation(new Vector3(10, 50, -0.58f), Quaternion.Euler(90, 0, 0));
                RenderPreview("LaneFitProof", "Logs/lane-fit-proof.png");
                File.WriteAllText("Logs/lane-fit-validation.json", Newtonsoft.Json.JsonConvert.SerializeObject(new
                    { passed = true, maxVehicleWidth = CityLabBuilder.VehicleWidth, minimumPaintedLineMargin = minMargin,
                      outboundZ = laneZ[0], inboundZ = laneZ[1] }, Newtonsoft.Json.Formatting.Indented));
                return "Logs/lane-fit-proof.png; minimum clearance " + minMargin.ToString("F3");
            }
            finally { foreach (var go in objects) Object.DestroyImmediate(go); }
        }
    }
}
