namespace TwinSight.Simulation
{
    /// <summary>
    /// 발표 시연(모델 검출 모드)용: 포트홀·낙하물 변형을 원하는 앞쪽 위치(x)에 만든다.
    /// 기존 BeginPotholeEpisode/BeginDebrisEpisode는 x = 12에 고정이라 금촌 자세의 VirtualCCTV에서는 너무 멀어
    /// 몇 픽셀로만 보인다. 생성 모양은 기존 변형 코드를 그대로 쓴다.
    /// </summary>
    public partial class RoadScenarioDirector
    {
        public void BeginPotholeEpisodeAt(PotholeVariant variant, float x, float lane = -1.06f)
        {
            BeginEpisode(RoadScenario.Normal);
            Current = RoadScenario.Pothole;
            SpawnPotholeVariant(variant, x, lane);
        }

        public void BeginDebrisEpisodeAt(DebrisVariant variant, float x, float lane = -1.06f)
        {
            BeginEpisode(RoadScenario.Normal);
            Current = RoadScenario.FallingDebris;
            SpawnDebrisVariant(variant, x, lane);
        }
    }
}
