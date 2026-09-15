import { AcquisitionStudio } from "../../../sales-xray-web/app/acquisition-studio";
import { SalesXrayShell } from "./sales-xray-shell";

export default function SalesXrayPage() {
  return (
    <SalesXrayShell current="analyse">
      <AcquisitionStudio homeHref="/home" variant="embedded" />
    </SalesXrayShell>
  );
}
