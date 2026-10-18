using System.Collections.Generic;
using UnityEngine;

namespace TwinSight.Simulation
{
    public class TrafficVehicleAgent : MonoBehaviour
    {
        public static readonly List<TrafficVehicleAgent> All = new List<TrafficVehicleAgent>();
        public TrafficSignalController signals;
        public float halfLength = 0.8f;
        public float gap = 0.25f;
        public float stopLineGap = 0.08f;
        public bool collisionActor;
        public string StopReason { get; private set; } = "moving";
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        static void ResetStatics() => All.Clear();
        void OnEnable() => All.Add(this);
        void OnDisable() => All.Remove(this);

        public float LimitStep(float requested)
        {
            StopReason = "moving";
            if (collisionActor) return requested;
            Vector3 forward = transform.forward, position = transform.position;
            float allowed = requested;
            if (signals != null)
            {
                float stop = forward.x > 0 ? signals.outboundStopX : signals.inboundStopX;
                float distance = (stop - position.x) * Mathf.Sign(forward.x) - halfLength;
                // Once the nose has crossed the stop line, clear the crossing rather than braking inside it.
                bool exitBlocked = !CrossingExitFree(forward);
                if ((!signals.VehiclesMayEnter || exitBlocked) && distance >= -0.02f && distance < allowed + stopLineGap)
                { allowed = Mathf.Max(0, distance - stopLineGap); StopReason = exitBlocked ? "crossing_exit_blocked" : "signal"; }
            }
            foreach (var other in All)
            {
                if (other == null || other == this) continue;
                Vector3 delta = other.transform.position - position;
                float ahead = Vector3.Dot(delta, forward);
                float lateral = Mathf.Abs(Vector3.Dot(delta, transform.right));
                if (ahead <= 0 || lateral > 0.6f) continue;
                float clearance = ahead - halfLength - other.halfLength - gap;
                if (clearance < allowed) { allowed = Mathf.Max(0, clearance); StopReason = "queue"; }
            }
            foreach (var obstacle in ScenarioObstacle.All)
            {
                if (obstacle == null || !obstacle.BlocksTraffic) continue;
                Vector3 delta = obstacle.transform.position - position;
                float ahead = Vector3.Dot(delta, forward);
                if (ahead <= 0 || Mathf.Abs(Vector3.Dot(delta, transform.right)) > 0.65f) continue;
                float clearance = ahead - halfLength - obstacle.radius - gap;
                if (clearance < allowed) { allowed = Mathf.Max(0, clearance); StopReason = "obstacle"; }
            }
            return Mathf.Clamp(allowed, 0, requested);
        }

        bool CrossingExitFree(Vector3 forward)
        {
            float direction = Mathf.Sign(forward.x);
            float stop = direction > 0 ? signals.outboundStopX : signals.inboundStopX;
            float exit = signals.crossingX + direction * (1.2f + halfLength + gap);
            foreach (var other in All)
            {
                if (other == null || other == this || Mathf.Abs(other.transform.position.z - transform.position.z) > 0.6f) continue;
                float x = other.transform.position.x;
                if ((x - stop) * direction > 0 && (x - exit) * direction < other.halfLength + gap) return false;
            }
            return true;
        }
    }
}
