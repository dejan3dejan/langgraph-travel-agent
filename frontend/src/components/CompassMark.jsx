// The Atlas brand mark: a four-point compass. Forest needle over a gold hub, drawn from --brand-*
// tokens so it follows the active theme. Decorative beside the wordmark (caller passes aria-hidden);
// standalone it announces itself as an image titled Atlas.
export default function CompassMark({ size = 44, ...rest }) {
  const decorative = rest['aria-hidden'] === true || rest['aria-hidden'] === 'true'
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 44 44"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      role={decorative ? undefined : 'img'}
      {...rest}
    >
      {!decorative && <title>Atlas</title>}
      <circle cx="22" cy="22" r="20" stroke="var(--brand-forest)" strokeWidth="0.5" opacity="0.15" />
      <circle cx="22" cy="22" r="3.7" stroke="var(--brand-forest)" strokeWidth="0.5" opacity="0.22" />
      <polygon points="22,3.5 24.5,19.3 22,22 19.5,19.3" fill="var(--brand-forest)" />
      <polygon points="22,40.5 19.5,24.7 22,22 24.5,24.7" fill="var(--brand-forest)" opacity="0.24" />
      <polygon points="40.5,22 25.1,24.4 22,22 25.1,19.6" fill="var(--brand-forest)" opacity="0.44" />
      <polygon points="3.5,22 18.9,19.6 22,22 18.9,24.4" fill="var(--brand-forest)" opacity="0.44" />
      <circle cx="33.5" cy="10.5" r="1" fill="var(--brand-forest)" opacity="0.3" />
      <circle cx="10.5" cy="10.5" r="1" fill="var(--brand-forest)" opacity="0.3" />
      <circle cx="33.5" cy="33.5" r="1" fill="var(--brand-forest)" opacity="0.3" />
      <circle cx="10.5" cy="33.5" r="1" fill="var(--brand-forest)" opacity="0.3" />
      <circle cx="22" cy="22" r="2" fill="var(--brand-gold)" />
    </svg>
  )
}
