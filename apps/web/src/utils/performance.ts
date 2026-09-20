export function performanceMark(name: string) {
  if (import.meta.env.VITE_PERFORMANCE_MARKS === "true" && typeof performance !== "undefined") {
    performance.mark(`p01:${name}`);
  }
}
