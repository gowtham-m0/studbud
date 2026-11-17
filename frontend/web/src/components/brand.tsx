import Link from "next/link";

export function Brand({ href = "/" }: { href?: string }) {
  return (
    <Link className="brand" href={href} aria-label="StudBud library">
      StudBud
    </Link>
  );
}
