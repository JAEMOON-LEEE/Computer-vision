using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;
using Object = UnityEngine.Object;

namespace TwinSight.Simulation.EditorTools
{
    public static class CitySignalAssetBinder
    {
        public static void Bind(GameObject city, TrafficSignalController signals, Transform parent)
        {
            var source = city.GetComponentsInChildren<MeshRenderer>().FirstOrDefault(r => r.name == "Cylinder005_01 - Default_0.004");
            var opposite = city.GetComponentsInChildren<MeshRenderer>().FirstOrDefault(r => r.name == "Cylinder005_01 - Default_0");
            if (source == null || opposite == null) throw new InvalidOperationException("Expected original city traffic-light models are missing.");
            string path = CityAssetTools.Generated + "/Materials/ControlledOriginalSignal.mat";
            var material = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (material == null) { material = new Material(Shader.Find("TwinSight/AssetSignal")); AssetDatabase.CreateAsset(material, path); }
            material.shader = Shader.Find("TwinSight/AssetSignal");
            string texture = CityAssetTools.Imported + "/City/Textures/south korea textures/01_-_Default_baseColor.jpeg";
            material.mainTexture = AssetDatabase.LoadAssetAtPath<Texture2D>(texture);
            if (material.mainTexture == null) throw new InvalidOperationException("Original signal atlas is missing.");
            EditorUtility.SetDirty(material);
            // Reposition the existing opposite signal to the crossing's stop line, retaining its asset mesh.
            var position = opposite.transform.position;
            position.x += signals.inboundStopX - opposite.bounds.center.x; opposite.transform.position = position;
            signals.vehicleLamps = new[] { Attach(source, material, false), Attach(opposite, material, false) };
            signals.pedestrianLamps = new SignalLamp[2];
            for (int i = 0; i < 2; i++)
            {
                var instance = Object.Instantiate(source.gameObject, parent);
                instance.name = "OriginalAsset_PedestrianSignal_" + i;
                instance.transform.localScale = source.transform.lossyScale * 0.4f;
                instance.transform.rotation = Quaternion.Euler(0, i == 0 ? 90 : -90, 0) * source.transform.rotation;
                var renderer = instance.GetComponent<MeshRenderer>();
                Vector3 target = new Vector3(8.3f, 0.507f, i == 0 ? -3.1f : 2.45f);
                instance.transform.position += target - new Vector3(renderer.bounds.center.x, renderer.bounds.min.y, renderer.bounds.center.z);
                signals.pedestrianLamps[i] = Attach(renderer, material, true);
            }
            signals.RefreshLamps();
        }

        static SignalLamp Attach(MeshRenderer renderer, Material material, bool pedestrian)
        {
            renderer.sharedMaterial = material;
            var lamp = renderer.GetComponent<SignalLamp>();
            if (lamp == null) lamp = renderer.gameObject.AddComponent<SignalLamp>();
            lamp.assetRenderer = renderer; lamp.pedestrianMode = pedestrian;
            EditorUtility.SetDirty(renderer); EditorUtility.SetDirty(lamp); return lamp;
        }

        public static void RestoreRoadAtlas(GameObject city)
        {
            var roadMaterials = city.GetComponentsInChildren<Renderer>().SelectMany(r => r.sharedMaterials).Distinct()
                .Where(m => m.name.StartsWith("ROAD", StringComparison.OrdinalIgnoreCase) || m.name.StartsWith("SIDEWALK", StringComparison.OrdinalIgnoreCase));
            foreach (var material in roadMaterials)
            {
                string filename = material.mainTexture != null ? Path.GetFileName(AssetDatabase.GetAssetPath(material.mainTexture)) : "";
                string texturePath = CityAssetTools.Imported + "/City/Textures/south korea textures/new road textures/wide road/" + filename;
                var texture = AssetDatabase.LoadAssetAtPath<Texture2D>(texturePath);
                if (texture == null) continue;
                material.mainTexture = texture; material.color = Color.white; material.SetFloat("_Glossiness", 0.08f);
                material.SetFloat("_Mode", 0); material.DisableKeyword("_ALPHATEST_ON"); material.renderQueue = -1;
                EditorUtility.SetDirty(material);
            }
        }
    }
}
