using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace TwinSight.Simulation
{
    public enum RoadsideDamageVariant { Delineators, GuardrailBent, GuardrailBroken }
    public enum ManholeVariant { Open, Raised, Sunken }

    /// <summary>
    /// 발표 시연용 도로 시설물 위험 장면: 시선유도봉·가드레일 파손, 맨홀 이상.
    /// 단순 도형으로 만든 시각 모형이며 검출 모델 학습·검증에는 아직 쓰지 않았다.
    /// 장면을 만들 때 RoadScenarioDirector에 정상 에피소드를 시작시키고(이전 사고 정리) 정답 기록을 같은 목록에 남긴다.
    /// City Lab 축척: 1단위 ≈ 2.92 m, 중앙선 z = -0.41, 차로 z = -1.06 / 0.24, 도로 가장자리 z ≈ -1.75, 앞쪽 +X.
    /// </summary>
    public class DemoRoadHazards : MonoBehaviour
    {
        public RoadScenarioDirector director;
        public float centreX = 12.2f;

        readonly List<GameObject> spawned = new List<GameObject>();
        int episode = -1;
        Material orange, white, black, steel, darkSteel, asphaltHole, railSteel, railPost, reflector;

        public string Current { get; private set; } = "";
        public string Variant { get; private set; } = "";

        void Update()
        {
            // 다른 시나리오가 시작되면(표지판·자동 에피소드) 시연 장면을 치운다
            if (episode >= 0 && director != null && director.Episode != episode) Clear();
        }

        public void Clear()
        {
            foreach (var go in spawned) if (go != null) Destroy(go);
            spawned.Clear(); episode = -1; Current = ""; Variant = "";
        }

        public void Spawn(RoadsideDamageVariant variant)
        {
            Begin("RoadsideDamage", variant.ToString());
            float edge = -1.72f;
            if (variant == RoadsideDamageVariant.Delineators)
            {
                for (int i = 0; i < 7; i++)
                {
                    float x = centreX - 1.8f + i * 0.6f;
                    var post = Delineator(new Vector3(x, Ground(x, edge), edge));
                    if (i >= 2 && i <= 4)   // 가운데 세 개가 차에 받혀 차로 쪽으로 쓰러진다
                        StartCoroutine(Topple(post.transform, Quaternion.Euler(0, Random.Range(-40f, 40f), 0) * Quaternion.Euler(86f, 0, 0),
                            0.25f + i * 0.12f, i == 3 ? new Vector3(0.15f, 0, 0.35f) : Vector3.zero));
                }
                Record("delineator_knocked_down", "procedural_visual");
            }
            else
            {
                const float railZ = -0.41f;   // 중앙선 위 중앙분리 가드레일
                var segments = new List<Transform>();
                for (int i = 0; i < 8; i++)
                {
                    float x = centreX - 2.1f + i * 0.6f;
                    Post(new Vector3(x, Ground(x, railZ), railZ), i == 3 || i == 4 ? (variant == RoadsideDamageVariant.GuardrailBent ? 28f : 55f) : 0f);
                    if (i < 7) segments.Add(Rail(new Vector3(x + 0.3f, Ground(x, railZ) + 0.2f, railZ + 0.02f), 0.6f));
                }
                if (variant == RoadsideDamageVariant.GuardrailBent)
                {
                    // 가운데 두 칸이 반대편 차로(+Z, 카메라 쪽)로 꺾인다(충격 방향)
                    StartCoroutine(Bend(segments[3], Quaternion.Euler(0, 22f, -6f), new Vector3(0, -0.03f, 0.12f), 0.3f));
                    StartCoroutine(Bend(segments[4], Quaternion.Euler(0, -22f, 6f), new Vector3(0, -0.03f, 0.12f), 0.3f));
                    Record("guardrail_bent", "procedural_visual");
                }
                else
                {
                    // 한 칸이 떨어져 나가 반대편 차로 위에 놓인다
                    var piece = segments[3];
                    var target = new Vector3(piece.position.x + 0.4f, Ground(piece.position.x + 0.4f, 0.12f) + 0.02f, 0.12f);
                    StartCoroutine(Fling(piece, target, Quaternion.Euler(0, 35f, 90f), 0.25f));
                    StartCoroutine(Bend(segments[2], Quaternion.Euler(0, 14f, 0), new Vector3(0, 0, 0.05f), 0.3f));
                    Record("guardrail_broken", "procedural_visual");
                }
            }
        }

        public void Spawn(ManholeVariant variant)
        {
            Begin("Manhole", variant.ToString());
            float x = centreX, z = -1.06f, y = Ground(x, z);
            const float radius = 0.13f;   // 지름 약 0.76 m (실제 0.65 m보다 조금 크게 해 화면에서 보이게)
            var root = Track(new GameObject("Demo_Manhole"));
            root.transform.position = new Vector3(x, y, z);
            Disc(root.transform, "Frame", radius * 1.18f, 0.006f, 0.003f, darkSteel);
            if (variant == ManholeVariant.Open)
            {
                Disc(root.transform, "Hole", radius, 0.004f, 0.005f, black);
                var cover = Disc(root.transform, "Cover", radius, 0.012f, 0.012f, steel);
                CoverPattern(cover.transform);
                StartCoroutine(Slide(cover.transform, cover.transform.position + new Vector3(0.18f, 0.004f, 0.27f), Quaternion.Euler(0, 40f, 0), 0.4f));
                Record("manhole_cover_open", "procedural_visual");
            }
            else if (variant == ManholeVariant.Raised)
            {
                var cover = Disc(root.transform, "Cover", radius, 0.012f, 0.012f, steel);
                CoverPattern(cover.transform);
                StartCoroutine(Slide(cover.transform, cover.transform.position + new Vector3(0, 0.035f, 0), Quaternion.Euler(14f, 0, 9f), 0.4f));
                Record("manhole_cover_raised", "procedural_visual");
            }
            else
            {
                // 주변 포장이 꺼져 맨홀 둘레에 어두운 홈이 생긴다
                Disc(root.transform, "Sink", radius * 1.75f, 0.004f, 0.004f, asphaltHole);
                var cover = Disc(root.transform, "Cover", radius, 0.012f, 0.009f, steel);
                CoverPattern(cover.transform);
                StartCoroutine(Slide(cover.transform, cover.transform.position + new Vector3(0, -0.02f, 0), Quaternion.Euler(0, 0, 4f), 0.4f));
                Record("manhole_sunken", "procedural_visual");
            }
        }

        // ---- 공통 ----

        void Begin(string scenario, string variant)
        {
            Clear();
            if (director != null) { director.BeginEpisode(RoadScenario.Normal); episode = director.Episode; }
            else episode = 0;
            Current = scenario; Variant = variant;
            EnsureMaterials();
        }

        void Record(string kind, string evidence) { if (director != null) director.Record(kind, evidence, null, null); }

        GameObject Track(GameObject go) { spawned.Add(go); return go; }

        float Ground(float x, float z)
        {
            var origin = new Vector3(x, 6f, z);
            foreach (var hit in Physics.RaycastAll(origin, Vector3.down, 12f))
                if (hit.point.y < 1.2f && hit.collider.GetComponentInParent<TrafficVehicleAgent>() == null) return hit.point.y;
            return 0.507f;
        }

        void EnsureMaterials()
        {
            if (orange != null) return;
            Material source = director != null && director.concreteMaterial != null ? director.concreteMaterial : null;
            Material Make(Color c, float smooth)
            {
                var m = source != null ? new Material(source) : new Material(Shader.Find("Standard"));
                m.color = c;
                if (m.HasProperty("_Glossiness")) m.SetFloat("_Glossiness", smooth);
                if (m.HasProperty("_MainTex")) m.SetTexture("_MainTex", null);
                return m;
            }
            orange = Make(new Color(1f, 0.42f, 0.05f), 0.4f);
            white = Make(new Color(0.95f, 0.95f, 0.95f), 0.5f);
            black = Make(new Color(0.01f, 0.01f, 0.01f), 0f);
            steel = Make(new Color(0.42f, 0.43f, 0.45f), 0.55f);
            darkSteel = Make(new Color(0.22f, 0.22f, 0.23f), 0.3f);
            asphaltHole = Make(new Color(0.05f, 0.045f, 0.04f), 0f);
            // 가드레일: 아연 도금 은색 + 노란 반사지. 회색 노면과 구분되게 밝게
            railSteel = Make(new Color(0.86f, 0.88f, 0.9f), 0.75f);
            railPost = Make(new Color(0.7f, 0.72f, 0.75f), 0.6f);
            reflector = Make(new Color(1f, 0.82f, 0.05f), 0.8f);
            if (reflector.HasProperty("_EmissionColor")) { reflector.EnableKeyword("_EMISSION"); reflector.SetColor("_EmissionColor", new Color(0.45f, 0.35f, 0f)); }
        }

        static GameObject Primitive(PrimitiveType type, Transform parent, string name, Material material)
        {
            var go = GameObject.CreatePrimitive(type);
            go.name = name;
            var collider = go.GetComponent<Collider>();
            if (collider != null) Destroy(collider);   // 교통 차량·노면 판정에 끼어들지 않게
            go.GetComponent<Renderer>().sharedMaterial = material;
            if (parent != null) go.transform.SetParent(parent, false);
            return go;
        }

        GameObject Delineator(Vector3 basePoint)
        {
            const float height = 0.27f, radius = 0.022f;   // 약 0.8 m, 지름 0.13 m
            var root = Track(new GameObject("Demo_Delineator"));
            root.transform.position = basePoint;
            var foot = Primitive(PrimitiveType.Cylinder, root.transform, "Base", black);
            foot.transform.localPosition = new Vector3(0, 0.006f, 0); foot.transform.localScale = new Vector3(0.085f, 0.006f, 0.085f);
            var body = Primitive(PrimitiveType.Cylinder, root.transform, "Body", orange);
            body.transform.localPosition = new Vector3(0, height / 2, 0); body.transform.localScale = new Vector3(radius * 2, height / 2, radius * 2);
            foreach (float h in new[] { 0.62f, 0.82f })
            {
                var band = Primitive(PrimitiveType.Cylinder, root.transform, "Band", white);
                band.transform.localPosition = new Vector3(0, height * h, 0); band.transform.localScale = new Vector3(radius * 2.1f, 0.012f, radius * 2.1f);
            }
            return root;
        }

        void Post(Vector3 basePoint, float tilt)
        {
            var post = Track(Primitive(PrimitiveType.Cube, null, "Demo_GuardrailPost", railPost));
            post.transform.position = basePoint + Vector3.up * 0.12f;
            post.transform.localScale = new Vector3(0.035f, 0.24f, 0.035f);
            if (tilt != 0f) post.transform.RotateAround(basePoint, Vector3.right, tilt);   // 충격 방향(+Z)으로 기운다
        }

        Transform Rail(Vector3 centre, float length)
        {
            var rail = Track(new GameObject("Demo_GuardrailBeam"));
            rail.transform.position = centre;
            // W형 빔을 두 장의 얇은 판으로 단순화
            for (int k = 0; k < 2; k++)
            {
                var plate = Primitive(PrimitiveType.Cube, rail.transform, "Plate", railSteel);
                plate.transform.localPosition = new Vector3(0, k == 0 ? 0.022f : -0.022f, k == 0 ? 0f : 0.008f);
                plate.transform.localScale = new Vector3(length, 0.04f, 0.008f);
            }
            var mark = Primitive(PrimitiveType.Cube, rail.transform, "Reflector", reflector);
            mark.transform.localPosition = new Vector3(0, 0, 0.012f);
            mark.transform.localScale = new Vector3(0.05f, 0.03f, 0.006f);
            return rail.transform;
        }

        GameObject Disc(Transform parent, string name, float radius, float thickness, float top, Material material)
        {
            var disc = Primitive(PrimitiveType.Cylinder, parent, name, material);
            disc.transform.localPosition = new Vector3(0, top - thickness / 2, 0);
            disc.transform.localScale = new Vector3(radius * 2, thickness / 2, radius * 2);
            return disc;
        }

        void CoverPattern(Transform cover)
        {
            // 뚜껑 위 격자 무늬(멀리서도 맨홀로 보이게)
            for (int i = -1; i <= 1; i++)
            {
                var bar = Primitive(PrimitiveType.Cube, cover, "Grip", darkSteel);
                bar.transform.localPosition = new Vector3(i * 0.28f, 1.05f, 0);
                bar.transform.localScale = new Vector3(0.06f, 0.15f, 0.8f);
            }
        }

        // ---- 움직임: 버튼을 누른 순간 무슨 일이 생겼는지 보이게 ----

        IEnumerator Topple(Transform t, Quaternion fallen, float delay, Vector3 slide)
        {
            yield return new WaitForSeconds(delay);
            Quaternion start = t.rotation; Vector3 from = t.position;
            for (float a = 0; a < 1f; a += Time.deltaTime / 0.45f)
            {
                float e = a * a;   // 넘어질수록 빨라진다
                t.rotation = Quaternion.Slerp(start, fallen, e);
                t.position = from + slide * e + Vector3.up * 0.02f * Mathf.Sin(e * Mathf.PI);
                yield return null;
            }
            t.rotation = fallen; t.position = from + slide + Vector3.up * 0.02f;
        }

        IEnumerator Bend(Transform t, Quaternion delta, Vector3 offset, float delay)
        {
            yield return new WaitForSeconds(delay);
            Quaternion start = t.rotation, end = delta * start; Vector3 from = t.position;
            for (float a = 0; a < 1f; a += Time.deltaTime / 0.25f)
            {
                float e = 1f - (1f - a) * (1f - a);
                t.rotation = Quaternion.Slerp(start, end, e); t.position = from + offset * e;
                yield return null;
            }
            t.rotation = end; t.position = from + offset;
        }

        IEnumerator Fling(Transform t, Vector3 target, Quaternion end, float delay)
        {
            yield return new WaitForSeconds(delay);
            Vector3 from = t.position; Quaternion start = t.rotation;
            for (float a = 0; a < 1f; a += Time.deltaTime / 0.6f)
            {
                t.position = Vector3.Lerp(from, target, a) + Vector3.up * 0.25f * Mathf.Sin(a * Mathf.PI);
                t.rotation = Quaternion.Slerp(start, end, a);
                yield return null;
            }
            t.position = target; t.rotation = end;
        }

        IEnumerator Slide(Transform t, Vector3 target, Quaternion end, float delay)
        {
            yield return new WaitForSeconds(delay);
            Vector3 from = t.position; Quaternion start = t.rotation;
            for (float a = 0; a < 1f; a += Time.deltaTime / 0.8f)
            {
                float e = a * a * (3f - 2f * a);
                t.position = Vector3.Lerp(from, target, e) + Vector3.up * 0.01f * Mathf.Sin(e * Mathf.PI);
                t.rotation = Quaternion.Slerp(start, end, e);
                yield return null;
            }
            t.position = target; t.rotation = end;
        }
    }
}
