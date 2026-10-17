using System.Collections.Generic;
using UnityEngine;

namespace TwinSight.Simulation
{
    /// <summary>
    /// 노면 위에 격자 기준점을 만든다. 실제 CCTV에서 측량 좌표를 아는 점(차선 끝 등)을 화면에서 찍는 작업을 대신한다.
    /// 격자는 이 오브젝트의 위치·회전을 기준으로 놓이므로 도로 방향에 맞춰 돌려 두면 된다(스케일은 1로 둔다).
    /// </summary>
    public class CalibrationGrid : MonoBehaviour
    {
        [Tooltip("로컬 x 범위(m)")] public Vector2 xRange = new Vector2(-6f, 6f);
        [Tooltip("로컬 z 범위(m)")] public Vector2 zRange = new Vector2(0f, 150f);
        [Min(0.5f)] public float spacing = 3f;

        [Tooltip("게임 화면에도 작은 표시를 그린다. YOLO용 데이터를 만들 때는 끈다.")]
        public bool showMarkersInGame;
        public float markerSize = 0.3f;

        readonly List<Vector3> points = new List<Vector3>();
        public IReadOnlyList<Vector3> Points => points;

        void Awake() => Build();

        public void Build()
        {
            points.Clear();
            Physics.SyncTransforms();
            for (float z = zRange.x; z <= zRange.y + 1e-3f; z += spacing)
            for (float x = xRange.x; x <= xRange.y + 1e-3f; x += spacing)
            {
                var p = transform.TransformPoint(new Vector3(x, 0f, z));
                if (RoadSurface.TryGetSurfacePoint(p, out var hit)) points.Add(hit);
            }

            if (points.Count == 0)
                Debug.LogWarning("CalibrationGrid: 노면을 찾지 못했습니다. 도로에 Collider와 RoadSurface가 있는지 확인하세요.", this);
            if (showMarkersInGame) SpawnMarkers();
        }

        void SpawnMarkers()
        {
            foreach (var p in points)
            {
                var marker = GameObject.CreatePrimitive(PrimitiveType.Quad);
                marker.name = "ControlPointMarker";
                Destroy(marker.GetComponent<Collider>());
                marker.transform.SetPositionAndRotation(p + Vector3.up * 0.01f, Quaternion.Euler(90f, 0f, 0f));
                marker.transform.localScale = Vector3.one * markerSize;
                marker.transform.SetParent(transform, true);
            }
        }

        void OnDrawGizmos()
        {
            Gizmos.color = Color.yellow;
            if (Application.isPlaying)
            {
                foreach (var p in points) Gizmos.DrawSphere(p, markerSize * 0.5f);
                return;
            }
            Gizmos.matrix = transform.localToWorldMatrix;
            var center = new Vector3((xRange.x + xRange.y) * 0.5f, 0f, (zRange.x + zRange.y) * 0.5f);
            var size = new Vector3(xRange.y - xRange.x, 0.01f, zRange.y - zRange.x);
            Gizmos.DrawWireCube(center, size);
        }
    }
}
