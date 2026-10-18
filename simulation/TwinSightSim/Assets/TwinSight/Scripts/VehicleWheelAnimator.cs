using System;
using UnityEngine;

namespace TwinSight.Simulation
{
    /// <summary>Visual wheel rig for deterministic synthetic traffic, driven by actual travelled distance.</summary>
    [DefaultExecutionOrder(100)]
    public class VehicleWheelAnimator : MonoBehaviour
    {
        [Serializable]
        public class Wheel
        {
            public Transform steeringPivot;
            public Transform rollingPivot;
            public float radius = 0.32f;
            public bool steers;
        }

        public Wheel[] wheels = Array.Empty<Wheel>();
        public float wheelbase = 2.6f;
        public float maxSteerAngle = 35f;
        public float teleportDistance = 10f;
        Vector3 previousPosition;
        Vector3 previousForward;
        Quaternion[] rollingRest;
        Quaternion[] steeringRest;
        float roll;

        void OnEnable()
        {
            previousPosition = transform.position;
            previousForward = transform.forward;
            rollingRest = new Quaternion[wheels.Length];
            steeringRest = new Quaternion[wheels.Length];
            for (int i = 0; i < wheels.Length; i++)
            {
                rollingRest[i] = wheels[i].rollingPivot == null ? Quaternion.identity : wheels[i].rollingPivot.localRotation;
                steeringRest[i] = wheels[i].steeringPivot == null ? Quaternion.identity : wheels[i].steeringPivot.localRotation;
            }
            roll = 0f;
        }

        void LateUpdate() => Animate(Time.deltaTime);

        public void Animate(float deltaTime)
        {
            Vector3 movement = transform.position - previousPosition;
            movement.y = 0f;
            float distance = Vector3.Dot(movement, (previousForward + transform.forward).normalized);
            float turn = Vector3.SignedAngle(previousForward, transform.forward, Vector3.up) * Mathf.Deg2Rad;
            if (movement.magnitude > teleportDistance) distance = 0f;
            roll += distance;
            float steer = Mathf.Abs(distance) > 0.0001f
                ? Mathf.Clamp(Mathf.Atan(wheelbase * turn / distance) * Mathf.Rad2Deg, -maxSteerAngle, maxSteerAngle) : 0f;
            for (int i = 0; i < wheels.Length; i++)
            {
                var wheel = wheels[i];
                if (wheel.rollingPivot != null)
                    wheel.rollingPivot.localRotation = rollingRest[i] * Quaternion.AngleAxis(roll / Mathf.Max(0.01f, wheel.radius) * Mathf.Rad2Deg % 360f, Vector3.right);
                if (wheel.steeringPivot != null)
                    wheel.steeringPivot.localRotation = steeringRest[i] * Quaternion.AngleAxis(wheel.steers ? steer : 0f, Vector3.up);
            }
            previousPosition = transform.position;
            previousForward = transform.forward;
        }
    }
}
