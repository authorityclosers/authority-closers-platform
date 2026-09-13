import { CallStudio } from "./call-studio";
import { StandaloneStudio } from "./standalone-studio";

export default function Page() {
  return (
    <StandaloneStudio>
      <CallStudio />
    </StandaloneStudio>
  );
}
