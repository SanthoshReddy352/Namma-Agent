// Imperium's laurel wreath (Phase 9 W1): original art drawn in code. Two
// branches rise from a tied stem and curve up either side; leaves sit along
// each arc, angled outwards, shrinking towards the tips. Drawn in currentColor
// (`--laurel`) and shown only under the Imperium theme (`.laurel` in index.css).
const LEAVES = 9;

function branch(side) {
  // side -1 = left, 1 = right. Math angles (y up): the left branch climbs from
  // 250° (near the bottom) to 100° (short of the top), the right one mirrors it.
  const cx = 50, cy = 50, r = 38;
  const out = [];
  for (let i = 0; i < LEAVES; i++) {
    const t = i / (LEAVES - 1);
    const deg = side < 0 ? 250 - t * 150 : -70 + t * 150;
    const a = (deg * Math.PI) / 180;
    const x = cx + r * Math.cos(a);
    const y = cy - r * Math.sin(a);                      // SVG y runs down
    // Direction of growth (towards the tip), in SVG degrees.
    const dir = side < 0 ? Math.atan2(Math.cos(a), Math.sin(a)) : Math.atan2(-Math.cos(a), -Math.sin(a));
    const grow = (dir * 180) / Math.PI;
    const len = 11 - t * 5;
    for (const [off, scale, op] of [[-38, 1, 1], [38, 0.85, 0.85]]) {
      out.push(
        <ellipse key={`${side}-${i}-${off}`} rx={(len * scale) / 2} ry={(len * scale) / 5.2} opacity={op}
                 transform={`translate(${x.toFixed(2)} ${y.toFixed(2)}) rotate(${(grow + off).toFixed(1)}) translate(${((len * scale) / 2).toFixed(2)} 0)`} />,
      );
    }
  }
  return out;
}

export default function Laurel({ size = 120, className = "" }) {
  return (
    <svg className={`laurel pointer-events-none ${className}`} width={size} height={size} viewBox="0 0 100 100"
         fill="currentColor" aria-hidden="true" focusable="false">
      {/* stems */}
      <path d="M37 85.7 A 38 38 0 0 1 43.4 12.6" fill="none" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" opacity="0.75" />
      <path d="M63 85.7 A 38 38 0 0 0 56.6 12.6" fill="none" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" opacity="0.75" />
      {branch(-1)}
      {branch(1)}
      {/* the tie */}
      <path d="M37 85.7 Q50 93 63 85.7 M50 90 L45 98 M50 90 L55 98" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  );
}
