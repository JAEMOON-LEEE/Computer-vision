using System.Collections.Generic;
using UnityEngine;

namespace TwinSight.Simulation
{
    public class ScenarioObstacle : MonoBehaviour
    {
        public static readonly List<ScenarioObstacle> All = new List<ScenarioObstacle>();
        public string category = "debris";
        public float radius = 0.35f;
        public RoadScenarioDirector director;
        public bool BlocksTraffic => category != "pothole" && transform.position.y < 1.3f;
        bool landed;
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        static void ResetStatics() => All.Clear();
        void OnEnable() => All.Add(this);
        void OnDisable() => All.Remove(this);
        void OnCollisionEnter(Collision collision)
        {
            if (category != "debris" || landed || collision.collider.GetComponent<RoadSurface>() == null) return;
            landed = true;
            if (director != null) director.Record("debris_landed", "physics_contact", gameObject, null);
        }
    }
}
