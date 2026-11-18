using UnityEngine;

namespace TwinSight.Simulation
{
    public class FacilityPassingVehicle : MonoBehaviour
    {
        void Update() { transform.position += Vector3.right * (1.4f * Time.deltaTime); }
    }
}
