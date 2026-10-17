using UnityEngine;

namespace TwinSight.Simulation
{
    /// <summary>
    /// 노면(도로·인도·바닥)으로 쓰는 오브젝트에 붙인다. Collider가 있어야 한다.
    /// 기준점 배치와 차량 높이 맞추기는 이 컴포넌트가 붙은 Collider만 노면으로 본다.
    /// </summary>
    public class RoadSurface : MonoBehaviour
    {
        const float RayOriginHeight = 1000f;
        static readonly RaycastHit[] Hits = new RaycastHit[64];

        /// <summary>(x, z) 위치에서 가장 위에 있는 노면 점을 찾는다.</summary>
        public static bool TryGetSurfacePoint(Vector3 position, out Vector3 point)
        {
            var origin = new Vector3(position.x, RayOriginHeight, position.z);
            int count = Physics.RaycastNonAlloc(
                origin, Vector3.down, Hits, RayOriginHeight * 2f, ~0, QueryTriggerInteraction.Ignore);

            point = default;
            float best = float.MaxValue;
            for (int i = 0; i < count; i++)
            {
                if (Hits[i].distance >= best) continue;
                if (Hits[i].collider.GetComponentInParent<RoadSurface>() == null) continue;
                best = Hits[i].distance;
                point = Hits[i].point;
            }
            return best < float.MaxValue;
        }
    }
}
