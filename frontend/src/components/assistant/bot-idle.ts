export type BotIdleScene = "rest" | "wave" | "win" | "lose";

/** One timer, using only visible idle time. CSS handles the motion within each scene. */
export function startBotIdle(onScene: (scene: BotIdleScene) => void) {
  let elapsed = 0;
  let startedAt = Date.now();
  let running = true;
  let stopped = false;
  let timer: ReturnType<typeof setTimeout>;
  let nextWave = 6000 + Math.random() * 2000;
  let nextGame = 20000;
  let sceneEnd = Infinity;

  const time = () => elapsed + (running ? Date.now() - startedAt : 0);
  const schedule = () => {
    timer = setTimeout(tick, Math.max(0, Math.min(nextWave, nextGame, sceneEnd) - time()));
  };
  const tick = () => {
    const now = time();
    if (now >= sceneEnd) {
      sceneEnd = Infinity;
      onScene("rest");
    }
    if (now >= nextGame) {
      onScene(Math.random() < 0.5 ? "win" : "lose");
      sceneEnd = now + 5600;
      nextGame = now + 30000;
      nextWave = sceneEnd + 6000 + Math.random() * 2000;
    } else if (now >= nextWave) {
      onScene("wave");
      sceneEnd = now + 1800;
      nextWave = now + 6000 + Math.random() * 2000;
    }
    schedule();
  };
  schedule();

  return {
    pause() {
      if (!running || stopped) return;
      elapsed = time();
      running = false;
      clearTimeout(timer);
    },
    resume() {
      if (running || stopped) return;
      startedAt = Date.now();
      running = true;
      schedule();
    },
    stop() {
      stopped = true;
      running = false;
      clearTimeout(timer);
    },
  };
}
