/**
 * Soft, static gradient blobs behind the app content — adds depth for the
 * glassmorphism surfaces without any animation (perf + reduced-motion friendly).
 */
export function BackgroundDecor() {
  return (
    <div
      aria-hidden
      className="pointer-events-none fixed inset-0 -z-10 overflow-hidden"
    >
      <div className="absolute inset-0 bg-background" />
      <div className="absolute -left-40 -top-40 size-[38rem] rounded-full bg-primary/20 blur-[120px] dark:bg-primary/15" />
      <div className="absolute -right-40 top-10 size-[34rem] rounded-full bg-[hsl(270_80%_65%)]/20 blur-[120px] dark:bg-[hsl(270_80%_60%)]/12" />
      <div className="absolute bottom-[-12rem] left-1/3 size-[36rem] rounded-full bg-success/10 blur-[130px] dark:bg-success/10" />
    </div>
  );
}
