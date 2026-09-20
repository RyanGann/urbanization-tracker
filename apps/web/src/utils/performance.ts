export const performanceEnabled = import.meta.env.VITE_PERFORMANCE_MARKS === "true";

export function performanceMark(name: string) {
  if (performanceEnabled && typeof performance !== "undefined" && !performance.getEntriesByName(`p01:${name}`, "mark").length) {
    performance.mark(`p01:${name}`);
  }
}
