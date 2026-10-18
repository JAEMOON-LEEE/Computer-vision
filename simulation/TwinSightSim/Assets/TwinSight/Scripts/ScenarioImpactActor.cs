using UnityEngine;

namespace TwinSight.Simulation
{
    [RequireComponent(typeof(Rigidbody))]
    public class ScenarioImpactActor : MonoBehaviour
    {
        public RoadScenarioDirector director;
        public Vector3 drivingVelocity;
        public bool drive;
        public bool Impacted { get; private set; }
        Rigidbody body;
        void Awake() => body = GetComponent<Rigidbody>();
        void FixedUpdate()
        {
            if (drive && !Impacted) body.linearVelocity = drivingVelocity;
        }
        void OnCollisionEnter(Collision collision)
        {
            var vehicle = collision.collider.GetComponentInParent<ScenarioImpactActor>();
            var obstacle = collision.collider.GetComponentInParent<ScenarioObstacle>();
            if (vehicle == null && obstacle == null) return;
            if (Impacted || collision.relativeVelocity.magnitude < 0.45f) return;
            string kind = vehicle != null ? "vehicle_collision" : "vehicle_structure_collision";
            if (director != null) director.Record(kind, "physics_contact", gameObject, vehicle != null ? vehicle.gameObject : obstacle.gameObject);
            StopAfterImpact();
            if (vehicle != null) vehicle.StopAfterImpact();
        }
        public void StopAfterImpact()
        {
            Impacted = true; drive = false;
            body.linearVelocity = Vector3.zero; body.angularVelocity = Vector3.zero;
            body.constraints = RigidbodyConstraints.FreezeAll;
        }
    }
}
