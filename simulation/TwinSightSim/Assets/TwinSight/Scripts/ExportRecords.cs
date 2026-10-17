using System;
using System.Collections.Generic;

namespace TwinSight.Simulation
{
    // docs/data_format.md 에 적은 JSON 형식. 필드 이름이 곧 JSON 키다.

    [Serializable]
    public class CameraInfo
    {
        public string camera_id;
        public string scene;
        public string unity_version;
        public int image_width;
        public int image_height;
        public float vertical_fov_deg;
        public float capture_fps;
        public float fx;
        public float fy;
        public float cx;
        public float cy;
        public float[] position;
        public float[] rotation_euler_deg;
        public float[] forward;
        public float[] world_to_camera_cv;
        public string coordinate_system =
            "world: Unity meters (x right, y up, z forward); image: pixels, origin top-left";
    }

    [Serializable]
    public class ControlPoint
    {
        public int id;
        public float[] world;
        public float[] pixel;
        public bool in_frame;
    }

    [Serializable]
    public class ControlPointFile
    {
        public string camera_id;
        public List<ControlPoint> points = new List<ControlPoint>();
    }

    [Serializable]
    public class ObjectRecord
    {
        public int track_id;
        public string class_name;
        public float[] bbox_xyxy;
        public bool truncated;
        public float[] ground_point_world;
        public float[] ground_point_pixel;
        public bool ground_point_in_frame;
    }

    [Serializable]
    public class FrameRecord
    {
        public string camera_id;
        public int frame;
        public float timestamp;
        public string image;
        public int width;
        public int height;
        public List<ObjectRecord> objects = new List<ObjectRecord>();
    }
}
