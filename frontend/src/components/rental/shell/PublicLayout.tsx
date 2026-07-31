import type { ReactNode } from "react";
import { TopBar, type TopBarProps } from "./TopBar";
import { Footer } from "./Footer";

const VARIANT_TO_AREA: Partial<Record<NonNullable<TopBarProps["variant"]>, string>> = {
  rental: "rental",
  estudio: "estudio",
  escuela: "escuela",
};

export function PublicLayout({ children, topBar }: { children: ReactNode; topBar?: TopBarProps }) {
  const area = topBar?.variant ? VARIANT_TO_AREA[topBar.variant] : undefined;
  return (
    <div
      className="min-h-dvh flex flex-col bg-background text-foreground"
      {...(area ? { "data-area": area } : {})}
    >
      <TopBar {...topBar} />
      <main className="flex-1">{children}</main>
      <Footer />
    </div>
  );
}
