import { AsyncLocalStorage } from "node:async_hooks";

export type StaticAssetBinding = Readonly<{
  fetch(request: Request): Promise<Response>;
}>;

const staticAssetBindingStorage =
  new AsyncLocalStorage<StaticAssetBinding>();

export function runWithStaticAssetBinding<T>(
  binding: StaticAssetBinding | undefined,
  callback: () => T,
): T {
  if (!binding) return callback();
  return staticAssetBindingStorage.run(binding, callback);
}

export function currentStaticAssetFetcher(): typeof fetch | undefined {
  const binding = staticAssetBindingStorage.getStore();
  if (!binding) return undefined;

  return (input, init) => {
    const request =
      input instanceof Request && init === undefined
        ? input
        : new Request(input, init);
    return binding.fetch(request);
  };
}
