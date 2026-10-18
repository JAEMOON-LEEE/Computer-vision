using System;
using System.Collections.Generic;
using UnityEngine;

namespace TwinSight.Simulation
{
    /// <summary>
    /// 한 차로의 경로 시작점에서 차량 프리팹을 주기적으로 만든다.
    /// 만든 차량에는 TrackedObject와 WaypointMover를 붙인다. 같은 차로의 차량은 같은 속도로 달려 서로 겹치지 않는다.
    /// </summary>
    public class TrafficSpawner : MonoBehaviour
    {
        [Serializable]
        public class Entry
        {
            public GameObject prefab;
            [Tooltip("비우면 프리팹의 TrackedObject 설정을 그대로 쓴다")]
            public string className = "car";
            [Min(0f)] public float weight = 1f;
        }

        public Entry[] prefabs;
        [Tooltip("자식 Transform들을 순서대로 경로점으로 쓴다")]
        public Transform path;
        [Tooltip("다음 차량까지 기다리는 시간(초) 범위")]
        public Vector2 intervalSeconds = new Vector2(2f, 5f);
        [Tooltip("차로 속도(m/s) 범위. 시작할 때 한 번 정한다")]
        public Vector2 speedRange = new Vector2(10f, 16f);
        [Tooltip("직전 차량이 출발점에서 이만큼(m) 벗어나야 다음 차량을 만든다")]
        public float minGap = 14f;
        public int maxAlive = 15;
        public int seed = 1;
        public TrafficSignalController signals;

        System.Random random;
        Transform[] waypoints;
        float laneSpeed;
        float nextSpawnTime;
        GameObject lastSpawned;
        int spawnedCount;
        readonly List<GameObject> alive = new List<GameObject>();

        void Start()
        {
            random = new System.Random(seed);
            waypoints = new Transform[path.childCount];
            for (int i = 0; i < waypoints.Length; i++) waypoints[i] = path.GetChild(i);
            laneSpeed = Range(speedRange);
            nextSpawnTime = Time.time;
        }

        void Update()
        {
            alive.RemoveAll(v => v == null);  // 경로 끝에서 사라진 차량 정리
            if (waypoints.Length == 0 || Time.time < nextSpawnTime || alive.Count >= maxAlive) return;
            if (lastSpawned != null &&
                Vector3.Distance(lastSpawned.transform.position, waypoints[0].position) < minGap) return;

            Spawn();
            nextSpawnTime = Time.time + Range(intervalSeconds);
        }

        void Spawn()
        {
            var entry = PickEntry();
            if (entry == null) return;

            Vector3 start = waypoints[0].position;
            Vector3 heading = waypoints.Length > 1 ? waypoints[1].position - start : transform.forward;
            heading.y = 0f;
            var rotation = heading.sqrMagnitude > 1e-6f ? Quaternion.LookRotation(heading) : Quaternion.identity;

            var vehicle = Instantiate(entry.prefab, start, rotation);
            vehicle.name = $"{name}_{spawnedCount++}";

            if (!vehicle.TryGetComponent(out TrackedObject tracked)) tracked = vehicle.AddComponent<TrackedObject>();
            if (!string.IsNullOrEmpty(entry.className)) tracked.className = entry.className;

            if (!vehicle.TryGetComponent(out WaypointMover mover)) mover = vehicle.AddComponent<WaypointMover>();
            mover.waypoints = waypoints;
            mover.speed = laneSpeed;
            mover.loop = false;
            mover.destroyAtEnd = true;

            if (signals != null)
            {
                var agent = vehicle.AddComponent<TrafficVehicleAgent>();
                agent.signals = signals;
                if (tracked.TryGetWorldBounds(out var bounds)) agent.halfLength = bounds.size.x * 0.5f;
            }

            alive.Add(vehicle);
            lastSpawned = vehicle;
        }

        Entry PickEntry()
        {
            float total = 0f;
            foreach (var e in prefabs) if (e.prefab != null) total += e.weight;
            if (total <= 0f) return null;

            float roll = (float)random.NextDouble() * total;
            foreach (var e in prefabs)
            {
                if (e.prefab == null) continue;
                roll -= e.weight;
                if (roll <= 0f) return e;
            }
            return null;
        }

        float Range(Vector2 r) => r.x + (float)random.NextDouble() * (r.y - r.x);

        void OnDrawGizmos()
        {
            if (path == null || path.childCount < 2) return;
            Gizmos.color = Color.cyan;
            for (int i = 1; i < path.childCount; i++)
                Gizmos.DrawLine(path.GetChild(i - 1).position, path.GetChild(i).position);
        }
    }
}
