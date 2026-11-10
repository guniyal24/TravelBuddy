// Layered mountain skyline. Colours come from CSS variables (--mt-*), so each place that uses it
// (light hero, dark hero, navy banners) sets its own palette. Pure SVG, no assets.
const TREES = Array.from({ length: 38 }, (_, i) => {
  const x = 14 + i * 39 + (i % 3) * 7;
  const h = 28 + ((i * 17) % 24);
  const base = 398 - ((i * 13) % 12);
  return `${x},${base - h} ${x - 9},${base} ${x + 9},${base}`;
});

const fill = (v) => ({ fill: `var(${v})` });

export default function Mountains({ className = "" }) {
  return (
    <svg className={className} viewBox="0 0 1440 420" preserveAspectRatio="xMidYMax slice"
         aria-hidden="true" focusable="false">
      <path style={fill("--mt-far")}
            d="M0 300 90 230l80 50 120-130 90 90 90-50 110 100 120-120 100 80 110-130 100 110 110-50 110 90 100-70 100 60V420H0z" />
      <g style={fill("--mt-snow")}>
        <polygon points="290,150 262,192 280,184 292,200 306,184 322,194" />
        <polygon points="700,170 674,206 690,200 702,214 716,200 730,208" />
        <polygon points="910,120 878,170 896,160 910,178 926,160 944,172" />
      </g>
      <path style={fill("--mt-mid")}
            d="M0 340C120 290 200 330 300 290S480 260 560 300 760 250 860 290s200-20 300 10 200-30 280 0V420H0z" />
      <path style={fill("--mt-near")}
            d="M0 380C140 350 260 392 400 366S660 340 800 372s300-22 450 6 150-18 190-6V420H0z" />
      <g style={fill("--mt-tree")}>
        {TREES.map((p) => <polygon key={p} points={p} />)}
      </g>
      <rect x="0" y="396" width="1440" height="24" style={fill("--mt-near")} />
    </svg>
  );
}
