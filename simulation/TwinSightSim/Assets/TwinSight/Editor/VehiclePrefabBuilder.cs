using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;

namespace TwinSight.Simulation.EditorTools
{
    /// <summary>
    /// 메뉴 TwinSight > Build Vehicle Prefabs.
    /// Assets/ThirdParty 아래의 차량 모델(FBX)로 TrafficSpawner가 쓸 프리팹을 Assets/TwinSight/Vehicles 에 만든다.
    /// - 차량 길이 방향(가로면 중 긴 쪽)을 +z로, 피벗을 바닥 가운데로 맞춘다.
    /// - 축척을 비율 그대로 맞춘다. 실제 길이를 아는 모델(KnownLength)은 그 길이로, 모르는 모델은
    ///   클래스별 실제 범위(승용차 3.7~5.6 m, 버스 8~13 m 등)를 벗어날 때만 대표 길이로 맞춘다.
    /// - 모델 Read/Write를 켜고(정답 박스를 메시 정점으로 계산), 모델에 들어 있는 카메라·조명은 가져오지 않는다.
    /// - 폴더 이름으로 클래스를 정한다: bus → bus, bike → motorcycle, truck → truck, 나머지 → car.
    /// 앞뒤가 반대로 달리는 모델은 만들어진 프리팹의 Model 자식을 y축으로 180° 돌리면 된다.
    /// 다시 실행하면 같은 이름의 프리팹을 덮어쓴다.
    /// </summary>
    public static class VehiclePrefabBuilder
    {
        public const string SourceRoot = "Assets/ThirdParty";
        public const string OutputRoot = "Assets/TwinSight/Vehicles";

        static readonly Dictionary<string, float> TypicalLength = new Dictionary<string, float>
        {
            { "car", 4.6f }, { "bus", 11f }, { "truck", 7f }, { "motorcycle", 2.1f },
        };

        // 실제 차량으로 볼 수 있는 길이 범위(m). 벗어나면 모델 단위가 다른 것으로 보고 대표 길이로 맞춘다
        static readonly Dictionary<string, Vector2> PlausibleLength = new Dictionary<string, Vector2>
        {
            { "car", new Vector2(3.7f, 5.6f) }, { "bus", new Vector2(8f, 13f) },
            { "truck", new Vector2(4.5f, 12f) }, { "motorcycle", new Vector2(1.5f, 2.8f) },
        };

        // 모델 파일 이름별 대략적인 실제 길이(m). Papabear 패키지는 모델마다 축척이 달라 이 값으로 맞춘다
        static readonly Dictionary<string, float> KnownLength = new Dictionary<string, float>
        {
            { "taxi1", 4.9f }, { "taxi2", 4.9f }, { "ford_tauras", 5.1f }, { "police", 4.9f },
            { "police_american", 5.1f }, { "suv", 4.7f }, { "f0rrari", 4.5f }, { "mini_coo0er", 3.9f },
            { "bus_1", 11f }, { "bus2", 11f }, { "bus2_2", 11f }, { "bus3", 11f }, { "bus3_2", 11f },
            { "bus4", 11f }, { "bus4_2", 11f }, { "baminbike", 1.8f }, { "baminbike2", 1.8f },
        };

        [MenuItem("TwinSight/Build Vehicle Prefabs")]
        public static void Build()
        {
            if (!AssetDatabase.IsValidFolder(SourceRoot))
            {
                Debug.LogWarning($"TwinSight: {SourceRoot} 폴더가 없습니다. simulation/tools/copy_vehicle_assets.py로 차량 에셋을 먼저 복사하세요.");
                return;
            }
            DemoSceneBuilder.EnsureFolder(OutputRoot);

            var usedNames = new HashSet<string>();
            var counts = new Dictionary<string, int>();
            foreach (var guid in AssetDatabase.FindAssets("t:Model", new[] { SourceRoot }))
            {
                string path = AssetDatabase.GUIDToAssetPath(guid);
                string className = Classify(path);
                ConfigureImporter(path);

                var model = AssetDatabase.LoadAssetAtPath<GameObject>(path);
                if (model == null) continue;
                string name = UniqueName($"{className}_{Path.GetFileNameWithoutExtension(path)}", usedNames);
                if (!BuildPrefab(model, className, name, path)) continue;
                counts[className] = counts.TryGetValue(className, out int n) ? n + 1 : 1;
            }
            AssetDatabase.SaveAssets();

            var summary = new List<string>();
            foreach (var pair in counts) summary.Add($"{pair.Key} {pair.Value}");
            Debug.Log($"TwinSight: 차량 프리팹을 만들었습니다 ({string.Join(", ", summary)}) → {OutputRoot}. " +
                      "TwinSight > Create Demo Road Scene을 다시 실행하면 예제 씬에 쓰입니다.");
        }

        static bool BuildPrefab(GameObject model, string className, string name, string sourcePath)
        {
            var root = new GameObject(name);
            var instance = (GameObject)PrefabUtility.InstantiatePrefab(model);
            instance.name = "Model";
            instance.transform.SetParent(root.transform, false);

            if (!TryGetBounds(root, out var bounds))
            {
                Debug.LogWarning($"TwinSight: {sourcePath}에 렌더러가 없어 건너뜁니다.", model);
                Object.DestroyImmediate(root);
                return false;
            }

            // 길이 방향을 +z로
            if (bounds.size.x > bounds.size.z)
            {
                instance.transform.localRotation = Quaternion.Euler(0f, 90f, 0f) * instance.transform.localRotation;
                TryGetBounds(root, out bounds);
            }
            if (bounds.size.y > Mathf.Max(bounds.size.x, bounds.size.z))
                Debug.LogWarning($"TwinSight: {sourcePath}는 높이가 길이보다 큽니다. 모델이 누워 있으면 Import Settings의 축 설정을 확인하세요.", model);

            // 축척을 비율 그대로 맞춘다: 실제 길이를 아는 모델은 그 길이로,
            // 모르는 모델은 클래스별 실제 범위를 벗어날 때만 대표 길이로
            float length = bounds.size.z;
            var range = PlausibleLength[className];
            float target = KnownLength.TryGetValue(Path.GetFileNameWithoutExtension(sourcePath).ToLowerInvariant(), out float known)
                ? known
                : (length < range.x || length > range.y ? TypicalLength[className] : length);
            if (Mathf.Abs(target - length) > 0.01f)
            {
                instance.transform.localScale *= target / length;
                TryGetBounds(root, out bounds);
                Debug.Log($"TwinSight: {name} 길이를 {length:F2} → {bounds.size.z:F2}로 맞췄습니다.");
            }

            // 피벗을 바닥 가운데로
            instance.transform.localPosition -= new Vector3(bounds.center.x, bounds.min.y, bounds.center.z);

            root.AddComponent<TrackedObject>().className = className;
            PrefabUtility.SaveAsPrefabAsset(root, $"{OutputRoot}/{name}.prefab");
            Object.DestroyImmediate(root);
            Debug.Log($"TwinSight: {name} ({bounds.size.z:F1} x {bounds.size.x:F1} x {bounds.size.y:F1} m) ← {sourcePath}");
            return true;
        }

        static string Classify(string path)
        {
            string p = path.ToLowerInvariant();
            if (p.Contains("bus")) return "bus";
            if (p.Contains("bike") || p.Contains("motorcycle")) return "motorcycle";
            if (p.Contains("truck")) return "truck";
            return "car";
        }

        /// <summary>
        /// Read/Write를 켜고, 모델 파일에 함께 들어 있는 카메라·조명은 가져오지 않는다.
        /// (오픈카 모델처럼 카메라가 들어 있으면 차가 생길 때마다 그 카메라가 Game 화면을 차지하고 렌더링도 느려진다)
        /// </summary>
        static void ConfigureImporter(string path)
        {
            if (!(AssetImporter.GetAtPath(path) is ModelImporter importer)) return;
            if (importer.isReadable && !importer.importCameras && !importer.importLights) return;
            importer.isReadable = true;
            importer.importCameras = false;
            importer.importLights = false;
            importer.SaveAndReimport();
        }

        static bool TryGetBounds(GameObject go, out Bounds bounds)
        {
            bounds = default;
            bool any = false;
            foreach (var r in go.GetComponentsInChildren<Renderer>())
            {
                if (r is ParticleSystemRenderer) continue;
                if (any) bounds.Encapsulate(r.bounds);
                else { bounds = r.bounds; any = true; }
            }
            return any;
        }

        static string UniqueName(string name, HashSet<string> used)
        {
            string candidate = name;
            for (int i = 2; !used.Add(candidate); i++) candidate = $"{name}_{i}";
            return candidate;
        }
    }
}
