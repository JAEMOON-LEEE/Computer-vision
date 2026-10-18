using System.Collections.Generic;
using UnityEngine;

namespace TwinSight.Simulation
{
    public class PedestrianCrossingAgent : MonoBehaviour
    {
        static readonly List<PedestrianCrossingAgent> agents = new List<PedestrianCrossingAgent>();
        public static int CrossingCount
        {
            get { int count = 0; foreach (var agent in agents) if (agent != null && agent.Crossing) count++; return count; }
        }
        public TrafficSignalController signals;
        public Vector3 from;
        public Vector3 to;
        public float speed = 0.85f;
        public float waitSeconds = 1f;
        public Transform leftLeg;
        public Transform rightLeg;
        public bool Crossing { get; private set; }
        float waitUntil;
        bool reverse;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        static void ResetStatics() => agents.Clear();
        void OnEnable() => agents.Add(this);
        void OnDisable() => agents.Remove(this);
        void Start() { transform.position = from; waitUntil = Time.time + waitSeconds; }
        void Update() => Step(Time.deltaTime);

        public void Step(float seconds)
        {
            if (signals == null) return;
            if (!Crossing)
            {
                float crossingTime = Vector3.Distance(from, to) / Mathf.Max(speed, 0.01f);
                if (Time.time < waitUntil || !signals.PedestriansMayEnter || signals.Remaining < crossingTime + 0.5f) return;
                Crossing = true;
            }
            Vector3 target = reverse ? from : to;
            Vector3 direction = target - transform.position;
            if (direction.sqrMagnitude > 1e-6f) transform.rotation = Quaternion.LookRotation(direction);
            transform.position = Vector3.MoveTowards(transform.position, target, speed * seconds);
            float swing = Mathf.Sin(Time.time * 9f) * 24f;
            if (leftLeg != null) leftLeg.localRotation = Quaternion.Euler(swing, 0, 0);
            if (rightLeg != null) rightLeg.localRotation = Quaternion.Euler(-swing, 0, 0);
            if (Vector3.Distance(transform.position, target) < 0.01f)
            {
                Crossing = false; reverse = !reverse; waitUntil = Time.time + waitSeconds;
                if (leftLeg != null) leftLeg.localRotation = Quaternion.identity;
                if (rightLeg != null) rightLeg.localRotation = Quaternion.identity;
            }
        }
    }
}
