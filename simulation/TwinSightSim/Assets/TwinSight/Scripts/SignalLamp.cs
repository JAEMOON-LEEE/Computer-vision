using UnityEngine;

namespace TwinSight.Simulation
{
    public class SignalLamp : MonoBehaviour
    {
        public Renderer assetRenderer;
        public bool pedestrianMode;
        MaterialPropertyBlock properties;

        public void Set(int active, bool visible)
        {
            if (assetRenderer == null) return;
            if (properties == null) properties = new MaterialPropertyBlock();
            properties.SetFloat("_SignalIndex", active); properties.SetFloat("_SignalVisible", visible ? 1 : 0);
            properties.SetFloat("_Pedestrian", pedestrianMode ? 1 : 0); assetRenderer.SetPropertyBlock(properties);
        }
    }
}
