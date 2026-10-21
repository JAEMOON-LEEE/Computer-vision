/**
 * 3D 디지털 트윈 자리.
 * 나중에 react-unity-webgl을 설치하면 이 컴포넌트 본문을
 * `<Unity unityProvider>`로 바꾸고,
 * `sendMessage("TwinBridge", "ApplyObjects", JSON.stringify(objects))`로 객체를 넘긴다.
 * 지금은 라이브러리를 설치하지 않는다.
 */
import { useState } from "react";
import type { TwinObject } from "../twinModel";

type Props = {
  cameraId: string;
  objects: TwinObject[];
  placeholderSrc?: string;
};

export function TwinView3D({ cameraId, objects, placeholderSrc = "/twin-placeholder.png" }: Props) {
  const [view, setView] = useState<"cctv" | "top">("cctv");
  const [imageOk, setImageOk] = useState(true);
  return (
    <div className="twin-3d">
      <div className="panel-row">
        <strong>3D 디지털 트윈</strong>
        <div className="segment light">
          <button type="button" className={view === "cctv" ? "on" : ""} onClick={() => setView("cctv")}>
            CCTV 시점
          </button>
          <button type="button" className={view === "top" ? "on" : ""} onClick={() => setView("top")}>
            위에서 보기
          </button>
        </div>
      </div>
      {imageOk ? (
        <img
          src={placeholderSrc}
          alt={`${cameraId} 3D 디지털 트윈 자리`}
          onError={() => setImageOk(false)}
        />
      ) : (
        <div className="twin-slot">
          <p>[Unity 3D 디지털 트윈 화면 자리]</p>
          <p>WebGL 빌드 · 실시간 객체 배치</p>
          <small>
            {view === "cctv" ? "CCTV 시점" : "위에서 보기"} · 객체 {objects.length}
          </small>
        </div>
      )}
    </div>
  );
}
