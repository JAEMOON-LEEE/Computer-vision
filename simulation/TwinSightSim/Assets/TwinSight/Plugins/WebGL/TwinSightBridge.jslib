// WebDemoBridge.cs → 웹 페이지. window에 "twinsight-unity" 이벤트로 JSON을 전달한다.
mergeInto(LibraryManager.library, {
  TwinSightEmit: function (ptr) {
    var text = UTF8ToString(ptr);
    try {
      window.dispatchEvent(new CustomEvent("twinsight-unity", { detail: JSON.parse(text) }));
    } catch (e) {
      console.warn("TwinSight bridge message ignored", e);
    }
  },
  // 모델 검출용 가상 CCTV 프레임(JPEG base64)
  TwinSightFrame: function (ptr) {
    var data = "data:image/jpeg;base64," + UTF8ToString(ptr);
    window.dispatchEvent(new CustomEvent("twinsight-frame", { detail: data }));
  }
});
