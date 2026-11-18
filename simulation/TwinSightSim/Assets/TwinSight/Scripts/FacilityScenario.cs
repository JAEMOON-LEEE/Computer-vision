using System;
using UnityEngine;

namespace TwinSight.Simulation
{
    public enum FacilityCase
    {
        DelineatorNormal, DelineatorBroken, DelineatorFallen, DelineatorMissing, DelineatorPassingVehicle,
        GuardrailNormal, GuardrailBent, GuardrailDisplaced, GuardrailBroken, GuardrailPassingVehicle,
        SignalNormal, SignalTransition, SignalFlashing, SignalDark,
        ManholeNormal, ManholeOpen, ManholeDisplaced,
        GuardrailNormalCurved, GuardrailNormalJoint, GuardrailNormalLight,
        ManholeNormalPattern, ManholeNormalWorn, ManholePassingVehicle,
        GuardrailNormalShadow, ManholeNormalShadow,
        GuardrailBrokenLeft, GuardrailBrokenRight, GuardrailBentOpposite,
        ManholeOpenShadow, ManholeDisplacedSmall, ManholeDisplacedLateral
    }

    // Simulation truth only; never use as an observation at inference time.
    [Serializable]
    public class FacilityTruth
    {
        public string facility_id, kind, state, variant;
        public float[] reference_position_world;
        public float[] actual_position_world;
        public float scale, rotation_degrees, displacement;
        public int signal_lamp_index;
        public bool present;
        public string visibility = "not_measured";
        public bool passing_vehicle;
        public string appearance_detail;
    }

    public partial class RoadScenarioDirector
    {
        public FacilityTruth Facility { get; private set; }
        // Opt-in only: existing facility simulations retain their previous export format.
        [NonSerialized] public bool exportDelineatorBoxes;
        [NonSerialized] public bool exportOtherFacilityBoxes;
        [NonSerialized] public bool useCloserFacilityPositions;
        [NonSerialized] public bool useCenterlineFacilities;
        [NonSerialized] public bool useNearestFacilityPositions;

        public void BeginFacilityEpisode(FacilityCase variant)
        {
            BeginEpisode(RoadScenario.Normal);
            Current = RoadScenario.Facility;
            ScenarioVariant = variant.ToString();
            bool manhole = ((int)variant >= (int)FacilityCase.ManholeNormal && (int)variant <= (int)FacilityCase.ManholeDisplaced) ||
                variant == FacilityCase.ManholeNormalPattern || variant == FacilityCase.ManholeNormalWorn || variant == FacilityCase.ManholePassingVehicle || variant == FacilityCase.ManholeNormalShadow ||
                variant == FacilityCase.ManholeOpenShadow || variant == FacilityCase.ManholeDisplacedSmall || variant == FacilityCase.ManholeDisplacedLateral;
            bool signal = (int)variant >= (int)FacilityCase.SignalNormal && (int)variant <= (int)FacilityCase.SignalDark;
            bool post = (int)variant <= (int)FacilityCase.DelineatorPassingVehicle;
            bool passingVehicle = variant == FacilityCase.DelineatorPassingVehicle || variant == FacilityCase.GuardrailPassingVehicle || variant == FacilityCase.ManholePassingVehicle;
            bool normal = variant == FacilityCase.DelineatorNormal || variant == FacilityCase.GuardrailNormal ||
                passingVehicle || variant == FacilityCase.SignalNormal || variant == FacilityCase.SignalTransition || variant == FacilityCase.SignalFlashing || variant == FacilityCase.ManholeNormal ||
                variant == FacilityCase.GuardrailNormalCurved || variant == FacilityCase.GuardrailNormalJoint || variant == FacilityCase.GuardrailNormalLight ||
                variant == FacilityCase.ManholeNormalPattern || variant == FacilityCase.ManholeNormalWorn ||
                variant == FacilityCase.GuardrailNormalShadow || variant == FacilityCase.ManholeNormalShadow;
            float x = useNearestFacilityPositions ? Range(-7f, -3f) : useCloserFacilityPositions ? Range(-1f, 5f) : Range(10f, 14f);
            // CityLabBuilder.PaintedCentreZ; opt in for synthetic experiments only.
            float z = manhole ? (Range(0, 1) > .5f ? -1.06f : .24f) : useCenterlineFacilities ? -.41f : -2.05f;
            float ground = Ground(x, z);
            float size = Range(.85f, 1.15f);
            var reference = new Vector3(x, ground, z);
            Facility = new FacilityTruth { facility_id = signal ? "vehicle-signal-0" : post ? "delineator-0" : manhole ? "manhole-0" : "guardrail-0",
                kind = signal ? "traffic_signal" : post ? "delineator" : manhole ? "manhole" : "guardrail", state = normal ? "normal" : "abnormal",
                variant = variant.ToString(), present = variant != FacilityCase.DelineatorMissing && variant != FacilityCase.ManholeOpen && variant != FacilityCase.ManholeOpenShadow,
                scale = size, signal_lamp_index = signal ? 0 : -1, passing_vehicle = passingVehicle,
                appearance_detail = variant.ToString() };
            if (signal)
            {
                if (signals == null || signals.vehicleLamps == null || signals.vehicleLamps.Length == 0 || signals.vehicleLamps[0] == null)
                    throw new InvalidOperationException("Facility signal scenario requires vehicle lamp 0.");
                reference = signals.vehicleLamps[0].transform.position;
                signals.enabled = true;
                signals.SetPhaseForExperiment(variant == FacilityCase.SignalFlashing ? SignalPhase.PedestrianFlash :
                    variant == FacilityCase.SignalTransition ? SignalPhase.VehicleYellow : SignalPhase.VehicleGreen);
                if (variant == FacilityCase.SignalTransition) signals.AdvanceClock(Mathf.Max(0, signals.vehicleYellowSeconds - .5f));
                if (variant == FacilityCase.SignalDark) { signals.suppressedVehicleLampIndex = 0; signals.RefreshLamps(); }
            }
            else if (manhole)
            {
                GameObject group = null;
                if (exportOtherFacilityBoxes) { group = new GameObject("Facility_ManholeLabelGroup"); Register(group); }
                // Flat dark disk represents the opening; no road mesh or collider is cut.
                var opening = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
                opening.name = "Facility_ManholeOpening"; Register(opening);
                if (group != null) opening.transform.SetParent(group.transform, true);
                opening.transform.position = reference + Vector3.up * .035f;
                opening.transform.localScale = new Vector3(.68f * size, .005f, .68f * size);
                opening.GetComponent<Renderer>().sharedMaterial = roadDamageMaterial;
                if (Facility.present)
                {
                    float shift = variant == FacilityCase.ManholeDisplaced ? Range(.65f, 1.0f) * size :
                        variant == FacilityCase.ManholeDisplacedSmall ? Range(.25f, .40f) * size :
                        variant == FacilityCase.ManholeDisplacedLateral ? Range(.65f, 1.0f) * size : 0f;
                    bool lateral = variant == FacilityCase.ManholeDisplacedLateral;
                    var cover = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
                    cover.name = "Facility_ManholeCover"; Register(cover);
                    if (group != null) cover.transform.SetParent(group.transform, true);
                    cover.transform.position = reference + new Vector3(lateral ? 0 : shift, .055f, lateral ? shift : 0);
                    cover.transform.localScale = new Vector3(.65f * size, .009f, .65f * size);
                    cover.GetComponent<Renderer>().sharedMaterial = rimMaterial;
                    if (variant == FacilityCase.ManholeNormalPattern || variant == FacilityCase.ManholeNormalWorn)
                    {
                        if (variant == FacilityCase.ManholeNormalWorn) Tint(cover, new Color(.43f, .39f, .32f));
                        int stripes = variant == FacilityCase.ManholeNormalPattern ? 3 : 1;
                        for (int i = 0; i < stripes; i++)
                        {
                            var stripe = Primitive("Facility_ManholeMark_" + i,
                                reference + new Vector3((i - (stripes - 1) * .5f) * .12f * size, .077f, 0),
                                new Vector3(.025f * size, .004f, .38f * size), concreteMaterial);
                            Tint(stripe, variant == FacilityCase.ManholeNormalWorn ? new Color(.27f,.25f,.22f) : new Color(.50f,.50f,.48f));
                        }
                    }
                    Facility.displacement = shift;
                }
                if (group != null)
                {
                    var tracked = group.AddComponent<TrackedObject>();
                    tracked.className = normal ? "manhole_normal" : "manhole_abnormal";
                }
            }
            else if (post && Facility.present)
            {
                float height = .9f * size;
                float angle = variant == FacilityCase.DelineatorFallen ? Range(70f, 88f) : 0f;
                float fraction = variant == FacilityCase.DelineatorBroken ? Range(.25f, .55f) : 1f;
                var pole = Primitive("Facility_Delineator", reference, new Vector3(.12f * size, height * fraction, .12f * size), concreteMaterial);
                pole.transform.rotation = Quaternion.Euler(0, 0, angle);
                pole.transform.position = reference + pole.transform.up * (height * fraction * .5f);
                Tint(pole, new Color(1f, .28f, .02f));
                if (exportDelineatorBoxes)
                {
                    var tracked = pole.AddComponent<TrackedObject>();
                    tracked.className = variant == FacilityCase.DelineatorBroken ? "delineator_broken" :
                        variant == FacilityCase.DelineatorFallen ? "delineator_fallen" : "delineator_normal";
                }
                Facility.rotation_degrees = angle; Facility.scale = size * fraction;
            }
            else if (!post)
            {
                GameObject group = null;
                if (exportOtherFacilityBoxes) { group = new GameObject("Facility_GuardrailLabelGroup"); Register(group); }
                float length = 2.4f * size;
                float shift = variant == FacilityCase.GuardrailDisplaced ? Range(.35f, .65f) : 0f;
                float angle = variant == FacilityCase.GuardrailBent ? Range(15f, 35f) : variant == FacilityCase.GuardrailBentOpposite ? -Range(15f, 35f) : 0f;
                bool broken = variant == FacilityCase.GuardrailBroken;
                // Three independently positioned beam sections; a gap represents breakage.
                for (int i = -1; i <= 1; i++)
                {
                    if ((broken && i == 0) || (variant == FacilityCase.GuardrailBrokenLeft && i == -1) ||
                        (variant == FacilityCase.GuardrailBrokenRight && i == 1)) continue;
                    float segmentAngle = variant == FacilityCase.GuardrailNormalCurved ? i * 4f : i == 0 ? angle : 0f;
                    float segmentLength = variant == FacilityCase.GuardrailNormalJoint ? length / 3f + .06f * size : length / 3f;
                    float curveOffset = variant == FacilityCase.GuardrailNormalCurved && i != 0 ? .04f * size : 0f;
                    var beam = Primitive("Facility_Guardrail_" + i,
                        reference + new Vector3(i * length / 3f, .65f * size, shift + curveOffset + (i == 0 && angle != 0 ? .18f : 0)),
                        new Vector3(segmentLength, .20f * size, .09f * size), rimMaterial);
                    beam.transform.rotation = Quaternion.Euler(0, segmentAngle, 0);
                    if (group != null) beam.transform.SetParent(group.transform, true);
                    if (variant == FacilityCase.GuardrailNormalLight) Tint(beam, new Color(.52f, .55f, .57f));
                }
                for (int i = -1; i <= 1; i += 2)
                {
                    var guardPost = Primitive("Facility_GuardrailPost_" + i, reference + new Vector3(i * length * .4f, .32f * size, 0),
                        new Vector3(.10f * size, .64f * size, .10f * size), rimMaterial);
                    if (group != null) guardPost.transform.SetParent(group.transform, true);
                }
                if (group != null)
                {
                    var tracked = group.AddComponent<TrackedObject>();
                    tracked.className = normal ? "guardrail_normal" : "guardrail_abnormal";
                }
                Facility.rotation_degrees = angle; Facility.displacement = shift;
            }
            Facility.reference_position_world = new[] { reference.x, reference.y, reference.z };
            bool lateralManhole = variant == FacilityCase.ManholeDisplacedLateral;
            Facility.actual_position_world = Facility.present ? new[] { reference.x + (manhole && !lateralManhole ? Facility.displacement : 0), reference.y, reference.z + (!manhole || lateralManhole ? Facility.displacement : 0) } : new float[0];
            if (variant == FacilityCase.GuardrailNormalShadow || variant == FacilityCase.ManholeNormalShadow || variant == FacilityCase.ManholeOpenShadow)
            {
                var environment = FindFirstObjectByType<DayNightEnvironment>();
                if (environment == null || environment.sun == null) throw new InvalidOperationException("Shadow scenario requires a sun light.");
                var center = reference + Vector3.up * (manhole ? .05f : .6f);
                var caster = Primitive("Facility_ShadowCaster", center - environment.sun.transform.forward * 2f,
                    new Vector3(1.3f, .15f, 1.1f), concreteMaterial);
                caster.GetComponent<Renderer>().shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.ShadowsOnly;
                var collider = caster.GetComponent<Collider>();
                if (collider != null) Destroy(collider);
            }
            if (passingVehicle)
            {
                if (suvPrefab == null) throw new InvalidOperationException("Passing vehicle case requires the existing SUV prefab.");
                float vehicleLane = manhole ? z : -1.06f;
                var vehicle = Instantiate(suvPrefab, new Vector3(x - 4f, Ground(x - 4f, vehicleLane), vehicleLane), Quaternion.Euler(0, 90, 0));
                vehicle.name = "Facility_PassingVehicle"; Register(vehicle);
                vehicle.AddComponent<FacilityPassingVehicle>();
            }
            Record("facility_setup", "simulation_ground_truth", null, null);
        }

        static void Tint(GameObject obj, Color color)
        {
            var renderer = obj.GetComponent<Renderer>();
            var block = new MaterialPropertyBlock();
            renderer.GetPropertyBlock(block);
            block.SetColor("_BaseColor", color); block.SetColor("_Color", color);
            renderer.SetPropertyBlock(block);
        }
    }

}
