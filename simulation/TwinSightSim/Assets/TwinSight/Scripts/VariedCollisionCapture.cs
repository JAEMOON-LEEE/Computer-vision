#if UNITY_EDITOR
using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEngine;

namespace TwinSight.Simulation
{
    /// <summary>Independent collision clips with pre-impact context and physical-contact audit.</summary>
    public class VariedCollisionCapture : MonoBehaviour
    {
        public bool Finished { get; private set; }
        public string Progress { get; private set; }
        public int framesPerClip=80;
        public int captureFps=8;
        public bool smokeOnly;
        public string onlyCase="";
        public string outputRoot="TwinSightExport/collision-v1";
        readonly List<object> audits=new List<object>();

        IEnumerator Start()
        {
            if(FindObjectsByType<VariedCollisionCapture>(FindObjectsSortMode.None).Any(c=>c!=this && !c.Finished))
                throw new InvalidOperationException("A collision capture is already running.");
            outputRoot=Path.GetFullPath(outputRoot);
            if(!string.Equals(Path.GetPathRoot(outputRoot),"D:\\",StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Project captures must be stored on D:.");
            if(Directory.Exists(outputRoot) && Directory.EnumerateFileSystemEntries(outputRoot).Any())
                outputRoot=Path.Combine(outputRoot,"run-"+DateTime.Now.ToString("yyyyMMdd_HHmmss")+"-"+Guid.NewGuid().ToString("N").Substring(0,6));
            Directory.CreateDirectory(outputRoot);
            Debug.Log("TwinSight collision capture: "+outputRoot);
            Application.runInBackground=true;
            var director=FindFirstObjectByType<RoadScenarioDirector>();
            director.automaticEpisodes=false; director.cleanDatasetCapture=true;
            foreach(var spawner in FindObjectsByType<TrafficSpawner>(FindObjectsSortMode.None)) spawner.enabled=false;
            foreach(var car in TrafficVehicleAgent.All.ToArray()) if(car!=null) Destroy(car.gameObject);
            var city=GameObject.Find("SeoulCity");
            foreach(var renderer in city.GetComponentsInChildren<Renderer>())
                if(renderer.name=="Plane.002_Chrome_0") renderer.enabled=false;
            var camera=GameObject.Find("VirtualCCTV").GetComponent<Camera>();
            var original=camera.GetComponent<GroundTruthExporter>(); original.enabled=false;
            var lighting=FindFirstObjectByType<DayNightEnvironment>(); lighting.showControls=false;
            var cases=new[]{"NormalQueue","TightQueue","RearEnd","HighSpeedRearEnd","HeadOn","SideImpact","ChainReaction"};
            var splits=smokeOnly?new[]{"smoke"}:new[]{"train","val","test"};
            foreach(var split in splits)
            foreach(var mode in (smokeOnly?new[]{SimulationTimeOfDay.Day}:new[]{SimulationTimeOfDay.Day,SimulationTimeOfDay.Night}))
            for(int index=0;index<cases.Length;index++)
            {
                string scenario=cases[index];
                if(!string.IsNullOrEmpty(onlyCase) && scenario!=onlyCase) continue;
                int stage=split=="train"?0:split=="val"?1:split=="test"?2:3;
                int seed=251001+stage*10000+(int)mode*1000+index*97;
                bool inbound=(stage+index+(int)mode)%2==1;
                director.ResetSampling(seed); lighting.Apply(mode,seed);
                bool normal=index<2;
                if(normal) director.BeginStopZoneEpisode(index==0?StopZoneScenario.SignalQueue:StopZoneScenario.TightQueue,
                    inbound,(index-3)*.025f,2.1f,index==0?TrafficVehicleAgent.NormalQueueGap:.18f);
                else director.BeginVehicleCollisionEpisode((VehicleCollisionScenario)Enum.Parse(typeof(VehicleCollisionScenario),scenario),
                    inbound,(stage-1)*.13f,3f);
                var actors=FindObjectsByType<ScenarioImpactActor>(FindObjectsSortMode.None);
                foreach(var actor in actors) actor.enabled=false;
                var movers=FindObjectsByType<WaypointMover>(FindObjectsSortMode.None);
                foreach(var mover in movers) mover.enabled=false;
                var exporter=camera.gameObject.AddComponent<GroundTruthExporter>();
                exporter.outputRoot=outputRoot; exporter.calibrationGrid=original.calibrationGrid;
                exporter.manualCapture=true; exporter.imageWidth=1440; exporter.imageHeight=960;
                exporter.captureFps=captureFps; exporter.maxFrames=0; exporter.warmupSeconds=0;
                exporter.stopPlayModeWhenDone=false;
                exporter.cameraId=$"collision-v1-{split}-{mode}-{scenario}-{(inbound?"in":"out")}-s{seed}";
                yield return null;
                var traces=new List<object>();
                float began=Time.time;
                for(int frame=0;frame<framesPerClip;frame++)
                {
                    Progress=$"{split} {mode} {scenario} {frame+1}/{framesPerClip}";
                    yield return null; exporter.CaptureOneForDataset();
                    traces.Add(new { frame, timestamp=Time.time, vehicles=TrafficVehicleAgent.All
                        .Where(v=>v!=null && v.transform.IsChildOf(director.transform)).Select(v=>new {
                            track_id=v.GetComponent<TrackedObject>().TrackId,
                            position=new[]{v.transform.position.x,v.transform.position.y,v.transform.position.z},
                            yaw=v.transform.eulerAngles.y, half_length=v.halfLength,
                            velocity=v.TryGetComponent<Rigidbody>(out var body)?body.linearVelocity.magnitude:0f,
                            impacted=v.TryGetComponent<ScenarioImpactActor>(out var a)&&a.Impacted }).ToArray() });
                    if(frame==0)
                    {
                        foreach(var actor in actors) if(actor!=null) actor.enabled=true;
                        foreach(var mover in movers) if(mover!=null) mover.enabled=true;
                    }
                }
                var impacts=director.Events.Where(e=>e.evidence=="physics_contact" && e.event_type=="vehicle_collision").ToArray();
                int required=scenario=="ChainReaction"?2:normal?0:1;
                bool passed=normal?impacts.Length==0:impacts.Length>=required;
                var entry=new { split,lighting=mode.ToString(),scenario,inbound,seed,
                    source=exporter.RunDirectory,frames=framesPerClip,capture_fps=captureFps,
                    expected_collision=!normal,required_distinct_contacts=required,physics_events=impacts,
                    first_contact_after_seconds=impacts.Length>0?(float?)(impacts.Min(e=>e.timestamp)-began):null,
                    intended_queue_gap=normal?(index==0?TrafficVehicleAgent.NormalQueueGap:.18f):(float?)null,
                    physics_passed=passed };
                File.WriteAllText(Path.Combine(exporter.RunDirectory,"motion_audit.json"),
                    Newtonsoft.Json.JsonConvert.SerializeObject(new { audit=entry,frames=traces },Newtonsoft.Json.Formatting.Indented));
                exporter.CompleteManualDataset(); audits.Add(entry); Destroy(exporter);
                Directory.CreateDirectory(outputRoot);
                File.WriteAllText(Path.Combine(outputRoot,"capture-audit.json"),
                    Newtonsoft.Json.JsonConvert.SerializeObject(audits,Newtonsoft.Json.Formatting.Indented));
                yield return null;
            }
            Time.captureDeltaTime=0; Finished=true; Progress="complete";
            File.WriteAllText(Path.Combine(outputRoot,"capture-complete.txt"),DateTime.Now.ToString("O"));
        }
    }
}
#endif
