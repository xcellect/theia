export type OrbState = "idle" | "listening" | "routing" | "analyzing" | "speaking" | "error";

export default function ResearchOrb({ state }: { state: OrbState }) {
  return (
    <div className={`research-orb-scene orb-${state}`} aria-hidden="true">
      <div className="research-orb-orbit" />
      <div className="research-orb-orbit orbit-second" />
      <div className="research-orb-halo" />
      <div className="research-orb"><div className="research-orb-cloud" /><div className="research-orb-shine" /></div>
      <span className="orb-satellite satellite-one" /><span className="orb-satellite satellite-two" />
    </div>
  );
}
