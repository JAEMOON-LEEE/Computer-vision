/** 카메라별 원점 위경도.
 * calibration/<카메라ID>.json의 origin_latlon[0], origin_latlon[1]을 넣는다.
 * road_heading_deg는 도로 방향이지 카메라 방위가 아니므로 쓰지 않는다.
 * 우준이 파일을 주면 이 맵에 채운다. 지금은 비어 있다.
 */
export type CameraCalibration = {
  originLat: number;
  originLon: number;
};

export const CALIBRATION: Record<string, CameraCalibration> = {};
