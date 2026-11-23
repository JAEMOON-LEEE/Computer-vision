using System;
using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace TwinSight.Simulation.EditorTools
{
    /// <summary>Road-relative placement reused from baewoojun's CityLabCctvPlacer (2b75753).</summary>
    public static class CityLabCameraProfile
    {
        [Serializable] class RoadPose
        {
            public string virtual_camera_id;
            public float lateral_m, height_m, yaw_to_road_deg, pitch_deg, roll_deg;
            public float vertical_fov_deg, ref_ahead_m;
            public int[] image_size;
            public bool has_ref;
        }

        [MenuItem("TwinSight/City Lab/Restore Reference CCTV (Geumchon)")]
        public static void Restore()
        {
            if (EditorApplication.isPlaying) throw new InvalidOperationException("Stop Play before restoring CCTV.");
            if (UnityEngine.SceneManagement.SceneManager.GetActiveScene().path != CityLabBuilder.ScenePath)
                throw new InvalidOperationException("Open CityTrafficLab before restoring this CCTV profile.");
            Apply(GameObject.Find("VirtualCCTV").GetComponent<Camera>());
            var scene = UnityEngine.SceneManagement.SceneManager.GetActiveScene();
            EditorSceneManager.MarkSceneDirty(scene);
            EditorSceneManager.SaveScene(scene);
        }

        public static void Apply(Camera camera)
        {
            string path = Path.Combine(Directory.GetParent(Application.dataPath).FullName, "RealCctv/geumchon.road_pose.json");
            var pose = JsonUtility.FromJson<RoadPose>(File.ReadAllText(path));
            const float metersPerUnit = 2.92f;
            var signal = UnityEngine.Object.FindFirstObjectByType<TrafficSignalController>();
            float stopX = signal != null ? signal.outboundStopX : 6.8f;
            float x = pose.has_ref ? Mathf.Clamp(stopX - pose.ref_ahead_m / metersPerUnit, -17f, 26f) : -17f;
            // Looking along +X, camera-right is -Z in Unity's coordinate system.
            var position = new Vector3(x, 0.507f + pose.height_m / metersPerUnit,
                CityLabBuilder.PaintedCentreZ - pose.lateral_m / metersPerUnit);
            camera.transform.SetPositionAndRotation(position,
                Quaternion.Euler(pose.pitch_deg, 90f + pose.yaw_to_road_deg, pose.roll_deg));
            camera.fieldOfView = pose.vertical_fov_deg;
            var exporter = camera.GetComponent<GroundTruthExporter>();
            // Keep the reference aspect/FOV; render extra pixels for distant hazards.
            exporter.imageWidth = pose.image_size[0] * 2; exporter.imageHeight = pose.image_size[1] * 2;
            exporter.cameraId = pose.virtual_camera_id;
            Debug.Log($"TwinSight restored reference CCTV: {position:F6}, {camera.transform.eulerAngles:F6}, FOV {camera.fieldOfView:F6}");
        }
    }
}
