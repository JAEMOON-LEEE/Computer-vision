const KST = "Asia/Seoul";

export function formatKstClock(date = new Date()): string {
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: KST,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(date);
}

export function formatKstTime(value: number | string): string {
  const date = typeof value === "number" ? new Date(value) : new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: KST,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).format(date);
}

export function formatKst(value: number | string): string {
  const date = typeof value === "number" ? new Date(value) : new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: KST,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).format(date);
}

export function kstParts(ms: number): { hour: string; minute: string; sort: number } {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: KST,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(ms));
  const pick = (type: string) => parts.find((part) => part.type === type)?.value ?? "00";
  const hour = pick("hour");
  const minute = pick("minute");
  const sort = Number(`${pick("year")}${pick("month")}${pick("day")}${hour}${minute}`);
  return { hour, minute, sort };
}

/** datetime-local 값을 오프셋이 붙은 KST ISO8601로 만든다. */
export function kstInputToIso(value: string): string | undefined {
  if (!value) return undefined;
  const withSeconds = value.length === 16 ? `${value}:00` : value;
  return `${withSeconds}+09:00`;
}

/** datetime-local 값을 KST 시각으로 해석한다. */
export function kstInputToMs(value: string): number | null {
  if (!value) return null;
  const parsed = new Date(`${value}:00+09:00`);
  return Number.isNaN(parsed.getTime()) ? null : parsed.getTime();
}
