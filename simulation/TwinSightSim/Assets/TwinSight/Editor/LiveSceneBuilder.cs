using System.Collections.Generic;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace TwinSight.Simulation.EditorTools
{
    /// <summary>
    /// 메뉴 TwinSight > Create CCTV Live Scene.
    /// 실제 CCTV 파이프라인(python CCTV --serve 8765)의 실시간 검출 결과를 받아 차량을 움직이는 디지털 트윈 씬을 만든다.
    /// 넓은 노면, 캘리브레이션 원점(TwinOrigin), 차량들을 따라가는 카메라, CctvLiveClient를 둔다.
    /// 차량 모델은 Build Vehicle Prefabs로 만든 프리팹을 모두 쓰고(클래스별로 추적 ID에 따라 고름), 트럭은 상자 모델을 쓴다.
    /// </summary>
    public static class LiveSceneBuilder
    {
        const string Root = "Assets/TwinSight/Live";

        [MenuItem("TwinSight/Create CCTV Live Scene")]
        public static void Create()
        {
            if (!EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;
            DemoSceneBuilder.EnsureFolder(Root);
            var scene = EditorSceneManager.NewScene(NewSceneSetup.DefaultGameObjects, NewSceneMode.Single);

            // 실제 CCTV의 노면 좌표를 받을 넓은 바닥(300 x 300 m). 캘리브레이션 원점이 TwinOrigin이다
            var ground = GameObject.CreatePrimitive(PrimitiveType.Plane);
            ground.name = "Ground";
            ground.transform.localScale = new Vector3(30f, 1f, 30f);
            ground.AddComponent<RoadSurface>();
            var asphalt = AssetDatabase.LoadAssetAtPath<Material>("Assets/TwinSight/Demo/Materials/Asphalt.mat");
            if (asphalt) ground.GetComponent<Renderer>().sharedMaterial = asphalt;

            var origin = new GameObject("TwinOrigin").transform;
            var marker = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
            marker.name = "OriginMarker";
            Object.DestroyImmediate(marker.GetComponent<Collider>());
            marker.transform.SetParent(origin, false);
            marker.transform.localScale = new Vector3(0.5f, 0.05f, 0.5f);

            var cam = Camera.main;
            cam.name = "TwinViewCamera";
            cam.transform.SetPositionAndRotation(new Vector3(0f, 45f, -35f), Quaternion.Euler(50f, 0f, 0f));
            cam.farClipPlane = 2000f;

            var client = new GameObject("CctvLive").AddComponent<CctvLiveClient>();
            client.twinOrigin = origin;
            client.followCamera = cam;
            client.prefabs = FindVehiclePrefabs();
            client.fallbackPrefab = AssetDatabase.LoadAssetAtPath<GameObject>("Assets/TwinSight/Demo/Prefabs/BoxCar.prefab");

            EditorSceneManager.SaveScene(scene, Root + "/CctvLive.unity");
            Selection.activeGameObject = client.gameObject;
            Debug.Log($"TwinSight: CCTV 실시간 씬을 만들었습니다 (차량 프리팹 {client.prefabs.Count}개). " +
                      "먼저 python CCTV --mode live --cctv <번호> --serve 8765 를 실행한 뒤 Play를 누르세요.");
        }

        static List<CctvLiveClient.ClassPrefab> FindVehiclePrefabs()
        {
            var list = new List<CctvLiveClient.ClassPrefab>();
            if (AssetDatabase.IsValidFolder(VehiclePrefabBuilder.OutputRoot))
            {
                foreach (var guid in AssetDatabase.FindAssets("t:Prefab", new[] { VehiclePrefabBuilder.OutputRoot }))
                {
                    var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(AssetDatabase.GUIDToAssetPath(guid));
                    if (prefab && prefab.TryGetComponent(out TrackedObject tracked))
                        list.Add(new CctvLiveClient.ClassPrefab { className = tracked.className, prefab = prefab });
                }
            }
            if (!list.Exists(p => p.className == "truck"))
            {
                var truck = AssetDatabase.LoadAssetAtPath<GameObject>("Assets/TwinSight/Demo/Prefabs/BoxTruck.prefab");
                if (truck) list.Add(new CctvLiveClient.ClassPrefab { className = "truck", prefab = truck });
            }
            return list;
        }
    }
}
