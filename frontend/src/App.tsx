import { Icon, type IconName } from "./components/Icon";
import { useHashRoute } from "./hooks";
import { AlertDetailPage } from "./pages/AlertDetailPage";
import { AlertsPage } from "./pages/AlertsPage";
import { DataImportPage } from "./pages/DataImportPage";
import { MachineDetailPage } from "./pages/MachineDetailPage";
import { MachineFormPage, MachinesPage } from "./pages/MachinesPage";
import { MethodPage } from "./pages/MethodPage";
import { OverviewPage } from "./pages/OverviewPage";
import { SimLabPage } from "./pages/SimLabPage";

const NAV: { href: string; label: string; icon: IconName; match: string[] }[] = [
  { href: "#/", label: "Genel görünüm", icon: "chart", match: [""] },
  { href: "#/uyarilar", label: "Uyarılar", icon: "bell", match: ["uyarilar", "uyari"] },
  { href: "#/simulasyon", label: "Simülasyon laboratuvarı", icon: "flask", match: ["simulasyon"] },
  { href: "#/veri", label: "Veri aktarımı", icon: "upload", match: ["veri"] },
  { href: "#/makineler", label: "Makineler", icon: "edit", match: ["makineler", "makine-ekle"] },
  { href: "#/yontem", label: "Yöntem", icon: "info", match: ["yontem"] },
];

function Page({ parts, query }: { parts: string[]; query: URLSearchParams }) {
  const [first, second, third] = parts;
  if (!first) return <OverviewPage />;
  if (first === "makine" && second && third === "duzenle") return <MachineFormPage key={second} machineId={second} />;
  if (first === "makine" && second) return <MachineDetailPage key={`${second}?${query.toString()}`} machineId={second} query={query} />;
  if (first === "makineler") return <MachinesPage />;
  if (first === "makine-ekle") return <MachineFormPage />;
  if (first === "uyarilar") return <AlertsPage query={query} />;
  if (first === "uyari" && second) return <AlertDetailPage key={second} alertId={Number(second)} />;
  if (first === "simulasyon") return <SimLabPage query={query} />;
  if (first === "veri") return <DataImportPage />;
  if (first === "yontem") return <MethodPage />;
  return (
    <div className="page">
      <h1>Sayfa bulunamadı</h1>
      <a href="#/">Genel görünüme dön</a>
    </div>
  );
}

export default function App() {
  const { parts, query } = useHashRoute();
  const section = parts[0] ?? "";
  const activeSection = section === "makine" ? "makineler" : section;
  return (
    <div className="app">
      <a className="skip-link" href="#icerik">
        İçeriğe geç
      </a>
      <header className="topbar">
        <a className="brand" href="#/">
          <svg viewBox="0 0 32 32" width="28" height="28" aria-hidden="true">
            <rect width="32" height="32" rx="7" fill="#1d3b53" />
            <path d="M5 18h5l3-8 4 14 3-9 2 3h5" fill="none" stroke="#7fd1b9" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <span>Makine İz</span>
        </a>
        <nav aria-label="Ana menü">
          {NAV.map((item) => {
            const active = item.match.includes(activeSection) || (item.match.includes("") && !activeSection);
            return (
              <a key={item.href} href={item.href} className={active ? "active" : ""} aria-current={active ? "page" : undefined}>
                <Icon name={item.icon} size={16} />
                {item.label}
              </a>
            );
          })}
        </nav>
      </header>
      <main id="icerik">
        <Page parts={parts} query={query} />
      </main>
      <footer className="footer">
        Makine İz · ilk sürüm (prototip) · Zamanlar Europe/Istanbul saat diliminde gösterilir · Uyarılar ölçüm sapmasıdır, arıza teşhisi
        değildir.
      </footer>
    </div>
  );
}
