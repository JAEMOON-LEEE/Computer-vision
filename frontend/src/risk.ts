export type RiskLevel = "high" | "mid" | "low";

/** 위험 70 이상, 주의 40–69, 정상 40 미만. */
export const RISK_HIGH_MIN = 70;
export const RISK_MID_MIN = 40;

export const RISK_THEME: Record<
  RiskLevel,
  { fill: string; badgeBg: string; badgeText: string; label: string; rule: string }
> = {
  high: { fill: "#C2352A", badgeBg: "#F9DEDB", badgeText: "#8E2119", label: "위험", rule: "70 이상" },
  mid: { fill: "#E08A1E", badgeBg: "#FCEBD3", badgeText: "#8A4B06", label: "주의", rule: "40–69" },
  low: { fill: "#5B95D6", badgeBg: "#E3EDF8", badgeText: "#1D4A7A", label: "정상", rule: "40 미만" },
};

export function riskLevel(score: number): RiskLevel {
  if (score >= RISK_HIGH_MIN) return "high";
  if (score >= RISK_MID_MIN) return "mid";
  return "low";
}

const ALERT_TYPE_LABELS: Record<string, string> = {
  road_damage: "도로 파손",
  road_debris: "낙하물",
  suspected_vehicle_collision: "차량 추돌 의심",
  suspected_vehicle_structure_collision: "방호벽 충돌 의심",
};

export function alertTypeLabel(type: string): string {
  return ALERT_TYPE_LABELS[type] ?? type;
}
