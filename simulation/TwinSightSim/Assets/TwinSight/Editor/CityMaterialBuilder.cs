using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using UnityEditor;
using UnityEngine;

namespace TwinSight.Simulation.EditorTools
{
    /// <summary>Restores Blender FBX diffuse texture connections without changing the original FBX.</summary>
    public static class CityMaterialBuilder
    {
        sealed class Node
        {
            public string name;
            public List<object> values = new List<object>();
            public List<Node> children = new List<Node>();
        }

        public static int Apply(GameObject city)
        {
            var nodes = Read(Path.Combine(CityAssetTools.Repository, "south_korea_FBX.fbx"));
            var objects = nodes.Single(n => n.name == "Objects").children;
            var textures = objects.Where(n => n.name == "Texture").ToDictionary(n => Convert.ToInt64(n.values[0]));
            var names = objects.Where(n => n.name == "Material").ToDictionary(n => Convert.ToInt64(n.values[0]), n => Clean((string)n.values[1]));
            var links = new Dictionary<string, string>();
            foreach (var c in nodes.Single(n => n.name == "Connections").children)
            {
                if (c.values.Count < 4 || !textures.TryGetValue(Convert.ToInt64(c.values[1]), out var texture)
                    || !names.TryGetValue(Convert.ToInt64(c.values[2]), out string material)) continue;
                string channel = Convert.ToString(c.values[3]);
                if (channel != "DiffuseColor" && channel != "BaseColor") continue;
                var filename = texture.children.FirstOrDefault(n => n.name == "RelativeFilename")
                    ?? texture.children.FirstOrDefault(n => n.name == "FileName");
                if (filename != null) links[material] = Path.GetFileName(Convert.ToString(filename.values[0]).Replace('\\', '/'));
            }

            var lookup = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            foreach (string guid in AssetDatabase.FindAssets("t:Texture2D", new[] { CityAssetTools.Imported + "/City" }))
            {
                string path = AssetDatabase.GUIDToAssetPath(guid);
                lookup.TryAdd(Path.GetFileName(path), path);
            }
            string folder = CityAssetTools.Generated + "/Materials";
            Directory.CreateDirectory(folder); AssetDatabase.Refresh();
            var mapped = new Dictionary<string, Material>(); int textured = 0;
            foreach (var renderer in city.GetComponentsInChildren<MeshRenderer>())
            {
                var materials = renderer.sharedMaterials;
                for (int s = 0; s < materials.Length; s++)
                {
                    Material source = materials[s]; if (source == null) continue;
                    if (!mapped.TryGetValue(source.name, out var material))
                    {
                        string safe = string.Concat(source.name.Select(c => Path.GetInvalidFileNameChars().Contains(c) ? '_' : c));
                        string path = folder + "/" + safe + ".mat";
                        material = AssetDatabase.LoadAssetAtPath<Material>(path);
                        if (material == null) { material = new Material(Shader.Find("Standard")); AssetDatabase.CreateAsset(material, path); }
                        material.color = source.HasProperty("_Color") ? source.color : Color.white;
                        material.SetFloat("_Glossiness", 0.15f);
                        material.mainTexture = null;
                        if (links.TryGetValue(source.name, out string filename) && lookup.TryGetValue(filename, out string texturePath))
                        {
                            material.mainTexture = AssetDatabase.LoadAssetAtPath<Texture2D>(texturePath);
                            material.color = Color.white; textured++;
                            // Preserve texture alpha for vegetation and cutout props.
                            material.SetFloat("_Mode", 1); material.SetFloat("_Cutoff", 0.3f);
                            material.EnableKeyword("_ALPHATEST_ON"); material.renderQueue = 2450;
                        }
                        EditorUtility.SetDirty(material); mapped[source.name] = material;
                    }
                    materials[s] = material;
                }
                renderer.sharedMaterials = materials;
            }
            File.WriteAllText("Logs/city-materials.json", Newtonsoft.Json.JsonConvert.SerializeObject(new
            { sourceLinks = links.Count, restoredTextures = textured, materialCount = mapped.Count }, Newtonsoft.Json.Formatting.Indented));
            if (textured == 0) throw new InvalidOperationException("No city diffuse textures restored. Verify source FBX and LFS textures.");
            return textured;
        }

        static string Clean(string value) => value.Split('\0')[0].Replace("Material::", "");

        static List<Node> Read(string path)
        {
            using var reader = new BinaryReader(File.OpenRead(path));
            reader.BaseStream.Position = 23; uint version = reader.ReadUInt32(); bool wide = version >= 7500;
            object Property()
            {
                char t = (char)reader.ReadByte();
                switch (t)
                {
                    case 'Y': return reader.ReadInt16(); case 'C': return reader.ReadBoolean();
                    case 'I': return reader.ReadInt32(); case 'L': return reader.ReadInt64();
                    case 'F': return reader.ReadSingle(); case 'D': return reader.ReadDouble();
                    case 'S': return Encoding.UTF8.GetString(reader.ReadBytes((int)reader.ReadUInt32()));
                    case 'R': uint rawBytes = reader.ReadUInt32(); reader.BaseStream.Position += rawBytes; return null;
                    case 'f': case 'd': case 'l': case 'i': case 'b': case 'c':
                        reader.ReadUInt32(); reader.ReadUInt32(); uint bytes = reader.ReadUInt32(); reader.BaseStream.Position += bytes; return null;
                    default: throw new InvalidDataException("Unknown FBX property type " + t);
                }
            }
            Node ReadNode()
            {
                long end = wide ? (long)reader.ReadUInt64() : reader.ReadUInt32();
                long count = wide ? (long)reader.ReadUInt64() : reader.ReadUInt32();
                if (wide) reader.ReadUInt64(); else reader.ReadUInt32();
                byte length = reader.ReadByte(); if (end == 0) return null;
                string name = Encoding.UTF8.GetString(reader.ReadBytes(length));
                if (new[] { "Geometry", "Video", "Model", "Definitions", "Documents", "References", "Takes", "AnimationCurve", "AnimationCurveNode", "AnimationStack", "AnimationLayer", "Deformer", "Pose", "NodeAttribute" }.Contains(name))
                { reader.BaseStream.Position = end; return new Node { name = name }; }
                var node = new Node { name = name };
                for (long i = 0; i < count; i++) node.values.Add(Property());
                while (reader.BaseStream.Position < end)
                {
                    var child = ReadNode(); if (child == null) break; node.children.Add(child);
                }
                reader.BaseStream.Position = end; return node;
            }
            var nodes = new List<Node>();
            while (reader.BaseStream.Position < reader.BaseStream.Length)
            { var node = ReadNode(); if (node == null) break; nodes.Add(node); }
            return nodes;
        }
    }
}
