using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;
using Object = UnityEngine.Object;

namespace TwinSight.Simulation
{
    public enum RoadScenario { Normal, Pothole, FallingDebris, VehicleCollision, StructureCollision, SignalViolation }
    public enum ScenarioProfile { Training, Evaluation }
    public enum StopZoneScenario { SignalQueue, TightQueue, BarrierStop, RearEnd, StructureImpact }
    public enum VehicleCollisionScenario { RearEnd, HighSpeedRearEnd, HeadOn, SideImpact, ChainReaction, MovingRearEnd, OffsetRearEnd }

    [Serializable]
    public class ScenarioEventRecord
    {
        public string event_id;
        public string event_type;
        public string evidence;
        public float timestamp;
        public int object_a;
        public int object_b;
        public float relative_speed_units_per_second;
        public float impulse;
        public float[] contact_world;
    }
    [Serializable]
    public class ScenarioSnapshot
    {
        public int episode;
        public int seed;
        public string sampling_profile;
        public string scenario;
        public string collision_variant;
        public string scenario_variant;
        public float started_at;
        public float[] sampling_probabilities;
        public List<ScenarioEventRecord> events;
    }

    public partial class RoadScenarioDirector : MonoBehaviour
    {
        public ScenarioProfile profile = ScenarioProfile.Training;
        public int seed = 42;
        public float episodeSeconds = 24f;
        public Vector2 incidentXRange = new Vector2(10.7f, 14.3f);
        [Range(0, 1)] public float stopZoneIncidentFraction = 0.4f;
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
        public string CollisionVariant { get; private set; } = "";
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
            if (Input.GetKeyDown(KeyCode.Alpha6)) BeginStopZoneEpisode(StopZoneScenario.RearEnd,false,0,2.4f,0.25f);
            if (Input.GetKeyDown(KeyCode.Alpha7)) BeginStopZoneEpisode(StopZoneScenario.StructureImpact,false,0,2.4f,0.25f);
            if (Input.GetKeyDown(KeyCode.Alpha8)) BeginStopZoneEpisode(StopZoneScenario.RearEnd,true,0,2.4f,0.25f);
            if (Input.GetKeyDown(KeyCode.Alpha9)) BeginStopZoneEpisode(StopZoneScenario.StructureImpact,true,0,2.4f,0.25f);
            if (Input.GetKeyDown(KeyCode.F1)) BeginVehicleCollisionEpisode(VehicleCollisionScenario.RearEnd);
            if (Input.GetKeyDown(KeyCode.F2)) BeginVehicleCollisionEpisode(VehicleCollisionScenario.HighSpeedRearEnd);
            if (Input.GetKeyDown(KeyCode.F3)) BeginVehicleCollisionEpisode(VehicleCollisionScenario.HeadOn);
            if (Input.GetKeyDown(KeyCode.F4)) BeginVehicleCollisionEpisode(VehicleCollisionScenario.SideImpact);
            if (Input.GetKeyDown(KeyCode.F5)) BeginVehicleCollisionEpisode(VehicleCollisionScenario.ChainReaction);
            if (Input.GetKeyDown(KeyCode.F6)) BeginStopZoneEpisode(StopZoneScenario.SignalQueue,false,0,2f,TrafficVehicleAgent.NormalQueueGap);
            if (Input.GetKeyDown(KeyCode.F7)) BeginSignalViolationEpisode(SignalViolationVariant.OutboundRed);
            if (Input.GetKeyDown(KeyCode.F8)) BeginSignalViolationEpisode(SignalViolationVariant.InboundRed);
            if (Input.GetKeyDown(KeyCode.F9)) BeginSignalViolationEpisode(SignalViolationVariant.FastOutboundRed);
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
            if (!cleanDatasetCapture && signals != null) signals.enabled=true;
            if (random == null) random = new System.Random(seed);
            foreach (var item in spawned) if (item != null) { item.SetActive(false); Destroy(item); }
            spawned.Clear(); Events.Clear(); Current = scenario; CollisionVariant=""; ScenarioVariant=""; Episode++; StartedAt = Time.time;
            foreach (var mesh in ownedMeshes) if (mesh != null) Destroy(mesh);
            ownedMeshes.Clear();
            nextEpisode = Time.time + Mathf.Max(5, episodeSeconds);
            float x = Range(incidentXRange.x, incidentXRange.y), laneZ = Range(0, 1) > 0.5f ? -1.06f : 0.24f;
            if (cleanDatasetCapture) laneZ = -1.06f;
            if (!cleanDatasetCapture && (scenario == RoadScenario.VehicleCollision || scenario == RoadScenario.StructureCollision)
                && Range(0, 1) < stopZoneIncidentFraction)
            {
                signals.SetPhaseForExperiment(SignalPhase.PedestrianGreen);
                signals.enabled = false;
                SpawnStopZoneActors(scenario == RoadScenario.VehicleCollision ? StopZoneScenario.RearEnd : StopZoneScenario.StructureImpact,
                    Range(0,1) > 0.5f, Range(-0.15f,0.15f), Range(2.1f,2.8f), 0.25f);
                Record("episode_started", "sampling_configuration", null, null);
                return;
            }
            if (scenario == RoadScenario.Pothole) { if (cleanDatasetCapture) CreatePothole(new Vector3(x, Ground(x, laneZ), laneZ)); else SpawnPotholeVariant((PotholeVariant)random.Next(4), x, laneZ); }
            else if (scenario == RoadScenario.FallingDebris) { if (cleanDatasetCapture) CreateDebris(new Vector3(x, Ground(x, laneZ) + 2.4f, laneZ)); else SpawnDebrisVariant((DebrisVariant)random.Next(4), x, laneZ); }
            else if (scenario == RoadScenario.SignalViolation) SpawnSignalViolation((SignalViolationVariant)random.Next(3));
            else if (scenario == RoadScenario.VehicleCollision && !cleanDatasetCapture)
            {
                var variant=(VehicleCollisionScenario)random.Next(Enum.GetValues(typeof(VehicleCollisionScenario)).Length);
                SpawnVehicleCollisionActors(variant,Range(0,1)>.5f,Range(-.15f,.15f),1f);
            }
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

        public void BeginStopZoneEpisode(StopZoneScenario scenario, bool inbound, float offset, float speed, float gap)
        {
            BeginEpisode(RoadScenario.Normal);
            Current = scenario == StopZoneScenario.RearEnd ? RoadScenario.VehicleCollision
                : scenario == StopZoneScenario.StructureImpact ? RoadScenario.StructureCollision : RoadScenario.Normal;
            signals.SetPhaseForExperiment(SignalPhase.PedestrianGreen);
            signals.enabled = false;
            SpawnStopZoneActors(scenario, inbound, offset, speed, gap);
        }

        public void BeginVehicleCollisionEpisode(VehicleCollisionScenario scenario, bool inbound=false,
            float offset=0, float driveDelay=0)
        {
            BeginEpisode(RoadScenario.Normal);
            Current=RoadScenario.VehicleCollision;
            SpawnVehicleCollisionActors(scenario,inbound,offset,driveDelay);
        }

        void SpawnVehicleCollisionActors(VehicleCollisionScenario scenario, bool inbound, float offset, float delay)
        {
            CollisionVariant=scenario.ToString();
            float sign=inbound?-1f:1f;
            Vector3 forward=Vector3.right*sign;
            float x=11.8f+offset, lane=inbound?.24f:-1.06f;
            Vector3 target=new Vector3(x,Ground(x,lane),lane);
            if (scenario==VehicleCollisionScenario.HeadOn)
            {
                var first=CreateImpactVehicle(suvPrefab,target-forward*3.7f,forward,3.8f,true,delay);
                var second=CreateImpactVehicle(miniPrefab,target+forward*3.7f,-forward,3.8f,true,delay);
                foreach(var car in new[]{first,second})
                {
                    var actor=car.GetComponent<ScenarioImpactActor>();
                    actor.linearDampingAfterImpact=8f; actor.angularDampingAfterImpact=8f;
                }
            }
            else if (scenario==VehicleCollisionScenario.SideImpact)
            {
                CreateImpactVehicle(suvPrefab,target,forward,0,true,delay);
                Vector3 approach=(forward+Vector3.forward*.6f).normalized;
                CreateImpactVehicle(miniPrefab,target-approach*4.8f,approach,4.8f,true,delay);
            }
            else if (scenario==VehicleCollisionScenario.ChainReaction)
            {
                CreateImpactVehicle(suvPrefab,target+forward*1.65f,forward,0,true,delay);
                CreateImpactVehicle(miniPrefab,target,forward,0,true,delay);
                CreateImpactVehicle(suvPrefab,target-forward*5.8f+Vector3.forward*.1f,forward,6.5f,true,delay);
            }
            else if (scenario==VehicleCollisionScenario.MovingRearEnd)
            {
                CreateImpactVehicle(suvPrefab,target,forward,1f,true,delay);
                CreateImpactVehicle(miniPrefab,target-forward*4f,forward,3.5f,true,delay);
            }
            else if (scenario==VehicleCollisionScenario.OffsetRearEnd)
            {
                CreateImpactVehicle(suvPrefab,target,forward,0,true,delay);
                CreateImpactVehicle(miniPrefab,target-forward*4f+Vector3.forward*.28f,forward,3f,true,delay);
            }
            else
            {
                CreateImpactVehicle(suvPrefab,target,forward,0,true,delay);
                bool severe=scenario==VehicleCollisionScenario.HighSpeedRearEnd;
                CreateImpactVehicle(miniPrefab,target-forward*(severe?6f:4f)+Vector3.forward*(severe?.18f:0),
                    forward,severe?6.5f:2.4f,true,delay);
            }
            Record("varied_collision_setup","scheduled_not_yet_contact",null,null);
        }

        void SpawnStopZoneActors(StopZoneScenario scenario, bool inbound, float offset, float speed, float gap)
        {
            if (scenario==StopZoneScenario.SignalQueue || scenario==StopZoneScenario.BarrierStop)
                gap=Mathf.Max(gap,TrafficVehicleAgent.NormalQueueGap);
            float direction = inbound ? -1f : 1f;
            float lane = inbound ? 0.24f : -1.06f;
            float stop = inbound ? signals.inboundStopX : signals.outboundStopX;
            float targetX = stop - direction * (0.9f + Mathf.Abs(offset));
            Vector3 target = new Vector3(targetX, Ground(targetX,lane), lane);
            Vector3 forward = Vector3.right * direction;
            if (scenario == StopZoneScenario.RearEnd)
            {
                var lead = CreateImpactVehicle(suvPrefab,target,forward,0,!cleanDatasetCapture);
                var follower = CreateImpactVehicle(miniPrefab,target-forward*Range(3.4f,4.2f),forward,speed,!cleanDatasetCapture);
                Record("stop_zone_rear_end_setup","scheduled_not_yet_contact",follower,lead);
            }
            else if (scenario == StopZoneScenario.StructureImpact || scenario == StopZoneScenario.BarrierStop)
            {
                var barrier = CreateBarrier(target);
                barrier.GetComponent<ScenarioObstacle>().radius = 0.25f;
                if (scenario == StopZoneScenario.StructureImpact)
                {
                    var car = CreateImpactVehicle(suvPrefab,target-forward*Range(3.4f,4.2f),forward,speed);
                    Record("stop_zone_structure_setup","scheduled_not_yet_contact",car,barrier);
                }
                else MakeQueueCar(suvPrefab,target-forward*3.6f,forward,inbound,speed,gap,true);
            }
            else
            {
                bool movingLead = scenario == StopZoneScenario.SignalQueue;
                MakeQueueCar(suvPrefab,target,forward,inbound,speed,gap,movingLead);
                MakeQueueCar(miniPrefab,target-forward*Range(3.2f,4.0f),forward,inbound,speed,gap,true);
            }
            Record("stop_zone_case","experiment_configuration",null,null);
        }

        void MakeQueueCar(GameObject prefab, Vector3 position, Vector3 forward, bool inbound, float speed, float gap, bool moving)
        {
            var car = Instantiate(prefab,position,Quaternion.LookRotation(forward));
            car.name = "StopZone_"+prefab.name; Register(car);
            var agent = car.AddComponent<TrafficVehicleAgent>(); agent.signals=signals; agent.gap=gap;
            if (car.GetComponent<TrackedObject>().TryGetWorldBounds(out var bounds)) agent.halfLength=bounds.size.x*0.5f;
            if (!moving) return;
            var path = FindObjectsByType<TrafficSpawner>(FindObjectsSortMode.None)
                .First(s=>s.name==(inbound?"Inbound":"Outbound")).path;
            var mover=car.AddComponent<WaypointMover>(); mover.speed=speed; mover.destroyAtEnd=false;
            mover.waypoints=Enumerable.Range(0,path.childCount).Select(i=>path.GetChild(i)).ToArray();
        }

        public ScenarioSnapshot Snapshot() => new ScenarioSnapshot
        {
            episode = Episode, seed = seed, sampling_profile = profile.ToString(), scenario = Current.ToString(),
            collision_variant=CollisionVariant, scenario_variant=ScenarioVariant,
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

        public void RecordPhysicsImpact(string kind, GameObject first, GameObject second, Collision collision)
        {
            int a=first.GetComponent<TrackedObject>().TrackId, b=second.GetComponent<TrackedObject>().TrackId;
            if (Events.Any(e=>e.event_type==kind && e.evidence=="physics_contact" &&
                ((e.object_a==a && e.object_b==b)||(e.object_a==b && e.object_b==a)))) return;
            Record(kind,"physics_contact",first,second);
            var record=Events[Events.Count-1];
            record.relative_speed_units_per_second=collision.relativeVelocity.magnitude;
            record.impulse=collision.impulse.magnitude;
            var point=collision.contactCount>0?collision.GetContact(0).point:first.transform.position;
            record.contact_world=new[]{point.x,point.y,point.z};
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

        GameObject CreateImpactVehicle(GameObject prefab, Vector3 position, Vector3 direction, float speed,
            bool dynamicImpact=false, float driveDelay=0)
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
            body.constraints = dynamicImpact
                ? RigidbodyConstraints.FreezePositionY|RigidbodyConstraints.FreezeRotationX|RigidbodyConstraints.FreezeRotationZ
                : RigidbodyConstraints.FreezeRotation|RigidbodyConstraints.FreezePositionY;
            body.collisionDetectionMode = CollisionDetectionMode.ContinuousDynamic;
            var actor = go.AddComponent<ScenarioImpactActor>(); actor.director = this;
            actor.dynamicAfterImpact=dynamicImpact; actor.driveDelay=driveDelay;
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
