using System;
using System.Collections.Generic;
using UnityEngine;
using Object = UnityEngine.Object;

namespace TwinSight.Simulation
{
    public enum RoadScenario { Normal, Pothole, FallingDebris, VehicleCollision, StructureCollision }
    public enum ScenarioProfile { Training, Evaluation }

    [Serializable]
    public class ScenarioEventRecord
    {
        public string event_id;
        public string event_type;
        public string evidence;
        public float timestamp;
        public int object_a;
        public int object_b;
    }
    [Serializable]
    public class ScenarioSnapshot
    {
        public int episode;
        public int seed;
        public string sampling_profile;
        public string scenario;
        public float started_at;
        public float[] sampling_probabilities;
        public List<ScenarioEventRecord> events;
    }

    public class RoadScenarioDirector : MonoBehaviour
    {
        public ScenarioProfile profile = ScenarioProfile.Training;
        public int seed = 42;
        public float episodeSeconds = 24f;
        public float firstEpisodeDelay = 3f;
        public bool automaticEpisodes = true;
        [HideInInspector] public bool cleanDatasetCapture;
        public GameObject suvPrefab;
        public GameObject miniPrefab;
        public Material roadDamageMaterial;
        public Material concreteMaterial;
        public Material rimMaterial;
        public TrafficSignalController signals;
        public RoadScenario Current { get; private set; }
        public int Episode { get; private set; }
        public float StartedAt { get; private set; }
        public readonly List<ScenarioEventRecord> Events = new List<ScenarioEventRecord>();
        readonly List<GameObject> spawned = new List<GameObject>();
        readonly List<Mesh> ownedMeshes = new List<Mesh>();
        System.Random random;
        float nextEpisode;
        int eventIndex;

        void Start() { random = new System.Random(seed); nextEpisode = Time.time + firstEpisodeDelay; }
        public void ResetSampling(int value) { seed = value; random = new System.Random(value); }
        void Update()
        {
            if (Input.GetKeyDown(KeyCode.Alpha1)) BeginEpisode(RoadScenario.Normal);
            if (Input.GetKeyDown(KeyCode.Alpha2)) BeginEpisode(RoadScenario.Pothole);
            if (Input.GetKeyDown(KeyCode.Alpha3)) BeginEpisode(RoadScenario.FallingDebris);
            if (Input.GetKeyDown(KeyCode.Alpha4)) BeginEpisode(RoadScenario.VehicleCollision);
            if (Input.GetKeyDown(KeyCode.Alpha5)) BeginEpisode(RoadScenario.StructureCollision);
            if (automaticEpisodes && Time.time >= nextEpisode) BeginEpisode(Sample((float)random.NextDouble(), profile));
        }

        public static float[] Probabilities(ScenarioProfile mode) => mode == ScenarioProfile.Training
            ? new[] { 0.2f, 0.2f, 0.2f, 0.2f, 0.2f }
            : new[] { 0.9f, 0.025f, 0.025f, 0.025f, 0.025f };

        public static RoadScenario Sample(float roll, ScenarioProfile mode)
        {
            var probabilities = Probabilities(mode);
            for (int i = 0; i < probabilities.Length; i++)
            { roll -= probabilities[i]; if (roll < 0) return (RoadScenario)i; }
            return RoadScenario.StructureCollision;
        }

        public void BeginEpisode(RoadScenario scenario)
        {
            if (random == null) random = new System.Random(seed);
            foreach (var item in spawned) if (item != null) { item.SetActive(false); Destroy(item); }
            spawned.Clear(); Events.Clear(); Current = scenario; Episode++; StartedAt = Time.time;
            foreach (var mesh in ownedMeshes) if (mesh != null) Destroy(mesh);
            ownedMeshes.Clear();
            nextEpisode = Time.time + Mathf.Max(5, episodeSeconds);
            float x = 12.5f + Range(-1.8f, 1.8f), laneZ = Range(0, 1) > 0.5f ? -1.06f : 0.24f;
            if (cleanDatasetCapture) laneZ = -1.06f;
            if (scenario == RoadScenario.Pothole) CreatePothole(new Vector3(x, Ground(x, laneZ), laneZ));
            else if (scenario == RoadScenario.FallingDebris) CreateDebris(new Vector3(x, Ground(x, laneZ) + 2.4f, laneZ));
            else if (scenario == RoadScenario.VehicleCollision)
            {
                var leading = CreateImpactVehicle(suvPrefab, new Vector3(x, Ground(x, -1.06f) + 0.015f, -1.06f), Vector3.right, 0);
                var following = CreateImpactVehicle(miniPrefab, leading.transform.position - Vector3.right * 4.0f, Vector3.right, 2.4f);
                Record("collision_setup", "scheduled_not_yet_contact", following, leading);
            }
            else if (scenario == RoadScenario.StructureCollision)
            {
                Vector3 target = new Vector3(x + 1f, Ground(x, -1.8f), -1.8f);
                var barrier = CreateBarrier(target);
                Vector3 start = target + new Vector3(-4, 0.015f, 1.8f);
                var vehicle = CreateImpactVehicle(suvPrefab, start, (target - start).normalized, 2.6f);
                Record("structure_collision_setup", "scheduled_not_yet_contact", vehicle, barrier);
            }
            Record("episode_started", "sampling_configuration", null, null);
        }

        public ScenarioSnapshot Snapshot() => new ScenarioSnapshot
        {
            episode = Episode, seed = seed, sampling_profile = profile.ToString(), scenario = Current.ToString(),
            started_at = StartedAt, sampling_probabilities = Probabilities(profile), events = Events
        };

        public void Record(string kind, string evidence, GameObject first, GameObject second)
        {
            // Ground truth only. The Python warning engine never consumes this list.
            Events.Add(new ScenarioEventRecord { event_id = seed + ":" + Episode + ":" + eventIndex++, event_type = kind,
                evidence = evidence, timestamp = Time.time,
                object_a = first != null && first.TryGetComponent<TrackedObject>(out var a) ? a.TrackId : 0,
                object_b = second != null && second.TryGetComponent<TrackedObject>(out var b) ? b.TrackId : 0 });
        }

        GameObject CreatePothole(Vector3 position)
        {
            // A shallow, irregular depression visual; the imported city road collider is preserved.
            var go = new GameObject("Scenario_Pothole"); go.transform.position = position; Register(go);
            var vertices = new List<Vector3> { new Vector3(0, 0.025f, 0) };
            const int count = 18;
            for (int ring = 0; ring < 2; ring++) for (int i = 0; i < count; i++)
            {
                float angle = i * Mathf.PI * 2 / count;
                float jitter = 0.9f + Range(0, 0.2f), radius = ring == 0 ? 0.30f : 0.47f;
                vertices.Add(new Vector3(Mathf.Cos(angle) * radius * jitter, ring == 0 ? 0.03f : 0.06f,
                    Mathf.Sin(angle) * radius * jitter * 0.75f));
            }
            var center = new List<int>(); var rim = new List<int>();
            for (int i = 0; i < count; i++)
            {
                int a = 1 + i, b = 1 + (i + 1) % count, c = a + count, d = b + count;
                center.AddRange(new[] { 0, b, a }); rim.AddRange(new[] { a, b, c, b, d, c });
            }
            var mesh = new Mesh { name = "ProceduralPothole" }; mesh.SetVertices(vertices); mesh.subMeshCount = 2;
            ownedMeshes.Add(mesh);
            mesh.SetTriangles(center, 0); mesh.SetTriangles(rim, 1); mesh.RecalculateNormals(); mesh.RecalculateBounds();
            go.AddComponent<MeshFilter>().sharedMesh = mesh;
            go.AddComponent<MeshRenderer>().sharedMaterials = new[] { roadDamageMaterial, rimMaterial };
            go.AddComponent<TrackedObject>().className = "pothole";
            Record("pothole_created", "procedural_visual", go, null);
            return go;
        }

        GameObject CreateDebris(Vector3 position)
        {
            var go = Primitive("Scenario_FallingConcrete", position, new Vector3(0.62f, 0.38f, 0.45f), concreteMaterial);
            go.transform.rotation = Quaternion.Euler(Range(-35, 35), Range(0, 180), Range(-25, 25));
            go.AddComponent<TrackedObject>().className = "debris";
            var obstacle = go.AddComponent<ScenarioObstacle>(); obstacle.category = "debris"; obstacle.director = this;
            var body = go.AddComponent<Rigidbody>(); body.mass = 20; body.collisionDetectionMode = CollisionDetectionMode.ContinuousDynamic;
            Record("debris_dropped", "gravity_enabled", go, null);
            return go;
        }

        GameObject CreateBarrier(Vector3 position)
        {
            var go = Primitive("Scenario_ConcreteBarrier", position + Vector3.up * 0.32f,
                new Vector3(0.5f, 0.64f, 1.0f), concreteMaterial);
            go.AddComponent<TrackedObject>().className = "barrier";
            var obstacle = go.AddComponent<ScenarioObstacle>(); obstacle.category = "barrier"; obstacle.director = this;
            return go;
        }

        GameObject CreateImpactVehicle(GameObject prefab, Vector3 position, Vector3 direction, float speed)
        {
            var go = Instantiate(prefab, position, Quaternion.LookRotation(new Vector3(direction.x, 0, direction.z)));
            go.name = "Scenario_" + prefab.name; Register(go);
            var bounds = go.GetComponent<TrackedObject>();
            if (bounds == null) bounds = go.AddComponent<TrackedObject>();
            bounds.className = "car";
            // The generated rigs face local +Z, and the body is their first renderer.
            var collider = go.AddComponent<BoxCollider>();
            collider.size = new Vector3(0.67f, 0.45f, prefab.name == "SUV" ? 1.55f : 1.27f);
            collider.center = new Vector3(0, 0.32f, 0);
            var body = go.AddComponent<Rigidbody>(); body.mass = prefab.name == "SUV" ? 1400 : 1000;
            body.constraints = RigidbodyConstraints.FreezeRotation | RigidbodyConstraints.FreezePositionY;
            body.collisionDetectionMode = CollisionDetectionMode.ContinuousDynamic;
            var actor = go.AddComponent<ScenarioImpactActor>(); actor.director = this;
            actor.drivingVelocity = new Vector3(direction.x, 0, direction.z).normalized * speed; actor.drive = speed > 0;
            var traffic = go.AddComponent<TrafficVehicleAgent>(); traffic.collisionActor = true; traffic.halfLength = collider.size.z / 2;
            return go;
        }

        GameObject Primitive(string name, Vector3 position, Vector3 size, Material material)
        {
            var go = GameObject.CreatePrimitive(PrimitiveType.Cube); go.name = name; go.transform.position = position;
            go.transform.localScale = size; go.GetComponent<Renderer>().sharedMaterial = material; Register(go); return go;
        }
        void Register(GameObject go) { go.transform.SetParent(transform, true); spawned.Add(go); }
        void OnDestroy() { foreach (var mesh in ownedMeshes) if (mesh != null) Destroy(mesh); }
        float Range(float low, float high) => low + (float)random.NextDouble() * (high - low);
        static float Ground(float x, float z) => RoadSurface.TryGetSurfacePoint(new Vector3(x, 0, z), out var point) ? point.y : 0.507f;
    }
}
