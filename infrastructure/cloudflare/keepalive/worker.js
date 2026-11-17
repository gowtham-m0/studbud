export default {
  async fetch(request, env) {
    const target = env.HEALTH_URL;
    if (!target) {
      return new Response("HEALTH_URL is not configured", { status: 500 });
    }
    const response = await fetch(target, { cf: { cacheTtl: 0 } });
    return new Response(`keepalive ${response.status}\n`, {
      status: response.ok ? 200 : 502,
      headers: { "content-type": "text/plain" },
    });
  },

  async scheduled(_controller, env, ctx) {
    const target = env.HEALTH_URL;
    if (!target) return;
    ctx.waitUntil(
      (async () => {
        try {
          const response = await fetch(target, { cf: { cacheTtl: 0 } });
          if (!response.ok) {
            console.error(`keepalive failed: ${response.status} ${target}`);
          }
        } catch (error) {
          console.error("keepalive error", error);
        }
      })(),
    );
  },
};
