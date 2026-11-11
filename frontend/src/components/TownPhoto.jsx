import { DESTINATIONS, PHOTOS } from "../data.js";

// Town photos from Wikimedia Commons. Their licences (CC BY / BY-SA) need the author and
// licence shown, so every page that shows the photos also shows PhotoCredits.

const url = (src) => `${import.meta.env.BASE_URL}${src}`;

export function TownPhoto({ id, className = "" }) {
  const p = PHOTOS[id];
  if (!p) return null;
  return <img className={className} src={url(p.src)} alt={p.alt} loading="lazy" decoding="async"
              title={`${p.alt}. Photo: ${p.author}, ${p.license}`} />;
}

export function PhotoCredits({ className = "" }) {
  return (
    <details className={`photo-credits ${className}`}>
      <summary>Photo credits</summary>
      <ul>
        {DESTINATIONS.filter((d) => PHOTOS[d.id]).map((d) => {
          const p = PHOTOS[d.id];
          return (
            <li key={d.id}>
              {d.name}: <a href={p.source} target="_blank" rel="noreferrer">{p.alt}</a> by {p.author},{" "}
              <a href={p.licenseUrl} target="_blank" rel="noreferrer">{p.license}</a>, resized
            </li>
          );
        })}
      </ul>
      <p>From Wikimedia Commons.</p>
    </details>
  );
}
