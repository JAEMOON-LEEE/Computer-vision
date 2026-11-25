using System;
using System.IO;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEngine;

namespace TwinSight.Simulation.EditorTools
{
    /// <summary>
    /// 발표용 웹 대시보드(/demo)에 넣을 City Lab WebGL 빌드. 결과는 저장소의 frontend/public/unity에 쓴다(Git 제외).
    /// 금촌 실제 인식 재생 파일(RealCctv/)은 빌드 동안만 StreamingAssets에 복사했다가 지운다.
    /// 명령줄: Unity.exe -batchmode -projectPath simulation/TwinSightSim -buildTarget WebGL [-rebuildCityLab]
    ///         -executeMethod TwinSight.Simulation.EditorTools.WebDemoBuild.BuildFromCommandLine -logFile build.log
    /// </summary>
    public static class WebDemoBuild
    {
        const string Scene = "Assets/TwinSight/CityLab/CityTrafficLab.unity";
        const string StreamingRoot = "Assets/StreamingAssets";
        const string StreamingCopy = StreamingRoot + "/RealCctv";

        static string ProjectDir => Directory.GetParent(Application.dataPath).FullName;
        static string OutputDir => Path.GetFullPath(Path.Combine(ProjectDir, "..", "..", "frontend", "public", "unity"));

        [MenuItem("TwinSight/Web/Build WebGL Demo (frontend/public/unity)")]
        static void BuildFromMenu()
        {
            bool ok = Build(out var message);
            EditorUtility.DisplayDialog(ok ? "WebGL 빌드 완료" : "WebGL 빌드 실패", message, "확인");
        }

        public static void BuildFromCommandLine()
        {
            bool ok = false;
            try
            {
                // -rebuildCityLab: 생성물인 City Lab 씬을 최신 코드(시나리오 변형·주야간 조명·금촌 CCTV 자세)로 다시 만든다
                if (Array.IndexOf(Environment.GetCommandLineArgs(), "-rebuildCityLab") >= 0)
                    Debug.Log("[WebDemoBuild] City Lab: " + CityLabBuilder.Build());
                ok = Build(out var message);
                Debug.Log("[WebDemoBuild] " + message);
            }
            catch (Exception e) { Debug.LogError("[WebDemoBuild] " + e); }
            // 다음에 에디터를 열 때 Windows 대상으로 열리게 되돌린다(가져오기 캐시가 있어 빠르다)
            EditorUserBuildSettings.SwitchActiveBuildTarget(BuildTargetGroup.Standalone, BuildTarget.StandaloneWindows64);
            EditorApplication.Exit(ok ? 0 : 1);
        }

        static bool Build(out string message)
        {
            if (!File.Exists(Path.Combine(ProjectDir, Scene)))
            {
                message = "City Lab 씬이 없습니다. TwinSight → City Lab → Build City Traffic Lab을 먼저 실행하세요.";
                return false;
            }
            bool createdRoot = !Directory.Exists(Path.Combine(ProjectDir, StreamingRoot));
            var oldCompression = PlayerSettings.WebGL.compressionFormat;
            var oldBackground = PlayerSettings.runInBackground;
            try
            {
                CopyRealCctv();
                // 압축 없음: 발표 PC의 Vite 개발 서버가 별도 헤더 설정 없이 그대로 서빙한다(로컬이라 용량 부담이 작다)
                PlayerSettings.WebGL.compressionFormat = WebGLCompressionFormat.Disabled;
                PlayerSettings.runInBackground = true;
                if (Directory.Exists(OutputDir)) Directory.Delete(OutputDir, true);
                var report = BuildPipeline.BuildPlayer(new BuildPlayerOptions
                {
                    scenes = new[] { Scene }, locationPathName = OutputDir, target = BuildTarget.WebGL, options = BuildOptions.None,
                });
                var summary = report.summary;
                message = $"{summary.result}: {summary.totalSize / 1048576.0:0.0} MB, {summary.totalTime.TotalMinutes:0.0}분 → {OutputDir}";
                return summary.result == BuildResult.Succeeded;
            }
            finally
            {
                PlayerSettings.WebGL.compressionFormat = oldCompression;
                PlayerSettings.runInBackground = oldBackground;
                FileUtil.DeleteFileOrDirectory(Path.Combine(ProjectDir, StreamingCopy));
                FileUtil.DeleteFileOrDirectory(Path.Combine(ProjectDir, StreamingCopy + ".meta"));
                if (createdRoot)
                {
                    FileUtil.DeleteFileOrDirectory(Path.Combine(ProjectDir, StreamingRoot));
                    FileUtil.DeleteFileOrDirectory(Path.Combine(ProjectDir, StreamingRoot + ".meta"));
                }
                AssetDatabase.Refresh();
            }
        }

        static void CopyRealCctv()
        {
            string source = Path.Combine(ProjectDir, "RealCctv");
            string target = Path.Combine(ProjectDir, StreamingCopy);
            if (!Directory.Exists(source)) return;
            foreach (var file in Directory.GetFiles(source, "*", SearchOption.AllDirectories))
            {
                string relative = file.Substring(source.Length + 1);
                string ext = Path.GetExtension(file).ToLowerInvariant();
                if (ext != ".json" && ext != ".jpg" && ext != ".jpeg" && ext != ".png") continue;
                string destination = Path.Combine(target, relative);
                Directory.CreateDirectory(Path.GetDirectoryName(destination));
                File.Copy(file, destination, true);
            }
            AssetDatabase.Refresh();
        }
    }
}
