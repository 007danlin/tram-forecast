import { useEffect, useState } from "react";
import { loadNetwork, type Network } from "./loadMap";

export function useNetwork() {
  const [network, setNetwork] = useState<Network | null>(null);
  const [problem, setProblem] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    loadNetwork(controller.signal)
      .then(setNetwork)
      .catch((error) => {
        if (!controller.signal.aborted)
          setProblem(
            error.message === "MISSING"
              ? "Карта временно недоступна. Прогноз и CSV продолжают работать."
              : error.message,
          );
      });
    return () => controller.abort();
  }, []);
  return { network, problem };
}
