import { OperationsLogin } from "@ac/operations-web/login";
export default function Login() {
  return (
    <OperationsLogin
      surface="coach"
      local={
        process.env.NODE_ENV === "development" &&
        process.env.AC_DEV_LOCAL_SANDBOX_ENABLED === "true"
      }
    />
  );
}
