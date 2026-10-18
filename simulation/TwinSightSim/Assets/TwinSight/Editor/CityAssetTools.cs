using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using UnityEditor;
using UnityEngine;

namespace TwinSight.Simulation.EditorTools
{
    public static class CityAssetTools
    {
        public const string Imported = "Assets/TwinSight/Imported";
        public const string Generated = "Assets/TwinSight/CityLab";
        public static string Repository => Path.GetFullPath(Path.Combine(Application.dataPath, "../../.."));

        public static string ScheduleImport()
        {
            EditorApplication.delayCall += () =>
            {
                try { ImportSources(); Inventory(); File.WriteAllText("Logs/city-import-complete.txt", "OK"); }
                catch (Exception error) { File.WriteAllText("Logs/city-import-error.txt", error.ToString()); Debug.LogException(error); }
            };
            return "City and vehicle import scheduled";
        }

        public static void ImportSources(bool includeCity = true)
        {
            var pairs = new List<(string source, string target)>
            {
                ("Papabear_Papabear Car Package/suv_승용차", "Vehicles/SUV"),
                ("Papabear_Papabear Car Package/mini_coo0er_미니0퍼", "Vehicles/Mini")
            };
            if (includeCity)
            {
                CopyModel(Path.Combine(Repository, "south_korea_FBX.fbx"), Imported + "/City/south_korea_FBX.fbx");
                CopyTextures(Path.Combine(Repository, "south_korea_textures"), Imported + "/City/Textures");
            }
            foreach (var pair in pairs)
            {
                string source = Path.Combine(Repository, pair.source);
                foreach (string file in Directory.GetFiles(source, "*.fbx"))
                    CopyModel(file, Imported + "/" + pair.target + "/" + Path.GetFileName(file));
                CopyTextures(source, Imported + "/" + pair.target + "/Textures");
            }
            AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
            var models = AssetDatabase.FindAssets("t:Model", new[] { Imported });
            foreach (string guid in models)
            {
                var importer = (ModelImporter)AssetImporter.GetAtPath(AssetDatabase.GUIDToAssetPath(guid));
                if (importer.isReadable && importer.materialSearch == ModelImporterMaterialSearch.Everywhere) continue;
                importer.isReadable = true;
                importer.importCameras = false;
                importer.importLights = false;
                importer.materialSearch = ModelImporterMaterialSearch.Everywhere;
                importer.SaveAndReimport();
            }
        }

        static void CopyModel(string source, string target)
        {
            RequireHydrated(source);
            CopyChanged(source, target);
        }

        static void CopyTextures(string source, string target)
        {
            foreach (string file in Directory.GetFiles(source, "*", SearchOption.AllDirectories))
            {
                if (!new[] { ".png", ".jpg", ".jpeg", ".tga", ".tif", ".bmp" }.Contains(Path.GetExtension(file).ToLowerInvariant())) continue;
                RequireHydrated(file);
                string relative = file.Substring(source.Length).TrimStart('/', '\\');
                CopyChanged(file, target + "/" + relative);
            }
        }

        static void CopyChanged(string source, string target)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(target));
            if (File.Exists(target) && new FileInfo(source).Length == new FileInfo(target).Length
                && File.GetLastWriteTimeUtc(source) <= File.GetLastWriteTimeUtc(target)) return;
            File.Copy(source, target, true);
        }

        public static void RequireHydrated(string path)
        {
            if (!File.Exists(path)) throw new FileNotFoundException("Missing source asset. Run git lfs pull first.", path);
            if (new FileInfo(path).Length < 1024 && File.ReadAllText(path).StartsWith("version https://git-lfs.github.com/spec/"))
                throw new InvalidOperationException("Git LFS pointer, not asset data: " + path + ". Run git lfs pull.");
        }

        public static string Inventory()
        {
            var result = new StringBuilder();
            foreach (string guid in AssetDatabase.FindAssets("t:Model", new[] { Imported }))
            {
                string path = AssetDatabase.GUIDToAssetPath(guid);
                var root = AssetDatabase.LoadAssetAtPath<GameObject>(path);
                result.AppendLine(path);
                foreach (var filter in root.GetComponentsInChildren<MeshFilter>(true))
                {
                    Mesh mesh = filter.sharedMesh;
                    var renderer = filter.GetComponent<MeshRenderer>();
                    result.AppendLine($"  {GetPath(filter.transform)} vertices={mesh.vertexCount} submeshes={mesh.subMeshCount} bounds={mesh.bounds} world={renderer.bounds} pos={filter.transform.localPosition} scale={filter.transform.lossyScale} mats={string.Join(",", renderer.sharedMaterials.Select(m => m == null ? "null" : m.name))}");
                }
            }
            Directory.CreateDirectory("Logs");
            File.WriteAllText("Logs/asset-inventory.txt", result.ToString());
            return result.ToString();
        }

        static string GetPath(Transform t) => t.parent == null ? t.name : GetPath(t.parent) + "/" + t.name;
    }
}
