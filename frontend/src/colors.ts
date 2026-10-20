export const CLASS_COLORS: Record<string, string> = {
  car: "#3dde7a",
  person: "#4cc3ff",
  pothole: "#ff8a3d",
  crack: "#ffb020",
  debris: "#ff5d73",
  truck: "#8ea2ff",
  bus: "#c084fc",
  motorcycle: "#2dd4bf",
  bicycle: "#a3e635",
  barrier: "#f472b6",
};

export function classColor(name: string): string {
  return CLASS_COLORS[name] || "#ffffff";
}
