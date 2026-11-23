#if UNITY_EDITOR
using System;
using System.Collections;
using System.IO;
using System.Linq;
using UnityEngine;

namespace TwinSight.Simulation
{
    /// <summary>Independent temporal train/val/test scenes; physics events are labels, never inference inputs.</summary>
    public class StopZoneCapture : MonoBehaviour
    {
        public bool Finished { get; private set; }
        public string Progress { get; private set; }
        public int framesPerClip = 40;
        public bool nightCapture;
        public int seedOffset;
        public string sessionPrefix = "queue-v2-";
        IEnumerator Start()
        {
            Application.runInBackground=true;
            var director=FindFirstObjectByType<RoadScenarioDirector>();
            director.automaticEpisodes=false; director.cleanDatasetCapture=true;
            foreach(var spawner in FindObjectsByType<TrafficSpawner>(FindObjectsSortMode.None)) spawner.enabled=false;
            foreach(var vehicle in TrafficVehicleAgent.All.ToArray()) if(vehicle!=null) Destroy(vehicle.gameObject);
            var city=GameObject.Find("SeoulCity");
            foreach(var renderer in city.GetComponentsInChildren<Renderer>())
                if(renderer.name=="Plane.002_Chrome_0") renderer.enabled=false;
            var camera=GameObject.Find("VirtualCCTV").GetComponent<Camera>();
            var original=camera.GetComponent<GroundTruthExporter>(); original.enabled=false;
            var sun=GameObject.Find("Sun").GetComponent<Light>();
            var lighting=FindFirstObjectByType<DayNightEnvironment>();
            if(lighting!=null) lighting.showControls=false;
            foreach(var stage in new[]{("train",11401,4),("val",12502,2),("test",13603,2)})
            {
                var random=new System.Random(stage.Item2);
                for(int repetition=0;repetition<stage.Item3;repetition++)
                foreach(StopZoneScenario scenario in Enum.GetValues(typeof(StopZoneScenario)))
                {
                    int seed=stage.Item2+seedOffset+repetition*101+(int)scenario*17;
                    director.ResetSampling(seed);
                    bool inbound=repetition%2==1;
                    float offset=(float)random.NextDouble()*0.3f-0.15f;
                    float speed=1.8f+(float)random.NextDouble()*1.0f;
                    float gap=scenario==StopZoneScenario.TightQueue ? 0.12f+(float)random.NextDouble()*0.08f
                        : 0.24f+(float)random.NextDouble()*0.12f;
                    sun.intensity=1.05f+(float)random.NextDouble()*0.3f;
                    sun.transform.rotation=Quaternion.Euler(44+(float)random.NextDouble()*3,-37+(float)random.NextDouble()*4,0);
                    if(nightCapture) lighting.Apply(SimulationTimeOfDay.Night,seed);
                    director.BeginStopZoneEpisode(scenario,inbound,offset,speed,gap);
                    // The camera/exporter needs a frame to initialize. Preserve the
                    // complete approach instead of letting a fast impact happen first.
                    var actors=FindObjectsByType<ScenarioImpactActor>(FindObjectsSortMode.None);
                    var movers=FindObjectsByType<WaypointMover>(FindObjectsSortMode.None);
                    foreach(var actor in actors) actor.enabled=false;
                    foreach(var mover in movers) mover.enabled=false;
                    var exporter=camera.gameObject.AddComponent<GroundTruthExporter>();
                    exporter.calibrationGrid=original.calibrationGrid; exporter.manualCapture=true;
                    exporter.imageWidth=1440;exporter.imageHeight=960;exporter.captureFps=5;
                    exporter.cameraId=$"{sessionPrefix}{stage.Item1}-{scenario}-{repetition}-s{seed}";
                    exporter.maxFrames=0;exporter.warmupSeconds=0;exporter.stopPlayModeWhenDone=false;
                    yield return null;
                    for(int frame=0;frame<framesPerClip;frame++)
                    {
                        Progress=$"{stage.Item1} {scenario} {repetition} frame {frame}/{framesPerClip}";
                        yield return null;exporter.CaptureOneForDataset();
                        if(frame==0)
                        {
                            foreach(var actor in actors) if(actor!=null) actor.enabled=true;
                            foreach(var mover in movers) if(mover!=null) mover.enabled=true;
                        }
                    }
                    exporter.CompleteManualDataset();Destroy(exporter);yield return null;
                }
            }
            Directory.CreateDirectory("Logs");File.WriteAllText("Logs/"+sessionPrefix+"capture-complete.txt",DateTime.Now.ToString("O"));
            Finished=true;Progress="complete";
        }
    }
}
#endif
