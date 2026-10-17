using System.Collections.Generic;
using UnityEngine;

namespace TwinSight.Simulation
{
    /// <summary>
    /// 정답 라벨을 내보낼 객체(차량·보행자·포트홀·낙하물)에 붙인다.
    /// 자식까지 포함한 모든 Renderer를 객체의 모양으로 본다.
    /// </summary>
    public class TrackedObject : MonoBehaviour
    {
        public static readonly List<TrackedObject> All = new List<TrackedObject>();
        static int nextId = 1;

        [Tooltip("YOLO 클래스 이름과 맞춘다. 예: car, truck, bus, motorcycle, person, pothole, debris")]
        public string className = "car";

        [Tooltip("메시 정점이 이보다 많으면 건너뛰며 샘플링한다(박스 계산 속도용)")]
        public int maxVerticesPerMesh = 20000;

        /// <summary>실행할 때마다 1부터 새로 붙는 객체 번호.</summary>
        public int TrackId { get; private set; }

        Renderer[] renderers;
        readonly List<Vector3> vertices = new List<Vector3>();
        Mesh bakedMesh;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        static void ResetStatics()
        {
            All.Clear();
            nextId = 1;
        }

        void Awake()
        {
            TrackId = nextId++;
            renderers = GetComponentsInChildren<Renderer>();
        }

        void OnEnable() => All.Add(this);
        void OnDisable() => All.Remove(this);

        void OnDestroy()
        {
            if (bakedMesh != null) Destroy(bakedMesh);
        }

        public bool TryGetWorldBounds(out Bounds bounds)
        {
            bounds = default;
            bool any = false;
            foreach (var r in renderers)
            {
                if (!IsActive(r)) continue;
                if (any) bounds.Encapsulate(r.bounds);
                else { bounds = r.bounds; any = true; }
            }
            return any;
        }

        /// <summary>
        /// 바닥면 중심: 바운드 중심 바로 아래의 노면 점. 노면을 못 찾으면 바운드 바닥 높이를 쓴다.
        /// </summary>
        public bool TryGetGroundPoint(out Vector3 point)
        {
            point = default;
            if (!TryGetWorldBounds(out var b)) return false;
            if (!RoadSurface.TryGetSurfacePoint(b.center, out point))
                point = new Vector3(b.center.x, b.min.y, b.center.z);
            return true;
        }

        /// <summary>
        /// 박스 계산용 월드 좌표 점들. 메시를 읽을 수 있으면 정점을, 아니면 메시 바운드의 8 꼭짓점을 넣는다.
        /// 모델 Import Settings에서 Read/Write를 켜면 박스가 더 정확해진다.
        /// </summary>
        public void CollectWorldPoints(List<Vector3> output)
        {
            foreach (var r in renderers)
            {
                if (!IsActive(r)) continue;

                if (r is SkinnedMeshRenderer skinned)
                {
                    if (bakedMesh == null) bakedMesh = new Mesh();
                    skinned.BakeMesh(bakedMesh, true);  // 스케일까지 반영한 현재 자세
                    var t = skinned.transform;
                    AddVertices(bakedMesh, Matrix4x4.TRS(t.position, t.rotation, Vector3.one), output);
                }
                else if (r.TryGetComponent(out MeshFilter filter) && filter.sharedMesh != null)
                {
                    var mesh = filter.sharedMesh;
                    var localToWorld = r.transform.localToWorldMatrix;
                    if (mesh.isReadable) AddVertices(mesh, localToWorld, output);
                    else AddBoxCorners(mesh.bounds, localToWorld, output);
                }
                else
                {
                    AddBoxCorners(r.bounds, Matrix4x4.identity, output);
                }
            }
        }

        void AddVertices(Mesh mesh, Matrix4x4 localToWorld, List<Vector3> output)
        {
            mesh.GetVertices(vertices);
            int step = Mathf.Max(1, vertices.Count / Mathf.Max(1, maxVerticesPerMesh));
            for (int i = 0; i < vertices.Count; i += step)
                output.Add(localToWorld.MultiplyPoint3x4(vertices[i]));
        }

        static void AddBoxCorners(Bounds b, Matrix4x4 m, List<Vector3> output)
        {
            Vector3 min = b.min, max = b.max;
            for (int i = 0; i < 8; i++)
            {
                var corner = new Vector3(
                    (i & 1) == 0 ? min.x : max.x,
                    (i & 2) == 0 ? min.y : max.y,
                    (i & 4) == 0 ? min.z : max.z);
                output.Add(m.MultiplyPoint3x4(corner));
            }
        }

        static bool IsActive(Renderer r) => r != null && r.enabled && r.gameObject.activeInHierarchy;
    }
}
