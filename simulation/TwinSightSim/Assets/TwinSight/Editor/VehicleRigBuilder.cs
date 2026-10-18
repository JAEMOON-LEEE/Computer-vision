using System;
using System.Collections.Generic;
using System.Linq;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;
using Object = UnityEngine.Object;

namespace TwinSight.Simulation.EditorTools
{
    /// <summary>Extracts complete disconnected wheel islands; source FBX files are never modified.</summary>
    public static class VehicleRigBuilder
    {
        sealed class Geometry
        {
            public readonly List<Vector3> positions = new List<Vector3>();
            public readonly List<Vector3> normals = new List<Vector3>();
            public readonly List<Vector4> tangents = new List<Vector4>();
            public readonly List<Vector2> uv = new List<Vector2>();
            public readonly List<Color> colors = new List<Color>();
            public readonly List<Material> materials = new List<Material>();
            public readonly List<List<int>> triangles = new List<List<int>>();
        }

        sealed class Island
        {
            public readonly List<int> vertices = new List<int>();
            public Bounds bounds;
        }

        public static GameObject Build(string assetPath, string name, float length, float maxWidth = float.PositiveInfinity)
        {
            var source = AssetDatabase.LoadAssetAtPath<GameObject>(assetPath);
            if (source == null) throw new InvalidOperationException("Model not imported: " + assetPath);
            var instance = Object.Instantiate(source);
            var root = new GameObject(name);
            try
            {
                var geometry = ReadGeometry(instance, length, maxWidth);
                var islands = FindIslands(geometry);
                Bounds vehicleBounds = BoundsOf(geometry.positions);
                var centers = FindWheelCenters(islands, vehicleBounds);
                var assignment = Enumerable.Repeat(-1, geometry.positions.Count).ToArray();
                var radii = new float[4];
                for (int k = 0; k < 4; k++)
                {
                    var seed = centers[k];
                    radii[k] = (seed.bounds.size.y + seed.bounds.size.z) * 0.25f;
                    Vector3 center = seed.bounds.center;
                    foreach (var island in islands)
                    {
                        bool fits = true;
                        foreach (int v in island.vertices)
                        {
                            Vector3 d = geometry.positions[v] - center;
                            if (Mathf.Abs(d.x) > vehicleBounds.size.x * 0.22f || d.y * d.y + d.z * d.z > radii[k] * radii[k] * 1.16f)
                            { fits = false; break; }
                        }
                        if (fits) foreach (int v in island.vertices) assignment[v] = k;
                    }
                }

                string folder = CityAssetTools.Generated + "/Vehicles/" + name;
                System.IO.Directory.CreateDirectory(folder);
                AssetDatabase.Refresh();
                CreatePart(geometry, assignment, -1, Vector3.zero, "Body", root.transform, folder);
                var animator = root.AddComponent<VehicleWheelAnimator>();
                animator.wheels = new VehicleWheelAnimator.Wheel[4];
                for (int k = 0; k < 4; k++)
                {
                    string wheelName = (k < 2 ? "Front" : "Rear") + (k % 2 == 0 ? "Left" : "Right");
                    Vector3 center = centers[k].bounds.center;
                    var steering = new GameObject(wheelName + "_Steer").transform;
                    steering.SetParent(root.transform, false);
                    steering.localPosition = center;
                    var rolling = new GameObject(wheelName + "_Roll").transform;
                    rolling.SetParent(steering, false);
                    CreatePart(geometry, assignment, k, center, wheelName, rolling, folder);
                    animator.wheels[k] = new VehicleWheelAnimator.Wheel
                    { steeringPivot = steering, rollingPivot = rolling, radius = radii[k], steers = k < 2 };
                }
                animator.wheelbase = Mathf.Abs(centers[0].bounds.center.z - centers[2].bounds.center.z);
                root.AddComponent<TrackedObject>().className = "car";
                string prefabPath = folder + "/" + name + ".prefab";
                var prefab = PrefabUtility.SaveAsPrefabAsset(root, prefabPath);
                var report = new
                {
                    source = assetPath, prefab = prefabPath, vertexCount = geometry.positions.Count,
                    islands = islands.Count,
                    wheelVertices = Enumerable.Range(0, 4).Select(k => assignment.Count(a => a == k)).ToArray(),
                    radii, wheelbase = animator.wheelbase
                };
                System.IO.File.WriteAllText("Logs/" + name + "-rig.json", Newtonsoft.Json.JsonConvert.SerializeObject(report, Newtonsoft.Json.Formatting.Indented));
                return prefab;
            }
            finally
            {
                Object.DestroyImmediate(instance);
                Object.DestroyImmediate(root);
            }
        }

        static Geometry ReadGeometry(GameObject source, float targetLength, float maxWidth)
        {
            var data = new Geometry();
            foreach (var filter in source.GetComponentsInChildren<MeshFilter>(true))
            {
                Mesh mesh = filter.sharedMesh;
                var renderer = filter.GetComponent<MeshRenderer>();
                if (mesh == null || renderer == null) continue;
                Matrix4x4 matrix = filter.transform.localToWorldMatrix;
                Matrix4x4 normalMatrix = matrix.inverse.transpose;
                var vertices = mesh.vertices; var normals = mesh.normals; var tangents = mesh.tangents;
                var uv = mesh.uv; var colors = mesh.colors;
                int offset = data.positions.Count;
                for (int i = 0; i < vertices.Length; i++)
                {
                    data.positions.Add(matrix.MultiplyPoint3x4(vertices[i]));
                    data.normals.Add(normals.Length == vertices.Length ? normalMatrix.MultiplyVector(normals[i]).normalized : Vector3.up);
                    Vector4 t = tangents.Length == vertices.Length ? tangents[i] : new Vector4(1, 0, 0, 1);
                    Vector3 direction = matrix.MultiplyVector(new Vector3(t.x, t.y, t.z)).normalized;
                    data.tangents.Add(new Vector4(direction.x, direction.y, direction.z, t.w * Mathf.Sign(matrix.determinant)));
                    data.uv.Add(uv.Length == vertices.Length ? uv[i] : Vector2.zero);
                    data.colors.Add(colors.Length == vertices.Length ? colors[i] : Color.white);
                }
                for (int s = 0; s < mesh.subMeshCount; s++)
                {
                    var triangles = mesh.GetTriangles(s);
                    var list = new List<int>(triangles.Length);
                    for (int i = 0; i < triangles.Length; i += 3)
                    {
                        list.Add(triangles[i] + offset);
                        list.Add(triangles[i + (matrix.determinant < 0 ? 2 : 1)] + offset);
                        list.Add(triangles[i + (matrix.determinant < 0 ? 1 : 2)] + offset);
                    }
                    data.triangles.Add(list);
                    data.materials.Add(renderer.sharedMaterials[Mathf.Min(s, renderer.sharedMaterials.Length - 1)]);
                }
            }
            if (data.positions.Count == 0) throw new InvalidOperationException("No readable mesh in vehicle.");
            Bounds bounds = BoundsOf(data.positions);
            // Papabear vehicles face +X after FBX's handedness conversion. Standardize to +Z.
            Quaternion yaw = bounds.size.x > bounds.size.z ? Quaternion.Euler(0, -90, 0) : Quaternion.identity;
            for (int i = 0; i < data.positions.Count; i++)
            {
                data.positions[i] = yaw * data.positions[i];
                data.normals[i] = yaw * data.normals[i];
                Vector4 t = data.tangents[i]; Vector3 d = yaw * new Vector3(t.x, t.y, t.z);
                data.tangents[i] = new Vector4(d.x, d.y, d.z, t.w);
            }
            bounds = BoundsOf(data.positions);
            float scale = Mathf.Min(targetLength / bounds.size.z, maxWidth / bounds.size.x);
            Vector3 origin = new Vector3(bounds.center.x, bounds.min.y, bounds.center.z);
            for (int i = 0; i < data.positions.Count; i++) data.positions[i] = (data.positions[i] - origin) * scale;
            return data;
        }

        static List<Island> FindIslands(Geometry data)
        {
            int[] parent = Enumerable.Range(0, data.positions.Count).ToArray();
            int Find(int v) { while (parent[v] != v) { parent[v] = parent[parent[v]]; v = parent[v]; } return v; }
            void Union(int a, int b) { a = Find(a); b = Find(b); if (a != b) parent[b] = a; }
            // FBX duplicates vertices at UV seams and hard normals; weld only for topology analysis.
            var welded = new Dictionary<(int, int, int), int>();
            for (int i = 0; i < parent.Length; i++)
            {
                Vector3 p = data.positions[i];
                var key = (Mathf.RoundToInt(p.x * 100000), Mathf.RoundToInt(p.y * 100000), Mathf.RoundToInt(p.z * 100000));
                if (welded.TryGetValue(key, out int other)) Union(i, other); else welded[key] = i;
            }
            foreach (var indices in data.triangles)
                for (int t = 0; t < indices.Count; t += 3)
                { Union(indices[t], indices[t + 1]); Union(indices[t], indices[t + 2]); }
            var groups = new Dictionary<int, Island>();
            for (int i = 0; i < parent.Length; i++)
            {
                int id = Find(i);
                if (!groups.TryGetValue(id, out var group)) groups[id] = group = new Island { bounds = new Bounds(data.positions[i], Vector3.zero) };
                group.vertices.Add(i); group.bounds.Encapsulate(data.positions[i]);
            }
            return groups.Values.ToList();
        }

        static Island[] FindWheelCenters(List<Island> islands, Bounds vehicle)
        {
            var wheels = new Island[4];
            foreach (var island in islands)
            {
                Bounds b = island.bounds; Vector3 size = b.size; Vector3 c = b.center;
                if (island.vertices.Count < 24 || size.y < vehicle.size.y * 0.18f || size.y > vehicle.size.y * 0.65f
                    || size.z / size.y < 0.7f || size.z / size.y > 1.4f || size.x > size.y * 0.85f
                    || c.y > vehicle.size.y * 0.38f || b.min.y > vehicle.size.y * 0.16f
                    || Mathf.Abs(c.x) < vehicle.size.x * 0.28f || Mathf.Abs(c.z) < vehicle.size.z * 0.15f) continue;
                int k = (c.z > 0 ? 0 : 2) + (c.x < 0 ? 0 : 1);
                if (wheels[k] == null || size.y + size.z > wheels[k].bounds.size.y + wheels[k].bounds.size.z) wheels[k] = island;
            }
            if (wheels.Any(w => w == null))
                throw new InvalidOperationException("Cannot identify all four disconnected wheels safely. Inspect model topology; no partial rig was saved.");
            return wheels;
        }

        static void CreatePart(Geometry data, int[] assignments, int group, Vector3 origin, string name, Transform parent, string folder)
        {
            var vertices = new List<Vector3>(); var normals = new List<Vector3>(); var tangents = new List<Vector4>();
            var uv = new List<Vector2>(); var colors = new List<Color>();
            var materials = new List<Material>(); var submeshes = new List<List<int>>(); var remap = new Dictionary<int, int>();
            int Map(int old)
            {
                if (remap.TryGetValue(old, out int index)) return index;
                index = vertices.Count; remap[old] = index;
                vertices.Add(data.positions[old] - origin); normals.Add(data.normals[old]); tangents.Add(data.tangents[old]);
                uv.Add(data.uv[old]); colors.Add(data.colors[old]); return index;
            }
            int triangleCount = 0;
            for (int s = 0; s < data.triangles.Count; s++)
            {
                var selected = new List<int>(); var source = data.triangles[s];
                for (int t = 0; t < source.Count; t += 3)
                {
                    if (assignments[source[t]] != group) continue;
                    if (assignments[source[t + 1]] != group || assignments[source[t + 2]] != group)
                        throw new InvalidOperationException("Wheel split would cut across a connected triangle.");
                    selected.Add(Map(source[t])); selected.Add(Map(source[t + 1])); selected.Add(Map(source[t + 2]));
                }
                if (selected.Count == 0) continue;
                int existing = materials.IndexOf(data.materials[s]);
                if (existing >= 0) submeshes[existing].AddRange(selected);
                else { submeshes.Add(selected); materials.Add(data.materials[s]); }
                triangleCount += selected.Count / 3;
            }
            if (triangleCount == 0) throw new InvalidOperationException("Empty vehicle mesh group " + name);
            string path = folder + "/" + name + ".asset";
            var mesh = AssetDatabase.LoadAssetAtPath<Mesh>(path);
            bool isNew = mesh == null;
            if (isNew) mesh = new Mesh { name = name };
            // Use mesh setters so Unity also invalidates the existing GPU vertex buffers.
            // CopySerialized can update CPU bounds while the renderer retains the old geometry.
            mesh.Clear();
            mesh.indexFormat = IndexFormat.UInt32;
            mesh.SetVertices(vertices); mesh.SetNormals(normals); mesh.SetTangents(tangents); mesh.SetUVs(0, uv); mesh.SetColors(colors);
            mesh.subMeshCount = submeshes.Count;
            for (int s = 0; s < submeshes.Count; s++) mesh.SetTriangles(submeshes[s], s);
            mesh.RecalculateBounds();
            mesh.UploadMeshData(false);
            if (isNew) AssetDatabase.CreateAsset(mesh, path);
            else EditorUtility.SetDirty(mesh);
            var go = new GameObject(name, typeof(MeshFilter), typeof(MeshRenderer));
            go.transform.SetParent(parent, false);
            go.GetComponent<MeshFilter>().sharedMesh = mesh;
            go.GetComponent<MeshRenderer>().sharedMaterials = materials.ToArray();
        }

        static Bounds BoundsOf(List<Vector3> vertices)
        {
            var b = new Bounds(vertices[0], Vector3.zero);
            foreach (var v in vertices) b.Encapsulate(v);
            return b;
        }
    }
}
