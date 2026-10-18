Shader "TwinSight/AssetSignal"
{
    Properties
    {
        _MainTex ("Original asset atlas", 2D) = "white" {}
        _SignalIndex ("Red=0 Amber=1 Green=2", Float) = 0
        _SignalVisible ("Green flash visibility", Float) = 1
        _Pedestrian ("Pedestrian red/green mode", Float) = 0
    }
    SubShader
    {
        Tags { "RenderType"="Opaque" }
        CGPROGRAM
        #pragma surface surf Standard fullforwardshadows
        #pragma target 3.0
        sampler2D _MainTex;
        float _SignalIndex, _SignalVisible, _Pedestrian;
        struct Input { float2 uv_MainTex; };
        void surf(Input IN, inout SurfaceOutputStandard o)
        {
            fixed4 c = tex2D(_MainTex, IN.uv_MainTex);
            // Atlas UV regions of the original city mesh: keep its lens geometry and LED pattern.
            bool lens = IN.uv_MainTex.x > 0.015 && IN.uv_MainTex.x < 0.185 && IN.uv_MainTex.y > 0.105 && IN.uv_MainTex.y < 0.16;
            bool red = lens && IN.uv_MainTex.x >= 0.142;
            bool amber = lens && IN.uv_MainTex.x >= 0.104 && IN.uv_MainTex.x < 0.142;
            bool green = lens && IN.uv_MainTex.x < 0.104;
            bool arrow = green && IN.uv_MainTex.x > 0.06;
            bool lit = (red && _SignalIndex < 0.5) || (amber && abs(_SignalIndex - 1) < 0.5 && _Pedestrian < 0.5)
                || (green && _SignalIndex > 1.5 && _SignalVisible > 0.5 && !arrow);
            o.Albedo = c.rgb;
            if (red || amber || green)
            {
                float3 lightColor = red ? float3(1,0.01,0.005) : amber ? float3(1,0.45,0) : float3(0.005,1,0.025);
                float pattern = max(c.r, max(c.g, c.b));
                o.Albedo = lit ? lightColor * pattern * 0.5 : float3(0.012,0.012,0.012);
                o.Emission = lit ? lightColor * pattern * 1.8 : 0;
            }
            o.Smoothness = 0.1; o.Alpha = 1;
        }
        ENDCG
    }
    FallBack "Diffuse"
}
