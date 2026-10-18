using UnityEngine;

namespace TwinSight.Simulation
{
    /// <summary>
    /// 경로점을 따라 일정 속도로 움직인다. 피벗이 바닥 중심인 모델을 기준으로 노면 높이에 맞춘다.
    /// </summary>
    public class WaypointMover : MonoBehaviour
    {
        public Transform[] waypoints;
        [Tooltip("m/s")] public float speed = 12f;
        public bool loop;
        [Tooltip("마지막 점에 닿으면 오브젝트를 없앤다(스포너가 만든 차량용)")]
        public bool destroyAtEnd = true;
        public bool snapToRoad = true;

        int next;
        TrafficVehicleAgent trafficAgent;

        void Start()
        {
            trafficAgent = GetComponent<TrafficVehicleAgent>();
            // 첫 경로점에서 출발한다고 보고 두 번째 점부터 향한다
            if (waypoints != null && waypoints.Length > 0) next = Mathf.Min(1, waypoints.Length - 1);
        }

        void Update()
        {
            if (waypoints == null || waypoints.Length == 0) return;

            float step = speed * Time.deltaTime;
            if (trafficAgent != null) step = trafficAgent.LimitStep(step);
            Vector3 pos = transform.position;
            for (int guard = 0; step > 0f && guard <= waypoints.Length; guard++)
            {
                Vector3 target = waypoints[next].position;
                Vector3 delta = target - pos;
                delta.y = 0f;
                float distance = delta.magnitude;
                if (distance > step)
                {
                    pos += delta / distance * step;
                    transform.rotation = Quaternion.LookRotation(delta, Vector3.up);
                    break;
                }

                pos = new Vector3(target.x, pos.y, target.z);
                step -= distance;
                if (!Advance()) return;
            }

            if (snapToRoad && RoadSurface.TryGetSurfacePoint(pos, out var ground)) pos.y = ground.y;
            transform.position = pos;
        }

        bool Advance()
        {
            next++;
            if (next < waypoints.Length) return true;
            if (loop)
            {
                next = 0;
                return true;
            }
            if (destroyAtEnd) Destroy(gameObject);
            else enabled = false;
            return false;
        }
    }
}
