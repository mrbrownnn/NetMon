import { defineRailway, github, project, service } from "railway/iac";
// This repository manages only its own resources in the environment. Other
// repositories export their own partial name.
// See https://docs.railway.com/infrastructure-as-code#multi-repo-projects
export const partial = "NetMon";
export default defineRailway(() => {
  const NetMon = service("NetMon", {
    source: github("mrbrownnn/NetMon", { branch: "main", checkSuites: false }),
    build: { buildEnvironment: "V3", builder: "DOCKERFILE", dockerfilePath: "Dockerfile" },
    healthcheck: "/healthz",
    replicas: { "asia-southeast1-eqsg3a": 1 },
    // 1 replica only: MonitorScheduler is an in-process singleton.
    deploy: { restartPolicyType: "ON_FAILURE", limitOverride: { containers: { cpu: 4, memoryBytes: 4000000000 } } },
    networking: { privateNetworkEndpoint: "netmon" },
  });

  return project("netmon", {
    variables: { managed: false },
    resources: [NetMon],
  });
});
