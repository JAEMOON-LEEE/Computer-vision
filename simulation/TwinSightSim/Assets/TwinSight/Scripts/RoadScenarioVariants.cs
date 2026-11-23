using UnityEngine;

namespace TwinSight.Simulation
{
    public enum PotholeVariant { Small, Wide, Elongated, Cluster }
    public enum DebrisVariant { SmallBlock, LargeBlock, FlatSlab, MultipleBlocks }
    public enum SignalViolationVariant { OutboundRed, InboundRed, FastOutboundRed }

    public partial class RoadScenarioDirector
    {
        public string ScenarioVariant { get; private set; } = "";

        public void BeginPotholeEpisode(PotholeVariant variant)
        {
            BeginEpisode(RoadScenario.Normal);
            Current = RoadScenario.Pothole;
            SpawnPotholeVariant(variant, 12f, -1.06f);
        }

        void SpawnPotholeVariant(PotholeVariant variant, float x, float lane)
        {
            ScenarioVariant = variant.ToString();
            var hole = CreatePothole(new Vector3(x, Ground(x, lane), lane));
            if (variant == PotholeVariant.Small) hole.transform.localScale = new Vector3(.55f, 1, .55f);
            if (variant == PotholeVariant.Wide) hole.transform.localScale = new Vector3(1.35f, 1, 1.1f);
            if (variant == PotholeVariant.Elongated) hole.transform.localScale = new Vector3(1.5f, 1, .55f);
            if (variant == PotholeVariant.Cluster)
            {
                hole.transform.localScale = new Vector3(.65f, 1, .65f);
                var other = CreatePothole(new Vector3(x + .8f, Ground(x + .8f, lane + .25f), lane + .25f));
                other.transform.localScale = new Vector3(.55f, 1, .55f);
            }
        }

        public void BeginDebrisEpisode(DebrisVariant variant)
        {
            BeginEpisode(RoadScenario.Normal);
            Current = RoadScenario.FallingDebris;
            SpawnDebrisVariant(variant, 12f, -1.06f);
        }

        void SpawnDebrisVariant(DebrisVariant variant, float x, float lane)
        {
            ScenarioVariant = variant.ToString();
            var debris = CreateDebris(new Vector3(x, Ground(x, lane) + 2.4f, lane));
            if (variant == DebrisVariant.SmallBlock) debris.transform.localScale *= .6f;
            if (variant == DebrisVariant.LargeBlock) debris.transform.localScale *= 1.25f;
            if (variant == DebrisVariant.FlatSlab) debris.transform.localScale = new Vector3(.85f, .15f, .55f);
            if (variant == DebrisVariant.MultipleBlocks)
            {
                debris.transform.localScale *= .7f;
                var other = CreateDebris(new Vector3(x + .75f, Ground(x + .75f, lane) + 3f, lane));
                other.transform.localScale *= .55f;
            }
        }

        public void BeginSignalViolationEpisode(SignalViolationVariant variant)
        {
            BeginEpisode(RoadScenario.Normal);
            Current = RoadScenario.SignalViolation;
            SpawnSignalViolation(variant);
        }

        void SpawnSignalViolation(SignalViolationVariant variant)
        {
            if (signals == null) { Debug.LogError("Signal violation requires a signal controller."); return; }
            ScenarioVariant = variant.ToString();
            bool inbound = variant == SignalViolationVariant.InboundRed;
            float direction = inbound ? -1f : 1f;
            float lane = inbound ? .24f : -1.06f;
            float stop = inbound ? signals.inboundStopX : signals.outboundStopX;
            signals.SetPhaseForExperiment(SignalPhase.PedestrianGreen);
            signals.enabled = false;
            float x = stop - direction * 3.5f;
            var vehicle = CreateImpactVehicle(miniPrefab, new Vector3(x, Ground(x, lane) + .015f, lane),
                Vector3.right * direction, variant == SignalViolationVariant.FastOutboundRed ? 4f : 2f);
            var observer = vehicle.AddComponent<SignalViolationObserver>();
            observer.director = this; observer.signals = signals; observer.stopX = stop; observer.direction = direction;
            Record("signal_violation_setup", "scheduled_not_yet_crossed", vehicle, null);
        }
    }

    public class SignalViolationObserver : MonoBehaviour
    {
        public RoadScenarioDirector director;
        public TrafficSignalController signals;
        public float stopX, direction;
        bool crossed;
        void FixedUpdate()
        {
            if (crossed || signals == null || director == null) return;
            var tracked = GetComponent<TrackedObject>();
            if (tracked == null || !tracked.TryGetWorldBounds(out var bounds)) return;
            float nose = direction > 0 ? bounds.max.x : bounds.min.x;
            if ((nose - stopX) * direction < 0) return;
            crossed = true;
            if (signals.Phase != SignalPhase.VehicleGreen && signals.Phase != SignalPhase.VehicleYellow)
                director.Record("red_signal_crossing", "front_bumper_crossed_stop_line", gameObject, null);
        }
    }
}
