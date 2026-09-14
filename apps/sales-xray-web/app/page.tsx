import { AcquisitionStudio } from "./acquisition-studio";
import { StandaloneStudio } from "./standalone-studio";

export default function Page() {
  return (
    <StandaloneStudio>
      <AcquisitionStudio />
    </StandaloneStudio>
  );
}
