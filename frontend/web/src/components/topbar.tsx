import type { ReactNode } from "react";

export function TopBar({
  left,
  center,
  right,
}: {
  left: ReactNode;
  center?: ReactNode;
  right: ReactNode;
}) {
  return (
    <header className="topbar">
      <div className="topbar__left">{left}</div>
      {center ? <div className="topbar__center">{center}</div> : <div aria-hidden="true" />}
      <div className="topbar__right">{right}</div>
    </header>
  );
}
