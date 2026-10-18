#if UNITY_EDITOR
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEngine;

namespace TwinSight.Simulation
{
    /// <summary>Temporary Play-mode integration probe, never attached to the saved scene.</summary>
    public class ScenarioRuntimeValidation : MonoBehaviour
    {
        readonly List<object> results = new List<object>();
        bool passed = true;
        public bool Finished { get; private set; }
        void Check(string name, bool condition)
        { passed &= condition; results.Add(new { name, passed = condition }); }

        IEnumerator Start()
        {
            var director = FindFirstObjectByType<RoadScenarioDirector>();
            var signals = FindFirstObjectByType<TrafficSignalController>();
            director.automaticEpisodes = false;
            foreach (var spawner in FindObjectsByType<TrafficSpawner>(FindObjectsSortMode.None)) spawner.enabled = false;
            foreach (var vehicle in TrafficVehicleAgent.All.ToArray()) if (vehicle != null) Destroy(vehicle.gameObject);
            director.BeginEpisode(RoadScenario.Normal);
            yield return null;
            var car = Instantiate(director.suvPrefab, new Vector3(5.5f, 0.507f, -1.06f), Quaternion.Euler(0, 90, 0));
            var agent = car.AddComponent<TrafficVehicleAgent>(); agent.signals = signals;
            signals.SetPhaseForExperiment(SignalPhase.PedestrianGreen);
            float redStep = agent.LimitStep(5);
            car.transform.position += Vector3.right * redStep;
            Check("red_stops_nose_before_line", Mathf.Abs(car.transform.position.x + agent.halfLength - (signals.outboundStopX - agent.stopLineGap)) < 0.005f);
            Check("red_holds_stopped_vehicle", agent.LimitStep(0.5f) < 0.001f);
            signals.SetPhaseForExperiment(SignalPhase.VehicleGreen);
            Check("green_releases_vehicle", agent.LimitStep(0.5f) > 0.49f);
            var blocker = Instantiate(director.suvPrefab, new Vector3(signals.crossingX, 0.507f, -1.06f), car.transform.rotation);
            blocker.AddComponent<TrafficVehicleAgent>();
            Check("green_waits_at_line_when_crossing_exit_blocked", agent.LimitStep(0.5f) < 0.001f);
            blocker.SetActive(false); Destroy(blocker);
            var second = Instantiate(director.miniPrefab, car.transform.position - Vector3.right * 1.7f, car.transform.rotation);
            var follower = second.AddComponent<TrafficVehicleAgent>(); follower.signals = signals;
            Check("queue_preserves_gap", follower.LimitStep(1f) <= 0.001f);
            Destroy(car); Destroy(second);
            yield return null;
            var inbound = Instantiate(director.miniPrefab, new Vector3(12f, 0.507f, 0.24f), Quaternion.Euler(0, -90, 0));
            var inboundAgent = inbound.AddComponent<TrafficVehicleAgent>(); inboundAgent.signals = signals;
            inboundAgent.halfLength = inbound.GetComponent<TrackedObject>().TryGetWorldBounds(out var inboundBounds) ? inboundBounds.size.x * 0.5f : 0.8f;
            signals.SetPhaseForExperiment(SignalPhase.PedestrianGreen);
            inbound.transform.position += Vector3.left * inboundAgent.LimitStep(5f);
            Check("inbound_red_stops_nose_before_line", Mathf.Abs(inbound.transform.position.x - inboundAgent.halfLength - (signals.inboundStopX + inboundAgent.stopLineGap)) < 0.005f);
            Check("inbound_red_holds_stopped_vehicle", inboundAgent.LimitStep(0.5f) < 0.001f);
            signals.SetPhaseForExperiment(SignalPhase.VehicleGreen);
            Check("inbound_green_releases_vehicle", inboundAgent.LimitStep(0.5f) > 0.49f);
            Check("reduced_spawn_frequency", FindObjectsByType<TrafficSpawner>(FindObjectsSortMode.None).All(s => s.intervalSeconds.x >= 5.5f && s.intervalSeconds.y >= 8.5f && s.maxAlive <= 5));
            Destroy(inbound);
            yield return new WaitForSeconds(1.6f);
            var walkers = FindObjectsByType<PedestrianCrossingAgent>(FindObjectsSortMode.None);
            foreach (var walker in walkers)
            {
                Vector3 start = walker.transform.position;
                walker.Step(0.1f);
                Check("pedestrian_waits_on_red_" + walker.name, Vector3.Distance(start, walker.transform.position) < 0.001f);
            }
            signals.SetPhaseForExperiment(SignalPhase.PedestrianGreen);
            foreach (var walker in walkers) walker.Step(0.5f);
            Check("pedestrians_enter_on_green", PedestrianCrossingAgent.CrossingCount == walkers.Length);
            signals.SetPhaseForExperiment(SignalPhase.PedestrianClearance); signals.AdvanceClock(5);
            Check("all_red_waits_for_crossing_clearance", !signals.VehiclesMayEnter);
            foreach (var walker in walkers) walker.Step(20);
            signals.AdvanceClock(3);
            Check("vehicle_green_after_pedestrians_clear", signals.VehiclesMayEnter);
            Check("training_hazard_probability_80_percent", Mathf.Abs(1 - RoadScenarioDirector.Probabilities(ScenarioProfile.Training)[0] - 0.8f) < 0.001f);
            Check("evaluation_hazard_probability_10_percent", Mathf.Abs(1 - RoadScenarioDirector.Probabilities(ScenarioProfile.Evaluation)[0] - 0.1f) < 0.001f);

            director.BeginEpisode(RoadScenario.VehicleCollision);
            yield return new WaitForSeconds(2.5f);
            Check("vehicle_collision_requires_physics_contact", director.Events.Any(e => e.event_type == "vehicle_collision" && e.evidence == "physics_contact"));
            yield return new WaitForEndOfFrame();
            SaveView("Logs/scenario-vehicle-collision.png");
            director.BeginEpisode(RoadScenario.StructureCollision);
            yield return new WaitForSeconds(2.5f);
            Check("structure_collision_requires_physics_contact", director.Events.Any(e => e.event_type == "vehicle_structure_collision" && e.evidence == "physics_contact"));
            yield return new WaitForEndOfFrame();
            SaveView("Logs/scenario-structure-collision.png");
            director.BeginEpisode(RoadScenario.FallingDebris);
            yield return new WaitForSeconds(2f);
            Check("debris_lands_on_road_with_physics", director.Events.Any(e => e.event_type == "debris_landed"));
            yield return new WaitForEndOfFrame();
            SaveView("Logs/scenario-debris.png");
            director.BeginEpisode(RoadScenario.Pothole);
            yield return null;
            Check("pothole_has_ground_truth_label", TrackedObject.All.Any(o => o != null && o.className == "pothole"));
            yield return new WaitForEndOfFrame();
            SaveView("Logs/scenario-pothole.png");
            File.WriteAllText("Logs/traffic-scenario-validation.json", Newtonsoft.Json.JsonConvert.SerializeObject(new { passed, checks = results }, Newtonsoft.Json.Formatting.Indented));
            director.automaticEpisodes = true;
            foreach (var spawner in FindObjectsByType<TrafficSpawner>(FindObjectsSortMode.None)) spawner.enabled = true;
            Finished = true;
        }

        static void SaveView(string path)
        {
            var camera = GameObject.Find("VirtualCCTV").GetComponent<Camera>();
            var target = new RenderTexture(1280, 720, 24);
            var pixels = new Texture2D(1280, 720, TextureFormat.RGB24, false);
            var oldTarget = camera.targetTexture; var oldActive = RenderTexture.active;
            try
            {
                camera.targetTexture = target; camera.Render(); RenderTexture.active = target;
                pixels.ReadPixels(new Rect(0, 0, 1280, 720), 0, 0); pixels.Apply(); File.WriteAllBytes(path, pixels.EncodeToPNG());
            }
            finally
            {
                camera.targetTexture = oldTarget; RenderTexture.active = oldActive;
                target.Release(); Destroy(target); Destroy(pixels);
            }
        }
    }
}
#endif
