using UnityEngine;

namespace TwinSight.Simulation
{
    [RequireComponent(typeof(Rigidbody))]
    public class ScenarioImpactActor : MonoBehaviour
    {
        public RoadScenarioDirector director;
        public Vector3 drivingVelocity;
        public bool drive;
        public bool dynamicAfterImpact;
        public float driveDelay;
        public float settleSeconds = 2f;
        public float linearDampingAfterImpact = 2.1f;
        public float angularDampingAfterImpact = 3f;
        public bool Impacted { get; private set; }
        Rigidbody body;
        float driveAt, settleAt;
        void Awake() => body = GetComponent<Rigidbody>();
        void Start() => driveAt = Time.time + driveDelay;
        void FixedUpdate()
        {
            if (drive && !Impacted && Time.time >= driveAt) body.linearVelocity = drivingVelocity;
            if (Impacted && dynamicAfterImpact && Time.time >= settleAt) FreezeBody();
        }
        void OnCollisionEnter(Collision collision)
        {
            var vehicle = collision.collider.GetComponentInParent<ScenarioImpactActor>();
            var obstacle = collision.collider.GetComponentInParent<ScenarioObstacle>();
            if (vehicle == null && obstacle == null) return;
            if ((!dynamicAfterImpact && Impacted) || collision.relativeVelocity.magnitude < 0.45f) return;
            string kind = vehicle != null ? "vehicle_collision" : "vehicle_structure_collision";
            if (director != null) director.RecordPhysicsImpact(kind, gameObject,
                vehicle != null ? vehicle.gameObject : obstacle.gameObject, collision);
            StopAfterImpact();
            if (vehicle != null) vehicle.StopAfterImpact();
        }
        public void StopAfterImpact()
        {
            if (Impacted) return;
            Impacted = true; drive = false;
            if (dynamicAfterImpact)
            {
                // Let PhysX resolve the impact and transfer momentum, including yaw.
                // No teleport, scripted overlap, or immediate zeroing at contact.
                body.linearDamping = linearDampingAfterImpact; body.angularDamping = angularDampingAfterImpact;
                settleAt = Time.time + settleSeconds;
                return;
            }
            FreezeBody();
        }
        void FreezeBody()
        {
            body.linearVelocity = Vector3.zero; body.angularVelocity = Vector3.zero;
            body.constraints = RigidbodyConstraints.FreezeAll;
        }
    }
}
