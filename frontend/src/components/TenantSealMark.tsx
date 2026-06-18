interface TenantSealMarkProperties {
  /** Required so the rendered <img> is uniquely targetable (CLAUDE.md). */
  id: string;
  /** The tenant slug — selects the seal art at `/seals/<slug>.svg`. */
  slug: string;
}

// The tenant's seal mark in the masthead left cluster: a small square emblem
// beside the wordmark (Guide §2.3 / §6.8 — brand appears in the masthead seal
// mark). It is a plain `<img>` pointing at a slug-named SVG served from
// `public/seals/`, so swapping placeholder art for the real logo is a file drop
// with no code change. Decorative: the adjacent tenant name carries the brand in
// text, so the image takes an empty alt and is hidden from assistive tech rather
// than read out twice.
export default function TenantSealMark({ id, slug }: TenantSealMarkProperties) {
  return (
    <img
      id={id}
      className="masthead-seal-mark"
      src={`/seals/${slug}.svg`}
      alt=""
      aria-hidden="true"
      width={32}
      height={32}
    />
  );
}
