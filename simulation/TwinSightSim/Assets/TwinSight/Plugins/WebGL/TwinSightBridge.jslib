// WebDemoBridge.cs → 웹 페이지. window에 "twinsight-unity" 이벤트로 JSON을 전달한다.
mergeInto(LibraryManager.library, {
  TwinSightEmit: function (ptr) {
    var text = UTF8ToString(ptr);
    try {
      window.dispatchEvent(new CustomEvent("twinsight-unity", { detail: JSON.parse(text) }));
    } catch (e) {
      console.warn("TwinSight bridge message ignored", e);
    }
  }
});
