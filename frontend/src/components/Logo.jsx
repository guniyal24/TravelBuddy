// The TravelBuddy wordmark (navy + orange script). `onDark` swaps to the white + orange version
// for navy backgrounds; otherwise it follows the system light/dark preference.
const RATIO = 900 / 208;

export function LogoMark({ size = 34 }) {
  return <img className="logo-mark" src="/icon-192.png" width={size} height={size} alt="" aria-hidden="true" />;
}

export default function Logo({ onDark = false, height = 38 }) {
  const img = (src) => (
    <img className="logo-img" src={src} height={height} width={Math.round(height * RATIO)} alt="TravelBuddy" />
  );
  if (onDark) return <span className="logo">{img("/logo-dark.png")}</span>;
  return (
    <span className="logo">
      <picture>
        <source media="(prefers-color-scheme: dark)" srcSet="/logo-dark.png" />
        {img("/logo.png")}
      </picture>
    </span>
  );
}
