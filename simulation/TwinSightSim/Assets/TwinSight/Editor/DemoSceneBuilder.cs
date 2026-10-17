using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace TwinSight.Simulation.EditorTools
{
    /// <summary>
    /// 메뉴 TwinSight > Create Demo Road Scene.
    /// 왕복 4차로 직선 도로, 도로변 가상 CCTV, 노면 기준점 격자, 차로별 차량 스포너, 포트홀을 가진 예제 씬을 만든다.
    /// 상자 모양 차량은 공간 매핑 검증용이다. YOLO로 평가하려면 스포너의 프리팹을 실제 차량 3D 에셋으로 바꾼다.
    /// 다시 실행하면 Assets/TwinSight/Demo 아래 파일을 덮어쓴다.
    /// </summary>
    public static class DemoSceneBuilder
    {
        const string Root = "Assets/TwinSight/Demo";
        const float LaneWidth = 3.5f;
        const float RoadStartZ = -20f;
        const float RoadEndZ = 200f;

        [MenuItem("TwinSight/Create Demo Road Scene")]
        public static void Create()
        {
            if (!EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;

            EnsureFolder(Root + "/Materials");
            EnsureFolder(Root + "/Prefabs");
            var scene = EditorSceneManager.NewScene(NewSceneSetup.DefaultGameObjects, NewSceneMode.Single);

            var asphalt = CreateMaterial("Asphalt", new Color(0.20f, 0.20f, 0.22f));
            var grass = CreateMaterial("Ground", new Color(0.33f, 0.40f, 0.30f));
            var white = CreateMaterial("LaneWhite", new Color(0.92f, 0.92f, 0.92f));
            var yellow = CreateMaterial("LaneYellow", new Color(0.95f, 0.75f, 0.10f));
            var pothole = CreateMaterial("Pothole", new Color(0.07f, 0.07f, 0.07f));
            var glass = CreateMaterial("Glass", new Color(0.15f, 0.20f, 0.28f));
            var carPaint = CreateMaterial("CarPaint", new Color(0.70f, 0.12f, 0.12f));
            var truckPaint = CreateMaterial("TruckPaint", new Color(0.85f, 0.85f, 0.80f));

            BuildRoad(asphalt, grass);
            BuildLaneMarkings(white, yellow);

            var car = CreateCarPrefab(carPaint, glass);
            var truck = CreateTruckPrefab(truckPaint, glass);
            // 오른쪽 차로는 카메라에서 멀어지고(+z), 왼쪽 차로는 다가온다(-z)
            BuildLane("Lane_R1", +0.5f * LaneWidth, +1, 11, car, truck);
            BuildLane("Lane_R2", +1.5f * LaneWidth, +1, 12, car, truck);
            BuildLane("Lane_L1", -0.5f * LaneWidth, -1, 13, car, truck);
            BuildLane("Lane_L2", -1.5f * LaneWidth, -1, 14, car, truck);

            BuildPothole(new Vector3(1.2f, 0f, 25f), pothole);
            BuildPothole(new Vector3(-4.6f, 0f, 48f), pothole);
            BuildPothole(new Vector3(5.0f, 0f, 70f), pothole);

            var grid = new GameObject("CalibrationGrid").AddComponent<CalibrationGrid>();
            SetupCamera(grid);

            EditorSceneManager.SaveScene(scene, Root + "/DemoRoad.unity");
            Debug.Log("TwinSight: 예제 씬을 만들었습니다. Play를 누르면 TwinSightExport 폴더에 저장됩니다.");
        }

        static void BuildRoad(Material asphalt, Material grass)
        {
            float length = RoadEndZ - RoadStartZ;
            float centerZ = (RoadStartZ + RoadEndZ) * 0.5f;

            // Plane 기본 크기는 10 x 10 m
            var ground = GameObject.CreatePrimitive(PrimitiveType.Plane);
            ground.name = "Ground";
            ground.transform.position = new Vector3(0f, -0.01f, centerZ);
            ground.transform.localScale = new Vector3(12f, 1f, length / 10f + 4f);
            ground.GetComponent<Renderer>().sharedMaterial = grass;
            ground.AddComponent<RoadSurface>();

            var road = GameObject.CreatePrimitive(PrimitiveType.Plane);
            road.name = "Road";
            road.transform.position = new Vector3(0f, 0f, centerZ);
            road.transform.localScale = new Vector3(4f * LaneWidth / 10f, 1f, length / 10f);
            road.GetComponent<Renderer>().sharedMaterial = asphalt;
            road.AddComponent<RoadSurface>();
        }

        static void BuildLaneMarkings(Material white, Material yellow)
        {
            var parent = new GameObject("LaneMarkings").transform;
            float length = RoadEndZ - RoadStartZ;
            float centerZ = (RoadStartZ + RoadEndZ) * 0.5f;

            // 중앙 복선(황색), 가장자리 실선(백색)
            Block("CenterLine_L", parent, new Vector3(-0.15f, 0.005f, centerZ), new Vector3(0.12f, 0.01f, length), yellow);
            Block("CenterLine_R", parent, new Vector3(0.15f, 0.005f, centerZ), new Vector3(0.12f, 0.01f, length), yellow);
            float edge = 2f * LaneWidth - 0.15f;
            Block("EdgeLine_L", parent, new Vector3(-edge, 0.005f, centerZ), new Vector3(0.15f, 0.01f, length), white);
            Block("EdgeLine_R", parent, new Vector3(edge, 0.005f, centerZ), new Vector3(0.15f, 0.01f, length), white);

            // 차로 경계 점선: 칠 3 m, 빈칸 6 m
            foreach (float x in new[] { -LaneWidth, LaneWidth })
                for (float z = RoadStartZ + 1.5f; z < RoadEndZ; z += 9f)
                    Block("Dash", parent, new Vector3(x, 0.005f, z), new Vector3(0.15f, 0.01f, 3f), white);
        }

        static GameObject CreateCarPrefab(Material paint, Material glass)
        {
            const float w = 1.8f, h = 1.5f, l = 4.5f;
            var root = new GameObject("BoxCar");
            Block("Body", root.transform, new Vector3(0f, 0.275f * h, 0f), new Vector3(w, 0.55f * h, l), paint);
            Block("Cabin", root.transform, new Vector3(0f, 0.775f * h, -0.05f * l), new Vector3(0.85f * w, 0.45f * h, 0.5f * l), glass);
            root.AddComponent<TrackedObject>().className = "car";
            return SavePrefab(root);
        }

        static GameObject CreateTruckPrefab(Material paint, Material glass)
        {
            const float w = 2.5f, h = 3.2f, l = 8f;
            var root = new GameObject("BoxTruck");
            Block("Cargo", root.transform, new Vector3(0f, 0.5f * h, -0.14f * l), new Vector3(w, h, 0.72f * l), paint);
            Block("Cab", root.transform, new Vector3(0f, 0.375f * h, 0.38f * l), new Vector3(w, 0.75f * h, 0.24f * l), glass);
            root.AddComponent<TrackedObject>().className = "truck";
            return SavePrefab(root);
        }

        static void BuildLane(string name, float x, int direction, int seed, GameObject car, GameObject truck)
        {
            var lane = new GameObject(name);
            var path = new GameObject("Path").transform;
            path.SetParent(lane.transform, false);

            float from = direction > 0 ? RoadStartZ + 2f : RoadEndZ - 2f;
            float to = direction > 0 ? RoadEndZ - 2f : RoadStartZ + 2f;
            new GameObject("Start").transform.SetParent(path, false);
            path.GetChild(0).position = new Vector3(x, 0f, from);
            new GameObject("End").transform.SetParent(path, false);
            path.GetChild(1).position = new Vector3(x, 0f, to);

            var spawner = lane.AddComponent<TrafficSpawner>();
            spawner.path = path;
            spawner.seed = seed;
            spawner.prefabs = new[]
            {
                new TrafficSpawner.Entry { prefab = car, className = "car", weight = 4f },
                new TrafficSpawner.Entry { prefab = truck, className = "truck", weight = 1f },
            };
        }

        static void BuildPothole(Vector3 position, Material material)
        {
            var go = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
            go.name = "Pothole";
            Object.DestroyImmediate(go.GetComponent<Collider>());
            go.transform.position = position;
            go.transform.localScale = new Vector3(0.8f, 0.01f, 0.6f);
            go.GetComponent<Renderer>().sharedMaterial = material;
            go.AddComponent<TrackedObject>().className = "pothole";
        }

        static void SetupCamera(CalibrationGrid grid)
        {
            var cam = Camera.main;
            cam.name = "VirtualCCTV";
            // 오른쪽 도로변 높이 8 m 기둥 위, 도로 안쪽을 향해 내려다봄
            cam.transform.SetPositionAndRotation(new Vector3(8.5f, 8f, -10f), Quaternion.Euler(15f, -8f, 0f));
            cam.fieldOfView = 45f;
            cam.nearClipPlane = 0.3f;
            cam.farClipPlane = 1000f;

            var exporter = cam.gameObject.AddComponent<GroundTruthExporter>();
            exporter.calibrationGrid = grid;
            Selection.activeGameObject = cam.gameObject;
        }

        static GameObject Block(string name, Transform parent, Vector3 position, Vector3 scale, Material material)
        {
            var go = GameObject.CreatePrimitive(PrimitiveType.Cube);
            go.name = name;
            Object.DestroyImmediate(go.GetComponent<Collider>());
            go.transform.SetParent(parent, false);
            go.transform.localPosition = position;
            go.transform.localScale = scale;
            go.GetComponent<Renderer>().sharedMaterial = material;
            return go;
        }

        static GameObject SavePrefab(GameObject root)
        {
            var prefab = PrefabUtility.SaveAsPrefabAsset(root, $"{Root}/Prefabs/{root.name}.prefab");
            Object.DestroyImmediate(root);
            return prefab;
        }

        static Material CreateMaterial(string name, Color color)
        {
            // 현재 렌더 파이프라인(Built-in·URP·HDRP)의 기본 셰이더를 그대로 쓴다
            var probe = GameObject.CreatePrimitive(PrimitiveType.Cube);
            var shader = probe.GetComponent<Renderer>().sharedMaterial.shader;
            Object.DestroyImmediate(probe);

            var material = new Material(shader) { color = color };
            AssetDatabase.CreateAsset(material, $"{Root}/Materials/{name}.mat");
            return material;
        }

        static void EnsureFolder(string path)
        {
            if (AssetDatabase.IsValidFolder(path)) return;
            string parent = Path.GetDirectoryName(path).Replace('\\', '/');
            EnsureFolder(parent);
            AssetDatabase.CreateFolder(parent, Path.GetFileName(path));
        }
    }
}
