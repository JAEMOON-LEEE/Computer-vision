using System;
using UnityEngine;

namespace TwinSight.Simulation
{
    public enum SignalPhase { VehicleGreen, VehicleYellow, VehicleClearance, PedestrianGreen, PedestrianFlash, PedestrianClearance }

    [Serializable]
    public class SignalSnapshot
    {
        public string vehicle;
        public string pedestrian;
        public string phase;
        public float remaining_seconds;
        public int crossing_pedestrians;
    }

    public class TrafficSignalController : MonoBehaviour
    {
        public float crossingX = 8.3f;
        public float outboundStopX = 6.8f;
        public float inboundStopX = 9.65f;
        public float vehicleGreenSeconds = 12f;
        public float vehicleYellowSeconds = 3f;
        public float clearanceSeconds = 2f;
        public float pedestrianGreenSeconds = 10f;
        public float pedestrianFlashSeconds = 3f;
        public SignalLamp[] vehicleLamps;
        public SignalLamp[] pedestrianLamps;
        public SignalPhase Phase { get; private set; }
        public float PhaseElapsed { get; private set; }
        public bool VehiclesMayEnter => Phase == SignalPhase.VehicleGreen;
        public bool PedestriansMayEnter => Phase == SignalPhase.PedestrianGreen;
        public float Remaining => Mathf.Max(0, Duration(Phase) - PhaseElapsed);

        void Update() => AdvanceClock(Time.deltaTime);

        public void AdvanceClock(float seconds)
        {
            float left = Mathf.Max(0, seconds);
            for (int guard = 0; left > 0 && guard < 32; guard++)
            {
                float step = Mathf.Min(left, Mathf.Max(0, Duration(Phase) - PhaseElapsed));
                PhaseElapsed += step; left -= step;
                if (PhaseElapsed + 1e-5f < Duration(Phase)) break;
                // Give already crossing pedestrians time to clear before releasing vehicles.
                if (Phase == SignalPhase.PedestrianClearance && PedestrianCrossingAgent.CrossingCount > 0) break;
                if (Phase == SignalPhase.VehicleClearance && !CrossingClearOfVehicles()) break;
                Phase = (SignalPhase)(((int)Phase + 1) % 6); PhaseElapsed = 0;
            }
            RefreshLamps();
        }

        bool CrossingClearOfVehicles()
        {
            foreach (var vehicle in TrafficVehicleAgent.All)
                if (vehicle != null && Mathf.Abs(vehicle.transform.position.x - crossingX) < 1.2f + vehicle.halfLength
                    && vehicle.transform.position.z > -3f && vehicle.transform.position.z < 2.2f) return false;
            return true;
        }

        public void SetPhaseForExperiment(SignalPhase phase)
        { Phase = phase; PhaseElapsed = 0; RefreshLamps(); }

        float Duration(SignalPhase phase)
        {
            if (phase == SignalPhase.VehicleGreen) return Mathf.Max(0.1f, vehicleGreenSeconds);
            if (phase == SignalPhase.VehicleYellow) return Mathf.Max(0.1f, vehicleYellowSeconds);
            if (phase == SignalPhase.PedestrianGreen) return Mathf.Max(0.1f, pedestrianGreenSeconds);
            if (phase == SignalPhase.PedestrianFlash) return Mathf.Max(0.1f, pedestrianFlashSeconds);
            return Mathf.Max(0.1f, clearanceSeconds);
        }

        public SignalSnapshot Snapshot() => new SignalSnapshot
        {
            vehicle = VehiclesMayEnter ? "green" : Phase == SignalPhase.VehicleYellow ? "yellow" : "red",
            pedestrian = PedestriansMayEnter ? "green" : Phase == SignalPhase.PedestrianFlash ? "flashing_green" : "red",
            phase = Phase.ToString(), remaining_seconds = Remaining,
            crossing_pedestrians = PedestrianCrossingAgent.CrossingCount
        };

        public void RefreshLamps()
        {
            int vehicle = VehiclesMayEnter ? 2 : Phase == SignalPhase.VehicleYellow ? 1 : 0;
            bool flashOn = Phase != SignalPhase.PedestrianFlash || (int)(PhaseElapsed * 2) % 2 == 0;
            int pedestrian = PedestriansMayEnter || Phase == SignalPhase.PedestrianFlash ? 2 : 0;
            if (vehicleLamps != null) foreach (var lamp in vehicleLamps) if (lamp != null) lamp.Set(vehicle, true);
            if (pedestrianLamps != null) foreach (var lamp in pedestrianLamps) if (lamp != null) lamp.Set(pedestrian, flashOn);
        }
    }
}
